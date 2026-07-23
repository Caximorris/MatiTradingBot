from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tools.backtest_report import build_html
from tools.report_common import extract_markers, phase_bands


def test_v7_markers_render_all_operational_event_types():
    strategy = SimpleNamespace(_event_log=[
        {"timestamp": "2024-04-20T04:00:00+00:00", "event_type": "decision", "price": "64000",
         "previous_phase": "post_halving", "new_phase": "post_halving", "previous_target": "1",
         "new_target": "1", "status": "decision", "reason": "four_hour_evaluation"},
        {"timestamp": "2025-10-12T04:00:00+00:00", "event_type": "transition", "price": "64000",
         "previous_phase": "bull_peak", "new_phase": "bear_onset", "previous_target": "1",
         "new_target": "0", "status": "transition", "reason": "target_changed"},
        {"timestamp": "2025-10-12T04:00:00+00:00", "event_type": "submission", "price": "64000",
         "previous_phase": "bull_peak", "new_phase": "bear_onset", "previous_target": "1",
         "new_target": "0", "status": "submitted", "reason": "order_submitted"},
        {"timestamp": "2025-10-12T05:00:00+00:00", "event_type": "fill", "price": "64000",
         "previous_phase": "bull_peak", "new_phase": "bear_onset", "previous_target": "1",
         "new_target": "0", "status": "filled", "reason": "causal_fill_reconciled"},
    ])
    markers, kind = extract_markers(strategy)
    assert kind == "cycle_core"
    assert [marker["kind"] for marker in markers] == ["decision", "transition", "submission", "fill"]


def test_v7_html_uses_exact_cycle_clock_boundaries():
    start = datetime(2024, 4, 19, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bands = phase_bands("BTC-USDT", start, end, {})
    post = next(band for band in bands if band["name"] == "post_halving")
    assert post["from"] == "2024-04-20T00:09:27+00:00"

    result = SimpleNamespace(strategy_name="swing_cycle_core", cagr=0, max_drawdown_pct=0,
                             calmar=0, final_balance=10000, sharpe_ratio=0, sortino=0,
                             underwater_days=0, buy_hold_pnl_pct=0, profit_factor=0, bars_tested=2)
    run = SimpleNamespace(result=result, symbol="BTC-USDT", from_dt=start, to_dt=end,
                          cost_mode="realistic", config={})
    html = build_html(run, {"dates": ["2024-04-19", "2024-04-20"], "equity": [10000, 10000],
                            "bnh": [10000, 10000], "dd": [0, 0]},
                      [("2024-04-19", 1, 1, 1, 1), ("2024-04-20", 1, 1, 1, 1)], [], "cycle_core")
    assert '"from":"2024-04-20T00:09:27+00:00"' in html
    assert "decision:'#9aa0ab'" in html
