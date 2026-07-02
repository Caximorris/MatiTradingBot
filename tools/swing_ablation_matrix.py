"""Ablations minimas del Swing Allocator para el plan de auditoria.

Uso:
    python tools/swing_ablation_matrix.py

F6 mide halving-only contra v4 en ventanas/costes pendientes. No optimiza defaults.
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
class WindowCase:
    label: str
    from_dt: datetime
    to_dt: datetime
    cost_mode: str


@dataclass(frozen=True)
class ConfigCase:
    label: str
    overrides: dict


WINDOWS = [
    WindowCase(
        "2018_2026_realistic",
        datetime(2018, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "realistic",
    ),
    WindowCase(
        "2015_2026_conservative",
        datetime(2015, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "conservative",
    ),
]

CONFIGS = [
    ConfigCase("v4_frozen", {"daily_on_closed_only": False}),
    ConfigCase("halving_only", {"use_regime": False, "daily_on_closed_only": False}),
]


def _warmup_bars(bars, from_dt: datetime) -> int:
    from_ts = int(from_dt.timestamp() * 1000)
    return max(len([b for b in bars if b.timestamp < from_ts]), 20)


def _btc_ratio(strategy: SwingAllocatorBot, client: BacktestClient) -> tuple[float, float, float]:
    base_ccy = "BTC"
    final_btc = float(client.get_balance().get(base_ccy, Decimal("0")))
    init_ev = next((r for r in strategy._rebalance_log if r["direction"] == "INIT"), None)
    init_px = init_ev["price"] if init_ev else 0.0
    bnh_btc = (float(client.initial_balance) / init_px) if init_px > 0 else 0.0
    ratio = final_btc / bnh_btc if bnh_btc > 0 else 0.0
    return final_btc, bnh_btc, ratio


def _run(window: WindowCase, config_case: ConfigCase, bars):
    client = BacktestClient(
        "BTC-USDT",
        bars,
        initial_balance=Decimal("10000"),
        cost_mode=window.cost_mode,
    )

    def factory(c, s):
        cfg = SwingAllocatorConfig.from_dict(config_case.overrides)
        return SwingAllocatorBot(client=c, config=cfg, session=s)

    engine = BacktestEngine(
        client,
        factory,
        warmup_bars=_warmup_bars(bars, window.from_dt),
        timeframe="1H",
    )
    result = engine.run()
    final_btc, bnh_btc, btc_ratio = _btc_ratio(engine.last_strategy, client)
    return result, final_btc, bnh_btc, btc_ratio


def main() -> None:
    print("window,config,cost,cagr,max_dd,pf,trades,final,final_btc,bnh_btc,btc_vs_bnh")
    for window in WINDOWS:
        warmup_start = window.from_dt - timedelta(days=250)
        bars = fetch_historical_bars("BTC-USDT", "1H", warmup_start, window.to_dt)
        for cfg in CONFIGS:
            r, final_btc, bnh_btc, btc_ratio = _run(window, cfg, bars)
            print(
                f"{window.label},{cfg.label},{window.cost_mode},{r.cagr},"
                f"{r.max_drawdown_pct},{r.profit_factor},{r.total_trades},{r.final_balance:.2f},"
                f"{final_btc:.8f},{bnh_btc:.8f},{btc_ratio:.4f}"
            )


if __name__ == "__main__":
    main()
