from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import core.v7_operations as v7_operations
import tools.v7_promotion_controller as promotion_controller

from core.v7_operations import (
    JournalIntegrityError,
    PromotionState,
    TransitionJournal,
    assert_paper_only,
    canonical_unlocked_v7_state,
    canonical_hash,
    v7_configuration_evidence_hash,
    v7_evidence_source_hashes,
)
from strategies.swing_cycle_core import SwingCycleCoreBot, SwingCycleCoreConfig
from tools.v7_paper_setup import PAPER_NAME, SHADOW_NAME, config_for
from tools.v7_promotion_controller import _shadow_journal_identity, update


class _Settings:
    def __init__(self, paper: bool) -> None:
        self.is_paper = paper


def _event(*, transition_id: str = "2026-07-22T00:00:00+00:00:decision") -> dict:
    strategy_id, instance_id = _shadow_journal_identity()
    return {
        "strategy_id": strategy_id, "instance_id": instance_id,
        "transition_id": transition_id, "previous_phase": "bull_peak",
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
    assert shadow["transition_journal_path"] != paper["transition_journal_path"]
    assert shadow["service_managed"] is paper["service_managed"] is True
    assert {shadow["execution"], paper["execution"]} == {"v7_shadow", "v7_local_paper"}
    assert_paper_only(_Settings(True), shadow)
    with pytest.raises(RuntimeError, match="paper"):
        assert_paper_only(_Settings(False), paper)


def test_v7_setup_registers_both_instances_inactive_by_default(monkeypatch):
    from core import database
    from tools.v7_paper_setup import register

    class State:
        def __init__(self) -> None:
            self.config = None
            self.is_active = None

        def set_config(self, config) -> None:
            self.config = config

    states = {}

    def get_or_create(_session, name, _symbol, *, config):
        states[name] = State()
        return states[name]

    monkeypatch.setattr(database, "get_or_create_bot_state", get_or_create)
    result = register(object())

    assert set(result) == {SHADOW_NAME, PAPER_NAME}
    assert all(state.is_active is False for state in states.values())
    assert states[SHADOW_NAME].config["paper_portfolio_id"] != states[PAPER_NAME].config["paper_portfolio_id"]


def test_controller_accepts_identity_from_real_shadow_bot(tmp_path: Path):
    config = SwingCycleCoreConfig.from_dict(config_for("shadow"))
    bot = SwingCycleCoreBot(None, config)
    strategy_id, instance_id = _shadow_journal_identity()
    assert (strategy_id, instance_id) == (bot.name, config.instance_id)

    path = tmp_path / "transitions.jsonl"
    TransitionJournal(path).append(_event())
    state = update(PromotionState(), journal_path=path, shadow_state=_canonical_state())
    assert state.checks["transition_journal_valid"]


def test_transition_journal_is_append_only_and_hash_chained(tmp_path: Path):
    journal = TransitionJournal(tmp_path / "transitions.jsonl")
    first = journal.append(_event())
    second = journal.append(_event(transition_id="2026-07-22T04:00:00+00:00:decision"))
    assert second["previous_entry_hash"] == first["entry_hash"]
    assert len((tmp_path / "transitions.jsonl").read_text().splitlines()) == 2


def _canonical_state(**overrides: object) -> dict:
    return {
        "version": 2, "state": "STABLE_RISK_ON", "phase": "bull_peak",
        "last_block": "2026-07-22T00:00:00+00:00", "order_id": None,
        "pending_order": None, "error": None,
    } | overrides


def _write_decisions(path: Path, count: int = 18) -> None:
    journal = TransitionJournal(path)
    for hour in range(count):
        journal.append(_event(transition_id=f"2026-07-22T{hour:02d}:00:00+00:00:decision"))


def test_promotion_counters_come_only_from_valid_journal_and_state(tmp_path: Path):
    path = tmp_path / "transitions.jsonl"
    _write_decisions(path)
    state = update(PromotionState(), journal_path=path, shadow_state=_canonical_state())
    assert state.checks["transition_journal_valid"]
    assert state.checks["shadow_state_valid"]
    assert state.counters["valid_evaluation_windows"] == 18
    assert all(state.counters[key] == 0 for key in (
        "duplicate_transitions", "unexplained_error_locks", "fail_open_events",
        "unreconciled_position_events", "v6_regressions", "production_live_orders",
    ))


def test_later_shadow_config_mismatch_invalidates_promotion_evidence(tmp_path: Path, monkeypatch):
    path = tmp_path / "transitions.jsonl"
    _write_decisions(path)
    shadow_config = config_for("shadow")
    state = PromotionState(configuration_hash=v7_configuration_evidence_hash(shadow_config, root=Path.cwd()))
    state.checks = {key: True for key in state.checks}
    state = update(state, journal_path=path, shadow_state=_canonical_state())
    assert state.checks["configuration_evidence_valid"]

    changed_config = shadow_config | {"max_strategic_orders_per_day": 5}
    monkeypatch.setattr(promotion_controller, "config_for", lambda mode: changed_config)
    state = update(state, journal_path=path, shadow_state=_canonical_state())
    allowed, missing = state.eligible()
    assert not state.checks["configuration_evidence_valid"]
    assert not allowed and "configuration_evidence_valid" in missing


def test_later_v7_source_hash_mismatch_invalidates_promotion_evidence(tmp_path: Path, monkeypatch):
    path = tmp_path / "transitions.jsonl"
    _write_decisions(path)
    state = PromotionState(configuration_hash=v7_configuration_evidence_hash(
        config_for("shadow"), root=Path.cwd()
    ))
    state.checks = {key: True for key in state.checks}
    state = update(state, journal_path=path, shadow_state=_canonical_state())
    assert state.checks["configuration_evidence_valid"]

    changed_source_identity = v7_evidence_source_hashes(Path.cwd())
    changed_source_identity["files"] = dict(changed_source_identity["files"])
    changed_source_identity["files"]["core/v7_operations.py"] = "0" * 64
    monkeypatch.setattr(v7_operations, "v7_evidence_source_hashes",
                        lambda root: changed_source_identity)
    state = update(state, journal_path=path, shadow_state=_canonical_state())
    allowed, missing = state.eligible()
    assert not state.checks["configuration_evidence_valid"]
    assert not allowed and "configuration_evidence_valid" in missing


@pytest.mark.parametrize("attack", ("malformed", "schema", "hash", "duplicate"))
def test_tampered_or_duplicate_journal_fails_closed(tmp_path: Path, attack: str):
    path = tmp_path / "transitions.jsonl"
    _write_decisions(path, 2)
    lines = path.read_text(encoding="utf-8").splitlines()
    if attack == "malformed":
        lines[1] = "not-json"
    else:
        record = json.loads(lines[1])
        if attack == "schema":
            record["status"] = ["decision"]
            record["entry_hash"] = canonical_hash({key: value for key, value in record.items() if key != "entry_hash"})
        elif attack == "hash":
            record["new_target"] = "1"  # Changes evidence without updating the hash.
        else:
            record["transition_id"] = json.loads(lines[0])["transition_id"]
            record["entry_hash"] = canonical_hash({key: value for key, value in record.items() if key != "entry_hash"})
        lines[1] = json.dumps(record, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(JournalIntegrityError):
        strategy_id, instance_id = _shadow_journal_identity()
        TransitionJournal(path).validate(strategy_id=strategy_id, instance_id=instance_id)
    state = update(PromotionState(), journal_path=path, shadow_state=_canonical_state())
    assert not state.checks["transition_journal_valid"]
    assert state.counters["valid_evaluation_windows"] == 0
    assert not state.eligible()[0]


def test_invalid_or_locked_state_fails_promotion_even_with_valid_journal(tmp_path: Path):
    path = tmp_path / "transitions.jsonl"
    _write_decisions(path)
    invalid = update(PromotionState(), journal_path=path, shadow_state={"state": "ERROR_LOCKED"})
    assert not invalid.checks["shadow_state_valid"]
    locked = update(PromotionState(), journal_path=path,
                    shadow_state=_canonical_state(state="ERROR_LOCKED"))
    assert locked.checks["shadow_state_valid"]
    assert locked.counters["unexplained_error_locks"] == 1


def test_unresolved_order_prevents_promotion_and_unlock_state_schema_is_v2(tmp_path: Path):
    path = tmp_path / "transitions.jsonl"
    _write_decisions(path)
    state = update(PromotionState(), journal_path=path,
                   shadow_state=_canonical_state(state="EXIT_ORDER_SUBMITTED", order_id="v7order",
                                                pending_order={"order_id": "v7order"}))
    # The controller must count an outstanding order, not merely trust a journal
    # that happens to contain no terminal error.
    assert state.counters["unreconciled_position_events"] == 1
    unlocked = canonical_unlocked_v7_state()
    assert unlocked == _canonical_state(phase=None, last_block=None)


def test_promotion_gate_cannot_pass_before_soak_or_without_checks():
    state = PromotionState()
    eligible, missing = state.eligible(datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert not eligible and "shadow_started_at" in missing
    state.shadow_started_at = (datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()
    state.checks = {key: True for key in state.checks}
    state.counters["valid_evaluation_windows"] = 18
    eligible, missing = state.eligible()
    assert eligible, missing
