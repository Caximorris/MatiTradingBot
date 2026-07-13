"""Tests de tools/monthly_dist.py (plan income M0)."""
from datetime import datetime, timezone

from tools.monthly_dist import monthly_returns, summarize


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_monthly_returns_basic_and_carry_forward():
    closes = [
        (_dt(2024, 1, 15), 11000.0),   # ene: +10%
        (_dt(2024, 3, 10), 9900.0),    # mar: -10% (feb sin trades -> 0%)
        (_dt(2024, 3, 20), 10890.0),   # mar: neto 11000 -> 10890 = -1%
    ]
    rets = monthly_returns(closes, 10000.0, _dt(2024, 1, 1), _dt(2024, 3, 31))
    assert [k for k, _ in rets] == ["2024-01", "2024-02", "2024-03"]
    assert abs(rets[0][1] - 0.10) < 1e-9
    assert rets[1][1] == 0.0
    assert abs(rets[2][1] - (10890.0 / 11000.0 - 1.0)) < 1e-9


def test_monthly_returns_empty_and_inverted_range():
    assert monthly_returns([], 10000.0, _dt(2024, 2, 1), _dt(2024, 1, 1)) == []


def test_summarize_counts_positive_months_and_streak():
    rets = [("2024-01", 0.02), ("2024-02", -0.01), ("2024-03", -0.03),
            ("2024-04", 0.01), ("2024-05", -0.02)]
    s = summarize(rets)
    assert s["months"] == 5
    assert abs(s["pct_positive"] - 2 / 5) < 1e-9
    assert s["best"] == 0.02 and s["worst"] == -0.03
    assert s["max_neg_streak"] == 2
    assert abs(s["median"] - (-0.01)) < 1e-9
