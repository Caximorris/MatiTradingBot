"""Resumable corrected V7 robustness matrix using the independent reference path."""
from __future__ import annotations

import hashlib
import json
import random
import sys
import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.v7_independent_reference import Bar, Spec, frozen_spec, load_canonical, run  # noqa: E402

UTC = timezone.utc
OUT = ROOT / ".v7-corrected-robustness"
CACHE = ROOT / "data" / "cache" / "BTC-USDT_1H.json"
START = datetime(2014, 4, 26, tzinfo=UTC)
END = datetime(2026, 1, 1, tzinfo=UTC)
MASTER_SEED = 20260727
BLOCKS = (24, 72, 168, 720)
REPLICATIONS = 500


def load_checkpoint(path: Path | None = None) -> dict[str, object]:
    source = path or OUT / "checkpoint.json"
    return json.loads(source.read_text(encoding="utf-8"))


def bootstrap_status(state: dict[str, object]) -> list[dict[str, int | str]]:
    """Return terminal/pending counts without altering the checkpoint."""
    bootstrap = state.get("bootstrap", {})
    result: list[dict[str, int | str]] = []
    for family in ("moving", "stationary"):
        for block in BLOCKS:
            key = f"{family}_{block}h"
            entry = bootstrap.get(key, {})
            replications = entry.get("replications", {}) if isinstance(entry, dict) else {}
            completed = len(replications.get("completed", {})) if isinstance(replications, dict) else 0
            failed = len(replications.get("failed", {})) if isinstance(replications, dict) else 0
            invalid = len(replications.get("invalid", {})) if isinstance(replications, dict) else 0
            terminal = completed + failed + invalid
            result.append({"family": family, "block_hours": block, "completed": completed,
                           "failed": failed, "invalid": invalid, "pending": max(0, REPLICATIONS - terminal),
                           "total": REPLICATIONS})
    return result


def completion_summary(state: dict[str, object]) -> dict[str, object]:
    rows = bootstrap_status(state)
    terminal = sum(int(row["completed"]) + int(row["failed"]) + int(row["invalid"]) for row in rows)
    total = len(rows) * REPLICATIONS
    return {"terminal": terminal, "total": total, "pending": total - terminal,
            "complete": terminal == total, "families": rows}


def _metrics(curve: list[dict[str, str]]) -> dict[str, str]:
    initial, final = Decimal(curve[0]["equity"]), Decimal(curve[-1]["equity"])
    peak, max_dd = initial, Decimal("0")
    for row in curve:
        value = Decimal(row["equity"])
        peak = max(peak, value)
        max_dd = min(max_dd, value / peak - 1)
    years = Decimal(str((datetime.fromisoformat(curve[-1]["timestamp"]) - datetime.fromisoformat(curve[0]["timestamp"])).total_seconds())) / Decimal("31557600")
    cagr = (final / initial) ** (Decimal("1") / years) - 1
    return {"final_capital": str(final), "cagr": str(cagr), "max_dd": str(max_dd),
            "calmar": str(cagr / abs(max_dd)) if max_dd else "Infinity", "orders": str(0)}


def _case(name: str, bars, spec: Spec) -> dict[str, object]:
    trades, curve = run(bars, spec)
    result = _metrics(curve)
    result.update(name=name, trades=len(trades), first=curve[0]["timestamp"], last=curve[-1]["timestamp"])
    return result


def _shifted_halvings(days: int) -> tuple[str, ...]:
    return tuple((datetime.fromisoformat(item.replace("Z", "+00:00")) + timedelta(days=days)).isoformat().replace("+00:00", "Z") for item in Spec().halvings)


def _bootstrap_sample(bars: list[Bar], block: int, stationary: bool, seed: int) -> list[Bar]:
    """Moving/stationary contiguous blocks; timestamps are rebased solely for the clock."""
    rng, selected = random.Random(seed), []
    index = rng.randrange(len(bars))
    while len(selected) < len(bars):
        length = max(1, int(rng.expovariate(1 / block))) if stationary else block
        for _ in range(length):
            selected.append(bars[index % len(bars)])
            index += 1
            if len(selected) == len(bars):
                break
        index = rng.randrange(len(bars))
    start = bars[0].timestamp
    return [Bar(start + offset * 3_600_000, row.open, row.high, row.low, row.close, row.volume)
            for offset, row in enumerate(selected)]


