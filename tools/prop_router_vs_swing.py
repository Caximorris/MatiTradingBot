#!/usr/bin/env python
"""Compare the phase-router prop candidate against Swing and B&H.

This report treats the prop router as if it were run with own capital. That is
not its intended objective, but it makes the opportunity cost versus Swing and
Buy & Hold explicit.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger

logger.remove()

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from core.prop_rules import simulate_challenges
from strategies import registry
from strategies.macro_context import MacroContext
from tools.prop_challenge_sim import rule_configs


PROP_ROUTER = {
    "entry_mode": "breakout",
    "risk_per_trade": 0.018,
    "tp1_r": 1.5,
    "allow_shorts": True,
    "max_notional_pct": 0.8,
    "model_funding": True,
    "entry_halving_phases": "bear_onset,accumulation",
}


@dataclass(frozen=True)
class Window:
    label: str
    start: str
    end: str


WINDOWS = [
    Window("2018-2026", "2018-01-01", "2026-01-01"),
    Window("2020-2026", "2020-01-01", "2026-01-01"),
]
_PHASE_CTX = MacroContext("BTC")


def _dt(raw: str) -> datetime:
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


def _run_strategy(
    strategy: str,
    start: datetime,
    end: datetime,
    costs: str,
    config: dict[str, Any] | None = None,
):
    meta = registry.get(strategy)
    bars = fetch_historical_bars("BTC-USDT", "1H",
                                 start - timedelta(days=meta.warmup_days), end)
    client = BacktestClient("BTC-USDT", bars, initial_balance=Decimal("10000"),
                            cost_mode=costs)
    cfg_obj = meta.make_config("BTC-USDT", config or {})

    def factory(c, s):
        return meta.make_bot(c, cfg_obj, s)

    from_ts = int(start.timestamp() * 1000)
    warmup = max(len([b for b in bars if b.timestamp < from_ts]), 20)
    result = BacktestEngine(client, factory, warmup_bars=warmup,
                            timeframe="1H").run()
    strategy_obj = getattr(result, "_strategy", None)
    return result, client


def _run_prop_with_stats(start: datetime, end: datetime, costs: str):
    meta = registry.get("prop")
    bars = fetch_historical_bars("BTC-USDT", "1H",
                                 start - timedelta(days=meta.warmup_days), end)
    client = BacktestClient("BTC-USDT", bars, initial_balance=Decimal("10000"),
                            cost_mode=costs)
    cfg_obj = meta.make_config("BTC-USDT", PROP_ROUTER)

    def factory(c, s):
        return meta.make_bot(c, cfg_obj, s)

    from_ts = int(start.timestamp() * 1000)
    warmup = max(len([b for b in bars if b.timestamp < from_ts]), 20)
    engine = BacktestEngine(client, factory, warmup_bars=warmup, timeframe="1H")
    result = engine.run()
    trades = list(getattr(engine.last_strategy, "realized", None) or [])
    label, cfg, two_step = next(x for x in rule_configs("cft") if x[0] == "cft_two_phase")
    cfg = cfg.with_(label=f"{label}@540d", intrabar_buffer=0.2, max_days=540)
    def start_filter(ts: datetime) -> bool:
        return _PHASE_CTX.halving_phase(ts)[1] in ("bear_onset", "accumulation")

    stats = simulate_challenges(result.equity_curve, cfg, trade_pnls=trades,
                                two_step=two_step, start_filter=start_filter)
    return result, stats


def _max_dd(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100)
    return worst


def _bnh_row(window: Window) -> dict[str, Any]:
    start, end = _dt(window.start), _dt(window.end)
    bars = fetch_historical_bars("BTC-USDT", "1H", start, end)
    initial = 10000.0
    fee = 0.001
    slip = 0.0005
    entry_cost = (1 + fee) * (1 + slip)
    qty = initial / (float(bars[0].close) * entry_cost)
    curve = [qty * float(b.close) for b in bars]
    final = curve[-1]
    pnl = (final / initial - 1) * 100
    years = (_dt(window.end) - _dt(window.start)).days / 365.25
    cagr = ((final / initial) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    return {
        "window": window.label,
        "strategy": "BTC Buy & Hold",
        "objective": "own_capital",
        "costs": "realistic_entry",
        "final_balance": round(final, 2),
        "total_return_pct": round(pnl, 2),
        "cagr_pct": round(cagr, 2),
        "max_dd_pct": round(_max_dd(curve), 2),
        "trades": 1,
        "pf": "",
        "pass_rate": "",
        "breach_rate": "",
        "timeout_rate": "",
    }


def _strategy_row(window: Window, name: str, objective: str, costs: str, result,
                  stats=None) -> dict[str, Any]:
    return {
        "window": window.label,
        "strategy": name,
        "objective": objective,
        "costs": costs,
        "final_balance": round(float(result.final_balance), 2),
        "total_return_pct": round(float(result.total_pnl_pct), 2),
        "cagr_pct": round(float(result.cagr), 2),
        "max_dd_pct": round(float(result.max_drawdown_pct), 2),
        "trades": result.total_trades,
        "pf": round(float(result.profit_factor), 2),
        "pass_rate": "" if stats is None else round(stats.pass_rate * 100, 1),
        "breach_rate": "" if stats is None else round(stats.breach_rate * 100, 1),
        "timeout_rate": "" if stats is None else round(stats.timeout_rate * 100, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/runtime/prop_router_vs_swing.csv")
    args = p.parse_args()

    rows = []
    for window in WINDOWS:
        start, end = _dt(window.start), _dt(window.end)
        swing_result, _client = _run_strategy("swing", start, end, "realistic")
        prop_result, prop_stats = _run_prop_with_stats(start, end, "bybit_cons")
        rows.append(_strategy_row(window, "Prop phase-router CFT", "prop_challenge",
                                  "bybit_cons", prop_result, prop_stats))
        rows.append(_strategy_row(window, "Swing Allocator v5", "own_capital",
                                  "realistic", swing_result))
        rows.append(_bnh_row(window))

    fieldnames = [
        "window", "strategy", "objective", "costs", "final_balance",
        "total_return_pct", "cagr_pct", "max_dd_pct", "trades", "pf",
        "pass_rate", "breach_rate", "timeout_rate",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"# wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
