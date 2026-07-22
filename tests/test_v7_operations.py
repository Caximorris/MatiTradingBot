from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.v7_operations import PromotionState, TransitionJournal, assert_paper_only
from tools.v7_paper_setup import PAPER_NAME, SHADOW_NAME, config_for


class _Settings:
    def __init__(self, paper: bool) -> None:
        self.is_paper = paper


def _event() -> dict:
    return {
        "strategy_id": "swing_cycle_core_v7", "instance_id": "v7_shadow",
        "transition_id": "2026-07-22T0:decision", "previous_phase": "bull_peak",
        "new_phase": "bear_onset", "previous_target": "1", "new_target": "0",
        "decision_timestamp": "2026-07-22T00:00:00+00:00",
        "market_data_timestamp": "2026-07-22T00:00:00+00:00",
        "expected_position": "0", "actual_position": "1", "order_id": "",
        "fill_ids": [], "fees": "0", "slippage": "unknown", "status": "decision",
        "retry_count": 0, "state_hash_before": "a", "state_hash_after": "b", "reason": "test",
    }


def test_v7_configs_are_separate_and_paper_only():
    shadow, paper = config_for("shadow"), config_for("paper")
    assert SHADOW_NAME != PAPER_NAME
    assert shadow["paper_portfolio_id"] != paper["paper_portfolio_id"]
    assert_paper_only(_Settings(True), shadow)
    with pytest.raises(RuntimeError, match="paper"):
        assert_paper_only(_Settings(False), paper)


def test_transition_journal_is_append_only_and_hash_chained(tmp_path: Path):
    journal = TransitionJournal(tmp_path / "transitions.jsonl")
    first = journal.append(_event())
    second = journal.append({**_event(), "transition_id": "2026-07-22T1:decision"})
    assert second["previous_entry_hash"] == first["entry_hash"]
    assert len((tmp_path / "transitions.jsonl").read_text().splitlines()) == 2


def test_promotion_gate_cannot_pass_before_soak_or_without_checks():
    state = PromotionState()
    eligible, missing = state.eligible(datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert not eligible and "shadow_started_at" in missing
    state.shadow_started_at = (datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()
    state.checks = {key: True for key in state.checks}
    state.counters["valid_evaluation_windows"] = 18
    eligible, missing = state.eligible()
    assert eligible, missing