def cases() -> list[tuple[str, Spec]]:
    base = frozen_spec()
    items = [("v7_realistic", base), ("v7_bear_20pct", replace(base, bear_onset_btc_pct="0.2")),
             ("cost_conservative", replace(base, slippage_bps="15")),
             ("cost_twice_conservative", replace(base, fee_rate="0.002", slippage_bps="30"))]
    for bear in (480, 540, 600):
        for accumulation in (840, 900, 960):
            items.append((f"sensitivity_b{bear}_a{accumulation}", replace(base, phase_bear_start=bear, phase_accumulation_start=accumulation)))
    items += [("joint_minus_120", replace(base, phase_bear_start=420, phase_accumulation_start=780)),
              ("joint_plus_120", replace(base, phase_bear_start=660, phase_accumulation_start=1020)),
              ("duration_minus_180", replace(base, phase_accumulation_start=720)),
              ("duration_plus_180", replace(base, phase_accumulation_start=1080))]
    items += [(f"delay_{delay}h", replace(base, transition_delay_hours=delay)) for delay in (1, 6, 12, 24, 72)]
    items += [(f"placebo_{shift:+d}d", replace(base, halvings=_shifted_halvings(shift))) for shift in (-365, -180, 180, 365)]
    return items


def _case_seed(method: str, block: int, replication: int) -> int:
    material = f"{MASTER_SEED}:{method}:{block}:{replication}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def execute(*, replications: int = REPLICATIONS, max_cases: int | None = None) -> dict[str, object]:
    bars = load_canonical(CACHE, START, END)
    state_path = OUT / "checkpoint.json"
    OUT.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"dataset_sha256": hashlib.sha256(CACHE.read_bytes()).hexdigest(), "cases": {}}
    state["bootstrap_contract"] = {"master_seed": MASTER_SEED, "replications_per_method_block": replications,
                                   "checkpoint_interval": 25, "method_limit": "calendar schedule fixed while sampled OHLC paths are rebased; stress diagnostic only"}
    for name, spec in cases():
        if name not in state["cases"]:
            state["cases"][name] = _case(name, bars, spec)
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    # These are historical reslices, explicitly not untouched OOS evidence.
    for year in (2015, 2017, 2019, 2021):
        name = f"rolling_start_{year}"
        if name not in state["cases"]:
            sliced = [bar for bar in bars if bar.timestamp >= int(datetime(year, 1, 1, tzinfo=UTC).timestamp() * 1000)]
            state["cases"][name] = _case(name, sliced, frozen_spec())
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    for year in (2018, 2020, 2022):
        name = f"pseudo_oos_from_{year}"
        if name not in state["cases"]:
            sliced = [bar for bar in bars if bar.timestamp >= int(datetime(year, 1, 1, tzinfo=UTC).timestamp() * 1000)]
            state["cases"][name] = _case(name, sliced, frozen_spec())
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    bootstrap = state.setdefault("bootstrap", {})
    for stationary in (False, True):
        family = "stationary" if stationary else "moving"
        for block in BLOCKS:
            key = f"{family}_{block}h"
            entry = bootstrap.setdefault(key, {"block_hours": block, "method": family, "replications": {"completed": {}, "failed": {}}})
            if isinstance(entry.get("replications"), list):
                # Legacy n=3 checkpoint is retained but cannot count toward the
                # fixed master-seed primary suite.
                entry["legacy_replications"] = entry["replications"]
                entry["replications"] = {"completed": {}, "failed": {}}
            cases_done = 0
            for replication in range(replications):
                label = str(replication)
                if label in entry["replications"]["completed"] or label in entry["replications"]["failed"]:
                    continue
                seed = _case_seed(family, block, replication)
                try:
                    entry["replications"]["completed"][label] = _case(f"{key}_seed{seed}", _bootstrap_sample(bars, block, stationary, seed), frozen_spec()) | {"seed": seed}
                except Exception as exc:  # preserve failed seed; never replace it
                    entry["replications"]["failed"][label] = {"seed": seed, "error": repr(exc)}
                cases_done += 1
                if cases_done % 25 == 0 or (max_cases is not None and cases_done >= max_cases):
                    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
                if max_cases is not None and cases_done >= max_cases:
                    state["status"] = "IN_PROGRESS"
                    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
                    return state
    state["status"] = "COMPLETE_PRIMARY_BOOTSTRAP" if all(
        len(item["replications"]["completed"]) + len(item["replications"]["failed"]) >= replications
        for item in bootstrap.values()) else "IN_PROGRESS"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replications", type=int, default=REPLICATIONS)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--status", action="store_true", help="print read-only per-family checkpoint status")
    parser.add_argument("--check-complete", action="store_true", help="exit 0 only when all 4,000 cases are terminal")
    args = parser.parse_args()
    if args.replications != REPLICATIONS:
        parser.error("the frozen primary bootstrap requires exactly 500 replications per family/block")
    if args.status or args.check_complete:
        summary = completion_summary(load_checkpoint())
        print(json.dumps(summary, indent=2))
        if args.check_complete and not summary["complete"]:
            raise SystemExit(2)
    else:
        try:
            state = execute(replications=args.replications, max_cases=args.max_cases)
        except Exception as exc:
            print(f"BOOTSTRAP_FATAL: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        summary = completion_summary(state)
        print(f"BOOTSTRAP_COMPLETE={str(summary['complete']).lower()} TERMINAL={summary['terminal']}/{summary['total']} PENDING={summary['pending']}")
