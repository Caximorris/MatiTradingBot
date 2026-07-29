"""Deterministic one-time operational bootstrap policy for V8 X-Perp.

This module does not generate historical V8 backtest targets and has no order
client.  It converts one same-source reference/current index pair into a bounded
startup leverage and persists the frozen decision separately from order intents.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Mapping

from strategies.cycle_phase_clock import CyclePhaseClock

from .adapter import SafetyError

BOOTSTRAP_SCHEMA = 1
HARD_MAX_EQUITY_LOSS_PCT = Decimal("0.20")
HARD_MAX_LEVERAGE = Decimal("2")
HARD_MIN_ENTRY_LEVERAGE = Decimal("0.25")
BOOTSTRAP_STATES = {"PLANNED", "EXECUTED", "FLAT", "SUPERSEDED"}


def _decimal(source: Mapping[str, str], name: str, default: str) -> Decimal:
    try:
        return Decimal(source.get(name, default))
    except Exception as exc:
        raise SafetyError(f"invalid bootstrap configuration: {name}") from exc


def _hash(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BootstrapConfig:
    max_equity_loss_to_reference_pct: Decimal = HARD_MAX_EQUITY_LOSS_PCT
    maximum_leverage: Decimal = HARD_MAX_LEVERAGE
    minimum_entry_leverage: Decimal = HARD_MIN_ENTRY_LEVERAGE
    operational_reserve_usd: Decimal = Decimal("5")

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> "BootstrapConfig":
        values = source or os.environ
        config = cls(
            max_equity_loss_to_reference_pct=_decimal(
                values, "V8_BOOTSTRAP_MAX_EQUITY_LOSS_TO_REFERENCE_PCT", "0.20"
            ),
            maximum_leverage=_decimal(values, "V8_BOOTSTRAP_MAX_LEVERAGE", "2.0"),
            minimum_entry_leverage=_decimal(
                values, "V8_BOOTSTRAP_MIN_ENTRY_LEVERAGE", "0.25"
            ),
            operational_reserve_usd=_decimal(
                values, "V8_BOOTSTRAP_OPERATIONAL_RESERVE_USD", "5"
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if (
            self.max_equity_loss_to_reference_pct <= 0
            or self.max_equity_loss_to_reference_pct > HARD_MAX_EQUITY_LOSS_PCT
        ):
            raise SafetyError("bootstrap equity-loss budget exceeds the hard ceiling")
        if self.maximum_leverage <= 0 or self.maximum_leverage > HARD_MAX_LEVERAGE:
            raise SafetyError("bootstrap leverage exceeds the hard ceiling")
        if (
            self.minimum_entry_leverage < HARD_MIN_ENTRY_LEVERAGE
            or self.minimum_entry_leverage > self.maximum_leverage
        ):
            raise SafetyError("bootstrap minimum entry weakens the hard safety floor")
        if self.operational_reserve_usd < Decimal("5"):
            raise SafetyError("bootstrap operational reserve is below the hard floor")


@dataclass(frozen=True)
class OperationalPhase:
    name: str
    direction: str
    last_transition_kind: str
    last_transition_at: datetime
    next_transition_at: datetime | None
    halving_at: datetime


def operational_phase(
    at: datetime,
    *,
    clock: CyclePhaseClock | None = None,
) -> OperationalPhase:
    if at.tzinfo is None:
        raise SafetyError("operational phase requires timezone-aware UTC")
    now = at.astimezone(UTC)
    active = clock or CyclePhaseClock()
    transitions: list[tuple[datetime, str, str, datetime]] = []
    for halving in active.halving_timestamps:
        transitions.extend((
            (
                halving + timedelta(days=active.bear_onset_start),
                "day_540",
                "short",
                halving,
            ),
            (
                halving + timedelta(days=active.accumulation_start),
                "day_900",
                "long",
                halving,
            ),
        ))
    transitions.sort(key=lambda item: item[0])
    elapsed = [item for item in transitions if item[0] <= now]
    if not elapsed:
        raise SafetyError("current time precedes every authoritative V8 transition")
    last = elapsed[-1]
    future = [item for item in transitions if item[0] > now]
    return OperationalPhase(
        name=f"{last[2]}_phase",
        direction=last[2],
        last_transition_kind=last[1],
        last_transition_at=last[0],
        next_transition_at=future[0][0] if future else None,
        halving_at=last[3],
    )


@dataclass(frozen=True)
class IndexPriceSample:
    source: str
    instrument_id: str
    timestamp: datetime
    price: Decimal
    retrieved_at: datetime
    source_hash: str

    def validate(self) -> None:
        if (
            self.source != "okx_eea_btc_usd_index"
            or self.instrument_id != "BTC-USD"
            or self.timestamp.tzinfo is None
            or self.retrieved_at.tzinfo is None
            or self.price <= 0
            or len(self.source_hash) != 64
        ):
            raise SafetyError("invalid BTC-USD index price sample")


@dataclass(frozen=True)
class BootstrapDecision:
    transition_id: str
    environment: str
    account_hash: str
    instrument_id: str
    phase: str
    direction: str
    last_transition_kind: str
    last_transition_at: str
    reference_timestamp: str
    reference_price: str
    current_timestamp: str
    current_price: str
    price_source: str
    reference_source_hash: str
    current_source_hash: str
    adverse_move_to_reference: str
    risk_budget_pct: str
    eligible_equity: str
    leverage_from_reference: str
    margin_safe_leverage: str
    liquidation_safe_leverage: str
    account_safe_leverage: str
    calculated_leverage: str
    minimum_entry_leverage: str
    enter: bool
    reason: str
    final_contracts: str = "0"
    final_notional: str = "0"
    actual_leverage: str = "0"
    state: str = "PLANNED"
    schema: int = BOOTSTRAP_SCHEMA


def calculate_bootstrap(
    *,
    environment: str,
    account_hash: str,
    instrument_id: str,
    phase: OperationalPhase,
    reference: IndexPriceSample,
    current: IndexPriceSample,
    eligible_equity: Decimal,
    margin_safe_leverage: Decimal,
    liquidation_safe_leverage: Decimal,
    account_safe_leverage: Decimal,
    config: BootstrapConfig,
) -> BootstrapDecision:
    config.validate()
    reference.validate()
    current.validate()
    if environment != "okx_demo" or not account_hash or not instrument_id:
        raise SafetyError("bootstrap identity is incomplete or outside Demo")
    if reference.source != current.source or reference.instrument_id != current.instrument_id:
        raise SafetyError("bootstrap reference and current prices must use the same source")
    if reference.timestamp <= phase.last_transition_at:
        raise SafetyError("bootstrap reference is not strictly after the official transition")
    if current.timestamp < reference.timestamp or current.retrieved_at < current.timestamp:
        raise SafetyError("bootstrap current price timestamp is inconsistent")
    if eligible_equity <= 0:
        raise SafetyError("bootstrap eligible equity is nonpositive")
    safety_bounds = (
        margin_safe_leverage,
        liquidation_safe_leverage,
        account_safe_leverage,
    )
    if any(value <= 0 for value in safety_bounds):
        raise SafetyError("bootstrap safety leverage is unavailable")

    if phase.direction == "long":
        adverse = max(Decimal("0"), (current.price - reference.price) / current.price)
    elif phase.direction == "short":
        adverse = max(Decimal("0"), (reference.price - current.price) / current.price)
    else:
        raise SafetyError("bootstrap phase direction is ambiguous")
    leverage_from_reference = (
        config.maximum_leverage
        if adverse == 0
        else config.max_equity_loss_to_reference_pct / adverse
    )
    calculated = min(
        config.maximum_leverage,
        leverage_from_reference,
        margin_safe_leverage,
        liquidation_safe_leverage,
        account_safe_leverage,
    )
    enter = calculated >= config.minimum_entry_leverage
    if not enter:
        calculated = Decimal("0")
    identity = {
        "environment": environment,
        "account_hash": account_hash,
        "instrument_id": instrument_id,
        "phase": phase.name,
        "direction": phase.direction,
        "last_transition_at": phase.last_transition_at.isoformat(),
        "reference_timestamp": reference.timestamp.isoformat(),
        "reference_hash": reference.source_hash,
        "current_timestamp": current.timestamp.isoformat(),
        "current_hash": current.source_hash,
        "risk_budget": str(config.max_equity_loss_to_reference_pct),
        "maximum_leverage": str(config.maximum_leverage),
        "minimum_entry": str(config.minimum_entry_leverage),
    }
    transition_id = f"v8-bootstrap-{_hash(identity)[:32]}"
    return BootstrapDecision(
        transition_id=transition_id,
        environment=environment,
        account_hash=account_hash,
        instrument_id=instrument_id,
        phase=phase.name,
        direction=phase.direction,
        last_transition_kind=phase.last_transition_kind,
        last_transition_at=phase.last_transition_at.isoformat(),
        reference_timestamp=reference.timestamp.isoformat(),
        reference_price=str(reference.price),
        current_timestamp=current.timestamp.isoformat(),
        current_price=str(current.price),
        price_source=current.source,
        reference_source_hash=reference.source_hash,
        current_source_hash=current.source_hash,
        adverse_move_to_reference=str(adverse),
        risk_budget_pct=str(config.max_equity_loss_to_reference_pct),
        eligible_equity=str(eligible_equity),
        leverage_from_reference=str(leverage_from_reference),
        margin_safe_leverage=str(margin_safe_leverage),
        liquidation_safe_leverage=str(liquidation_safe_leverage),
        account_safe_leverage=str(account_safe_leverage),
        calculated_leverage=str(calculated),
        minimum_entry_leverage=str(config.minimum_entry_leverage),
        enter=enter,
        reason=(
            "dynamic bootstrap allowed"
            if enter
            else "calculated leverage is below the minimum entry threshold"
        ),
    )


def finalize_bootstrap(
    decision: BootstrapDecision,
    *,
    adverse_price: Decimal,
    contract_value: Decimal,
    lot_size: Decimal,
    maximum_notional: Decimal,
    margin_safe_notional: Decimal,
) -> BootstrapDecision:
    if decision.state != "PLANNED" or min(
        adverse_price, contract_value, lot_size, maximum_notional, margin_safe_notional
    ) <= 0:
        raise SafetyError("invalid bootstrap finalization inputs")
    leverage = Decimal(decision.calculated_leverage)
    eligible = Decimal(decision.eligible_equity)
    if not decision.enter or leverage <= 0:
        return replace(decision, state="FLAT")
    requested_notional = eligible * leverage
    allowed = min(requested_notional, maximum_notional, margin_safe_notional)
    raw = allowed / (adverse_price * contract_value)
    contracts = (raw / lot_size).to_integral_value(rounding=ROUND_DOWN) * lot_size
    notional = contracts * adverse_price * contract_value
    actual_leverage = notional / eligible
    if contracts <= 0 or actual_leverage > leverage or notional > maximum_notional:
        raise SafetyError("bootstrap quantization violates the calculated leverage or cap")
    return replace(
        decision,
        final_contracts=str(contracts),
        final_notional=str(notional),
        actual_leverage=str(actual_leverage),
    )


class BootstrapDecisionLedger:
    """Atomic exactly-once decision store; raw order state remains in IntentLedger."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[BootstrapDecision]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            decisions = [BootstrapDecision(**row) for row in rows]
        except Exception as exc:
            raise SafetyError("corrupt V8 bootstrap decision ledger") from exc
        if any(
            item.schema != BOOTSTRAP_SCHEMA or item.state not in BOOTSTRAP_STATES
            for item in decisions
        ):
            raise SafetyError("invalid V8 bootstrap decision schema/state")
        identities = [item.transition_id for item in decisions]
        if len(identities) != len(set(identities)):
            raise SafetyError("duplicate V8 bootstrap transition identity")
        return decisions

    def create(self, decision: BootstrapDecision) -> BootstrapDecision:
        rows = self.load()
        if decision.state not in {"PLANNED", "FLAT"}:
            raise SafetyError("new bootstrap decision has an invalid state")
        existing = next(
            (item for item in rows if item.transition_id == decision.transition_id),
            None,
        )
        if existing is not None:
            if existing != decision:
                raise SafetyError("bootstrap transition identity content changed")
            return existing
        self._write([*rows, decision])
        return decision

    def update_state(self, transition_id: str, state: str) -> BootstrapDecision:
        if state not in BOOTSTRAP_STATES:
            raise SafetyError("invalid bootstrap state update")
        rows = self.load()
        updated: BootstrapDecision | None = None
        output: list[BootstrapDecision] = []
        for item in rows:
            if item.transition_id == transition_id:
                updated = replace(item, state=state)
                output.append(updated)
            else:
                output.append(item)
        if updated is None:
            raise SafetyError("unknown bootstrap transition")
        self._write(output)
        return updated

    def _write(self, rows: list[BootstrapDecision]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump([asdict(item) for item in rows], handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
