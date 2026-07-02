"""Anchor report for Swing Allocator v5 post-audit freeze.

Usage:
    python tools/swing_v5_freeze_report.py

Runs the required Swing validation anchors with the current default config:
2015-2026 realistic, 2018-2026 realistic, and 2015-2026 conservative.
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
class Anchor:
    label: str
    from_dt: datetime
    to_dt: datetime
    cost_mode: str


ANCHORS = [
    Anchor(
        "BTC_2015_2026_realistic",
        datetime(2015, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "realistic",
    ),
    Anchor(
        "BTC_2018_2026_realistic",
        datetime(2018, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "realistic",
    ),
    Anchor(
        "BTC_2015_2026_conservative",
        datetime(2015, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "conservative",
    ),
]


def _warmup_bars(bars, from_dt: datetime) -> int:
    from_ts = int(from_dt.timestamp() * 1000)
    return max(len([b for b in bars if b.timestamp < from_ts]), 20)


def _btc_ratio(strategy: SwingAllocatorBot, client: BacktestClient) -> tuple[float, float, float]:
    final_btc = float(client.get_balance().get("BTC", Decimal("0")))
    init_ev = next((r for r in strategy._rebalance_log if r["direction"] == "INIT"), None)
    init_px = init_ev["price"] if init_ev else 0.0
    bnh_btc = (float(client.initial_balance) / init_px) if init_px > 0 else 0.0
    ratio = final_btc / bnh_btc if bnh_btc > 0 else 0.0
    return final_btc, bnh_btc, ratio


def _run(anchor: Anchor):
    warmup_start = anchor.from_dt - timedelta(days=250)
    bars = fetch_historical_bars("BTC-USDT", "1H", warmup_start, anchor.to_dt)
    client = BacktestClient(
        "BTC-USDT",
        bars,
        initial_balance=Decimal("10000"),
        cost_mode=anchor.cost_mode,
    )

    def factory(c, s):
        return SwingAllocatorBot(client=c, config=SwingAllocatorConfig(), session=s)

    engine = BacktestEngine(
        client,
        factory,
        warmup_bars=_warmup_bars(bars, anchor.from_dt),
        timeframe="1H",
    )
    result = engine.run()
    final_btc, bnh_btc, btc_ratio = _btc_ratio(engine.last_strategy, client)
    return result, final_btc, bnh_btc, btc_ratio


def main() -> None:
    print(
        "label,cost,bars,final,cagr,max_dd,calmar,sharpe,sortino,pf,"
        "rebalances,underwater_days,final_btc,bnh_btc,btc_vs_bnh,buy_hold_pct"
    )
    for anchor in ANCHORS:
        r, final_btc, bnh_btc, btc_ratio = _run(anchor)
        print(
            f"{anchor.label},{anchor.cost_mode},{r.bars_tested},{r.final_balance:.2f},"
            f"{r.cagr},{r.max_drawdown_pct},{r.calmar},{r.sharpe_ratio},{r.sortino},"
            f"{r.profit_factor},{r.total_trades},{r.underwater_days},"
            f"{final_btc:.8f},{bnh_btc:.8f},{btc_ratio:.4f},{r.buy_hold_pnl_pct}"
        )


if __name__ == "__main__":
    main()
