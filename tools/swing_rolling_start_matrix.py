"""Rolling-start matrix for Swing v6 candidates.

Each start date runs baseline v5 and candidate config on the same window, cost
mode, and candle count. Use --max-runs for cheap smoke tests.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.swing_v6_common import (
    halving_phase_at,
    iter_start_dates,
    load_bars,
    parse_config,
    parse_utc_date,
    run_swing_backtest,
    verdict_vs_baseline,
    write_csv,
)

logger.remove()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--from", dest="from_date", default="2015-01-01")
    p.add_argument("--to", dest="to_date", default="2026-01-01")
    p.add_argument("--start-every-days", type=int, default=30)
    p.add_argument("--min-days", type=int, default=365)
    p.add_argument("--costs", default="realistic")
    p.add_argument("--baseline-config", default="{}")
    p.add_argument("--config", default="{}")
    p.add_argument("--out", default="data/runtime/swing_rolling_start_matrix.csv")
    p.add_argument("--max-runs", type=int, default=0)
    args = p.parse_args()

    from_dt = parse_utc_date(args.from_date)
    to_dt = parse_utc_date(args.to_date)
    starts = iter_start_dates(from_dt, to_dt, args.start_every_days, args.min_days)
    if args.max_runs > 0:
        starts = starts[: args.max_runs]

    baseline_cfg = parse_config(args.baseline_config)
    candidate_cfg = parse_config(args.config)
    rows = []

    for i, start in enumerate(starts, start=1):
        bars = load_bars(args.symbol, start, to_dt)
        baseline = run_swing_backtest(
            symbol=args.symbol,
            from_dt=start,
            to_dt=to_dt,
            cost_mode=args.costs,
            config=baseline_cfg,
            bars=bars,
        )
        candidate = run_swing_backtest(
            symbol=args.symbol,
            from_dt=start,
            to_dt=to_dt,
            cost_mode=args.costs,
            config=candidate_cfg,
            bars=bars,
        )
        verdict = verdict_vs_baseline(candidate, baseline)
        row = {
            "run": i,
            "start_date": start.date().isoformat(),
            "start_phase": halving_phase_at(start, args.symbol),
            "cost": args.costs,
            "baseline_bars": baseline.result.bars_tested,
            "candidate_bars": candidate.result.bars_tested,
            "baseline_final": f"{baseline.result.final_balance:.2f}",
            "candidate_final": f"{candidate.result.final_balance:.2f}",
            "baseline_cagr": str(baseline.result.cagr),
            "candidate_cagr": str(candidate.result.cagr),
            "baseline_max_dd": str(baseline.result.max_drawdown_pct),
            "candidate_max_dd": str(candidate.result.max_drawdown_pct),
            "baseline_rebalance_events": len([x for x in baseline.strategy._rebalance_log if x.get("direction") != "INIT"]),
            "candidate_rebalance_events": len([x for x in candidate.strategy._rebalance_log if x.get("direction") != "INIT"]),
            "baseline_acb_trades": baseline.result.total_trades,
            "candidate_acb_trades": candidate.result.total_trades,
            "baseline_final_btc": f"{baseline.final_btc_qty:.8f}",
            "candidate_final_btc": f"{candidate.final_btc_qty:.8f}",
            "baseline_btc_vs_bnh": f"{baseline.btc_vs_bnh_ratio:.4f}",
            "candidate_btc_vs_bnh": f"{candidate.btc_vs_bnh_ratio:.4f}",
            "verdict": verdict,
        }
        rows.append(row)
        print(",".join(str(row[k]) for k in row))

    write_csv(Path(args.out), rows)
    print(f"csv,{args.out}")


if __name__ == "__main__":
    main()
