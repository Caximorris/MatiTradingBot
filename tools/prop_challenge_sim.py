"""Simulador de challenge HyroTrader sobre una estrategia del registry (P1, HYROTRADER_PLAN).

Corre el backtest de la estrategia y lanza challenges en ventanas rodantes sobre su curva
de equity, evaluando las reglas verificadas (seccion 9 del plan): One-Step, Two-Step
(encadenado P1+P2), con y sin Swing Drawdown Upgrade.

Uso:
    python tools/prop_challenge_sim.py --strategy swing --from 2018-01-01 --to 2026-01-01
    python tools/prop_challenge_sim.py --strategy swing --buffer 0.2 --start-every 7

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
                 overrides: dict | None = None):
    meta = registry.get(strategy)
    bars = fetch_historical_bars("BTC-USDT", "1H",
                                 from_dt - timedelta(days=meta.warmup_days), to_dt)
    client = BacktestClient("BTC-USDT", bars, initial_balance=Decimal("10000"),
                            cost_mode=costs)
    cfg_obj = meta.make_config("BTC-USDT", overrides or {})

    def factory(c, s):
        return meta.make_bot(c, cfg_obj, s)

    from_ts = int(from_dt.timestamp() * 1000)
    warmup = max(len([b for b in bars if b.timestamp < from_ts]), 20)
    engine = BacktestEngine(client, factory, warmup_bars=warmup, timeframe="1H")
    return engine.run()


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
    args = p.parse_args()

    import json
    overrides = json.loads(args.config)
    from_dt = datetime.fromisoformat(args.from_).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(args.to).replace(tzinfo=timezone.utc)

    result = run_backtest(args.strategy, from_dt, to_dt, args.costs, overrides)
    if overrides:
        print(f"# config overrides: {overrides}")
    trades = trade_pnls_from_result(result)
    print(f"# backtest: {result.strategy_name} {args.from_}->{args.to} {args.costs} | "
          f"bars={result.bars_tested} | trades_con_pnl={len(trades)} | buffer={args.buffer}")
    print(f"# edge: pnl={result.total_pnl_pct}% | PF={result.profit_factor} | "
          f"WR={result.win_rate}% | expectancy={result.expectancy} | "
          f"trades={result.total_trades} | maxDD={result.max_drawdown_pct}%")

    configs = [
        ("one_step_std",   ONE_STEP,    False),
        ("one_step_swing", ONE_STEP.with_(swing_upgrade=True), False),
        ("two_step_std",   TWO_STEP_P1, True),
        ("two_step_swing", TWO_STEP_P1.with_(swing_upgrade=True), True),
    ]
    print("label,windows,pass_rate,breach_rate,timeout_rate,median_days_pass,"
          "near_breach_day_pct,worst_daily_dd,by_status")
    for label, cfg, two_step in configs:
        cfg = cfg.with_(label=label, intrabar_buffer=args.buffer)
        stats = simulate_challenges(result.equity_curve, cfg,
                                    start_every_days=args.start_every,
                                    trade_pnls=trades or None, two_step=two_step)
        status_str = ";".join(f"{k}={v}" for k, v in sorted(stats.by_status.items()))
        print(f"{stats.row()},{status_str}")


if __name__ == "__main__":
    main()
