"""Read-only expiry gates and X-Perp rollover planning.

This module deliberately has no trading client dependency.  It accepts already
retrieved instrument and market rows and returns a deterministic dry-run report.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any, Iterable, Mapping

from .adapter import Instrument, SafetyError, _decimal
from .canary import (
    EXPIRY_MANDATORY_FLAT_DAYS,
    EXPIRY_NEW_STOP_DAYS,
    EXPIRY_WARNING_DAYS,
)


@dataclass(frozen=True)
class ExpiryStatus:
    instrument_id: str
    expiry: str
    days_remaining: Decimal
    warning: bool
    block_new_exposure: bool
    mandatory_flat: bool


@dataclass(frozen=True)
class RolloverReport:
    status: str
    current: ExpiryStatus
    successor_id: str | None
    metadata_compatible: bool
    collateral_compatible: bool
    current_spread_bps: Decimal | None
    successor_spread_bps: Decimal | None
    current_liquidity_usd: Decimal | None
    successor_liquidity_usd: Decimal | None
    current_basis_bps: Decimal | None
    successor_basis_bps: Decimal | None
    estimated_close_open_cost_usd: Decimal | None
    current_contracts: Decimal
    successor_contracts: Decimal | None
    reason: str
    source_hash: str


def expiry_status(
    instrument: Instrument,
    *,
    now: datetime | None = None,
) -> ExpiryStatus:
    checked = now or datetime.now(UTC)
    if checked.tzinfo is None:
        raise SafetyError("expiry check requires a timezone-aware timestamp")
    remaining = Decimal(str((instrument.exp_time - checked).total_seconds())) / Decimal("86400")
    return ExpiryStatus(
        instrument_id=instrument.inst_id,
        expiry=instrument.exp_time.isoformat(),
        days_remaining=remaining,
        warning=remaining <= EXPIRY_WARNING_DAYS,
        block_new_exposure=remaining <= EXPIRY_NEW_STOP_DAYS,
        mandatory_flat=remaining <= EXPIRY_MANDATORY_FLAT_DAYS,
    )


def _compatible_successor(current: Instrument, row: Mapping[str, Any]) -> bool:
    required = {
        "instId", "instFamily", "uly", "settleCcy", "ctType", "ctVal",
        "ctValCcy", "lotSz", "minSz", "tickSz", "expTime", "ruleType", "state",
    }
    if required - set(row) or any(row.get(field) in (None, "") for field in required):
        return False
    return (
        row["state"] == "live"
        and row["ruleType"] == "xperp"
        and row["instId"] != current.inst_id
        and row["instFamily"] == current.inst_family
        and row["uly"] == current.uly
        and row["settleCcy"] == current.settle_ccy
        and row["ctType"] == current.ct_type
        and _decimal(row["ctVal"]) == current.ct_val
        and row["ctValCcy"] == current.ct_val_ccy
        and int(row["expTime"]) > int(current.exp_time.timestamp() * 1000)
    )


def discover_successor(
    current: Instrument,
    rows: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any]:
    candidates = [row for row in rows if _compatible_successor(current, row)]
    candidates.sort(key=lambda row: int(row["expTime"]))
    if not candidates:
        raise SafetyError("no valid later X-Perp successor exists")
    earliest_expiry = int(candidates[0]["expTime"])
    earliest = [row for row in candidates if int(row["expTime"]) == earliest_expiry]
    if len(earliest) != 1:
        raise SafetyError("successor discovery is ambiguous")
    return earliest[0]


def _market_metrics(row: Mapping[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    required = {"bidPx", "askPx", "bidSz", "askSz", "indexPx"}
    if required - set(row) or any(row.get(field) in (None, "") for field in required):
        raise SafetyError("rollover market snapshot is incomplete")
    bid, ask = _decimal(row["bidPx"]), _decimal(row["askPx"])
    bid_size, ask_size, index = (
        _decimal(row["bidSz"]),
        _decimal(row["askSz"]),
        _decimal(row["indexPx"]),
    )
    if min(bid, ask, bid_size, ask_size, index) <= 0 or ask <= bid:
        raise SafetyError("rollover market snapshot is invalid")
    mid = (bid + ask) / Decimal("2")
    spread = (ask - bid) / mid * Decimal("10000")
    liquidity = min(bid * bid_size, ask * ask_size)
    basis = (mid - index) / index * Decimal("10000")
    return spread, liquidity, basis


def rollover_dry_run(
    *,
    current: Instrument,
    instrument_rows: Iterable[Mapping[str, Any]],
    markets: Mapping[str, Mapping[str, Any]],
    current_contracts: Decimal,
    fee_rate: Decimal = Decimal("0.001"),
    now: datetime | None = None,
) -> RolloverReport:
    status = expiry_status(current, now=now)
    base: dict[str, Any] = {
        "status": "BLOCKED",
        "current": status,
        "successor_id": None,
        "metadata_compatible": False,
        "collateral_compatible": False,
        "current_spread_bps": None,
        "successor_spread_bps": None,
        "current_liquidity_usd": None,
        "successor_liquidity_usd": None,
        "current_basis_bps": None,
        "successor_basis_bps": None,
        "estimated_close_open_cost_usd": None,
        "current_contracts": current_contracts,
        "successor_contracts": None,
        "reason": "",
    }
    try:
        successor = discover_successor(current, instrument_rows)
        successor_id = str(successor["instId"])
        current_metrics = _market_metrics(markets[current.inst_id])
        successor_metrics = _market_metrics(markets[successor_id])
        successor_lot = _decimal(successor["lotSz"])
        successor_ct_val = _decimal(successor["ctVal"])
        if successor_lot <= 0 or successor_ct_val <= 0:
            raise SafetyError("successor contract sizing metadata is invalid")
        btc_quantity = abs(current_contracts) * current.ct_val
        successor_contracts = (
            btc_quantity / successor_ct_val / successor_lot
        ).to_integral_value(rounding=ROUND_DOWN) * successor_lot
        if current_contracts != 0 and successor_contracts < _decimal(successor["minSz"]):
            raise SafetyError("rollover target is below successor minimum size")
        current_mid = (
            _decimal(markets[current.inst_id]["bidPx"])
            + _decimal(markets[current.inst_id]["askPx"])
        ) / Decimal("2")
        successor_mid = (
            _decimal(markets[successor_id]["bidPx"])
            + _decimal(markets[successor_id]["askPx"])
        ) / Decimal("2")
        close_notional = abs(current_contracts) * current.ct_val * current_mid
        open_notional = successor_contracts * successor_ct_val * successor_mid
        estimated_cost = (
            close_notional * (fee_rate + current_metrics[0] / Decimal("20000"))
            + open_notional * (fee_rate + successor_metrics[0] / Decimal("20000"))
        )
        base.update(
            status="READY_DRY_RUN",
            successor_id=successor_id,
            metadata_compatible=True,
            collateral_compatible=successor["settleCcy"] == "USDC",
            current_spread_bps=current_metrics[0],
            successor_spread_bps=successor_metrics[0],
            current_liquidity_usd=current_metrics[1],
            successor_liquidity_usd=successor_metrics[1],
            current_basis_bps=current_metrics[2],
            successor_basis_bps=successor_metrics[2],
            estimated_close_open_cost_usd=estimated_cost,
            successor_contracts=successor_contracts,
            reason="read-only plan; execution is intentionally unavailable",
        )
    except (KeyError, SafetyError) as exc:
        base["reason"] = str(exc)
    canonical = json.dumps(
        {key: asdict(value) if hasattr(value, "__dataclass_fields__") else value for key, value in base.items()},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    base["source_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return RolloverReport(**base)
