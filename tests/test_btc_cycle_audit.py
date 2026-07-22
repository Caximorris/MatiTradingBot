from datetime import date
from decimal import Decimal

import pytest

from tools.btc_cycle_audit.core import (
    boundary_stats,
    bootstrap_centers,
    causal_confirmations,
    consensus_daily,
    days_since,
    immutable_snapshot,
    retrospective_extremes,
    validate_bars,
)
from tools.btc_cycle_audit.models import PriceBar


def bar(source, day, close, high=None, low=None):
    high = high or close
    low = low or close
    return PriceBar(source, f"{day}T00:00:00Z", str(close), str(high), str(low), str(close), "1")


def test_utc_and_day_calculation():
    assert days_since(date(2024, 4, 20), "2024-04-20T23:59:00+02:00") == 0


def test_validation_detects_duplicate_gap_and_impossible_candle():
    rows = [bar("a", "2024-01-01", 10), bar("a", "2024-01-01", 10), bar("a", "2024-01-03", 10, high=5)]
    errors, counts = validate_bars(rows, stale_after_days=10000)
    assert counts["duplicates"] == 1
    assert counts["gaps"] == 1
    assert counts["impossible"] > 0
    assert errors


def test_consensus_is_deterministic_and_marks_disagreement():
    rows = [bar("a", "2024-01-01", 100), bar("b", "2024-01-01", 101), bar("c", "2024-01-01", 103)]
    first = consensus_daily(rows)
    second = consensus_daily(list(reversed(rows)))
    assert first == second
    assert first[0]["confidence_status"] == "SOURCE_DISAGREEMENT"


def test_retrospective_top_bottom_and_incomplete_cycle():
    rows = [
        {"date_utc": "2020-05-11", "maximum_close": "100", "maximum_high": "110", "minimum_close": "90", "minimum_low": "80"},
        {"date_utc": "2021-01-01", "maximum_close": "200", "maximum_high": "210", "minimum_close": "190", "minimum_low": "180"},
        {"date_utc": "2021-06-01", "maximum_close": "150", "maximum_high": "160", "minimum_close": "50", "minimum_low": "40"},
    ]
    halvings = [{"block_timestamp_utc": "2020-05-11T00:00:00Z"}, {"block_timestamp_utc": "2024-04-20T00:00:00Z"}]
    extremes = retrospective_extremes(rows, halvings)
    assert {e.kind + "_" + e.method for e in extremes} == {"top_close", "top_intraday", "bottom_close", "bottom_intraday"}


def test_causal_confirmation_does_not_confirm_before_drawdown_window():
    rows = [{"date_utc": f"2020-01-{i:02d}", "maximum_high": "100" if i < 3 else "90", "minimum_low": "80" if i >= 3 else "100", "maximum_close": "100", "minimum_close": "80"} for i in range(1, 10)]
    assert causal_confirmations(rows, drawdown_pct=Decimal(".20"), confirmation_days=2)[0]["confirmed_at"] >= "2020-01-04"


def test_boundary_stats_and_bootstrap_are_sample_size_capped_and_seeded():
    stats = boundary_stats([520, 540, 560], 540)
    assert stats.confidence == "VERY_LOW"
    assert stats.verdict == "SUPPORTED_AS_APPROXIMATE_CENTER"
    assert bootstrap_centers([520, 540, 560], 540, iterations=100, seed=7) == bootstrap_centers([520, 540, 560], 540, iterations=100, seed=7)


def test_immutable_snapshot_rejects_revision(tmp_path):
    target = tmp_path / "snapshot.json"
    immutable_snapshot(target, {"a": 1})
    with pytest.raises(FileExistsError):
        immutable_snapshot(target, {"a": 2})
