from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.certification import SnapshotBar, StrategySnapshot, TargetIntent
from core.v7_certified_paper import (
    CIRCUIT_BREAKER_REASONS,
    CertifiedPaperAdapter,
    PaperSafetyError,
    make_config,
    replay_six_operation_ledger,
)
from tools.v7_daily_report import build
from tools.v7_paper_setup import CERTIFIED_NAME, config_for


ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path):
    spec = tmp_path / "docs" / "v7_frozen_candidate.json"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        (ROOT / "docs" / "v7_frozen_candidate.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return make_config(tmp_path)


def _ledger(tmp_path: Path) -> Path:
    """Local deterministic fixture; no certification evidence directory is an input."""
    path = tmp_path / "six_operations.csv"
    header = "sequence,decision_timestamp,information_cutoff,new_target,side,fill_timestamp,fill_open,fill_price,quantity,fee,cash_before,cash_after,btc_before,btc_after,equity_after\n"
    rows = []
    for index in range(1, 7):
        hour = (index - 1) * 4
        rows.append(
            f"{index},2026-01-01T{hour:02d}:00:00+00:00,2026-01-01T{hour:02d}:00:00+00:00,{index},buy,2026-01-01T{hour + 1:02d}:00:00+00:00,10,10,1,0,{10010 - index * 10},{10000 - index * 10},{index - 1},{index},10000\n"
        )
    path.write_text(header + "".join(rows), encoding="utf-8")
    return path


def test_paper_adapter_is_dependency_isolated_and_setup_is_inactive(tmp_path: Path):
    config = _config(tmp_path)
    source = (ROOT / "core" / "v7_certified_paper.py").read_text(encoding="utf-8")
    assert (
        "core.exchange" not in source
        and "okx" not in source.lower()
        and "place_order" not in source
    )
    assert (
        config.active is False
        and config.allow_shorts is False
        and config.promotion_allowed is False
    )
    assert CERTIFIED_NAME != "swing_cycle_core_v7_btc_usdt_shadow"
    assert config_for(ROOT)["mode"] == "paper"


def test_exact_six_operation_replay_parity_and_duplicate_suppression(tmp_path: Path):
    config = _config(tmp_path)
    ledger = _ledger(tmp_path)
    result = replay_six_operation_ledger(config, ledger)
    assert result["PAPER_REPLAY_PARITY"] == "PASS"
    assert result["intents"] == result["fills"] == 6
    assert Decimal(result["final_cash"]) == Decimal("9940")
    with ledger.open(newline="", encoding="utf-8") as handle:
        first = next(csv.DictReader(handle))
    assert (
        CertifiedPaperAdapter(config).replay_operation(first)["status"]
        == "duplicate_intent"
    )


def test_restart_after_each_persisted_operation_resumes_without_duplicate_fill(
    tmp_path: Path,
):
    config = _config(tmp_path)
    with _ledger(tmp_path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        assert (
            CertifiedPaperAdapter(config).replay_operation(row)["status"]
            == "reconciled"
        )
        # New object simulates a process restart after every durable write.
        assert CertifiedPaperAdapter(config).load_state()["pending"] is None
    state = CertifiedPaperAdapter(config).load_state()
    assert len(state["seen_intents"]) == len(state["seen_fills"]) == 6
    assert len(config.journal_path.read_text(encoding="utf-8").splitlines()) == 12


def test_hash_and_wallet_mismatch_fail_closed(tmp_path: Path):
    config = _config(tmp_path)
    adapter = CertifiedPaperAdapter(config)
    with _ledger(tmp_path).open(newline="", encoding="utf-8") as handle:
        first = next(csv.DictReader(handle))
    state = adapter.initial_state()
    state["candidate_hash"] = "bad"
    adapter.save_state(state)
    with pytest.raises(PaperSafetyError, match="hash mismatch"):
        adapter.replay_operation(first)
    assert adapter.load_state()["locked"] is True


def test_snapshot_requires_completed_utc_four_hour_inputs(tmp_path: Path):
    adapter = CertifiedPaperAdapter(_config(tmp_path))
    at = datetime(2026, 1, 1, 4, tzinfo=timezone.utc)
    bar = SnapshotBar(
        at, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1")
    )
    snapshot = StrategySnapshot(at, (bar,), {}, Decimal("1"), Decimal("0"))
    assert (
        adapter.decide(snapshot, TargetIntent("intent", target_base_pct=Decimal("1")))
        is not None
    )
    bad = StrategySnapshot(at.replace(hour=5), (bar,), {}, Decimal("1"), Decimal("0"))
    with pytest.raises(PaperSafetyError, match="four-hour"):
        adapter.decide(bad, None)


@pytest.mark.parametrize("reason", sorted(CIRCUIT_BREAKER_REASONS))
def test_synthetic_operational_drills_fail_closed_without_real_state(
    tmp_path: Path, reason: str
):
    adapter = CertifiedPaperAdapter(_config(tmp_path))
    adapter.fail_closed(reason, datetime(2026, 1, 1, tzinfo=timezone.utc))
    state = adapter.load_state()
    assert state["locked"] is True and state["lock_reason"] == reason


def test_candle_drills_reject_stale_conflicting_and_out_of_order_batches(
    tmp_path: Path,
):
    at = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    for candles, reason in (
        ([], "missing_required_candle"),
        ([{"timestamp": "2026-01-01T00:00:00+00:00"}], "stale_data"),
        (
            [
                {"timestamp": "2026-01-01T07:00:00+00:00"},
                {"timestamp": "2026-01-01T06:00:00+00:00"},
            ],
            "out_of_order_candle",
        ),
        (
            [
                {"timestamp": "2026-01-01T07:00:00+00:00", "close": "1"},
                {"timestamp": "2026-01-01T07:00:00+00:00", "close": "2"},
            ],
            "conflicting_duplicate_candle",
        ),
    ):
        adapter = CertifiedPaperAdapter(_config(tmp_path / reason))
        with pytest.raises(PaperSafetyError, match=reason):
            adapter.validate_candle_batch(candles, now=at)


def test_daily_report_is_read_only_and_never_calls_pending_an_executed_fill(
    tmp_path: Path,
):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "v7_frozen_candidate.json").write_text(
        (ROOT / "docs" / "v7_frozen_candidate.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    report = build(tmp_path)
    assert report["paper_vs_replay_parity_verdict"] == "NOT_STARTED"
    assert report["daily_fills"] == 0 and report["pending_intent_order"] is None
