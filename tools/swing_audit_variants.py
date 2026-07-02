"""Checks aislados de limpieza para Swing v4 (F8/F9/F10).

Uso:
    python tools/swing_audit_variants.py

Mide variantes tecnicas contra v4 sin elegir parametros por CAGR.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])  # portable (VM Linux / Windows)
sys.path.insert(0, ROOT)

from loguru import logger

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig

logger.remove()


@dataclass(frozen=True)
class VariantCase:
    label: str
    from_dt: datetime
    config: dict
    fill_next_open: bool = False


BASE_FROM = datetime(2015, 1, 1, tzinfo=timezone.utc)
OFFSET_FROM = datetime(2015, 1, 2, tzinfo=timezone.utc)
TO_DT = datetime(2026, 1, 1, tzinfo=timezone.utc)

CASES = [
    VariantCase("baseline_v4_frozen", BASE_FROM, {"daily_on_closed_only": False}),
    VariantCase("daily_closed_only", BASE_FROM, {"daily_on_closed_only": True}),
    VariantCase(
        "clock_aligned_v4_frozen",
        BASE_FROM,
        {"daily_on_closed_only": False, "clock_aligned_cadence": True},
    ),
    VariantCase(
        "fill_next_open_v4_frozen",
        BASE_FROM,
        {"daily_on_closed_only": False},
        fill_next_open=True,
    ),
    VariantCase("baseline_v4_frozen_from_2015_01_02", OFFSET_FROM, {"daily_on_closed_only": False}),
    VariantCase(
        "clock_aligned_v4_frozen_from_2015_01_02",
        OFFSET_FROM,
        {"daily_on_closed_only": False, "clock_aligned_cadence": True},
    ),
]


def _warmup_bars(bars, from_dt: datetime) -> int:
    from_ts = int(from_dt.timestamp() * 1000)
    return max(len([b for b in bars if b.timestamp < from_ts]), 20)


def _run(case: VariantCase, bars):
    client = BacktestClient(
        "BTC-USDT",
        bars,
        initial_balance=Decimal("10000"),
        cost_mode="realistic",
        fill_next_open=case.fill_next_open,
    )

    def factory(c, s):
        return SwingAllocatorBot(
            client=c,
            config=SwingAllocatorConfig.from_dict(case.config),
            session=s,
        )

    engine = BacktestEngine(
        client,
        factory,
        warmup_bars=_warmup_bars(bars, case.from_dt),
        timeframe="1H",
    )
    return engine.run()


def main() -> None:
    warmup_start = min(c.from_dt for c in CASES) - timedelta(days=250)
    bars = fetch_historical_bars("BTC-USDT", "1H", warmup_start, TO_DT)
    print("case,from,cagr,max_dd,pf,trades,final,underwater,buy_hold")
    for case in CASES:
        result = _run(case, bars)
        print(
            f"{case.label},{case.from_dt.date()},{result.cagr},{result.max_drawdown_pct},"
            f"{result.profit_factor},{result.total_trades},{result.final_balance:.2f},"
            f"{result.underwater_days},{result.buy_hold_pnl_pct}"
        )


if __name__ == "__main__":
    main()
