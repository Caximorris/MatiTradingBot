"""Resumable corrected V7 robustness matrix using the independent reference path."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.v7_independent_reference import Spec, load_canonical, run  # noqa: E402

UTC = timezone.utc
OUT = ROOT / ".v7-corrected-robustness"
CACHE = ROOT / "data" / "cache" / "BTC-USDT_1H.json"
START = datetime(2014, 4, 26, tzinfo=UTC)
END = datetime(2026, 1, 1, tzinfo=UTC)


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


def cases() -> list[tuple[str, Spec]]:
    base = Spec()
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


def execute() -> dict[str, object]:
    bars = load_canonical(CACHE, START, END)
    state_path = OUT / "checkpoint.json"
    OUT.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"dataset_sha256": hashlib.sha256(CACHE.read_bytes()).hexdigest(), "cases": {}}
    for name, spec in cases():
        if name not in state["cases"]:
            state["cases"][name] = _case(name, bars, spec)
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    # These are historical reslices, explicitly not untouched OOS evidence.
    for year in (2015, 2017, 2019, 2021):
        name = f"rolling_start_{year}"
        if name not in state["cases"]:
            sliced = [bar for bar in bars if bar.timestamp >= int(datetime(year, 1, 1, tzinfo=UTC).timestamp() * 1000)]
            state["cases"][name] = _case(name, sliced, Spec())
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    for year in (2018, 2020, 2022):
        name = f"pseudo_oos_from_{year}"
        if name not in state["cases"]:
            sliced = [bar for bar in bars if bar.timestamp >= int(datetime(year, 1, 1, tzinfo=UTC).timestamp() * 1000)]
            state["cases"][name] = _case(name, sliced, Spec())
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    state["status"] = "COMPLETE_CORE_MATRIX"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


if __name__ == "__main__":
    print(json.dumps(execute(), indent=2))
