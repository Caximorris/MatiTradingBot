#!/usr/bin/env python
"""Phase matrix for prop-firm candidates.

This is a diagnostic tool, not a strategy. It answers:
- If a challenge starts in each halving phase, does pass/breach improve?
- Which engines have realized PnL concentrated in which phase?

Defaults focus on the prop candidates that are already implemented and cheap to
measure. Scalp is intentionally excluded by default because the current
strategy path is too slow for this simulator.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
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


PHASES = ("post_halving", "bull_peak", "bear_onset", "accumulation")
_PHASE_CTX = MacroContext("BTC")
PHASE_CASES = {
    "default": (180, 540, 900),
    "shift_minus_30": (150, 510, 870),
    "shift_plus_30": (210, 570, 930),
    "shift_minus_60": (120, 480, 840),
    "shift_plus_60": (240, 600, 960),
}
PHASE_VIEWS = {
    "all": tuple(PHASES),
    "post_or_bull": ("post_halving", "bull_peak"),
    "bear_or_accum": ("bear_onset", "accumulation"),
    "post_halving": ("post_halving",),
    "bull_peak": ("bull_peak",),
    "bear_onset": ("bear_onset",),
    "accumulation": ("accumulation",),
}


@dataclass(frozen=True)
class Candidate:
    name: str
    strategy: str
    start: str
    end: str
    costs: str
    config: dict[str, Any]


def _e9(**overrides: Any) -> dict[str, Any]:
    cfg = dict(E9)
    cfg.update(overrides)
    return cfg


CANDIDATES: dict[str, Candidate] = {
    "e9_2018": Candidate(
        name="e9_2018",
        strategy="prop",
        start="2018-01-01",
        end="2026-01-01",
        costs="bybit",
        config=_e9(),
    ),
    "e9": Candidate(
        name="e9",
        strategy="prop",
        start="2020-01-01",
        end="2026-01-01",
        costs="bybit",
        config=_e9(),
    ),
    "e9_adx20_r1_n04_2018": Candidate(
        name="e9_adx20_r1_n04_2018",
        strategy="prop",
        start="2018-01-01",
        end="2026-01-01",
        costs="bybit",
        config=_e9(risk_per_trade=0.01, max_notional_pct=0.4, adx_min=20),
    ),
    "e9_adx20_r1_n04": Candidate(
        name="e9_adx20_r1_n04",
        strategy="prop",
        start="2020-01-01",
        end="2026-01-01",
        costs="bybit",
        config=_e9(risk_per_trade=0.01, max_notional_pct=0.4, adx_min=20),
    ),
    "range": Candidate(
        name="range",
        strategy="range",
        start="2020-01-01",
        end="2026-01-01",
        costs="bybit",
        config={},
    ),
    "funding": Candidate(
        name="funding",
        strategy="funding",
        start="2020-06-01",
        end="2026-01-01",
        costs="bybit",
        config={},
    ),
}


def phase_of(ts: datetime) -> str:
    return _PHASE_CTX.halving_phase(ts)[1]


def parse_candidates(raw: str) -> list[Candidate]:
    keys = [x.strip() for x in raw.split(",") if x.strip()]
    unknown = [k for k in keys if k not in CANDIDATES]
    if unknown:
        raise SystemExit(f"candidatos desconocidos: {unknown}. Disponibles: {sorted(CANDIDATES)}")
    return [CANDIDATES[k] for k in keys]


def parse_phase_cases(raw: str) -> list[tuple[str, tuple[int, int, int]]]:
    keys = [x.strip() for x in raw.split(",") if x.strip()]
    unknown = [k for k in keys if k not in PHASE_CASES]
    if unknown:
        raise SystemExit(f"phase-cases desconocidos: {unknown}. Disponibles: {sorted(PHASE_CASES)}")
    return [(k, PHASE_CASES[k]) for k in keys]


def parse_phase_views(raw: str) -> list[str]:
    keys = [x.strip() for x in raw.split(",") if x.strip()]
    unknown = [k for k in keys if k not in PHASE_VIEWS]
    if unknown:
        raise SystemExit(f"phase-views desconocidos: {unknown}. Disponibles: {sorted(PHASE_VIEWS)}")
    return keys


def selected_rule(rule_set: str, label: str):
    matches = [(l, cfg, two_step) for l, cfg, two_step in rule_configs(rule_set)
               if l == label]
    if not matches:
        available = [l for l, _cfg, _two_step in rule_configs(rule_set)]
        raise SystemExit(f"label no encontrado para {rule_set}: {label}. Disponibles: {available}")
    return matches[0]


def make_phase_filter(view: str):
    allowed = set(PHASE_VIEWS[view])
    if view == "all":
        return None
    return lambda ts: phase_of(ts) in allowed


def summarize_trades(trades: list[tuple[datetime, Any]], view: str) -> dict[str, Any]:
    allowed = set(PHASE_VIEWS[view])
    selected = []
    for ts, pnl in trades:
        if view == "all" or phase_of(ts) in allowed:
            selected.append(float(pnl))
    wins = [x for x in selected if x > 0]
    losses = [x for x in selected if x < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    return {
        "phase_trades": len(selected),
        "phase_trade_pnl": round(sum(selected), 2),
        "phase_trade_wr": round(len(wins) / len(selected), 3) if selected else 0.0,
        "phase_trade_pf": round(gross_profit / gross_loss, 2) if gross_loss else 0.0,
    }


def status_str(by_status: dict[str, int]) -> str:
    return ";".join(f"{k}={v}" for k, v in sorted(by_status.items()))


def run_candidate(
    candidate: Candidate,
    args,
    phase_cases: list[tuple[str, tuple[int, int, int]]],
    phase_views: list[str],
) -> list[dict[str, Any]]:
    from_dt = datetime.fromisoformat(candidate.start).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(candidate.end).replace(tzinfo=timezone.utc)
    label, cfg, two_step = selected_rule(args.rules, args.label)
    cfg = cfg.with_(label=f"{label}@{args.max_days}d",
                    intrabar_buffer=args.buffer,
                    max_days=args.max_days)

    costs = args.costs or candidate.costs
    print(f"# running {candidate.name}: {candidate.strategy} "
          f"{candidate.start}->{candidate.end} {costs}",
          file=sys.stderr)
    result, _bars, trades, _journal = run_backtest(
        candidate.strategy, from_dt, to_dt, costs, candidate.config,
    )

    rows = []
    for case_label, bounds in phase_cases:
        set_phase_bounds(*bounds)
        for view in phase_views:
            stats = simulate_challenges(
                result.equity_curve,
                cfg,
                start_every_days=args.start_every,
                trade_pnls=trades,
                two_step=two_step,
                start_filter=make_phase_filter(view),
            )
            trade_summary = summarize_trades(trades, view)
            rows.append({
                "candidate": candidate.name,
                "strategy": candidate.strategy,
                "window": f"{candidate.start}->{candidate.end}",
                "costs": costs,
                "rule_set": args.rules,
                "rule_label": label,
                "phase_case": case_label,
                "post_end": bounds[0],
                "peak_end": bounds[1],
                "onset_end": bounds[2],
                "phase": view,
                "bars": result.bars_tested,
                "total_trades": len(trades),
                "pnl_pct": float(result.total_pnl_pct),
                "pf": float(result.profit_factor),
                "max_dd_pct": float(result.max_drawdown_pct),
                "windows": stats.windows,
                "pass_rate": round(stats.pass_rate, 3),
                "breach_rate": round(stats.breach_rate, 3),
                "timeout_rate": round(stats.timeout_rate, 3),
                "median_days_pass": round(stats.median_days_pass, 0),
                "worst_daily_dd": round(stats.worst_daily_dd, 4),
                "by_status": status_str(stats.by_status),
                **trade_summary,
            })
    set_phase_bounds()
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--candidates", default="e9,e9_adx20_r1_n04,range,funding")
    p.add_argument("--costs", default="", help="override cost mode for all selected candidates")
    p.add_argument("--rules", default="cft", choices=("hyro", "breakout", "cft"))
    p.add_argument("--label", default="cft_two_phase")
    p.add_argument("--max-days", type=int, default=540)
    p.add_argument("--buffer", type=float, default=0.2)
    p.add_argument("--start-every", type=int, default=7)
    p.add_argument("--phase-cases", default="default",
                   help=f"comma list: {','.join(PHASE_CASES)}")
    p.add_argument("--phase-views",
                   default="all,post_halving,bull_peak,bear_onset,accumulation",
                   help=f"comma list: {','.join(PHASE_VIEWS)}")
    p.add_argument("--out", default="data/runtime/prop_phase_matrix.csv")
    args = p.parse_args()

    candidates = parse_candidates(args.candidates)
    phase_cases = parse_phase_cases(args.phase_cases)
    phase_views = parse_phase_views(args.phase_views)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        rows.extend(run_candidate(candidate, args, phase_cases, phase_views))

    fieldnames = [
        "candidate", "strategy", "window", "costs", "rule_set", "rule_label",
        "phase_case", "post_end", "peak_end", "onset_end", "phase",
        "bars", "total_trades", "pnl_pct", "pf", "max_dd_pct",
        "windows", "pass_rate", "breach_rate", "timeout_rate",
        "median_days_pass", "worst_daily_dd", "phase_trades",
        "phase_trade_pnl", "phase_trade_wr", "phase_trade_pf", "by_status",
    ]
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
        meta.write_text(json.dumps({
            "candidates": [c.name for c in candidates],
            "rules": args.rules,
            "label": args.label,
            "costs_override": args.costs,
            "phase_cases": [x[0] for x in phase_cases],
            "phase_views": phase_views,
            "max_days": args.max_days,
            "buffer": args.buffer,
            "start_every": args.start_every,
        }, indent=2), encoding="utf-8")
        print(f"# wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
