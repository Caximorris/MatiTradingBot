#!/usr/bin/env python
# ruff: noqa: E402
"""Persistent, fail-closed v7 shadow soak and promotion gate evaluator."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_operations import (
    JournalIntegrityError,
    PromotionState,
    RUNTIME,
    TransitionJournal,
    atomic_json,
    canonical_hash,
    is_valid_v7_state,
    v7_configuration_evidence_hash,
)
from strategies.swing_cycle_core import SwingCycleCoreBot, SwingCycleCoreConfig
from tools.v7_paper_setup import PAPER_NAME, SHADOW_NAME, config_for

STATE_PATH = RUNTIME / "promotion_state.json"
REPORT_PATH = RUNTIME / "promotion_report.json"


def _shadow_journal_identity() -> tuple[str, str]:
    """Derive the journal identity from the real shadow bot contract."""
    config = SwingCycleCoreConfig.from_dict(config_for("shadow"))
    return SwingCycleCoreBot(None, config).name, config.instance_id


def _shadow_configuration_evidence_hash() -> str:
    return v7_configuration_evidence_hash(config_for("shadow"), root=ROOT)


def _shadow_state() -> dict | None:
    """Read the persisted v7 state without creating rows or initializing the DB."""
    try:
        from core.database import BotState, get_session
        with get_session() as session:
            row = session.query(BotState).filter_by(
                strategy_name=SHADOW_NAME, symbol="BTC-USDT"
            ).first()
            return row.get_config() if row is not None else None
    except Exception:
        return None


def _valid_shadow_state(value: object) -> bool:
    return is_valid_v7_state(value)


def _derived_zero_counters(events: list[dict], shadow_state: dict) -> dict[str, int]:
    """Derive, never retain, every zero-event promotion counter from evidence."""
    statuses = [str(event["status"]).lower() for event in events]
    reasons = [str(event["reason"]).lower() for event in events]
    submitted = {"EXIT_ORDER_SUBMITTED", "ENTRY_ORDER_SUBMITTED"}
    return {
        "duplicate_transitions": 0,  # validation rejects the first duplicate.
        "unexplained_error_locks": int(shadow_state["state"] == "ERROR_LOCKED"),
        "fail_open_events": sum(status in {"fail_open", "continued_after_failure"} for status in statuses),
        "unreconciled_position_events": int(
            shadow_state["state"] in submitted
            or shadow_state["pending_order"] is not None
            or shadow_state["order_id"] is not None
        ),
        "v6_regressions": sum("v6_regression" in reason for reason in reasons),
        "production_live_orders": sum(
            status in {"live_order", "production_live_order"} for status in statuses
        ),
    }


def update(state: PromotionState, *, now: datetime | None = None,
           journal_path: Path | None = None, shadow_state: dict | None = None) -> PromotionState:
    now = now or datetime.now(timezone.utc)
    shadow_journal = journal_path or RUNTIME / "v7_btc_usdt_shadow" / "transitions.jsonl"
    strategy_id, instance_id = _shadow_journal_identity()
    try:
        expected_evidence_hash = _shadow_configuration_evidence_hash()
    except ValueError:
        expected_evidence_hash = None
    state.checks["configuration_evidence_valid"] = (
        isinstance(state.configuration_hash, str)
        and state.configuration_hash == expected_evidence_hash
    )
    try:
        events = TransitionJournal(shadow_journal).validate(
            strategy_id=strategy_id, instance_id=instance_id
        )
    except JournalIntegrityError:
        state.checks["transition_journal_valid"] = False
        state.counters["valid_evaluation_windows"] = 0
        state.counters.update({key: 1 for key in (
            "duplicate_transitions", "unexplained_error_locks", "fail_open_events",
            "unreconciled_position_events", "v6_regressions", "production_live_orders",
        )})
        return state
    state.checks["transition_journal_valid"] = True
    observed_state = shadow_state if shadow_state is not None else _shadow_state()
    if not _valid_shadow_state(observed_state):
        state.checks["shadow_state_valid"] = False
        state.counters["valid_evaluation_windows"] = 0
        state.counters.update({key: 1 for key in (
            "duplicate_transitions", "unexplained_error_locks", "fail_open_events",
            "unreconciled_position_events", "v6_regressions", "production_live_orders",
        )})
        return state
    state.checks["shadow_state_valid"] = True
    decisions = {event["transition_id"] for event in events if event["status"] == "decision"}
    state.counters["valid_evaluation_windows"] = len(decisions)
    state.counters.update(_derived_zero_counters(events, observed_state))
    if state.shadow_started_at is None and decisions:
        state.shadow_started_at = now.isoformat()
    return state


def promote_if_eligible(state: PromotionState) -> tuple[bool, list[str]]:
    state = update(state)
    allowed, missing = state.eligible()
    if not allowed:
        return False, missing
    from config.settings import load_settings
    from core.database import get_or_create_bot_state, get_session, init_db
    from core.v7_operations import assert_paper_only
    settings = load_settings()
    config = config_for("paper")
    assert_paper_only(settings, config)
    init_db()
    with get_session() as session:
        shadow = get_or_create_bot_state(session, SHADOW_NAME, "BTC-USDT")
        paper = get_or_create_bot_state(session, PAPER_NAME, "BTC-USDT", config=config)
        if shadow.get_config().get("paper_portfolio_id") == config["paper_portfolio_id"]:
            raise RuntimeError("v7 shadow and paper wallets are not isolated")
        paper.set_config(config)
        paper.is_active = True
    state.paper_promoted_at = datetime.now(timezone.utc).isoformat()
    state.soak_completed_at = state.paper_promoted_at
    state.v7_paper_prerequisite = "PASSED"
    return True, []


def evaluate(*, promote: bool = False) -> dict:
    state = update(PromotionState.load(STATE_PATH))
    promoted = False
    missing: list[str] = []
    if promote:
        promoted, missing = promote_if_eligible(state)
    allowed, missing_now = state.eligible()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promotion_eligible": allowed,
        "missing_gates": missing_now if not promoted else [],
        "promoted_this_run": promoted,
        "state": state.__dict__,
    }
    report["report_hash"] = canonical_hash(report)
    state.evidence_report = str(REPORT_PATH)
    state.save(STATE_PATH)
    atomic_json(REPORT_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--promote", action="store_true", help="Activate paper only after every frozen gate passes.")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--wait", action="store_true", help="Wait until promotion succeeds, then exit for systemd ExecStartPre.")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    while True:
        report = evaluate(promote=args.promote)
        print(json.dumps(report, sort_keys=True))
        if args.wait and report["promoted_this_run"]:
            return 0
        if not args.watch and not args.wait:
            return 0
        time.sleep(max(args.interval, 30))


if __name__ == "__main__":
    raise SystemExit(main())
