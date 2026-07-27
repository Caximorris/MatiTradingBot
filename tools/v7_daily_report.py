#!/usr/bin/env python
# ruff: noqa: E402
"""Persist a read-only daily v6-versus-v7 operational comparison."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_operations import RUNTIME, atomic_json, canonical_hash
from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import make_config


def _journal_tail(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    except (OSError, IndexError, ValueError):
        return {}


def _build_certified(root: Path) -> dict:
    """Read-only health report for the separate certified V7 candidate."""
    config = make_config(root)
    state = (
        json.loads(config.wallet_path.read_text(encoding="utf-8"))
        if config.wallet_path.exists()
        else None
    )
    healthy = (
        state is not None
        and not state.get("locked")
        and state.get("candidate_hash") == config.candidate_hash
    )
    journal = (
        []
        if not config.journal_path.is_file()
        else [
            json.loads(line)
            for line in config.journal_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    )
    fills = [row for row in journal if row.get("event") == "actual_fill"]
    intents = [row for row in journal if row.get("event") == "actual_intent"]
    owner = DemoAccountLease(
        root / "data" / "runtime" / "v7_certified" / "account_ownership.jsonl"
    ).current()
    report = {
        "candidate": "V7 certified isolated paper candidate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cash": None if state is None else state.get("cash"),
        "BTC_quantity": None if state is None else state.get("btc"),
        "pending_intent_order": None if state is None else state.get("pending"),
        "activation_baseline": None
        if state is None
        else state.get("activation_baseline"),
        "account_owner": None
        if owner is None
        else {
            "strategy": owner.get("owner_strategy_id"),
            "instance": owner.get("owner_instance_id"),
        },
        "daily_orders": len(intents),
        "daily_fills": len(fills),
        "actual_orders_and_fills": fills,
        "circuit_breaker_status": "NOT_STARTED"
        if state is None
        else ("LOCKED" if state.get("locked") else "CLEAR"),
        "candidate_hash": config.candidate_hash,
        "configuration_hash": config.configuration_hash,
        "source_hash": config.source_hash,
        "paper_vs_replay_parity_verdict": "NOT_STARTED"
        if state is None
        else ("PASS" if healthy else "FAIL_CLOSED"),
    }
    report["report_hash"] = canonical_hash(report)
    return report


def build(root: Path = ROOT) -> dict:
    if root != ROOT:
        return _build_certified(root)
    from core.database import BotState, get_session, init_db

    init_db()
    with get_session() as session:
        rows = {row.strategy_name: row for row in session.query(BotState).all()}
    v6 = next(
        (row for name, row in rows.items() if name.startswith("swing_allocator_v6_")),
        None,
    )
    v7 = {
        name: row
        for name, row in rows.items()
        if name.startswith("swing_cycle_core_v7_")
    }
    v7_view = {}
    for name, row in v7.items():
        cfg = row.get_config()
        instance = cfg.get("instance_id", "unknown")
        event = _journal_tail(Path(cfg.get("transition_journal_path", "")))
        v7_view[name] = {
            "active": row.is_active,
            "last_run": str(row.last_run),
            "mode": cfg.get("operational_mode"),
            "target": event.get("new_target"),
            "phase": event.get("new_phase"),
            "state": event.get("status"),
            "journal": cfg.get("transition_journal_path"),
            "instance_id": instance,
        }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "v6": None
        if v6 is None
        else {
            "active": v6.is_active,
            "last_run": str(v6.last_run),
            "config_hash": canonical_hash(v6.get_config()),
        },
        "v7": v7_view,
        "divergence_explanation": "Expected policy divergence: v6 uses its frozen regime/funding allocator; v7 uses the frozen 540/900 cycle clock. Any execution-state mismatch is not expected.",
        "alerts": [],
    }
    report["report_hash"] = canonical_hash(report)
    path = (
        RUNTIME
        / "reports"
        / f"v6_v7_{datetime.now(timezone.utc).date().isoformat()}.json"
    )
    atomic_json(path, report)
    report["path"] = str(path)
    return report


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
