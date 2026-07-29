"""Fail-closed V8 real/synthetic schedule selection and deterministic previews."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping

from .adapter import ENVIRONMENT, SafetyError

REAL_CYCLE = "real_cycle"
SYNTHETIC_DEMO_CYCLE = "synthetic_demo_cycle"
SCHEDULE_MODES = {REAL_CYCLE, SYNTHETIC_DEMO_CYCLE}
STRATEGY_VERSION = "v8"
CYCLE_LENGTH = timedelta(days=4)
BEAR_OFFSET = timedelta(days=2)
ACCUMULATION_OFFSET = timedelta(days=3)


def parse_utc(value: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise SafetyError("synthetic cycle anchor is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SafetyError("synthetic cycle anchor must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SafetyError("synthetic cycle anchor must be explicitly UTC")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class ScheduleConfig:
    mode: str = REAL_CYCLE
    synthetic_enabled: bool = False
    synthetic_anchor_utc: str | None = None
    environment: str = ENVIRONMENT
    live_execution_enabled: bool = False

    @classmethod
    def from_env(
        cls, source: Mapping[str, str] | None = None, *, environment: str = ENVIRONMENT
    ) -> "ScheduleConfig":
        values = source if source is not None else os.environ
        config = cls(
            mode=values.get("V8_SCHEDULE_MODE", REAL_CYCLE).strip(),
            synthetic_enabled=(
                values.get("V8_SYNTHETIC_DEMO_CYCLE_ENABLED", "").lower() == "true"
            ),
            synthetic_anchor_utc=(
                values.get("V8_SYNTHETIC_CYCLE_ANCHOR_UTC", "").strip() or None
            ),
            environment=environment,
            live_execution_enabled=(
                values.get("V8_LIVE_EXECUTION_ENABLED", "").lower() == "true"
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in SCHEDULE_MODES:
            raise SafetyError("unknown V8 schedule mode")
        if self.live_execution_enabled:
            raise SafetyError("V8 live execution must remain disabled")
        if self.mode == SYNTHETIC_DEMO_CYCLE:
            if self.environment != "okx_demo":
                raise SafetyError("synthetic schedule is restricted to OKX Demo")
            if not self.synthetic_enabled:
                raise SafetyError("synthetic Demo cycle requires its explicit enable flag")
            if not self.synthetic_anchor_utc:
                raise SafetyError("synthetic Demo cycle requires an explicit UTC anchor")
            parse_utc(self.synthetic_anchor_utc)

    @property
    def anchor(self) -> datetime | None:
        return parse_utc(self.synthetic_anchor_utc) if self.synthetic_anchor_utc else None


@dataclass(frozen=True)
class ScheduleEvent:
    environment: str
    schedule_mode: str
    cycle_number: int
    event_type: str
    effective_at: str
    direction: str
    strategy_leverage: str
    transition_id: str


@dataclass(frozen=True)
class SchedulePreview:
    environment: str
    schedule_mode: str
    synthetic_anchor: str
    synthetic_cycle_number: int
    last_synthetic_halving: str
    current_synthetic_day: str
    current_phase: str
    next_day_2_transition: str
    next_day_3_transition: str
    next_synthetic_halving: str
    current_target: str
    transition_due: bool


@dataclass(frozen=True)
class ModeState:
    mode: str = REAL_CYCLE
    synthetic_anchor_utc: str | None = None
    updated_at: str | None = None
    operator_acknowledgement: str | None = None


def _identity(
    environment: str, mode: str, cycle: int, event_type: str, effective: datetime
) -> str:
    raw = (
        f"{environment}|{mode}|{cycle}|{event_type}|"
        f"{effective.astimezone(UTC).isoformat()}|{STRATEGY_VERSION}"
    )
    return f"v8-{mode}-{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def synthetic_event(
    config: ScheduleConfig, cycle: int, event_type: str
) -> ScheduleEvent:
    config.validate()
    anchor = config.anchor
    if config.mode != SYNTHETIC_DEMO_CYCLE or anchor is None or cycle < 0:
        raise SafetyError("invalid synthetic schedule event request")
    offsets = {
        "synthetic_halving": (timedelta(0), "long"),
        "bear_transition": (BEAR_OFFSET, "short"),
        "accumulation_transition": (ACCUMULATION_OFFSET, "long"),
    }
    if event_type not in offsets:
        raise SafetyError("invalid synthetic event type")
    offset, direction = offsets[event_type]
    effective = anchor + cycle * CYCLE_LENGTH + offset
    return ScheduleEvent(
        config.environment,
        config.mode,
        cycle,
        event_type,
        effective.isoformat(),
        direction,
        "2",
        _identity(config.environment, config.mode, cycle, event_type, effective),
    )


def synthetic_events_between(
    config: ScheduleConfig,
    *,
    previous_observed_at: datetime | None,
    now: datetime,
) -> list[ScheduleEvent]:
    config.validate()
    anchor = config.anchor
    if config.mode != SYNTHETIC_DEMO_CYCLE or anchor is None:
        return []
    if now.tzinfo is None or (
        previous_observed_at is not None and previous_observed_at.tzinfo is None
    ):
        raise SafetyError("synthetic schedule timestamps must be timezone-aware")
    current = now.astimezone(UTC)
    previous = (
        previous_observed_at.astimezone(UTC) if previous_observed_at else anchor - timedelta(microseconds=1)
    )
    if previous > current:
        raise SafetyError("synthetic schedule server time moved backwards")
    if current < anchor:
        return []
    final_cycle = int((current - anchor) // CYCLE_LENGTH)
    first_cycle = max(0, int(max(timedelta(0), previous - anchor) // CYCLE_LENGTH))
    events: list[ScheduleEvent] = []
    for cycle in range(first_cycle, final_cycle + 1):
        for event_type in (
            "synthetic_halving",
            "bear_transition",
            "accumulation_transition",
        ):
            event = synthetic_event(config, cycle, event_type)
            effective = parse_utc(event.effective_at)
            if previous < effective <= current:
                events.append(event)
    return sorted(events, key=lambda item: item.effective_at)


def synthetic_preview(
    config: ScheduleConfig,
    *,
    now: datetime,
    previous_observed_at: datetime | None = None,
) -> SchedulePreview:
    config.validate()
    anchor = config.anchor
    if config.mode != SYNTHETIC_DEMO_CYCLE or anchor is None:
        raise SafetyError("synthetic preview requires synthetic Demo mode")
    if now.tzinfo is None or (
        previous_observed_at is not None and previous_observed_at.tzinfo is None
    ):
        raise SafetyError("synthetic preview timestamps must be timezone-aware")
    current = now.astimezone(UTC)
    cycle = max(0, int(max(timedelta(0), current - anchor) // CYCLE_LENGTH))
    cycle_anchor = anchor + cycle * CYCLE_LENGTH
    elapsed = current - cycle_anchor
    if current < anchor:
        phase, direction, elapsed = "pending", "flat", timedelta(0)
        cycle = 0
        cycle_anchor = anchor
    elif elapsed < BEAR_OFFSET:
        phase, direction = "long_phase", "long"
    elif elapsed < ACCUMULATION_OFFSET:
        phase, direction = "short_phase", "short"
    else:
        phase, direction = "long_phase", "long"
    due = bool(
        synthetic_events_between(
            config, previous_observed_at=previous_observed_at, now=current
        )
    )
    return SchedulePreview(
        config.environment,
        config.mode,
        config.anchor.isoformat(),
        cycle,
        cycle_anchor.isoformat(),
        str(elapsed.total_seconds() / 86400),
        phase,
        (cycle_anchor + BEAR_OFFSET).isoformat()
        if elapsed < BEAR_OFFSET
        else (cycle_anchor + CYCLE_LENGTH + BEAR_OFFSET).isoformat(),
        (cycle_anchor + ACCUMULATION_OFFSET).isoformat()
        if elapsed < ACCUMULATION_OFFSET
        else (cycle_anchor + CYCLE_LENGTH + ACCUMULATION_OFFSET).isoformat(),
        (cycle_anchor + CYCLE_LENGTH).isoformat(),
        f"{direction} 2x" if direction != "flat" else "flat",
        due,
    )


class ScheduleEventLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[ScheduleEvent]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            events = [ScheduleEvent(**row) for row in rows]
        except Exception as exc:
            raise SafetyError("corrupt V8 schedule event ledger") from exc
        ids = [item.transition_id for item in events]
        if len(ids) != len(set(ids)):
            raise SafetyError("duplicate V8 schedule transition identity")
        return events

    def append(self, event: ScheduleEvent) -> ScheduleEvent:
        rows = self.load()
        existing = next((item for item in rows if item.transition_id == event.transition_id), None)
        if existing:
            if existing != event:
                raise SafetyError("schedule transition identity content changed")
            return existing
        _atomic_json(self.path, [*(asdict(item) for item in rows), asdict(event)])
        return event


class ScheduleModeStore:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.path = base / "schedule_mode.json"
        self.archive_dir = base / "schedule_mode_archive"

    def load(self) -> ModeState:
        if not self.path.exists():
            return ModeState()
        try:
            state = ModeState(**json.loads(self.path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise SafetyError("corrupt V8 schedule mode state") from exc
        if state.mode not in SCHEDULE_MODES:
            raise SafetyError("invalid persisted V8 schedule mode")
        if state.synthetic_anchor_utc:
            parse_utc(state.synthetic_anchor_utc)
        return state

    def switch(
        self,
        *,
        new_mode: str,
        service_stopped: bool,
        reconciled: bool,
        position_contracts: str,
        open_orders: int,
        non_terminal_intents: int,
        acknowledgement: str,
        config: ScheduleConfig,
        now: datetime,
    ) -> ModeState:
        if new_mode not in SCHEDULE_MODES:
            raise SafetyError("unknown V8 schedule mode")
        if not acknowledgement.strip():
            raise SafetyError("schedule mode switch requires operator acknowledgement")
        if not service_stopped or not reconciled:
            raise SafetyError("schedule mode switch requires a stopped reconciled service")
        if (
            position_contracts != "0"
            or open_orders
            or non_terminal_intents
        ):
            raise SafetyError(
                "schedule mode switch requires flat position, zero orders, and terminal intents"
            )
        candidate = ScheduleConfig(
            mode=new_mode,
            synthetic_enabled=config.synthetic_enabled,
            synthetic_anchor_utc=config.synthetic_anchor_utc,
            environment=config.environment,
            live_execution_enabled=config.live_execution_enabled,
        )
        candidate.validate()
        current = self.load()
        timestamp = now.astimezone(UTC)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        archive = self.archive_dir / (
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{current.mode}.json"
        )
        _atomic_json(archive, asdict(current))
        updated = ModeState(
            new_mode,
            candidate.synthetic_anchor_utc,
            timestamp.isoformat(),
            acknowledgement.strip(),
        )
        _atomic_json(self.path, asdict(updated))
        return updated

    def set_anchor(
        self,
        anchor: str,
        *,
        service_stopped: bool,
        reconciled: bool,
        position_contracts: str,
        open_orders: int,
        non_terminal_intents: int,
        acknowledgement: str,
        now: datetime,
    ) -> ModeState:
        parsed = parse_utc(anchor)
        if parsed <= now.astimezone(UTC):
            raise SafetyError(
                "new synthetic anchor must be future UTC to avoid ambiguous transitions"
            )
        if (
            not service_stopped
            or not reconciled
            or position_contracts != "0"
            or open_orders
            or non_terminal_intents
            or not acknowledgement.strip()
        ):
            raise SafetyError(
                "synthetic anchor change requires stopped, flat, order-free, "
                "intent-free reconciliation and acknowledgement"
            )
        current = self.load()
        updated = ModeState(
            current.mode,
            parsed.isoformat(),
            now.astimezone(UTC).isoformat(),
            acknowledgement.strip(),
        )
        _atomic_json(self.path, asdict(updated))
        return updated


def runtime_namespace(base: Path, config: ScheduleConfig) -> Path:
    """Keep legacy real state adoptable; synthetic state is always isolated."""
    return base if config.mode == REAL_CYCLE else base / SYNTHETIC_DEMO_CYCLE


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
