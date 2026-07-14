from __future__ import annotations

from datetime import timedelta

import pandas as pd

import strategies.onchain_flow as onchain_flow
from strategies.onchain_flow import (
    build_flow_overlay_events, build_roc_series, flow_vol_adjustment_at,
)

D1 = 24 * 3_600_000


def _rows(levels):
    return [(i * D1, lvl) for i, lvl in enumerate(levels)]


def test_roc_series_empty_below_window():
    assert build_roc_series(_rows([100.0] * 10), window_days=30) == []


def test_roc_series_computes_pct_change():
    levels = [100.0] * 31 + [110.0]
    roc = build_roc_series(_rows(levels), window_days=30)
    assert roc[-1][1] == 0.10 or abs(roc[-1][1] - 0.10) < 1e-9


def test_roc_series_negative_when_level_falls():
    levels = [100.0] * 31 + [90.0]
    roc = build_roc_series(_rows(levels), window_days=30)
    assert roc[-1][1] < 0


def test_overlay_events_empty_when_insufficient_history():
    roc_rows = [(i * D1, 0.0) for i in range(10)]
    events = build_flow_overlay_events(roc_rows, pctile_window=180)
    assert events.empty


def test_overlay_flags_extreme_roc_both_directions():
    rocs = [0.0] * 200
    rocs[100] = -0.5   # reserva cayendo fuerte
    rocs[150] = 0.5    # reserva subiendo fuerte
    roc_rows = [(i * D1, r) for i, r in enumerate(rocs)]
    events = build_flow_overlay_events(roc_rows, pctile_window=90, dedup_days=7, ttl_days=7)
    signals = set(events["signal"])
    assert "reserve_falling" in signals
    assert "reserve_rising" in signals


def test_flow_vol_adjustment_only_reacts_to_rising_events():
    """EXP-014: solo el lado 'rising' (spike) demostro senal robusta (precede vol
    elevada); 'falling' nunca debe producir un delta, aunque este cargado."""
    dt = pd.Timestamp("2024-01-10", tz="UTC")
    onchain_flow._EVENTS["BTC-USDT"] = pd.DataFrame({
        "ts": [1], "dt": [dt], "expires_at": [dt + timedelta(days=14)],
        "roc": [0.3], "signal": ["reserve_rising"],
    })
    try:
        before = flow_vol_adjustment_at(dt - timedelta(hours=1), "BTC-USDT", -0.15)
        assert before == (0.0, None)

        inside = flow_vol_adjustment_at(dt + timedelta(days=1), "BTC-USDT", -0.15)
        assert inside[0] == -0.15
        assert inside[1] is not None

        outside = flow_vol_adjustment_at(dt + timedelta(days=20), "BTC-USDT", -0.15)
        assert outside == (0.0, None)
    finally:
        onchain_flow._EVENTS.pop("BTC-USDT", None)


def test_flow_vol_adjustment_no_events_loaded():
    onchain_flow._EVENTS.pop("ETH-USDT", None)
    assert flow_vol_adjustment_at(pd.Timestamp.now(tz="UTC"), "ETH-USDT", -0.15) == (0.0, None)
