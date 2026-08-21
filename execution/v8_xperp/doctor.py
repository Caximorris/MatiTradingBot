"""Read-only, local V8 operational diagnosis.

This module deliberately does not construct an exchange client.  It reports whether
the durable runtime artifacts are internally consistent and fresh; it never starts,
resumes, flattens, or reconciles the Demo account.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapter import SafetyError
from .intents import IntentLedger, TERMINAL
from .operator import OperatorControlStore
from .schedule import ScheduleConfig, ScheduleModeStore, parse_utc, runtime_namespace
from .service import CanaryStateStore


DEFAULT_MAX_HEALTH_AGE_SECONDS = 120


@dataclass(frozen=True)
class DoctorReport:
    status: str
    reason: str | None
    checked_at: str
    runtime_root: str
    configured_mode: str
    configured_anchor_utc: str | None
    persisted_mode: str
    persisted_anchor_utc: str | None
    anchors_match: bool
    health_status: str
    health_checked_at: str | None
    health_age_seconds: int | None
    max_health_age_seconds: int
    health_fresh: bool
    canary_state: str
    paused: bool
    manual_stop: bool
    non_terminal_intents: int
    findings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _max_health_age_seconds() -> int:
    raw = os.getenv("V8_XPERP_HEALTH_MAX_AGE_SECONDS", str(DEFAULT_MAX_HEALTH_AGE_SECONDS))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SafetyError("V8_XPERP_HEALTH_MAX_AGE_SECONDS must be an integer") from exc
    if value < 15 or value > 3600:
        raise SafetyError("V8_XPERP_HEALTH_MAX_AGE_SECONDS must be 15-3600 seconds")
    return value


def _read_health(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SafetyError("V8 health artifact is unreadable") from exc
    if not isinstance(value, dict):
        raise SafetyError("V8 health artifact is malformed")
    return value


def _health_timestamp(health: dict[str, Any]) -> datetime | None:
    value = health.get("checked_at", health.get("server_time"))
    if not isinstance(value, str):
        return None
    try:
        return parse_utc(value)
    except SafetyError:
        return None


def inspect_runtime(
    base_root: Path,
    configured: ScheduleConfig,
    *,
    now: datetime | None = None,
) -> DoctorReport:
    """Return a deterministic diagnosis from local artifacts only."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    persisted = ScheduleModeStore(base_root).load()
    runtime_root = runtime_namespace(base_root, configured)
    health = _read_health(runtime_root / "health.json")
    canary = CanaryStateStore(runtime_root / "canary_state.json").load()
    control = OperatorControlStore(runtime_root).load()
    intents = IntentLedger(runtime_root / "intents.json").load()
    non_terminal = sum(item.state not in TERMINAL for item in intents)
    configured_anchor = configured.anchor
    persisted_anchor = (
        parse_utc(persisted.synthetic_anchor_utc)
        if persisted.synthetic_anchor_utc
        else None
    )
    anchors_match = configured_anchor == persisted_anchor
    maximum_age = _max_health_age_seconds()
    recorded_at = _health_timestamp(health)
    age_seconds: int | None = None
    health_fresh = False
    if recorded_at is not None:
        age = (current - recorded_at).total_seconds()
        age_seconds = int(age)
        health_fresh = 0 <= age <= maximum_age

    findings: list[str] = []
    if configured.mode != persisted.mode:
        findings.append("configured and persisted schedule modes disagree")
    if not anchors_match:
        findings.append("configured and persisted synthetic anchors disagree")
    if not health:
        findings.append("no V8 health record exists")
    elif recorded_at is None:
        findings.append("V8 health record has no valid UTC timestamp")
    elif not health_fresh:
        findings.append("V8 health record is stale")
    health_status = str(health.get("status", "NO_HEALTH_RECORD"))
    if health_status == "BLOCKED":
        findings.append(str(health.get("reason", "V8 executor is blocked")))
    if non_terminal:
        findings.append(f"{non_terminal} non-terminal V8 intent(s)")

    if configured.mode != persisted.mode or not anchors_match:
        status, reason = "BLOCKED", findings[0]
    elif health_status == "BLOCKED":
        status, reason = "BLOCKED", str(health.get("reason", "V8 executor is blocked"))
    elif not health_fresh:
        status, reason = "STALE", findings[-1] if findings else "V8 health record is stale"
    elif canary.status != "RUNNING":
        status, reason = "STOPPED", "V8 Demo executor is not running"
    elif non_terminal:
        status, reason = "BLOCKED", findings[-1]
    else:
        status, reason = "HEALTHY", None

    return DoctorReport(
        status=status,
        reason=reason,
        checked_at=current.isoformat(),
        runtime_root=str(runtime_root),
        configured_mode=configured.mode,
        configured_anchor_utc=configured_anchor.isoformat() if configured_anchor else None,
        persisted_mode=persisted.mode,
        persisted_anchor_utc=persisted_anchor.isoformat() if persisted_anchor else None,
        anchors_match=anchors_match,
        health_status=health_status,
        health_checked_at=recorded_at.isoformat() if recorded_at else None,
        health_age_seconds=age_seconds,
        max_health_age_seconds=maximum_age,
        health_fresh=health_fresh,
        canary_state=canary.status,
        paused=control.paused,
        manual_stop=control.manual_stop or canary.manual_stop,
        non_terminal_intents=non_terminal,
        findings=tuple(findings),
    )


def alert_transition(
    report: dict[str, object], previous: str | None
) -> tuple[str, str | None]:
    """Return an idempotent, plain-text alert for a doctor-state transition."""
    status = str(report.get("status", "UNKNOWN"))
    reason = str(report.get("reason") or "no reason recorded")
    fingerprint = f"{status}:{reason}"
    if fingerprint == previous:
        return fingerprint, None
    if status == "HEALTHY":
        return fingerprint, "V8 doctor recovered: local runtime health is current."
    return fingerprint, (
        f"V8 doctor requires attention: {status}; {reason}. "
        "The monitor did not start, resume, flatten, or modify the Demo executor."
    )
