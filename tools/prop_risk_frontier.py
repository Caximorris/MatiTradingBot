#!/usr/bin/env python
"""Run an E9 risk/notional frontier across prop-firm rule sets.

Each task runs one backtest for one (window, risk_per_trade, max_notional_pct),
then evaluates selected rule presets on the same equity curve.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger

logger.remove()

from core.prop_rules import simulate_challenges
from tools.prop_breach_audit import E9, run_backtest
from tools.prop_challenge_sim import rule_configs


DEFAULT_LABELS = {
    "hyro": {"one_step_swing", "two_step_swing"},
    "breakout": {"breakout_classic"},
    "cft": {"cft_two_phase"},
}


def parse_windows(raw: str) -> list[tuple[str, str]]:
    out = []
    for part in raw.split(","):
        start, end = part.split(":")
        out.append((start.strip(), end.strip()))
    return out


def parse_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def run_cell(task: dict) -> list[dict]:
    overrides = dict(E9)
    overrides["risk_per_trade"] = task["risk"]
    overrides["max_notional_pct"] = task["notional"]
    from_dt = datetime.fromisoformat(task["start"]).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(task["end"]).replace(tzinfo=timezone.utc)
    result, _bars, trades, _journal = run_backtest("prop", from_dt, to_dt,
                                                   task["costs"], overrides)
    rows = []
    for rule_set in task["rules"]:
        wanted = DEFAULT_LABELS[rule_set]
        for label, cfg, two_step in rule_configs(rule_set):
            if label not in wanted:
                continue
            cfg = cfg.with_(label=f"{label}@{task['max_days']}d",
                            intrabar_buffer=task["buffer"],
                            max_days=task["max_days"])
            stats = simulate_challenges(result.equity_curve, cfg,
                                        trade_pnls=trades, two_step=two_step)
            rows.append({
                "window": f"{task['start']}->{task['end']}",
                "costs": task["costs"],
                "risk_per_trade": task["risk"],
                "max_notional_pct": task["notional"],
                "rule_set": rule_set,
                "label": label,
                "windows": stats.windows,
                "pass_rate": round(stats.pass_rate, 3),
                "breach_rate": round(stats.breach_rate, 3),
                "timeout_rate": round(stats.timeout_rate, 3),
                "median_days_pass": round(stats.median_days_pass, 0),
                "worst_daily_dd": round(stats.worst_daily_dd, 4),
                "by_status": ";".join(f"{k}={v}" for k, v in sorted(stats.by_status.items())),
                "pnl_pct": float(result.total_pnl_pct),
                "pf": float(result.profit_factor),
                "max_dd_pct": float(result.max_drawdown_pct),
                "trades": len(trades),
            })
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--windows", default="2018-01-01:2026-01-01,2020-01-01:2026-01-01")
    p.add_argument("--risks", default="0.0075,0.01,0.011,0.0125")
    p.add_argument("--notionals", default="0.4,0.5")
    p.add_argument("--costs", default="bybit")
    p.add_argument("--rules", default="hyro,breakout,cft")
    p.add_argument("--max-days", type=int, default=540)
    p.add_argument("--buffer", type=float, default=0.2)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", default="data/runtime/prop_risk_frontier.csv")
    args = p.parse_args()

    tasks = []
    rules = [r.strip() for r in args.rules.split(",") if r.strip()]
    for start, end in parse_windows(args.windows):
        for risk in parse_floats(args.risks):
            for notional in parse_floats(args.notionals):
                tasks.append({
                    "start": start, "end": end, "risk": risk, "notional": notional,
                    "costs": args.costs, "rules": rules, "max_days": args.max_days,
                    "buffer": args.buffer,
                })

    rows = []
    workers = max(1, min(args.workers, 4))
    if workers == 1:
        for task in tasks:
            cell_rows = run_cell(task)
            rows.extend(cell_rows)
            first = cell_rows[0]
            print(f"# done {first['window']} risk={first['risk_per_trade']} "
                  f"notional={first['max_notional_pct']} pnl={first['pnl_pct']:.2f}%")
    else:
        try:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(run_cell, task) for task in tasks]
                for fut in as_completed(futs):
                    cell_rows = fut.result()
                    rows.extend(cell_rows)
                    first = cell_rows[0]
                    print(f"# done {first['window']} risk={first['risk_per_trade']} "
                          f"notional={first['max_notional_pct']} pnl={first['pnl_pct']:.2f}%")
        except PermissionError:
            print("# ProcessPool bloqueado por el sandbox; fallback secuencial")
            for task in tasks:
                cell_rows = run_cell(task)
                rows.extend(cell_rows)
                first = cell_rows[0]
                print(f"# done {first['window']} risk={first['risk_per_trade']} "
                      f"notional={first['max_notional_pct']} pnl={first['pnl_pct']:.2f}%")

    rows.sort(key=lambda r: (
        r["window"], r["rule_set"], r["label"],
        r["max_notional_pct"], r["risk_per_trade"],
    ))
    fieldnames = [
        "window", "costs", "risk_per_trade", "max_notional_pct", "rule_set", "label",
        "windows", "pass_rate", "breach_rate", "timeout_rate", "median_days_pass",
        "worst_daily_dd", "pnl_pct", "pf", "max_dd_pct", "trades", "by_status",
    ]
    print(",".join(fieldnames))
    for row in rows:
        print(",".join(str(row[k]) for k in fieldnames))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        meta = path.with_suffix(".json")
        meta.write_text(json.dumps({"tasks": tasks}, indent=2), encoding="utf-8")
        print(f"# wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
