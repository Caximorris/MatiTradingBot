"""Checkpointed, research-only Swing phase experiments.

This runner reuses the existing Swing backtest harness. Every case is written
before execution and finalized atomically after success or failure, so a
process interruption cannot turn a missing cell into a passing result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "btc_cycle_audit"
CHECKPOINT = AUDIT / "research_checkpoint.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
START = datetime(2015, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)
CASE_COST = "realistic"
BEAR = (480, 510, 540, 570, 600)
ACCUM = (840, 870, 900, 930, 960)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkpoint() -> dict[str, Any]:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"schema": 1, "dataset_hash": stable_hash(AUDIT / "current_prices.json"), "matrix": {}, "placebos": {}, "loco": {}, "created_at": now()}


def save_checkpoint(payload: dict[str, Any]) -> None:
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(CHECKPOINT)


def import_harness():
    from loguru import logger
    logger.remove()
    try:
        from tools.swing_v6_common import load_bars, metrics_row, run_swing_backtest
    except ModuleNotFoundError:
        from swing_v6_common import load_bars, metrics_row, run_swing_backtest
    return load_bars, metrics_row, run_swing_backtest


def cycle_returns(run: Any) -> dict[str, Any]:
    curve = list(getattr(run.result, "equity_curve", []) or [])
    halvings = [date(2016, 7, 9), date(2020, 5, 11), date(2024, 4, 20)]
    output: dict[str, Any] = {}
    for index, start in enumerate(halvings[:2]):
        end = halvings[index + 1]
        values = [(ts.date(), Decimal(str(value))) for ts, value in curve if start <= ts.date() < end]
        if len(values) >= 2 and values[0][1] != 0:
            output[f"{start.year}_cycle"] = {"start_equity": str(values[0][1]), "end_equity": str(values[-1][1]), "return_pct": str((values[-1][1] / values[0][1] - 1) * 100)}
    return output


def run_case(case: tuple[int, int, str, str, str, str]) -> dict[str, Any]:
    bear, accum, start_raw, end_raw, costs, dataset_hash = case
    started = time.perf_counter()
    base = {"case": f"bear_{bear}_accum_{accum}", "bear_defense_start": bear, "accumulation_start": accum, "status": "RUNNING", "started_at": now(), "dataset_hash": dataset_hash, "costs": costs}
    try:
        load_bars, metrics_row, run_swing_backtest = import_harness()
        start = datetime.fromisoformat(start_raw).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(end_raw).replace(tzinfo=timezone.utc)
        bars = load_bars("BTC-USDT", start, end)
        run = run_swing_backtest(symbol="BTC-USDT", from_dt=start, to_dt=end, cost_mode=costs, config={"phase_post_end": 180, "phase_peak_end": bear, "phase_onset_end": accum, "use_funding_overlay": False}, bars=bars)
        row = metrics_row(base["case"], run, {"bear_defense_start": bear, "accumulation_start": accum})
        row["case"] = base["case"]
        row.update({"status": "SUCCEEDED", "started_at": base["started_at"], "finished_at": now(), "runtime_seconds": round(time.perf_counter() - started, 3), "dataset_hash": dataset_hash, "total_return_pct": str(run.result.total_pnl_pct), "calmar": str(run.result.calmar), "sharpe": str(run.result.sharpe_ratio), "sortino": str(run.result.sortino), "time_outside_btc_pct": str(100 - run.result.time_in_market_pct), "fee_rate": "0.001", "slippage_bps": "5", "orders": len(run.strategy._rebalance_log), "cycle_results": cycle_returns(run)})
        return row
    except Exception as exc:
        return {**base, "status": "FAILED", "finished_at": now(), "runtime_seconds": round(time.perf_counter() - started, 3), "failure_type": type(exc).__name__, "failure": str(exc)}


def run_matrix(args: argparse.Namespace) -> None:
    state = checkpoint()
    if state["dataset_hash"] != stable_hash(AUDIT / "current_prices.json"):
        raise RuntimeError("dataset hash changed; create a new checkpoint explicitly")
    pending = []
    for bear in BEAR:
        for accum in ACCUM:
            key = f"bear_{bear}_accum_{accum}"
            current = state["matrix"].get(key)
            if current and current.get("status") == "SUCCEEDED":
                continue
            state["matrix"][key] = {"status": "PENDING", "updated_at": now()}
            pending.append((bear, accum, START.isoformat(), END.isoformat(), CASE_COST, state["dataset_hash"]))
    save_checkpoint(state)
    for offset in range(0, len(pending), args.workers):
        batch = pending[offset:offset + args.workers]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(run_case, batch))
        for result in results:
            state["matrix"][result["case"]] = result
            save_checkpoint(state)
            print(json.dumps({"kind": "matrix", "case": result["case"], "status": result["status"]}), flush=True)
    complete = sum(value.get("status") == "SUCCEEDED" for value in state["matrix"].values())
    state["matrix_completed"] = complete == 25
    save_checkpoint(state)


def calendar_dates(kind: str, shift: int = 0, seed: int = 42) -> list[date]:
    actual = [date(2012, 11, 28), date(2016, 7, 9), date(2020, 5, 11), date(2024, 4, 20)]
    if kind == "actual":
        return actual
    if kind == "shift":
        return [item + timedelta(days=shift) for item in actual]
    if kind == "four_year":
        return [date(year, 1, 1) for year in (2013, 2017, 2021, 2025)]
    rng = random.Random(seed)
    return [date(year, 1, 1) + timedelta(days=rng.randrange(0, 365)) for year in (2013, 2017, 2021, 2025)]


def run_placebo(case: tuple[str, list[date], str]) -> dict[str, Any]:
    label, calendar, dataset_hash = case
    started = time.perf_counter()
    try:
        from loguru import logger
        logger.remove()
        load_bars, metrics_row, run_swing_backtest = import_harness()
        from strategies import macro_context
        previous = macro_context.HALVING_DATES
        macro_context.HALVING_DATES = calendar
        try:
            bars = load_bars("BTC-USDT", START, END)
            run = run_swing_backtest(symbol="BTC-USDT", from_dt=START, to_dt=END, cost_mode=CASE_COST, config={"phase_post_end": 180, "phase_peak_end": 540, "phase_onset_end": 900, "use_funding_overlay": False}, bars=bars)
        finally:
            macro_context.HALVING_DATES = previous
        row = metrics_row(label, run, {"calendar": [item.isoformat() for item in calendar]})
        row.update({
            "status": "SUCCEEDED",
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "dataset_hash": dataset_hash,
            "total_return_pct": str(run.result.total_pnl_pct),
            "calmar": str(run.result.calmar),
            "sharpe": str(run.result.sharpe_ratio),
            "sortino": str(run.result.sortino),
            "time_outside_btc_pct": str(100 - run.result.time_in_market_pct),
            "fee_rate": "0.001",
            "slippage_bps": "5",
            "orders": len(run.strategy._rebalance_log),
            "cycle_results": cycle_returns(run),
        })
        return row
    except Exception as exc:
        return {"label": label, "status": "FAILED", "calendar": [item.isoformat() for item in calendar], "dataset_hash": dataset_hash, "failure_type": type(exc).__name__, "failure": str(exc), "runtime_seconds": round(time.perf_counter() - started, 3)}


def run_placebos(args: argparse.Namespace) -> None:
    state = checkpoint()
    calendars = {"actual": calendar_dates("actual"), "shift_-365": calendar_dates("shift", -365), "shift_-180": calendar_dates("shift", -180), "shift_+180": calendar_dates("shift", 180), "shift_+365": calendar_dates("shift", 365), "random_seed_42": calendar_dates("random", seed=42), "four_year_non_halving": calendar_dates("four_year")}
    pending = [(label, dates, state["dataset_hash"]) for label, dates in calendars.items() if state["placebos"].get(label, {}).get("status") != "SUCCEEDED" or "cycle_results" not in state["placebos"].get(label, {}) or "calmar" not in state["placebos"].get(label, {})]
    for offset in range(0, len(pending), args.workers):
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(run_placebo, pending[offset:offset + args.workers]))
        for result in results:
            state["placebos"][result["label"]] = result
            save_checkpoint(state)
    state["placebo_suite_completed"] = all(state["placebos"].get(label, {}).get("status") == "SUCCEEDED" for label in calendars)
    save_checkpoint(state)


LOCO_EXTREMA = {"2016_cycle": (525, 889), "2020_cycle": (1402, 1437)}


def run_loco_case(item: tuple[str, tuple[int, int], date, date, str]) -> dict[str, Any]:
    excluded, (top, bottom), start, end, dataset_hash = item
    result = run_case((top, bottom, start.isoformat(), end.isoformat(), CASE_COST, dataset_hash))
    actual_top, actual_bottom = LOCO_EXTREMA[excluded]
    result.update({
        "excluded_cycle": excluded,
        "training_cycles": [name for name in ("2016_cycle", "2020_cycle") if name != excluded],
        "estimated_boundaries": {"bear_defense_start": top, "accumulation_start": bottom},
        "actual_global_extrema": {"top": actual_top, "bottom": actual_bottom},
        "top_error_days": top - actual_top,
        "bottom_error_days": bottom - actual_bottom,
    })
    return result


def run_loco(args: argparse.Namespace) -> None:
    state = checkpoint()
    eligible = [("2016_cycle", date(2016, 7, 9), date(2020, 5, 11)), ("2020_cycle", date(2020, 5, 11), date(2024, 4, 20))]
    pending: list[tuple[str, tuple[int, int], date, date, str]] = []
    for excluded, start, end in eligible:
        if state["loco"].get(excluded, {}).get("status") == "SUCCEEDED":
            continue
        training = [item for item in eligible if item[0] != excluded]
        top, bottom = LOCO_EXTREMA[training[0][0]]
        pending.append((excluded, (top, bottom), start, end, state["dataset_hash"]))
    if pending:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(pending))) as pool:
            for result in pool.map(run_loco_case, pending):
                state["loco"][result["excluded_cycle"]] = result
                save_checkpoint(state)
    state["loco_suite_completed"] = all(state["loco"].get(item[0], {}).get("status") == "SUCCEEDED" for item in eligible)
    save_checkpoint(state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("matrix", "placebos", "loco"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 5:
        raise SystemExit("workers must be between 1 and 5")
    {"matrix": run_matrix, "placebos": run_placebos, "loco": run_loco}[args.command](args)


if __name__ == "__main__":
    main()
