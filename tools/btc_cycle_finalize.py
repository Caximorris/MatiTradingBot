"""Validate and summarize the completed research checkpoint."""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "btc_cycle_audit"


def nums(rows, key):
    return [float(row[key]) for row in rows if row.get("status") == "SUCCEEDED" and row.get(key) not in (None, "")]


def main() -> None:
    checkpoint = json.loads((AUDIT / "research_checkpoint.json").read_text(encoding="utf-8"))
    matrix = list(checkpoint.get("matrix", {}).values())
    placebos = list(checkpoint.get("placebos", {}).values())
    loco = list(checkpoint.get("loco", {}).values())
    required = {
        "matrix_completed": len(matrix) == 25 and all(row.get("status") == "SUCCEEDED" for row in matrix),
        "placebo_suite_completed": len(placebos) == 7 and all(row.get("status") == "SUCCEEDED" for row in placebos),
        "loco_suite_completed": len(loco) == 2 and all(row.get("status") == "SUCCEEDED" for row in loco),
        "all_required_metrics_present": all(all(row.get(key) not in (None, "") for key in ("final", "cagr", "max_dd", "calmar", "sharpe", "sortino", "underwater_days", "buy_hold_pct", "rebalance_events", "cost", "cycle_results")) for row in matrix if row.get("status") == "SUCCEEDED") and all(all(row.get(key) not in (None, "") for key in ("final", "cagr", "max_dd", "calmar", "sharpe", "sortino", "underwater_days", "buy_hold_pct", "rebalance_events", "cost", "cycle_results")) for row in placebos if row.get("status") == "SUCCEEDED") and all(row.get("actual_global_extrema") and row.get("top_error_days") is not None and row.get("bottom_error_days") is not None for row in loco if row.get("status") == "SUCCEEDED"),
        "dataset_hash_unchanged": len({row.get("dataset_hash") for row in matrix + placebos + loco if row.get("dataset_hash")}) <= 1,
        "production_unchanged": json.loads((AUDIT / "active_production_policy.json").read_text(encoding="utf-8")).get("production_changed_by_audit") is False,
    }
    if not all(required.values()):
        payload = {"status": "INCOMPLETE", "gates": required}
        (AUDIT / "final_completeness.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        raise SystemExit(json.dumps(payload))
    values = nums(matrix, "final")
    cagr = nums(matrix, "cagr")
    ordered = sorted(matrix, key=lambda row: float(row["final"]))
    best, worst = ordered[-1], ordered[0]
    neighborhood = [row for row in matrix if row["bear_defense_start"] in (510, 540, 570) and row["accumulation_start"] in (870, 900, 930)]
    actual = next(row for row in placebos if row["label"] == "actual")
    placebo_finals = [float(row["final"]) for row in placebos]
    actual_rank = 1 + sum(value > float(actual["final"]) for value in placebo_finals)
    plateau = [row for row in matrix if float(row["final"]) >= statistics.median(values)]
    summary = {
        "status": "COMPLETE",
        "gates": required,
        "matrix": {"count": len(matrix), "best": best, "worst": worst, "median_final": statistics.median(values), "iqr_final": [statistics.quantiles(values, n=4)[0], statistics.quantiles(values, n=4)[2]], "median_cagr": statistics.median(cagr), "neighborhood_9_cells": neighborhood, "at_or_above_median_cells": len(plateau), "at_or_above_median_labels": [row["case"] for row in plateau]},
        "placebos": {"count": len(placebos), "real": actual, "real_rank_descending": actual_rank, "real_percentile_descending": round(100 * (len(placebo_finals) - actual_rank + 1) / len(placebo_finals), 2), "outperforming_real": [row["label"] for row in placebos if row["label"] != "actual" and float(row["final"]) > float(actual["final"])]},
        "loco": loco,
    }
    (AUDIT / "final_research_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (AUDIT / "matrix_5x5.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in matrix for key in row if key != "cycle_results"}))
        writer.writeheader()
        writer.writerows({key: value for key, value in row.items() if key != "cycle_results"} for row in matrix)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
