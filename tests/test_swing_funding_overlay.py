from __future__ import annotations

from datetime import timedelta

import pandas as pd

from strategies.swing_funding_overlay import active_overlay_at, build_overlay_events


def _funding_sample() -> pd.DataFrame:
    dt = pd.date_range("2020-01-01", periods=12, freq="8h", tz="UTC")
    rates = [0.0] * 8 + [0.01, 0.011, -0.01, -0.011]
    return pd.DataFrame({"dt": dt, "rate": rates})


def test_overlay_events_are_shifted_deduped_and_ttl_bounded():
    events = build_overlay_events(
        _funding_sample(),
        lookback=8,
        low_pctile=0.05,
        high_pctile=0.95,
        dedup_days=2,
        ttl_days=1,
    )

    assert list(events["signal"]) == ["funding_high", "funding_low"]

    high_dt = events.iloc[0]["dt"]
    assert active_overlay_at(events, high_dt.to_pydatetime(), "accumulation", "accumulation", 0.05) == (
        0.0,
        None,
    )

    inside = high_dt.to_pydatetime() + timedelta(minutes=1)
    assert active_overlay_at(events, inside, "accumulation", "accumulation", 0.05)[0] == 0.05

    outside = high_dt.to_pydatetime() + timedelta(days=2)
    assert active_overlay_at(events, outside, "accumulation", "accumulation", 0.05) == (0.0, None)


def test_overlay_respects_phase_filter_and_plus_separator():
    events = build_overlay_events(_funding_sample(), lookback=8, dedup_days=2, ttl_days=1)
    now = events.iloc[1]["dt"].to_pydatetime() + timedelta(minutes=1)

    assert active_overlay_at(events, now, "bull_peak", "accumulation", 0.05) == (0.0, None)
    assert active_overlay_at(events, now, "bear_onset", "bear_onset+accumulation", 0.05)[0] == 0.05
