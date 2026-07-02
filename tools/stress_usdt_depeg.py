"""Stress test de depeg USDT para Swing Allocator (F16).

Uso:
    python tools/stress_usdt_depeg.py

Aplica una perdida unica al saldo USDT en fechas de bear market y deja que el
backtest continue con menos capital estable disponible.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])  # portable (VM Linux / Windows)
sys.path.insert(0, ROOT)

from loguru import logger

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig

logger.remove()


@dataclass(frozen=True)
class StressCase:
    label: str
    shock_date: date | None
    haircut: Decimal


CASES = [
    StressCase("baseline", None, Decimal("0")),
    StressCase("depeg_2018_06_minus_5pct", date(2018, 6, 1), Decimal("0.05")),
    StressCase("depeg_2018_06_minus_10pct", date(2018, 6, 1), Decimal("0.10")),
    StressCase("depeg_2022_06_minus_5pct", date(2022, 6, 1), Decimal("0.05")),
    StressCase("depeg_2022_06_minus_10pct", date(2022, 6, 1), Decimal("0.10")),
]


def _run(case: StressCase, bars, warmup_bars: int):
    client = BacktestClient(
        "BTC-USDT",
        bars,
        initial_balance=Decimal("10000"),
        cost_mode="realistic",
    )

    def factory(c, s):
        return SwingAllocatorBot(client=c, config=SwingAllocatorConfig(), session=s)

    engine = BacktestEngine(client, factory, warmup_bars=warmup_bars, timeframe="1H")
    applied = {"done": False, "loss": Decimal("0")}

    def maybe_shock(_done: int, _total: int) -> None:
        if applied["done"] or case.shock_date is None:
            return
        if client.current_bar_ts().date() >= case.shock_date:
            usdt = client._balance.get("USDT", Decimal("0"))
            loss = (usdt * case.haircut).quantize(Decimal("0.01"))
            client._balance["USDT"] = usdt - loss
            applied["done"] = True
            applied["loss"] = loss

    result = engine.run(on_tick=maybe_shock, tick_interval=1)
    return result, applied["loss"]


def main() -> None:
    from_dt = datetime(2015, 1, 1, tzinfo=timezone.utc)
    to_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    warmup_start = from_dt - timedelta(days=250)
    bars = fetch_historical_bars("BTC-USDT", "1H", warmup_start, to_dt)
    from_ts = int(from_dt.timestamp() * 1000)
    warmup_bars = max(len([b for b in bars if b.timestamp < from_ts]), 20)

    print("case,shock_date,haircut,loss_usdt,cagr,max_dd,final")
    for case in CASES:
        result, loss = _run(case, bars, warmup_bars)
        print(
            f"{case.label},{case.shock_date or ''},{case.haircut},{loss},"
            f"{result.cagr},{result.max_drawdown_pct},{result.final_balance:.2f}"
        )


if __name__ == "__main__":
    main()
