"""Matriz de sensibilidad del calendario de halving para Swing Allocator.

Uso:
    python tools/sens_phases.py

La ventana 2015-2026 esta cerrada para optimizacion: este script mide robustez
de los defaults v4, no selecciona parametros nuevos.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

ROOT = r"C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot"
sys.path.insert(0, ROOT)

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig

from loguru import logger

logger.remove()


@dataclass(frozen=True)
class PhaseCase:
    label: str
    post_end: int
    peak_end: int
    onset_end: int


CASES = [
    PhaseCase("default_180_540_900", 180, 540, 900),
    PhaseCase("post_end_120", 120, 540, 900),
    PhaseCase("post_end_240", 240, 540, 900),
    PhaseCase("onset_end_800", 180, 540, 800),
    PhaseCase("onset_end_1000", 180, 540, 1000),
    PhaseCase("shift_minus_30", 150, 510, 870),
    PhaseCase("shift_plus_30", 210, 570, 930),
    PhaseCase("shift_minus_60", 120, 480, 840),
    PhaseCase("shift_plus_60", 240, 600, 960),
]


def _run_case(case: PhaseCase, bars, warmup_bars: int):
    client = BacktestClient(
        "BTC-USDT",
        bars,
        initial_balance=Decimal("10000"),
        cost_mode="realistic",
    )

    def factory(c, s):
        cfg = SwingAllocatorConfig(
            phase_post_end=case.post_end,
            phase_peak_end=case.peak_end,
            phase_onset_end=case.onset_end,
            daily_on_closed_only=False,  # matriz F5 sobre v4 congelado
        )
        return SwingAllocatorBot(client=c, config=cfg, session=s)

    engine = BacktestEngine(client, factory, warmup_bars=warmup_bars, timeframe="1H")
    return engine.run()


def main() -> None:
    from_dt = datetime(2015, 1, 1, tzinfo=timezone.utc)
    to_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    warmup_start = from_dt - timedelta(days=250)
    bars = fetch_historical_bars("BTC-USDT", "1H", warmup_start, to_dt)
    from_ts = int(from_dt.timestamp() * 1000)
    warmup_bars = max(len([b for b in bars if b.timestamp < from_ts]), 20)

    print("case,post_end,peak_end,onset_end,cagr,max_dd,pf,trades,final,buy_hold")
    for case in CASES:
        r = _run_case(case, bars, warmup_bars)
        print(
            f"{case.label},{case.post_end},{case.peak_end},{case.onset_end},"
            f"{r.cagr},{r.max_drawdown_pct},{r.profit_factor},{r.total_trades},"
            f"{r.final_balance:.2f},{r.buy_hold_pnl_pct}"
        )


if __name__ == "__main__":
    main()
