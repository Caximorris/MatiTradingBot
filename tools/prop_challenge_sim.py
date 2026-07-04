"""Simulador de challenge HyroTrader sobre una estrategia del registry (P1, HYROTRADER_PLAN).

Corre el backtest de la estrategia y lanza challenges en ventanas rodantes sobre su curva
de equity, evaluando las reglas verificadas (seccion 9 del plan): One-Step, Two-Step
(encadenado P1+P2), con y sin Swing Drawdown Upgrade.

Uso:
    python tools/prop_challenge_sim.py --strategy swing --from 2018-01-01 --to 2026-01-01
    python tools/prop_challenge_sim.py --strategy swing --buffer 0.2 --start-every 7
    python tools/prop_challenge_sim.py --strategy prop --max-days 365,540,730 --bull-start

--max-days: lista separada por comas de timeouts de simulacion (el challenge real es
ilimitado; 365 es la cota conservadora historica).
--bull-start: ademas de todas las ventanas, reporta filas "+bull" donde el challenge solo
arranca con regimen bull diario CERRADO (EMA50D>EMA200D, close>EMA200D, ADX14>=15 — mismo
criterio que prop_swing, dia anterior). Es la metrica de decision: el challenge se compra
cuando el regimen ya es bull, no en un punto aleatorio del ciclo.

Salida CSV: label,windows,pass_rate,breach_rate,timeout_rate,median_days_pass,
near_breach_day_pct,worst_daily_dd  (+ desglose por status).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])  # portable
sys.path.insert(0, ROOT)

from loguru import logger

logger.remove()

from core.backtest import BacktestClient, BacktestEngine, fetch_historical_bars
from core.prop_rules import (
    ONE_STEP, TWO_STEP_P1, simulate_challenges, trade_pnls_from_result,
)
from strategies import registry


def run_backtest(strategy: str, from_dt: datetime, to_dt: datetime, costs: str,
                 overrides: dict | None = None, symbol: str = "BTC-USDT"):
    meta = registry.get(strategy)
    bars = fetch_historical_bars(symbol, "1H",
                                 from_dt - timedelta(days=meta.warmup_days), to_dt)
    client = BacktestClient(symbol, bars, initial_balance=Decimal("10000"),
                            cost_mode=costs)
    cfg_obj = meta.make_config(symbol, overrides or {})

    def factory(c, s):
        return meta.make_bot(c, cfg_obj, s)

    from_ts = int(from_dt.timestamp() * 1000)
    warmup = max(len([b for b in bars if b.timestamp < from_ts]), 20)
    engine = BacktestEngine(client, factory, warmup_bars=warmup, timeframe="1H")
    result = engine.run()
    # PnL realizado por cierre segun la propia estrategia (incluye shorts sinteticos,
    # que no pasan por el pairing ACB del motor). Fallback: pairing del motor.
    realized = list(getattr(engine.last_strategy, "realized", None) or []) or None
    return result, bars, realized


def make_bull_start_filter(bars, adx_min: float = 15.0):
    """
    start_filter(ts): True si el dia UTC anterior a ts cerro en regimen bull
    (EMA50D>EMA200D, close>EMA200D, ADX14>=adx_min) — mismo criterio y mismo
    anti-lookahead (dias cerrados) que PropSwingBot._regime_ok.
    """
    import pandas as pd

    from strategies.indicators import adx as adx_fn, ema as ema_fn, resample_to_daily

    df = pd.DataFrame({
        "timestamp": [b.timestamp for b in bars],
        "open":  [float(b.open) for b in bars],
        "high":  [float(b.high) for b in bars],
        "low":   [float(b.low) for b in bars],
        "close": [float(b.close) for b in bars],
        "volume": [float(b.volume) for b in bars],
    })
    daily = resample_to_daily(df)
    close = daily["close"]
    ema50, ema200 = ema_fn(close, 50), ema_fn(close, 200)
    adx_d = adx_fn(daily["high"], daily["low"], close, 14)
    cond = (ema50 > ema200) & (close > ema200) & (adx_d >= adx_min)
    # shift(1): el valor del dia D es el regimen calculado con datos hasta D-1
    shifted = cond.shift(1).fillna(False)
    bull_by_date = dict(zip(daily["dt"].dt.date, shifted))
    return lambda ts: bool(bull_by_date.get(ts.date(), False))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default="swing")
    p.add_argument("--from", dest="from_", default="2018-01-01")
    p.add_argument("--to", default="2026-01-01")
    p.add_argument("--costs", default="realistic")
    p.add_argument("--start-every", type=int, default=7, help="dias entre arranques")
    p.add_argument("--buffer", type=float, default=0.2,
                   help="intrabar_buffer (0.2 recomendado: equity 1H subestima picos)")
    p.add_argument("--config", default="{}", help="overrides JSON de la estrategia")
    p.add_argument("--max-days", default="365",
                   help="timeouts de simulacion, separados por comas (real = ilimitado)")
    p.add_argument("--bull-start", action="store_true",
                   help="reporta ademas filas '+bull' (arranque solo en regimen bull)")
    p.add_argument("--symbols", default="BTC-USDT",
                   help="lista separada por comas; >1 = curva portfolio (sleeves "
                        "independientes de $10k, equity sumada, trades concatenados)")
    args = p.parse_args()

    import json
    overrides = json.loads(args.config)
    from_dt = datetime.fromisoformat(args.from_).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(args.to).replace(tzinfo=timezone.utc)
    max_days_list = [int(x) for x in args.max_days.split(",")]
    symbols = [s.strip() for s in args.symbols.split(",")]

    if overrides:
        print(f"# config overrides: {overrides}")
    results = []
    for sym in symbols:
        result, bars, realized = run_backtest(args.strategy, from_dt, to_dt,
                                              args.costs, overrides, symbol=sym)
        trades = realized or trade_pnls_from_result(result)
        results.append((sym, result, bars, trades))
        print(f"# backtest: {result.strategy_name} {args.from_}->{args.to} {args.costs} | "
              f"bars={result.bars_tested} | trades_con_pnl={len(trades)} | "
              f"buffer={args.buffer}")
        print(f"# edge {sym}: pnl={result.total_pnl_pct}% | PF={result.profit_factor} | "
              f"WR={result.win_rate}% | expectancy={result.expectancy} | "
              f"trades={result.total_trades} | maxDD={result.max_drawdown_pct}%")

    if len(results) == 1:
        equity_curve = results[0][1].equity_curve
        trades = results[0][3]
    else:
        # Portfolio: sleeves de $10k por simbolo; equity total = suma - (n-1)*10k.
        # Cada sleeve arriesga risk_per_trade de SU equity => con n sleeves el riesgo
        # por trade a nivel cuenta es ~1/n de eso (documentar al interpretar).
        maps = [dict(r.equity_curve) for _, r, _, _ in results]
        common = sorted(set(maps[0]).intersection(*[set(m) for m in maps[1:]]))
        offset = Decimal("10000") * (len(maps) - 1)
        equity_curve = [(ts, sum(m[ts] for m in maps) - offset) for ts in common]
        trades = sorted((t for _, _, _, tr in results for t in tr), key=lambda x: x[0])
        rel = float(equity_curve[-1][1] / equity_curve[0][1] - 1) * 100
        print(f"# portfolio {'+'.join(symbols)}: pnl={rel:.2f}% | "
              f"trades={len(trades)} | ventana comun {common[0].date()}->{common[-1].date()}")

    bars = results[0][2]   # regimen del filtro bull-start: primer simbolo (BTC)
    filters = [("", None)]
    if args.bull_start:
        filters.append(("+bull", make_bull_start_filter(bars)))

    configs = [
        ("one_step_std",   ONE_STEP,    False),
        ("one_step_swing", ONE_STEP.with_(swing_upgrade=True), False),
        ("two_step_std",   TWO_STEP_P1, True),
        ("two_step_swing", TWO_STEP_P1.with_(swing_upgrade=True), True),
    ]
    print("label,windows,pass_rate,breach_rate,timeout_rate,median_days_pass,"
          "near_breach_day_pct,worst_daily_dd,by_status")
    for md in max_days_list:
        for fsuffix, sfilter in filters:
            for label, cfg, two_step in configs:
                cfg = cfg.with_(label=f"{label}@{md}d{fsuffix}",
                                intrabar_buffer=args.buffer, max_days=md)
                stats = simulate_challenges(equity_curve, cfg,
                                            start_every_days=args.start_every,
                                            trade_pnls=trades or None,
                                            two_step=two_step, start_filter=sfilter)
                status_str = ";".join(f"{k}={v}" for k, v in sorted(stats.by_status.items()))
                print(f"{stats.row()},{status_str}")


if __name__ == "__main__":
    main()
