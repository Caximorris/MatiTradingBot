"""Exactly-once operational target identities for the continuous V8 service."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from strategies.cycle_phase_clock import CyclePhaseClock

from .adapter import SafetyError
from .bootstrap import BootstrapDecision

TARGET_SCHEMA = 1
TARGET_STATES = {"PLANNED", "EXECUTED", "ADOPTED", "FLAT", "SUPERSEDED"}
EXACT_START_WINDOW = timedelta(hours=2)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperationalTarget:
    transition_id: str
    kind: str
    direction: str
    strategy_leverage: str
    final_contracts: str
    final_notional: str
    actual_leverage: str
    effective_at: str
    source_id: str
    state: str = "PLANNED"
    schema: int = TARGET_SCHEMA

    @property
    def signed_contracts(self) -> Decimal:
        contracts = Decimal(self.final_contracts)
        return contracts if self.direction == "long" else -contracts if self.direction == "short" else Decimal("0")


@dataclass(frozen=True)
class TransportState:
    last_observed_at: str | None = None
    active_transition_id: str | None = None
    explicit_flat_requested: bool = False


@dataclass(frozen=True)
class TransportDecision:
    action: str
    target: OperationalTarget | None
    reason: str


def scheduled_target(
    *,
    at: datetime,
    previous_observed_at: datetime | None,
    clock: CyclePhaseClock | None = None,
) -> OperationalTarget | None:
    if at.tzinfo is None or (
        previous_observed_at is not None and previous_observed_at.tzinfo is None
    ):
        raise SafetyError("scheduled transport timestamps must be timezone-aware")
    now = at.astimezone(UTC)
    previous = previous_observed_at.astimezone(UTC) if previous_observed_at else None
    active = clock or CyclePhaseClock()
    transitions: list[tuple[datetime, str]] = []
    for halving in active.halving_timestamps:
        transitions.extend((
            (halving + timedelta(days=active.bear_onset_start), "short"),
            (halving + timedelta(days=active.accumulation_start), "long"),
        ))
    due = [
        item for item in sorted(transitions)
        if (
            previous is not None and previous < item[0] <= now
        ) or (
            previous is None and item[0] <= now <= item[0] + EXACT_START_WINDOW
        )
    ]
    if len(due) > 1:
        raise SafetyError("multiple scheduled V8 transitions were missed")
    if not due:
        return None
    effective, direction = due[0]
    identity = f"okx_demo|scheduled|{effective.isoformat()}|{direction}|2"
    return OperationalTarget(
        transition_id=f"v8-scheduled-{_hash(identity)[:32]}",
        kind="scheduled_540_900",
        direction=direction,
        strategy_leverage="2",
        final_contracts="0",
        final_notional="0",
        actual_leverage="0",
        effective_at=effective.isoformat(),
        source_id=effective.isoformat(),
    )


def target_from_bootstrap(decision: BootstrapDecision) -> OperationalTarget:
    if decision.state not in {"PLANNED", "EXECUTED", "FLAT"}:
        raise SafetyError("bootstrap decision is not executable")
    return OperationalTarget(
        transition_id=decision.transition_id,
        kind="operational_bootstrap",
        direction=decision.direction if decision.enter else "flat",
        strategy_leverage=decision.calculated_leverage,
        final_contracts=decision.final_contracts,
        final_notional=decision.final_notional,
        actual_leverage=decision.actual_leverage,
        effective_at=decision.current_timestamp,
        source_id=decision.transition_id,
        state="PLANNED" if decision.enter else "FLAT",
    )


def decide_transport(
    *,
    now: datetime,
    previous_observed_at: datetime | None,
    current_position: Decimal,
    active_target: OperationalTarget | None,
    bootstrap_target: OperationalTarget | None,
    explicit_flat_requested: bool = False,
    clock: CyclePhaseClock | None = None,
) -> TransportDecision:
    due = scheduled_target(
        at=now, previous_observed_at=previous_observed_at, clock=clock
    )
    if explicit_flat_requested:
        if current_position == 0:
            return TransportDecision("NOOP", None, "explicit flat already satisfied")
        identity = f"okx_demo|operator-flat|{now.astimezone(UTC).isoformat()}"
        target = OperationalTarget(
            f"v8-operator-flat-{_hash(identity)[:32]}",
            "operator_flat", "flat", "0", "0", "0", "0",
            now.astimezone(UTC).isoformat(), "operator",
        )
        return TransportDecision("EXECUTE", target, "explicit operator flat")
    if due is not None:
        return TransportDecision(
            "EXECUTE", due, "scheduled 540/900 transition became effective"
        )
    if current_position != 0:
        if active_target is None:
            raise SafetyError("known position lacks a frozen operational target")
        if (
            active_target.direction == "flat"
            or current_position != active_target.signed_contracts
        ):
            raise SafetyError("position and frozen operational target disagree")
        return TransportDecision(
            "ADOPT",
            replace(active_target, state="ADOPTED"),
            "process restart adopted the existing target without recalculation",
        )
    if active_target is not None and active_target.direction != "flat":
        return TransportDecision(
            "RESTORE",
            replace(active_target, state="PLANNED"),
            "startup reconciliation proved a flat mismatch to the frozen target",
        )
    if bootstrap_target is None:
        return TransportDecision("NOOP", None, "no new operational target is required")
    if bootstrap_target.direction == "flat":
        return TransportDecision("NOOP", bootstrap_target, "bootstrap remains flat")
    return TransportDecision("EXECUTE", bootstrap_target, "new flat mid-phase bootstrap")


class OperationalTargetLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[OperationalTarget]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            targets = [OperationalTarget(**row) for row in rows]
        except Exception as exc:
            raise SafetyError("corrupt V8 operational target ledger") from exc
        if any(
            item.schema != TARGET_SCHEMA
            or item.state not in TARGET_STATES
            or item.direction not in {"flat", "long", "short"}
            for item in targets
        ):
            raise SafetyError("invalid V8 operational target schema/state")
        identities = [item.transition_id for item in targets]
        if len(identities) != len(set(identities)):
            raise SafetyError("duplicate V8 operational target identity")
        return targets

    def active(self) -> OperationalTarget | None:
        active = [
            item for item in self.load()
            if item.state in {"PLANNED", "EXECUTED", "ADOPTED"}
        ]
        if len(active) > 1:
            raise SafetyError("multiple active V8 operational targets")
        return active[0] if active else None

    def create(self, target: OperationalTarget) -> OperationalTarget:
        rows = self.load()
        existing = next(
            (item for item in rows if item.transition_id == target.transition_id), None
        )
        if existing:
            if existing != target:
                raise SafetyError("operational target identity content changed")
            return existing
        active = [
            item for item in rows
            if item.state in {"PLANNED", "EXECUTED", "ADOPTED"}
        ]
        if active:
            rows = [
                replace(item, state="SUPERSEDED")
                if item.transition_id == active[0].transition_id
                else item
                for item in rows
            ]
        self._write([*rows, target])
        return target

    def update(self, transition_id: str, state: str) -> OperationalTarget:
        if state not in TARGET_STATES:
            raise SafetyError("invalid operational target state update")
        rows = self.load()
        updated: OperationalTarget | None = None
        output: list[OperationalTarget] = []
        for item in rows:
            if item.transition_id == transition_id:
                updated = replace(item, state=state)
                output.append(updated)
            else:
                output.append(item)
        if updated is None:
            raise SafetyError("unknown operational target")
        self._write(output)
        return updated

    def _write(self, rows: list[OperationalTarget]) -> None:
        _atomic_json(self.path, [asdict(item) for item in rows])


class TransportStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> TransportState:
        if not self.path.exists():
            return TransportState()
        try:
            return TransportState(**json.loads(self.path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise SafetyError("corrupt V8 target transport state") from exc

    def write(self, state: TransportState) -> None:
        _atomic_json(self.path, asdict(state))


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
