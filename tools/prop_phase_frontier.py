#!/usr/bin/env python
"""Risk/notional frontier inside a halving phase gate.

This is narrower than prop_risk_frontier.py: it only evaluates E9-style
PropSwing candidates started in selected phase views, typically
bear_onset|accumulation, where the phase matrix found edge.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger

logger.remove()

from core.prop_rules import simulate_challenges
from strategies.macro_context import MacroContext, set_phase_bounds
from tools.prop_breach_audit import E9, run_backtest
from tools.prop_challenge_sim import rule_configs
from tools.prop_phase_matrix import PHASE_CASES, PHASE_VIEWS, parse_phase_cases, parse_phase_views


_PHASE_CTX = MacroContext("BTC")


def parse_windows(raw: str) -> list[tuple[str, str]]:
    out = []
    for part in raw.split(","):
        start, end = part.split(":")
        out.append((start.strip(), end.strip()))
    return out


def parse_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def selected_rule(rule_set: str, label: str):
    matches = [(l, cfg, two_step) for l, cfg, two_step in rule_configs(rule_set)
               if l == label]
    if not matches:
        available = [l for l, _cfg, _two_step in rule_configs(rule_set)]
        raise SystemExit(f"label no encontrado para {rule_set}: {label}. Disponibles: {available}")
    return matches[0]


def phase_of(ts: datetime) -> str:
    return _PHASE_CTX.halving_phase(ts)[1]


def make_phase_filter(view: str):
    if view == "all":
        return None
    allowed = set(PHASE_VIEWS[view])
    return lambda ts: phase_of(ts) in allowed


def status_str(by_status: dict[str, int]) -> str:
    return ";".join(f"{k}={v}" for k, v in sorted(by_status.items()))


def run_cell(task: dict[str, Any], args, phase_cases, phase_views) -> list[dict[str, Any]]:
    from_dt = datetime.fromisoformat(task["start"]).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(task["end"]).replace(tzinfo=timezone.utc)
    overrides = dict(E9)
    overrides["risk_per_trade"] = task["risk"]
    overrides["max_notional_pct"] = task["notional"]
    if args.entry_halving_phases:
        overrides["entry_halving_phases"] = args.entry_halving_phases
    if task["adx_min"] is not None:
        overrides["adx_min"] = task["adx_min"]
    label, cfg, two_step = selected_rule(args.rules, args.label)
    cfg = cfg.with_(label=f"{label}@{args.max_days}d",
                    intrabar_buffer=args.buffer,
                    max_days=args.max_days)
    rows = []
    base_run = None
    if not args.entry_halving_phases:
        base_run = run_backtest("prop", from_dt, to_dt, args.costs, overrides)
    for case_label, bounds in phase_cases:
        set_phase_bounds(*bounds)
        # Si el propio motor usa el gate de fases, el backtest debe reconstruirse
        # bajo los mismos umbrales que el filtro de arranque.
        if args.entry_halving_phases:
            result, _bars, trades, _journal = run_backtest(
                "prop", from_dt, to_dt, args.costs, overrides,
            )
        else:
            result, _bars, trades, _journal = base_run
        for view in phase_views:
            stats = simulate_challenges(
                result.equity_curve,
                cfg,
                start_every_days=args.start_every,
                trade_pnls=trades,
                two_step=two_step,
                start_filter=make_phase_filter(view),
            )
            rows.append({
                "window": f"{task['start']}->{task['end']}",
                "costs": args.costs,
                "rule_set": args.rules,
                "rule_label": label,
                "phase_case": case_label,
                "phase": view,
                "risk_per_trade": task["risk"],
                "max_notional_pct": task["notional"],
                "adx_min": task["adx_min"] if task["adx_min"] is not None else "",
                "entry_halving_phases": args.entry_halving_phases,
                "bars": result.bars_tested,
                "pnl_pct": float(result.total_pnl_pct),
                "pf": float(result.profit_factor),
                "max_dd_pct": float(result.max_drawdown_pct),
                "trades": len(trades),
                "windows": stats.windows,
                "pass_rate": round(stats.pass_rate, 3),
                "breach_rate": round(stats.breach_rate, 3),
                "timeout_rate": round(stats.timeout_rate, 3),
                "median_days_pass": round(stats.median_days_pass, 0),
                "worst_daily_dd": round(stats.worst_daily_dd, 4),
                "by_status": status_str(stats.by_status),
            })
    set_phase_bounds()
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--windows", default="2020-01-01:2026-01-01,2018-01-01:2026-01-01")
    p.add_argument("--risks", default="0.011,0.0125,0.014")
    p.add_argument("--notionals", default="0.4,0.5,0.6")
    p.add_argument("--adx-mins", default="",
                   help="comma list; blank means default PropSwing adx_min")
    p.add_argument("--costs", default="bybit_cons")
    p.add_argument("--rules", default="cft", choices=("hyro", "breakout", "cft"))
    p.add_argument("--label", default="cft_two_phase")
    p.add_argument("--phase-cases", default="default")
    p.add_argument("--phase-views", default="bear_or_accum")
    p.add_argument("--entry-halving-phases", default="",
                   help="CSV phase gate passed into PropSwingConfig for entries")
    p.add_argument("--max-days", type=int, default=540)
    p.add_argument("--buffer", type=float, default=0.2)
    p.add_argument("--start-every", type=int, default=7)
    p.add_argument("--out", default="data/runtime/prop_phase_frontier.csv")
    args = p.parse_args()

    risks = parse_floats(args.risks)
    notionals = parse_floats(args.notionals)
    adx_mins = [None]
    if args.adx_mins.strip():
        adx_mins = [float(x.strip()) for x in args.adx_mins.split(",") if x.strip()]
    phase_cases = parse_phase_cases(args.phase_cases)
    phase_views = parse_phase_views(args.phase_views)

    tasks = []
    for start, end in parse_windows(args.windows):
        for risk in risks:
            for notional in notionals:
                for adx_min in adx_mins:
                    tasks.append({
                        "start": start,
                        "end": end,
                        "risk": risk,
                        "notional": notional,
                        "adx_min": adx_min,
                    })

    rows: list[dict[str, Any]] = []
    for task in tasks:
        print(f"# run {task['start']}->{task['end']} "
              f"risk={task['risk']} notional={task['notional']} "
              f"adx={task['adx_min']}",
              file=sys.stderr)
        rows.extend(run_cell(task, args, phase_cases, phase_views))

    fieldnames = [
        "window", "costs", "rule_set", "rule_label", "phase_case", "phase",
        "risk_per_trade", "max_notional_pct", "adx_min", "bars", "pnl_pct",
        "entry_halving_phases", "pf", "max_dd_pct", "trades", "windows",
        "pass_rate", "breach_rate", "timeout_rate", "median_days_pass",
        "worst_daily_dd", "by_status",
    ]
    rows.sort(key=lambda r: (
        r["window"], r["phase_case"], r["phase"], r["max_notional_pct"],
        r["risk_per_trade"], str(r["adx_min"]),
    ))
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        meta = path.with_suffix(".json")
        meta.write_text(json.dumps({"tasks": tasks, "args": vars(args)}, indent=2),
                        encoding="utf-8")
        print(f"# wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
