from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from tools.swing_funding_overlay_screen import deduplicate_events, mark_extremes
from tools.backtest_report import PRESETS
from tools.okx_demo_setup import demo_config
from tools.swing_paper_setup import _v5_config, _v6_config
from tools.swing_v5_freeze_report import V5_CONFIG
from tools.swing_v6_freeze_report import V6_CONFIG
from tools.swing_v6_common import infer_phase, iter_start_dates
from strategies.swing_allocator import SwingAllocatorConfig


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


def test_v6_default_presets_and_v5_rollback_are_explicit():
    v5_configs = [V5_CONFIG, _v5_config(), PRESETS["v5"][1]]
    for cfg in v5_configs:
        assert cfg["use_phase_policy_router"] is False
        assert cfg["use_funding_overlay"] is False

    v6_configs = [V6_CONFIG, _v6_config(), demo_config(), PRESETS["v6"][1]]
    defaults = SwingAllocatorConfig().to_dict()
    for cfg in v6_configs:
        assert cfg["use_phase_policy_router"] is True
        assert cfg["phase_policy_profile"] == "v5_equiv"
        assert cfg["use_funding_overlay"] is True
        assert cfg["funding_overlay_phases"] == "accumulation"
        assert cfg["funding_overlay_delta"] == 0.05
        assert cfg["funding_overlay_lookback_settlements"] == 90
        for key, value in V6_CONFIG.items():
            assert defaults[key] == value
