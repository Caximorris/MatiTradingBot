"""Benchmarks simples para Swing Allocator (F18 parcial).

Uso:
    python tools/swing_benchmarks.py

Incluye DCA semanal, EMA200D long/flat y 60/40 mensual. No optimiza parametros.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd

ROOT = r"C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot"
sys.path.insert(0, ROOT)

from loguru import logger

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig

logger.remove()


FEE = Decimal("0.001")
SLIP = Decimal("0.0005")


@dataclass
class BenchResult:
    name: str
    final: Decimal
    cagr: float
    max_dd: float
    trades: int


def _buy(usdt: Decimal, price: Decimal, spend: Decimal) -> tuple[Decimal, Decimal]:
    spend = min(spend, usdt)
    exec_price = price * (Decimal("1") + SLIP)
    qty = spend / (exec_price * (Decimal("1") + FEE))
    return usdt - spend, qty


def _sell(usdt: Decimal, btc: Decimal, price: Decimal, qty: Decimal) -> tuple[Decimal, Decimal]:
    qty = min(qty, btc)
    exec_price = price * (Decimal("1") - SLIP)
    proceeds = qty * exec_price * (Decimal("1") - FEE)
    return usdt + proceeds, btc - qty


def _metrics(name: str, curve: list[Decimal], trades: int, years: float) -> BenchResult:
    peak = curve[0]
    worst = Decimal("0")
    for value in curve:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak * Decimal("100")
            if dd > worst:
                worst = dd
    final = curve[-1]
    cagr = ((float(final / curve[0]) ** (1 / years)) - 1) * 100
    return BenchResult(name, final, cagr, float(worst), trades)


def _df_from_bars(bars):
    return pd.DataFrame(
        {
            "timestamp": [b.timestamp for b in bars],
            "dt": [datetime.fromtimestamp(b.timestamp / 1000, tz=timezone.utc) for b in bars],
            "close": [float(b.close) for b in bars],
        }
    )


def _dca_weekly(test_bars, balance: Decimal, years: float) -> BenchResult:
    weeks = []
    seen = set()
    for b in test_bars:
        dt = datetime.fromtimestamp(b.timestamp / 1000, tz=timezone.utc)
        key = dt.isocalendar()[:2]
        if key not in seen:
            seen.add(key)
            weeks.append(b.timestamp)
    tranche = balance / Decimal(len(weeks))
    usdt, btc = balance, Decimal("0")
    week_set = set(weeks)
    trades = 0
    curve = []
    for b in test_bars:
        if b.timestamp in week_set and usdt > Decimal("0"):
            usdt, qty = _buy(usdt, b.close, tranche)
            btc += qty
            trades += 1
        curve.append(usdt + btc * b.close)
    return _metrics("DCA semanal", curve, trades, years)


def _monthly_6040(test_bars, balance: Decimal, years: float) -> BenchResult:
    usdt, btc = balance, Decimal("0")
    trades = 0
    curve = []
    last_month = None
    for b in test_bars:
        dt = datetime.fromtimestamp(b.timestamp / 1000, tz=timezone.utc)
        month = (dt.year, dt.month)
        total = usdt + btc * b.close
        if last_month != month:
            target_btc = total * Decimal("0.60")
            current_btc = btc * b.close
            delta = target_btc - current_btc
            if delta > Decimal("1"):
                usdt, qty = _buy(usdt, b.close, delta)
                btc += qty
                trades += 1
            elif delta < Decimal("-1"):
                usdt, btc = _sell(usdt, btc, b.close, abs(delta) / b.close)
                trades += 1
            last_month = month
        curve.append(usdt + btc * b.close)
    return _metrics("60/40 mensual", curve, trades, years)


def _ema200_longflat(bars, from_dt: datetime, balance: Decimal, years: float) -> BenchResult:
    df = _df_from_bars(bars)
    daily = df.set_index("dt")["close"].resample("1D").last().dropna()
    ema = daily.ewm(span=200, adjust=False).mean().shift(1)
    ema_by_day = {idx.date(): val for idx, val in ema.items()}
    usdt, btc = balance, Decimal("0")
    trades = 0
    curve = []
    for b in bars:
        dt = datetime.fromtimestamp(b.timestamp / 1000, tz=timezone.utc)
        if dt < from_dt:
            continue
        ema_val = ema_by_day.get(dt.date())
        if ema_val is not None:
            long = float(b.close) > float(ema_val)
            if long and btc == 0:
                usdt, qty = _buy(usdt, b.close, usdt)
                btc += qty
                trades += 1
            elif not long and btc > 0:
                usdt, btc = _sell(usdt, btc, b.close, btc)
                trades += 1
        curve.append(usdt + btc * b.close)
    return _metrics("EMA200D long/flat", curve, trades, years)


def _swing(bars, warmup_bars: int, balance: Decimal) -> BenchResult:
    client = BacktestClient("BTC-USDT", bars, initial_balance=balance, cost_mode="realistic")

    def factory(c, s):
        return SwingAllocatorBot(client=c, config=SwingAllocatorConfig(), session=s)

    result = BacktestEngine(client, factory, warmup_bars=warmup_bars, timeframe="1H").run()
    return BenchResult("Swing current", result.final_balance, float(result.cagr), float(result.max_drawdown_pct), result.total_trades)


def main() -> None:
    from_dt = datetime(2015, 1, 1, tzinfo=timezone.utc)
    to_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    balance = Decimal("10000")
    bars = fetch_historical_bars("BTC-USDT", "1H", from_dt - timedelta(days=250), to_dt)
    from_ts = int(from_dt.timestamp() * 1000)
    warmup_bars = max(len([b for b in bars if b.timestamp < from_ts]), 20)
    test_bars = [b for b in bars if b.timestamp >= from_ts]
    years = (to_dt - from_dt).days / 365.25

    results = [
        _swing(bars, warmup_bars, balance),
        _monthly_6040(test_bars, balance, years),
        _ema200_longflat(bars, from_dt, balance, years),
        _dca_weekly(test_bars, balance, years),
    ]
    print("benchmark,final,cagr,max_dd,trades")
    for r in results:
        print(f"{r.name},{r.final:.2f},{r.cagr:.2f},{r.max_dd:.2f},{r.trades}")


if __name__ == "__main__":
    main()
