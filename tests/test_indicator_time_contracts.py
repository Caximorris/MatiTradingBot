"""Regression checks for closed-prefix indicator resampling contracts."""
from __future__ import annotations

import pandas as pd
from pandas.testing import assert_frame_equal

from strategies.indicators import resample_to_4h, resample_to_daily, resample_to_weekly


def _hourly(start: str, periods: int) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="h", tz="UTC")
    values = list(range(100, 100 + periods))
    return pd.DataFrame(
        {
            "timestamp": (index.astype("int64") // 1_000_000).astype("int64"),
            "open": values,
            "high": [value + 2 for value in values],
            "low": [value - 1 for value in values],
            "close": [value + 1 for value in values],
            "volume": [1] * periods,
        }
    )


def test_daily_closed_prefix_does_not_change_when_current_day_grows() -> None:
    early = resample_to_daily(_hourly("2024-01-01", 25))
    later = resample_to_daily(_hourly("2024-01-01", 30))

    assert_frame_equal(early.iloc[:-1].reset_index(drop=True), later.iloc[:-1].reset_index(drop=True))
    assert early.iloc[0]["close"] == 124


def test_4h_closed_prefix_does_not_change_when_current_block_grows() -> None:
    early = resample_to_4h(_hourly("2024-01-01", 5))
    later = resample_to_4h(_hourly("2024-01-01", 7))

    assert_frame_equal(early.iloc[:-1].reset_index(drop=True), later.iloc[:-1].reset_index(drop=True))
    assert early.iloc[0]["close"] == 104


def test_weekly_closed_prefix_does_not_change_when_current_week_grows() -> None:
    early = resample_to_weekly(_hourly("2024-01-01", 193))
    later = resample_to_weekly(_hourly("2024-01-01", 215))

    assert_frame_equal(early.iloc[:-1].reset_index(drop=True), later.iloc[:-1].reset_index(drop=True))
