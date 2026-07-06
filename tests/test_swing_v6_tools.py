from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from tools.swing_funding_overlay_screen import deduplicate_events, mark_extremes
from tools.swing_v6_common import infer_phase, iter_start_dates


def test_infer_phase_prefers_rebalance_signal():
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert infer_phase(["regime_bear", "halving_bear_onset"], ts) == "bear_onset"
    assert infer_phase(["halving_bull_peak", "bull_peak_ema50_cap_0.85"], ts) == "bull_peak"


def test_iter_start_dates_respects_min_days():
    starts = iter_start_dates(
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2021, 1, 1, tzinfo=timezone.utc),
        step_days=90,
        min_days=180,
    )
    assert [d.date().isoformat() for d in starts] == [
        "2020-01-01",
        "2020-03-31",
        "2020-06-29",
    ]


def test_funding_extremes_use_shifted_thresholds_and_dedup():
    dt = pd.date_range("2020-01-01", periods=12, freq="8h", tz="UTC")
    rates = [0.0] * 8 + [0.01, 0.011, -0.01, -0.011]
    funding = pd.DataFrame({"dt": dt, "rate": rates})
    events = mark_extremes(funding, lookback=8, low_pctile=0.05, high_pctile=0.95)

    assert list(events["signal"]) == ["funding_high", "funding_high", "funding_low", "funding_low"]

    deduped = deduplicate_events(events, dedup_days=2)
    assert list(deduped["signal"]) == ["funding_high", "funding_low"]
