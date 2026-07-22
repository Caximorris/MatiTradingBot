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

from core.v7_operations import PromotionState, RUNTIME, atomic_json, canonical_hash
from tools.v7_paper_setup import PAPER_NAME, SHADOW_NAME, config_for

STATE_PATH = RUNTIME / "promotion_state.json"
REPORT_PATH = RUNTIME / "promotion_report.json"


def _events(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, ValueError):
        return []


def update(state: PromotionState, *, now: datetime | None = None) -> PromotionState:
    now = now or datetime.now(timezone.utc)
    shadow_journal = RUNTIME / "v7_btc_usdt_shadow" / "transitions.jsonl"
    decisions = {e.get("transition_id") for e in _events(shadow_journal) if e.get("status") == "decision"}
    state.counters["valid_evaluation_windows"] = len({key for key in decisions if key})
    if state.shadow_started_at is None and decisions:
        state.shadow_started_at = now.isoformat()
    return state


def promote_if_eligible(state: PromotionState) -> tuple[bool, list[str]]:
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
