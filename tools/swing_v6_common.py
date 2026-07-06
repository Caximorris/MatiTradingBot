"""Shared helpers for Swing v6 validation tools.

These helpers keep the v6 research scripts on the same backtest path so
candidate/baseline rows use the same warmup, candle count, cost mode, and BTC
ratio calculation.
"""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.macro_context import HALVING_DATES, MacroContext
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig


@dataclass(frozen=True)
class SwingRun:
    result: Any
    strategy: SwingAllocatorBot
    client: BacktestClient
    final_btc_qty: float
    bnh_initial_btc: float
    btc_vs_bnh_ratio: float


def parse_utc_date(raw: str) -> datetime:
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


def parse_config(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("--config must be a JSON object")
    return data


def warmup_bars_for(bars: list[Any], from_dt: datetime) -> int:
    from_ts = int(from_dt.timestamp() * 1000)
    return max(len([b for b in bars if b.timestamp < from_ts]), 20)


def load_bars(
    symbol: str,
    from_dt: datetime,
    to_dt: datetime,
    warmup_days: int = 250,
) -> list[Any]:
    warmup_start = from_dt - timedelta(days=warmup_days)
    return fetch_historical_bars(symbol, "1H", warmup_start, to_dt)


def btc_ratio(strategy: SwingAllocatorBot, client: BacktestClient) -> tuple[float, float, float]:
    base = client._symbol.split("-")[0]
    final_btc = float(client.get_balance().get(base, Decimal("0")))
    init_ev = next((r for r in strategy._rebalance_log if r.get("direction") == "INIT"), None)
    init_px = float(init_ev.get("price", 0.0)) if init_ev else 0.0
    bnh_btc = float(client.initial_balance) / init_px if init_px > 0 else 0.0
    ratio = final_btc / bnh_btc if bnh_btc > 0 else 0.0
    return final_btc, bnh_btc, ratio


def run_swing_backtest(
    *,
    symbol: str,
    from_dt: datetime,
    to_dt: datetime,
    cost_mode: str,
    config: dict[str, Any] | None = None,
    bars: list[Any] | None = None,
    warmup_days: int = 250,
) -> SwingRun:
    bars = bars or load_bars(symbol, from_dt, to_dt, warmup_days=warmup_days)
    client = BacktestClient(
        symbol,
        bars,
        initial_balance=Decimal("10000"),
        cost_mode=cost_mode,
    )
    warmup = warmup_bars_for(bars, from_dt)
    cfg = SwingAllocatorConfig.from_dict(config or {})

    def factory(c, s):
        return SwingAllocatorBot(client=c, config=cfg, session=s)

    engine = BacktestEngine(client, factory, warmup_bars=warmup, timeframe="1H")
    result = engine.run()
    final_btc, bnh_btc, ratio = btc_ratio(engine.last_strategy, client)
    return SwingRun(result, engine.last_strategy, client, final_btc, bnh_btc, ratio)


def halving_phase_at(dt: datetime, symbol: str = "BTC-USDT") -> str:
    base = symbol.split("-")[0].upper()
    return MacroContext(base).halving_phase(dt)[1]


def cycle_label(dt: datetime) -> str:
    d = dt.date()
    last = HALVING_DATES[0]
    for h in HALVING_DATES:
        if h <= d:
            last = h
    return f"{last.year}_cycle"


def infer_phase(signals: list[str] | None, dt: datetime, symbol: str = "BTC-USDT") -> str:
    for sig in signals or []:
        if sig == "halving_bear_onset":
            return "bear_onset"
        if sig.startswith("halving_post_halving"):
            return "post_halving"
        if sig.startswith("halving_bull_peak"):
            return "bull_peak"
        if sig.startswith("halving_accumulation"):
            return "accumulation"
    return halving_phase_at(dt, symbol)


def metrics_row(label: str, run: SwingRun, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    r = run.result
    row: dict[str, Any] = {
        "label": label,
        "cost": r.cost_mode,
        "start": r.start_date.date().isoformat(),
        "end": r.end_date.date().isoformat(),
        "bars": r.bars_tested,
        "final": f"{r.final_balance:.2f}",
        "cagr": str(r.cagr),
        "max_dd": str(r.max_drawdown_pct),
        "pf": str(r.profit_factor),
        "rebalance_events": len([x for x in run.strategy._rebalance_log if x.get("direction") != "INIT"]),
        "acb_trades": r.total_trades,
        "underwater_days": r.underwater_days,
        "final_btc_qty": f"{run.final_btc_qty:.8f}",
        "bnh_initial_btc": f"{run.bnh_initial_btc:.8f}",
        "btc_vs_bnh_ratio": f"{run.btc_vs_bnh_ratio:.4f}",
        "buy_hold_pct": str(r.buy_hold_pnl_pct),
    }
    if extra:
        row.update(extra)
    return row


def verdict_vs_baseline(candidate: SwingRun, baseline: SwingRun) -> str:
    c = candidate.result
    b = baseline.result
    cagr_delta = float(c.cagr - b.cagr)
    dd_delta = float(c.max_drawdown_pct - b.max_drawdown_pct)
    ratio_delta = candidate.btc_vs_bnh_ratio - baseline.btc_vs_bnh_ratio
    reb_base = len([x for x in baseline.strategy._rebalance_log if x.get("direction") != "INIT"])
    reb_cand = len([x for x in candidate.strategy._rebalance_log if x.get("direction") != "INIT"])
    reb_limit = reb_base * 1.2 if reb_base else reb_cand
    if cagr_delta < -0.5 or dd_delta > 1.0 or ratio_delta < -0.03 or reb_cand > reb_limit:
        return "REJECT"
    return "NEEDS_MORE_VALIDATION"


def iter_start_dates(
    from_dt: datetime,
    to_dt: datetime,
    step_days: int,
    min_days: int = 365,
) -> list[datetime]:
    dates: list[datetime] = []
    cur = from_dt
    latest = to_dt - timedelta(days=min_days)
    while cur <= latest:
        dates.append(cur)
        cur += timedelta(days=step_days)
    return dates


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
