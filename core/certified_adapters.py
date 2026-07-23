"""Mode adapters that deliberately share one certified execution contract."""
from __future__ import annotations

from decimal import Decimal

from core.certification import CertifiedEngine


def run_captured(mode: str, bars, strategy, *, warmup_bars: int, fee_rate: Decimal,
                 slippage_bps: Decimal, initial_cash: Decimal = Decimal("10000")):
    if mode not in {"backtest", "replay", "report", "shadow", "paper", "live_dry_run"}:
        raise ValueError("unknown certified adapter mode")
    engine = CertifiedEngine(bars, initial_cash=initial_cash, fee_rate=fee_rate,
                             slippage_bps=slippage_bps)
    orders = engine.run(strategy, warmup_bars=warmup_bars)
    return orders, engine.cash, engine.base_qty
