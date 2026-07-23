"""Operational safety primitives for the isolated v7 Cycle Core candidate.

This module deliberately knows nothing about allocation policy.  It provides the
append-only evidence, paper-only assertions, and persistent promotion gates that
the deployment controller consumes.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
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
V7_FROZEN_GATE_INPUTS = {
    "evidence_schema_version": 1,
    "operational_tests": (
        "tests/test_swing_cycle_core.py",
        "tests/test_v7_operations.py",
    ),
}
V7_EVIDENCE_FILES = (
    "strategies/swing_cycle_core.py",
    "core/v7_operations.py",
    "tools/v7_operational_validation.py",
    "tools/v7_promotion_controller.py",
    "tests/test_swing_cycle_core.py",
    "tests/test_v7_operations.py",
)
_PROMOTION_CHECKS = (
    "replay_suite_passed", "adapter_parity_passed", "fault_injection_passed",
    "dataset_identity_unchanged", "paper_account_verified",
    "transition_journal_valid", "shadow_state_valid", "configuration_evidence_valid",
)
_ZERO_EVENT_COUNTERS = (
    "duplicate_transitions", "unexplained_error_locks", "fail_open_events",
    "unreconciled_position_events", "v6_regressions", "production_live_orders",
)
V7_STATE_SCHEMA_VERSION = 2
V7_STATE_KEYS = frozenset({
    "version", "state", "phase", "last_block", "order_id", "pending_order", "error",
})
V7_STATES = frozenset({
    "STABLE_RISK_ON", "EXIT_PENDING", "EXIT_ORDER_SUBMITTED", "BEAR_CASH",
    "ENTRY_PENDING", "ENTRY_ORDER_SUBMITTED", "ERROR_LOCKED",
})
V7_PHASES = frozenset({"post_halving", "bull_peak", "bear_onset", "accumulation"})


class JournalIntegrityError(ValueError):
    """Evidence journal is incomplete, tampered, or internally inconsistent."""


def canonical_unlocked_v7_state() -> dict[str, Any]:
    """The only state shape an operator may write when clearing an ERROR_LOCKED."""
    return {
        "version": V7_STATE_SCHEMA_VERSION,
        "state": "STABLE_RISK_ON",
        "phase": None,
        "last_block": None,
        "order_id": None,
        "pending_order": None,
        "error": None,
    }


def is_valid_v7_state(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != V7_STATE_KEYS:
        return False
    if (type(value.get("version")) is not int
            or value.get("version") != V7_STATE_SCHEMA_VERSION
            or value.get("state") not in V7_STATES):
        return False
    if value["phase"] is not None and value["phase"] not in V7_PHASES:
        return False
    for key in ("phase", "last_block", "order_id", "error"):
        if value[key] is not None and not isinstance(value[key], str):
            return False
    submitted = {"EXIT_ORDER_SUBMITTED", "ENTRY_ORDER_SUBMITTED"}
    if value["state"] in submitted:
        return (isinstance(value["order_id"], str) and bool(value["order_id"])
                and isinstance(value["pending_order"], dict))
    return value["order_id"] is None and value["pending_order"] is None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def v7_evidence_source_hashes(root: Path) -> dict[str, Any]:
    """Return the immutable source/test identities required by v7 promotion evidence."""
    hashes: dict[str, str] = {}
    for relative in V7_EVIDENCE_FILES:
        try:
            hashes[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError(f"v7 evidence file unreadable: {relative}") from exc
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=False, capture_output=True,
            text=True, timeout=2,
        )
        revision = completed.stdout.strip() if completed.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        revision = None
    return {"files": hashes, "revision": revision}


def v7_configuration_evidence_hash(shadow_config: dict[str, Any], *, root: Path) -> str:
    """Hash resolved config, frozen inputs, and exact v7 source/test identities."""
    if not isinstance(shadow_config, dict):
        raise ValueError("shadow configuration evidence must be a dictionary")
    return canonical_hash({
        "shadow_config": shadow_config,
        "frozen_gate_inputs": V7_FROZEN_GATE_INPUTS,
        "source_identity": v7_evidence_source_hashes(root),
    })


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
        "paper_account_verified": False, "transition_journal_valid": False,
        "shadow_state_valid": False, "configuration_evidence_valid": False,
    })

    @classmethod
    def load(cls, path: Path) -> "PromotionState":
        raw = read_json(path, {})
        if not isinstance(raw, dict) or raw.get("schema_version", 1) != 1:
            return cls()
        known = {key: raw[key] for key in cls.__dataclass_fields__ if key in raw}
        try:
            loaded = cls(**known)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(loaded.checks, dict) or not isinstance(loaded.counters, dict):
            return cls()
        # Persisted state is untrusted evidence. Missing or non-boolean checks must
        # never become implicit passes after a schema upgrade or manual edit.
        loaded.checks = {
            key: loaded.checks.get(key) is True for key in _PROMOTION_CHECKS
        }
        defaults = cls().counters
        loaded.counters = {
            key: value if type(value) is int and value >= 0 else defaults[key]
            for key, value in ((key, loaded.counters.get(key, defaults[key])) for key in defaults)
        }
        return loaded

    def save(self, path: Path) -> None:
        atomic_json(path, asdict(self))

    def eligible(self, now: datetime | None = None) -> tuple[bool, list[str]]:
        now = now or utc_now()
        failed = [key for key in _PROMOTION_CHECKS if self.checks.get(key) is not True]
        if not self.shadow_started_at:
            failed.append("shadow_started_at")
        else:
            try:
                started = datetime.fromisoformat(self.shadow_started_at)
            except (TypeError, ValueError):
                started = None
            if started is None or started.tzinfo is None or (now - started).total_seconds() < 72 * 3600:
                failed.append("shadow_soak_hours>=72")
        if self.counters.get("valid_evaluation_windows", 0) < 18:
            failed.append("valid_evaluation_windows>=18")
        for key in _ZERO_EVENT_COUNTERS:
            if type(self.counters.get(key)) is not int or self.counters[key] != 0:
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
    _STRING_FIELDS = frozenset({
        "strategy_id", "instance_id", "transition_id", "previous_phase", "new_phase",
        "previous_target", "new_target", "expected_position", "actual_position", "order_id",
        "fees", "slippage", "status", "state_hash_before", "state_hash_after", "reason",
        "logged_at", "previous_entry_hash", "entry_hash",
    })

    def __init__(self, path: Path) -> None:
        self.path = path

    def validate(self, *, strategy_id: str | None = None,
                 instance_id: str | None = None) -> list[dict[str, Any]]:
        """Return verified entries or reject the entire journal.

        Promotion never treats a partial prefix as evidence: one malformed line,
        broken hash, duplicate transition, or unexpected identity invalidates the
        complete journal.
        """
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise JournalIntegrityError(f"transition journal unreadable: {exc}") from exc
        if not lines:
            raise JournalIntegrityError("transition journal is empty")
        expected_previous = ""
        seen_ids: set[str] = set()
        entries: list[dict[str, Any]] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                raise JournalIntegrityError(f"blank transition journal line {number}")
            try:
                record = json.loads(line)
            except (TypeError, ValueError) as exc:
                raise JournalIntegrityError(f"malformed transition journal line {number}") from exc
            if not isinstance(record, dict):
                raise JournalIntegrityError(f"non-object transition journal line {number}")
            missing = (self.REQUIRED | {"logged_at", "previous_entry_hash", "entry_hash"}) - set(record)
            if missing:
                raise JournalIntegrityError(f"transition journal line {number} missing {sorted(missing)}")
            if (any(not isinstance(record[key], str) for key in self._STRING_FIELDS)
                    or not isinstance(record["fill_ids"], list)
                    or any(not isinstance(item, str) for item in record["fill_ids"])
                    or type(record["retry_count"]) is not int or record["retry_count"] < 0):
                raise JournalIntegrityError(f"invalid transition journal schema at line {number}")
            if record.get("previous_entry_hash") != expected_previous:
                raise JournalIntegrityError(f"transition journal chain mismatch at line {number}")
            entry_hash = record.get("entry_hash")
            hashed = dict(record)
            hashed.pop("entry_hash", None)
            if not isinstance(entry_hash, str) or entry_hash != canonical_hash(hashed):
                raise JournalIntegrityError(f"transition journal hash mismatch at line {number}")
            transition_id = record.get("transition_id")
            if not isinstance(transition_id, str) or not transition_id or transition_id in seen_ids:
                raise JournalIntegrityError(f"duplicate or invalid transition id at line {number}")
            if strategy_id is not None and record.get("strategy_id") != strategy_id:
                raise JournalIntegrityError(f"unexpected strategy identity at line {number}")
            if instance_id is not None and record.get("instance_id") != instance_id:
                raise JournalIntegrityError(f"unexpected instance identity at line {number}")
            for timestamp_key in ("logged_at", "decision_timestamp", "market_data_timestamp"):
                try:
                    timestamp = datetime.fromisoformat(str(record[timestamp_key]).replace("Z", "+00:00"))
                except ValueError as exc:
                    raise JournalIntegrityError(f"invalid {timestamp_key} at line {number}") from exc
                if timestamp.tzinfo is None:
                    raise JournalIntegrityError(f"naive {timestamp_key} at line {number}")
            expected_previous = entry_hash
            seen_ids.add(transition_id)
            entries.append(record)
        return entries

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        missing = self.REQUIRED - set(event)
        if missing:
            raise ValueError(f"transition journal missing fields: {sorted(missing)}")
        previous = ""
        if self.path.exists():
            entries = self.validate()
            previous = entries[-1]["entry_hash"]
        record = dict(event)
        record["logged_at"] = utc_now().isoformat()
        record["previous_entry_hash"] = previous
        record["entry_hash"] = canonical_hash(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return record
