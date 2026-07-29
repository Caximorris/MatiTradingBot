"""Fail-closed isolated-margin tier and liquidation calculations for V8 X-Perp."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Any, Iterable

from .adapter import Instrument, SafetyError, _decimal

MARGIN_ABS_TOLERANCE = Decimal("1")
MARGIN_REL_TOLERANCE = Decimal("0.01")
LIQ_PRICE_REL_TOLERANCE = Decimal("0.01")
MIN_LIQUIDATION_DISTANCE_PCT = Decimal("35")


@dataclass(frozen=True)
class MarginTier:
    tier: int
    instrument_family: str
    underlying: str
    minimum_position_size: Decimal
    maximum_position_size: Decimal
    maximum_leverage: Decimal
    initial_margin_rate: Decimal
    maintenance_margin_rate: Decimal
    deductions: tuple[tuple[str, Decimal], ...]
    source_hash: str


@dataclass(frozen=True)
class MarginAssessment:
    instrument_id: str
    contracts: Decimal
    mark_price: Decimal
    actual_notional: Decimal
    applicable_leverage: Decimal
    tier: MarginTier
    required_initial_margin: Decimal
    required_maintenance_margin: Decimal
    exchange_initial_margin: Decimal | None
    exchange_maintenance_margin: Decimal | None
    exchange_margin: Decimal | None
    exchange_liquidation_price: Decimal | None
    conservative_liquidation_price: Decimal
    liquidation_distance_pct: Decimal
    liquidation_distance_usdc: Decimal
    available_margin_after_reserves: Decimal
    source_hash: str


def _source_hash(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_margin_tiers(
    rows: Iterable[dict[str, Any]],
    *,
    instrument: Instrument,
) -> tuple[MarginTier, ...]:
    required = {"tier", "instFamily", "uly", "minSz", "maxSz", "maxLever", "imr", "mmr"}
    parsed: list[MarginTier] = []
    for row in rows:
        if required - set(row) or any(row.get(field) in (None, "") for field in required):
            raise SafetyError("position tier is missing required exchange fields")
        if row["instFamily"] != instrument.inst_family or row["uly"] != instrument.uly:
            raise SafetyError("position tier belongs to another instrument family")
        unknown_deductions = [
            key for key, value in row.items()
            if "deduct" in key.lower() and value not in (None, "", "0", 0)
        ]
        if unknown_deductions:
            raise SafetyError("position tier contains an undocumented nonzero deduction")
        deductions: tuple[tuple[str, Decimal], ...] = ()
        tier = MarginTier(
            tier=int(row["tier"]),
            instrument_family=str(row["instFamily"]),
            underlying=str(row["uly"]),
            minimum_position_size=_decimal(row["minSz"]),
            maximum_position_size=_decimal(row["maxSz"]),
            maximum_leverage=_decimal(row["maxLever"]),
            initial_margin_rate=_decimal(row["imr"]),
            maintenance_margin_rate=_decimal(row["mmr"]),
            deductions=deductions,
            source_hash=_source_hash(row),
        )
        if (
            tier.minimum_position_size < 0
            or tier.maximum_position_size <= tier.minimum_position_size
            or tier.maximum_leverage <= 0
            or not Decimal("0") < tier.maintenance_margin_rate < tier.initial_margin_rate < Decimal("1")
        ):
            raise SafetyError("position tier contains invalid margin boundaries")
        parsed.append(tier)
    parsed.sort(key=lambda item: item.tier)
    if not parsed or parsed[0].tier != 1 or parsed[0].minimum_position_size != 0:
        raise SafetyError("position tiers do not start at tier one and zero notional")
    if [item.tier for item in parsed] != list(range(1, len(parsed) + 1)):
        raise SafetyError("position tier numbering contains a gap")
    for previous, current in zip(parsed, parsed[1:], strict=False):
        quantum = instrument.lot_sz * instrument.ct_val
        expected = previous.maximum_position_size + quantum
        if current.minimum_position_size != expected:
            label = "overlap" if current.minimum_position_size <= previous.maximum_position_size else "gap"
            raise SafetyError(f"position tier boundaries contain an {label}")
    return tuple(parsed)


def select_margin_tier(
    tiers: Iterable[MarginTier],
    *,
    position_size: Decimal,
    quantum: Decimal,
) -> MarginTier:
    if quantum <= 0:
        raise SafetyError("position tier quantum is invalid")
    quantized = (position_size / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum
    matches = [
        tier
        for tier in tiers
        if tier.minimum_position_size <= quantized <= tier.maximum_position_size
    ]
    if len(matches) != 1:
        raise SafetyError("no unique applicable position tier exists")
    return matches[0]


def _within_tolerance(local: Decimal, exchange: Decimal) -> bool:
    tolerance = min(
        MARGIN_ABS_TOLERANCE,
        abs(exchange) * MARGIN_REL_TOLERANCE,
    )
    return abs(local - exchange) <= tolerance


def assess_margin(
    *,
    instrument: Instrument,
    tiers: Iterable[MarginTier],
    contracts: Decimal,
    side: str,
    mark_price: Decimal,
    entry_price: Decimal | None = None,
    leverage: Decimal,
    available_usdc: Decimal,
    reserve_usdc: Decimal,
    exchange_position: dict[str, Any] | None = None,
    minimum_liquidation_distance_pct: Decimal = MIN_LIQUIDATION_DISTANCE_PCT,
    liquidation_fee_rate: Decimal = Decimal("0.001"),
) -> MarginAssessment:
    if side not in {"long", "short"} or contracts <= 0 or mark_price <= 0 or leverage <= 0:
        raise SafetyError("invalid margin-assessment inputs")
    position_size = contracts * instrument.ct_val
    notional = position_size * mark_price
    entry = entry_price or mark_price
    tier = select_margin_tier(
        tiers,
        position_size=position_size,
        quantum=instrument.lot_sz * instrument.ct_val,
    )
    if leverage > tier.maximum_leverage:
        raise SafetyError("applicable leverage exceeds the exchange tier maximum")
    effective_imr = max(Decimal("1") / leverage, tier.initial_margin_rate)
    local_im = notional * effective_imr
    local_mm = notional * (
        tier.maintenance_margin_rate + liquidation_fee_rate
    )
    margin_after = available_usdc - local_im - reserve_usdc
    if margin_after < 0:
        raise SafetyError("available margin after reserves is negative")

    exchange_im = exchange_mm = exchange_margin = exchange_liq = None
    position_margin = local_im
    if exchange_position is not None:
        required = {
            "instId", "instType", "mgnMode", "ccy", "posSide", "notionalUsd",
            "lever", "margin", "mgnRatio", "mmr", "liqPx", "markPx", "avgPx", "pos",
        }
        if required - set(exchange_position) or any(
            exchange_position.get(field) in (None, "") for field in required
        ):
            raise SafetyError("exchange position is missing required margin fields")
        if (
            exchange_position["instId"] != instrument.inst_id
            or exchange_position["instType"] != "FUTURES"
            or exchange_position["mgnMode"] != "isolated"
            or exchange_position["ccy"] != instrument.settle_ccy
            or exchange_position["posSide"] != "net"
        ):
            raise SafetyError("exchange position identity or margin mode is incompatible")
        exchange_contracts = abs(_decimal(exchange_position["pos"]))
        if exchange_contracts != contracts:
            raise SafetyError("local and exchange contracts disagree")
        if (_decimal(exchange_position["pos"]) > 0) != (side == "long"):
            raise SafetyError("local and exchange position sides disagree")
        exchange_notional = abs(_decimal(exchange_position["notionalUsd"]))
        exchange_leverage = _decimal(exchange_position["lever"])
        exchange_margin = _decimal(exchange_position["margin"])
        exchange_mm = _decimal(exchange_position["mmr"])
        exchange_liq = _decimal(exchange_position["liqPx"])
        exchange_mark = _decimal(exchange_position["markPx"])
        exchange_entry = _decimal(exchange_position["avgPx"])
        if _decimal(exchange_position["mgnRatio"]) <= 0:
            raise SafetyError("exchange margin ratio is nonpositive")
        position_margin = exchange_margin
        if not _within_tolerance(notional, exchange_notional):
            raise SafetyError("local and exchange position notionals disagree")
        if leverage != exchange_leverage:
            raise SafetyError("local and exchange leverage disagree")
        mark_tolerance = max(instrument.tick_sz * 2, exchange_mark * MARGIN_REL_TOLERANCE)
        if abs(mark_price - exchange_mark) > mark_tolerance:
            raise SafetyError("local and exchange mark prices disagree")
        entry = exchange_entry

    long_denominator = position_size * (
        Decimal("1") - tier.maintenance_margin_rate - liquidation_fee_rate
    )
    short_denominator = position_size * (
        Decimal("1") + tier.maintenance_margin_rate + liquidation_fee_rate
    )
    if long_denominator <= 0 or short_denominator <= 0:
        raise SafetyError("local liquidation estimate denominator is invalid")
    local_liq = (
        (position_size * entry - position_margin) / long_denominator
        if side == "long"
        else (position_size * entry + position_margin) / short_denominator
    )
    if exchange_position is not None:
        # OKX's position ``mmr`` is the maintenance requirement itself.  The
        # separate liquidation-fee reserve belongs in our required total and
        # liquidation estimate, not in the venue-mmr parity comparison.
        exchange_comparable_mm = notional * tier.maintenance_margin_rate
        if not _within_tolerance(exchange_comparable_mm, exchange_mm):
            raise SafetyError("local and exchange maintenance margins disagree")
        liq_tolerance = max(
            instrument.tick_sz * 2,
            exchange_liq * LIQ_PRICE_REL_TOLERANCE,
        )
        if abs(local_liq - exchange_liq) > liq_tolerance:
            raise SafetyError("local and exchange liquidation prices disagree")

    authoritative_liq = (
        (max(local_liq, exchange_liq) if side == "long" else min(local_liq, exchange_liq))
        if exchange_liq is not None
        else local_liq
    )
    distance_price = (
        mark_price - authoritative_liq
        if side == "long"
        else authoritative_liq - mark_price
    )
    if distance_price <= 0:
        raise SafetyError("liquidation price is on the wrong side of the market")
    distance_pct = distance_price / mark_price * Decimal("100")
    distance_usdc = distance_price * contracts * instrument.ct_val
    if distance_pct < minimum_liquidation_distance_pct:
        raise SafetyError("liquidation distance is below the configured threshold")
    result_payload = {
        "instrument": instrument.inst_id,
        "contracts": str(contracts),
        "mark_price": str(mark_price),
        "notional": str(notional),
        "leverage": str(leverage),
        "tier_hash": tier.source_hash,
        "exchange_liq": str(exchange_liq) if exchange_liq is not None else None,
    }
    return MarginAssessment(
        instrument.inst_id,
        contracts,
        mark_price,
        notional,
        leverage,
        tier,
        local_im,
        local_mm,
        exchange_im,
        exchange_mm,
        exchange_margin,
        exchange_liq,
        local_liq,
        distance_pct,
        distance_usdc,
        margin_after,
        _source_hash(result_payload),
    )
