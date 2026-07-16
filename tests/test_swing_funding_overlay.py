from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from strategies.funding_coverage import make_coverage_evidence
from strategies.swing_allocator import SwingAllocatorConfig
from strategies.swing_funding_overlay import (
    FundingOverlayError,
    _require_fresh_snapshot,
    active_overlay_at,
    build_overlay_events,
    funding_cache_path,
    funding_market,
)


UTC = timezone.utc


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


def test_overlay_rejects_pre_first_row_without_proven_listing(monkeypatch):
    now = datetime(2020, 1, 1, tzinfo=UTC)
    rows = [(int(datetime(2020, 1, 2, tzinfo=UTC).timestamp() * 1000), 0.01)]
    monkeypatch.setattr("strategies.swing_funding_overlay.coverage_evidence_for", lambda *_args: None)

    with pytest.raises(FundingOverlayError, match="truncated_snapshot: unavailable_evidence"):
        _require_fresh_snapshot(rows, now, "BTC-USDT")


def test_overlay_accepts_only_proven_pre_listing(monkeypatch):
    now = datetime(2020, 1, 1, tzinfo=UTC)
    rows = [(int(datetime(2020, 1, 2, tzinfo=UTC).timestamp() * 1000), 0.01)]
    evidence = make_coverage_evidence(
        source="versioned test venue snapshot", instrument="BTC-USDT", venue="Bybit",
        series_start=datetime(2020, 1, 2, tzinfo=UTC), snapshot_identity="test-bybit-v1",
        generated_at=datetime(2020, 1, 3, tzinfo=UTC), validity_rule="before series start",
    )
    monkeypatch.setattr("strategies.swing_funding_overlay.coverage_evidence_for", lambda *_args: evidence)

    _require_fresh_snapshot(rows, now, "BTC-USDT")


def test_explicit_v5_rollback_keeps_the_funding_overlay_disabled():
    rollback = SwingAllocatorConfig.from_dict({
        "use_phase_policy_router": False, "use_funding_overlay": False,
    })

    assert rollback.use_phase_policy_router is False
    assert rollback.use_funding_overlay is False


def test_okx_source_has_a_distinct_swap_identity_and_cache_path():
    assert funding_market("BTC-USDT", "okx") == "BTC-USDT-SWAP"
    assert funding_cache_path("BTC-USDT", "okx").name == "funding_okx_BTC-USDT-SWAP.json"
    assert funding_cache_path("BTC-USDT", "bybit").name == "funding_bybit_BTCUSDT.json"
