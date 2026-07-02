"""Sensibilidad del umbral bear_onset (540d) del reloj de halving.
Uso: python sens_halving.py <bound_dias>
"""
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

ROOT = r"C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot"
sys.path.insert(0, ROOT)

BOUND = int(sys.argv[1])

import strategies.macro_context as mc

def patched(self, dt):
    from datetime import date as _date
    if self._asset != "BTC":
        return 0, "unknown"
    d = dt.date() if isinstance(dt, datetime) else dt
    last = mc.HALVING_DATES[0]
    for h in mc.HALVING_DATES:
        if h <= d:
            last = h
        else:
            break
    days = (d - last).days
    if days < 180:
        ph = "post_halving"
    elif days < BOUND:
        ph = "bull_peak"
    elif days < 900:
        ph = "bear_onset"
    else:
        ph = "accumulation"
    return days, ph

mc.MacroContext.halving_phase = patched

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig

from_dt = datetime(2015, 1, 1, tzinfo=timezone.utc)
to_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
warmup_start = from_dt - timedelta(days=250)
bars = fetch_historical_bars("BTC-USDT", "1H", warmup_start, to_dt)
from_ts = int(from_dt.timestamp() * 1000)
wb = len([b for b in bars if b.timestamp < from_ts])
client = BacktestClient("BTC-USDT", bars, initial_balance=Decimal("10000"), cost_mode="realistic")

def factory(c, s):
    return SwingAllocatorBot(client=c, config=SwingAllocatorConfig(), session=s)

engine = BacktestEngine(client, factory, warmup_bars=max(wb, 20), timeframe="1H")
r = engine.run()
print(f"RESULT BOUND={BOUND}: CAGR {r.cagr}% | MaxDD -{r.max_drawdown_pct}% | PF {r.profit_factor} "
      f"| trades {r.total_trades} | final {r.final_balance:,.0f} | B&H {r.buy_hold_pnl_pct}%")
