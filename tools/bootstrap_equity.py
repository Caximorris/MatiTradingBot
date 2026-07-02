"""Bootstrap por bloques mensuales de la equity Swing v4.

Uso:
    python tools/bootstrap_equity.py

Resamplea con reemplazo los retornos horarios agrupados por mes. El objetivo es estimar
cola de CAGR/MaxDD; no selecciona parametros.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])  # portable (VM Linux / Windows)
sys.path.insert(0, ROOT)

from loguru import logger

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig

logger.remove()


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = (len(ordered) - 1) * pct
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    weight = idx - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def _max_dd(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        dd = (peak - value) / peak * 100 if peak > 0 else 0.0
        if dd > worst:
            worst = dd
    return worst


def _run_v4():
    from_dt = datetime(2015, 1, 1, tzinfo=timezone.utc)
    to_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    warmup_start = from_dt - timedelta(days=250)
    bars = fetch_historical_bars("BTC-USDT", "1H", warmup_start, to_dt)
    from_ts = int(from_dt.timestamp() * 1000)
    warmup_bars = max(len([b for b in bars if b.timestamp < from_ts]), 20)
    client = BacktestClient(
        "BTC-USDT",
        bars,
        initial_balance=Decimal("10000"),
        cost_mode="realistic",
    )

    def factory(c, s):
        return SwingAllocatorBot(
            client=c,
            config=SwingAllocatorConfig(daily_on_closed_only=False),
            session=s,
        )

    engine = BacktestEngine(client, factory, warmup_bars=warmup_bars, timeframe="1H")
    return engine.run()


def _monthly_return_blocks(equity_curve: list[tuple[datetime, Decimal]]) -> list[list[float]]:
    blocks: dict[tuple[int, int], list[float]] = {}
    prev = float(equity_curve[0][1])
    for dt, value_dec in equity_curve[1:]:
        value = float(value_dec)
        if prev > 0:
            blocks.setdefault((dt.year, dt.month), []).append(value / prev)
        prev = value
    return [block for _, block in sorted(blocks.items()) if block]


def main() -> None:
    result = _run_v4()
    blocks = _monthly_return_blocks(result.equity_curve)
    years = (
        result.equity_curve[-1][0] - result.equity_curve[0][0]
    ).days / 365.25

    rng = random.Random(42)
    sims = 1000
    cagrs: list[float] = []
    dds: list[float] = []
    finals: list[float] = []

    for _ in range(sims):
        equity = [float(result.initial_balance)]
        for block in (rng.choice(blocks) for _ in range(len(blocks))):
            for ratio in block:
                equity.append(equity[-1] * ratio)
        final = equity[-1]
        finals.append(final)
        cagrs.append(((final / float(result.initial_balance)) ** (1 / years) - 1) * 100)
        dds.append(_max_dd(equity))

    print(f"source_cagr,{result.cagr}")
    print(f"source_max_dd,{result.max_drawdown_pct}")
    print(f"source_final,{result.final_balance:.2f}")
    print(f"blocks,{len(blocks)}")
    print(f"sims,{sims}")
    print(f"final_p05,{_percentile(finals, 0.05):.2f}")
    print(f"final_p50,{median(finals):.2f}")
    print(f"final_p95,{_percentile(finals, 0.95):.2f}")
    print(f"cagr_p05,{_percentile(cagrs, 0.05):.2f}")
    print(f"cagr_p50,{median(cagrs):.2f}")
    print(f"cagr_p95,{_percentile(cagrs, 0.95):.2f}")
    print(f"maxdd_p50,{median(dds):.2f}")
    print(f"maxdd_p95,{_percentile(dds, 0.95):.2f}")
    print(f"maxdd_p99,{_percentile(dds, 0.99):.2f}")


if __name__ == "__main__":
    main()
