from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.cft_monitor import CFTMonitorConfig, format_status, update_status


T0 = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)


def test_cft_monitor_normalizes_paper_equity_to_account_size(tmp_path):
    status = update_status(
        strategy="prop_swing_btc_usdt",
        symbol="BTC-USDT",
        ts=T0,
        equity=10_000.0,
        cfg=CFTMonitorConfig(account_size=50_000.0, daily_dd_pct=0.06, max_loss_pct=0.12),
        status_path=tmp_path / "status.json",
        events_path=tmp_path / "events.jsonl",
    )
    assert status["account_equity"] == 50_000.0
    assert round(status["daily_cushion_pct"], 4) == 0.06
    assert round(status["total_cushion_pct"], 4) == 0.12
    assert "CFT P1" in format_status(status)


def test_cft_monitor_counts_trade_days_and_passes_phase(tmp_path):
    status_path = tmp_path / "status.json"
    events_path = tmp_path / "events.jsonl"
    cfg = CFTMonitorConfig(account_size=50_000.0)
    for i in range(5):
        update_status(
            strategy="prop_swing_btc_usdt",
            symbol="BTC-USDT",
            ts=T0 + timedelta(days=i),
            equity=10_000.0 + i * 10,
            cfg=cfg,
            trade_event={"kind": "open", "side": "long"},
            status_path=status_path,
            events_path=events_path,
        )
    status = update_status(
        strategy="prop_swing_btc_usdt",
        symbol="BTC-USDT",
        ts=T0 + timedelta(days=5),
        equity=10_900.0,
        cfg=cfg,
        status_path=status_path,
        events_path=events_path,
    )
    assert status["trading_days"] == 5
    assert status["rule_state"] == "passed"


def test_cft_monitor_enters_halt_zone_near_daily_floor(tmp_path):
    cfg = CFTMonitorConfig(account_size=50_000.0, max_loss_pct=0.10, halt_buffer_pct=0.003)
    status_path = tmp_path / "status.json"
    events_path = tmp_path / "events.jsonl"
    update_status(
        strategy="prop_swing_btc_usdt",
        symbol="BTC-USDT",
        ts=T0,
        equity=10_000.0,
        cfg=cfg,
        status_path=status_path,
        events_path=events_path,
    )
    status = update_status(
        strategy="prop_swing_btc_usdt",
        symbol="BTC-USDT",
        ts=T0 + timedelta(hours=1),
        equity=9_510.0,
        cfg=cfg,
        status_path=status_path,
        events_path=events_path,
    )
    assert status["rule_state"] == "halt_zone"
    assert status["hard_stop"] is True
