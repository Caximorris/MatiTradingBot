"""Placeholder entrypoint retained for the explicit LOCO audit deliverable."""
import json
from pathlib import Path
from datetime import datetime, timezone

from btc_cycle_audit.core import boundary_stats, immutable_snapshot

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "btc_cycle_audit"

if __name__ == "__main__":
    audit = json.loads((AUDIT / "current_audit.json").read_text(encoding="utf-8"))
    extremes = audit.get("extremes", [])
    rows = []
    for excluded in sorted({row["cycle"] for row in extremes}):
        tops = [row["days_since_halving"] for row in extremes if row["cycle"] != excluded and row["kind"] == "top" and row["method"] == "close" and row["status"] == "RETROSPECTIVE"]
        bottoms = [row["days_since_halving"] for row in extremes if row["cycle"] != excluded and row["kind"] == "bottom" and row["method"] == "close" and row["status"] == "RETROSPECTIVE"]
        rows.append({"excluded_cycle": excluded, "top_estimate": boundary_stats(tops, 540).__dict__, "bottom_estimate": boundary_stats(bottoms, 900).__dict__})
    payload = {"status": "RESEARCH_ONLY", "rows": rows}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = immutable_snapshot(AUDIT / "snapshots" / f"leave_one_out_{stamp}.json", payload)
    print(json.dumps({**payload, "dataset_hash": digest}, indent=2))
