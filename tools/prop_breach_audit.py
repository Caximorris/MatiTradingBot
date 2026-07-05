#!/usr/bin/env python
"""Audit failed prop-challenge windows for E9.

The aggregate pass/breach rate is not enough to decide. This tool runs one
backtest, simulates a selected prop rule-set, and prints:
- status distribution by start year and regime
- worst failed windows
- worst trades inside those windows

It does not write heavy journals.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from loguru import logger

logger.remove()

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from core.prop_rules import simulate_challenges, trade_pnls_from_result
from strategies import registry
from strategies.indicators import adx as adx_fn, ema as ema_fn, resample_to_daily
from tools.prop_challenge_sim import rule_configs

E9 = {
    "entry_mode": "breakout",
    "risk_per_trade": 0.0125,
    "tp1_r": 1.5,
    "allow_shorts": True,
    "max_notional_pct": 0.5,
    "model_funding": True,
}


def run_backtest(strategy: str, from_dt: datetime, to_dt: datetime, costs: str,
                 overrides: dict, symbol: str = "BTC-USDT"):
    meta = registry.get(strategy)
    bars = fetch_historical_bars(symbol, "1H",
                                 from_dt - timedelta(days=meta.warmup_days), to_dt)
    client = BacktestClient(symbol, bars, initial_balance=Decimal("10000"),
                            cost_mode=costs)
    cfg_obj = meta.make_config(symbol, overrides)

    def factory(c, s):
        return meta.make_bot(c, cfg_obj, s)

    from_ts = int(from_dt.timestamp() * 1000)
    warmup = max(len([b for b in bars if b.timestamp < from_ts]), 20)
    engine = BacktestEngine(client, factory, warmup_bars=warmup, timeframe="1H")
    result = engine.run()
    strategy_obj = engine.last_strategy
    realized = list(getattr(strategy_obj, "realized", None) or []) or None
    trades = realized or trade_pnls_from_result(result)
    journal = list(getattr(strategy_obj, "_journal", []) or [])
    return result, bars, trades, journal


def regime_map(bars) -> dict:
    df = pd.DataFrame({
        "timestamp": [b.timestamp for b in bars],
        "open": [float(b.open) for b in bars],
        "high": [float(b.high) for b in bars],
        "low": [float(b.low) for b in bars],
        "close": [float(b.close) for b in bars],
        "volume": [float(b.volume) for b in bars],
    })
    daily = resample_to_daily(df)
    close = daily["close"]
    ema50 = ema_fn(close, 50)
    ema200 = ema_fn(close, 200)
    adx_d = adx_fn(daily["high"], daily["low"], close, 14)
    out = {}
    for dt, c, e50, e200, a in zip(daily["dt"], close, ema50, ema200, adx_d):
        if pd.isna(e200) or pd.isna(a):
            label = "insufficient"
        elif a < 15:
            label = "range"
        elif e50 > e200 and c > e200:
            label = "bull"
        elif e50 < e200 and c < e200:
            label = "bear"
        else:
            label = "transition"
        # Challenge start at day D can only know D-1 daily close.
        out[(dt + pd.Timedelta(days=1)).date()] = label
    return out


def closed_trades_between(journal: list[dict], start: datetime, end: datetime) -> list[dict]:
    out = []
    for trade in journal:
        close = trade.get("close") or {}
        ts_s = close.get("timestamp")
        if not ts_s:
            continue
        ts = datetime.fromisoformat(ts_s)
        if start <= ts <= end:
            out.append(trade)
    return out


def trade_pnl(trade: dict) -> float:
    close = trade.get("close") or {}
    return float(close.get("true_pnl_usdt", close.get("pnl_usdt", 0.0)) or 0.0)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="from_", default="2018-01-01")
    p.add_argument("--to", default="2026-01-01")
    p.add_argument("--costs", default="bybit")
    p.add_argument("--rules", default="hyro", choices=("hyro", "breakout", "cft"))
    p.add_argument("--label", default="two_step_swing",
                   help="label from selected rules, e.g. two_step_swing/cft_two_phase")
    p.add_argument("--max-days", type=int, default=540)
    p.add_argument("--buffer", type=float, default=0.2)
    p.add_argument("--config", default="")
    p.add_argument("--top", type=int, default=12)
    p.add_argument("--out", default="")
    args = p.parse_args()

    overrides = dict(E9)
    if args.config:
        overrides.update(json.loads(args.config))
    from_dt = datetime.fromisoformat(args.from_).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(args.to).replace(tzinfo=timezone.utc)

    result, bars, trades, journal = run_backtest("prop", from_dt, to_dt,
                                                 args.costs, overrides)
    configs = rule_configs(args.rules)
    selected = [(label, cfg, two_step) for label, cfg, two_step in configs
                if label == args.label]
    if not selected:
        raise SystemExit(f"label no encontrado para {args.rules}: {args.label}")
    label, cfg, two_step = selected[0]
    cfg = cfg.with_(label=f"{label}@{args.max_days}d",
                    intrabar_buffer=args.buffer, max_days=args.max_days)
    stats = simulate_challenges(result.equity_curve, cfg, trade_pnls=trades,
                                two_step=two_step)
    regimes = regime_map(bars)

    print(f"# edge pnl={result.total_pnl_pct}% PF={result.profit_factor} "
          f"WR={result.win_rate}% maxDD={result.max_drawdown_pct}% "
          f"trades={len(trades)} bars={result.bars_tested}")
    print(f"# stats {stats.row()} {stats.by_status}")

    by_year = defaultdict(Counter)
    by_regime = defaultdict(Counter)
    rows = []
    for r in stats.results:
        regime = regimes.get(r.start_ts.date(), "unknown")
        by_year[r.start_ts.year][r.status] += 1
        by_regime[regime][r.status] += 1
        rows.append({
            "start": r.start_ts.isoformat(),
            "end": r.end_ts.isoformat() if r.end_ts else "",
            "status": r.status,
            "start_year": r.start_ts.year,
            "regime": regime,
            "days": r.days_elapsed,
            "trading_days": r.trading_days,
            "final_return_pct": round(r.final_return_pct * 100, 2),
            "worst_daily_dd_pct": round(r.worst_daily_dd * 100, 2),
            "worst_day_pct": round(r.worst_day * 100, 2),
            "best_day_pct": round(r.best_day * 100, 2),
            "worst_trade_pct": round(r.worst_trade * 100, 2),
        })

    print("\n# by_start_year")
    for year in sorted(by_year):
        total = sum(by_year[year].values())
        bits = " ".join(f"{k}={v}" for k, v in sorted(by_year[year].items()))
        print(f"{year},total={total},{bits}")

    print("\n# by_regime")
    for regime in sorted(by_regime):
        total = sum(by_regime[regime].values())
        bits = " ".join(f"{k}={v}" for k, v in sorted(by_regime[regime].items()))
        print(f"{regime},total={total},{bits}")

    failed = [r for r in stats.results if r.status != "passed"]
    failed.sort(key=lambda r: (r.status != "breach_total", r.final_return_pct))
    print("\n# worst_failed_windows")
    print("start,end,status,regime,days,final_pct,worst_daily_pct,worst_trades")
    for r in failed[:args.top]:
        regime = regimes.get(r.start_ts.date(), "unknown")
        window_trades = closed_trades_between(journal, r.start_ts, r.end_ts or r.start_ts)
        worst = sorted(window_trades, key=trade_pnl)[:3]
        worst_s = "|".join(
            f"{(t.get('close') or {}).get('timestamp','?')[:10]}:"
            f"{t.get('side','?')}:{(t.get('close') or {}).get('reason','?')}:"
            f"{trade_pnl(t):.0f}"
            for t in worst
        )
        print(f"{r.start_ts.date()},{(r.end_ts or r.start_ts).date()},"
              f"{r.status},{regime},{r.days_elapsed},"
              f"{r.final_return_pct * 100:.2f},{r.worst_daily_dd * 100:.2f},"
              f"{worst_s}")

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
        print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
