"""Operational safety primitives for the isolated v7 Cycle Core candidate.

This module deliberately knows nothing about allocation policy.  It provides the
append-only evidence, paper-only assertions, and persistent promotion gates that
the deployment controller consumes.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNTIME = Path("data") / "runtime" / "v7"
PROMOTION_GATES = (
    "replay_suite_passed", "adapter_parity_passed", "fault_injection_passed",
    "shadow_soak_hours", "valid_evaluation_windows", "duplicate_transitions",
    "unexplained_error_locks", "fail_open_events", "unreconciled_position_events",
    "v6_regressions", "dataset_identity_unchanged", "production_live_orders",
    "paper_account_verified",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def assert_paper_only(settings: Any, config: dict[str, Any]) -> None:
    """Reject v7 before any order-capable client can be constructed in live mode."""
    if not bool(getattr(settings, "is_paper", False)):
        raise RuntimeError("v7 requires TRADING_MODE=paper; live execution is prohibited")
    if config.get("execution") not in {"v7_shadow", "v7_local_paper"}:
        raise RuntimeError("v7 execution must be an explicitly isolated local paper mode")
    # Presence of generic live credentials is not proof of capability: this v7 path
    # never constructs the live branch.  Record only boolean safety evidence, never values.
    if os.environ.get("TRADING_MODE", "paper").strip().lower() != "paper":
        raise RuntimeError("environment trading mode is not paper")


@dataclass
class PromotionState:
    schema_version: int = 1
    shadow_started_at: str | None = None
    soak_completed_at: str | None = None
    paper_promoted_at: str | None = None
    configuration_hash: str | None = None
    evidence_report: str | None = None
    v7_paper_prerequisite: str = "PENDING"
    counters: dict[str, int] = field(default_factory=lambda: {
        "valid_evaluation_windows": 0, "duplicate_transitions": 0,
        "unexplained_error_locks": 0, "fail_open_events": 0,
        "unreconciled_position_events": 0, "v6_regressions": 0,
        "production_live_orders": 0,
    })
    checks: dict[str, bool] = field(default_factory=lambda: {
        "replay_suite_passed": False, "adapter_parity_passed": False,
        "fault_injection_passed": False, "dataset_identity_unchanged": False,
        "paper_account_verified": False,
    })

    @classmethod
    def load(cls, path: Path) -> "PromotionState":
        raw = read_json(path, {})
        if not isinstance(raw, dict):
            return cls()
        known = {key: raw[key] for key in cls.__dataclass_fields__ if key in raw}
        return cls(**known)

    def save(self, path: Path) -> None:
        atomic_json(path, asdict(self))

    def eligible(self, now: datetime | None = None) -> tuple[bool, list[str]]:
        now = now or utc_now()
        failed = [key for key, value in self.checks.items() if not value]
        if not self.shadow_started_at:
            failed.append("shadow_started_at")
        else:
            started = datetime.fromisoformat(self.shadow_started_at)
            if started.tzinfo is None or (now - started).total_seconds() < 72 * 3600:
                failed.append("shadow_soak_hours>=72")
        if self.counters.get("valid_evaluation_windows", 0) < 18:
            failed.append("valid_evaluation_windows>=18")
        for key in ("duplicate_transitions", "unexplained_error_locks", "fail_open_events",
                    "unreconciled_position_events", "v6_regressions", "production_live_orders"):
            if self.counters.get(key, 0) != 0:
                failed.append(f"{key}=0")
        return (not failed, failed)


class TransitionJournal:
    """Hash-chained JSONL journal. Existing lines are never rewritten."""

    REQUIRED = frozenset({
        "strategy_id", "instance_id", "transition_id", "previous_phase", "new_phase",
        "previous_target", "new_target", "decision_timestamp", "market_data_timestamp",
        "expected_position", "actual_position", "order_id", "fill_ids", "fees", "slippage",
        "status", "retry_count", "state_hash_before", "state_hash_after", "reason",
    })

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        missing = self.REQUIRED - set(event)
        if missing:
            raise ValueError(f"transition journal missing fields: {sorted(missing)}")
        previous = ""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if lines:
                previous = str(json.loads(lines[-1]).get("entry_hash", ""))
        except (OSError, ValueError):
            previous = ""
        record = dict(event)
        record["logged_at"] = utc_now().isoformat()
        record["previous_entry_hash"] = previous
        record["entry_hash"] = canonical_hash(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return record
