"""Check puntual de paridad Swing: OKXClient vs BacktestClient con las mismas velas.

Uso:
    python tools/swing_parity_check.py

No sustituye el cierre F15 (30 dias consecutivos); solo detecta divergencias inmediatas
de schema/datos/target.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal

ROOT = r"C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot"
sys.path.insert(0, ROOT)

from config.settings import settings
from core.backtest import BacktestClient
from core.exchange import OKXClient
from data.market_data import OHLCVBar
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig
from loguru import logger

logger.remove()


def _bars_from_df(df) -> list[OHLCVBar]:
    bars = []
    for row in df.itertuples(index=False):
        bars.append(
            OHLCVBar(
                timestamp=int(row.timestamp),
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
            )
        )
    return bars


def main() -> None:
    symbol = "BTC-USDT"
    cfg = SwingAllocatorConfig()

    okx = OKXClient(settings)
    df = okx.get_ohlcv(symbol, "1H", limit=6000)
    if df is None or len(df) < 500:
        raise SystemExit(f"OHLCV insuficiente desde OKX: {0 if df is None else len(df)}")

    bars = _bars_from_df(df)
    latest_dt = datetime.fromtimestamp(bars[-1].timestamp / 1000, tz=timezone.utc)
    okx.current_time = lambda: latest_dt  # type: ignore[method-assign]
    okx.get_ohlcv = lambda _symbol, _timeframe="1H", limit=100: df.tail(limit).copy()  # type: ignore[method-assign]
    okx.get_ticker = lambda _symbol: Decimal(str(df.iloc[-1]["close"]))  # type: ignore[method-assign]

    bt = BacktestClient(symbol, bars, initial_balance=Decimal("10000"), cost_mode="realistic")
    bt.advance(len(bars) - 1)

    live_bot = SwingAllocatorBot(okx, cfg)
    bt_bot = SwingAllocatorBot(bt, cfg)
    current = cfg.base_btc_pct
    live_target, live_signals = live_bot._compute_target(current)
    bt_target, bt_signals = bt_bot._compute_target(current)

    print(f"timestamp,{latest_dt.isoformat()}")
    print(f"live_target,{live_target:.4f}")
    print(f"backtest_target,{bt_target:.4f}")
    print(f"live_signals,{';'.join(live_signals)}")
    print(f"backtest_signals,{';'.join(bt_signals)}")
    if live_target != bt_target or live_signals != bt_signals:
        raise SystemExit("PARITY_FAIL")
    print("PARITY_OK")


if __name__ == "__main__":
    main()
