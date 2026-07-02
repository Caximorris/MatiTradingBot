"""Reporte de degradacion para Swing paper/live (F19).

Uso:
    python tools/degradation_report.py [data/runtime/swing_rebalances.jsonl]

Trabaja sobre el JSONL persistido por SwingAllocatorBot en paper/live.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


DEFAULT_PATH = Path("data") / "runtime" / "swing_rebalances.jsonl"
BACKTEST_REBALANCES_PER_QUARTER = 3.1


def _quarter(ts: str) -> str:
    dt = datetime.fromisoformat(ts)
    return f"{dt.year}-Q{((dt.month - 1) // 3) + 1}"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    if not path.exists():
        print(f"no_data,{path}")
        return

    entries = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rebalances = [e for e in entries if e.get("direction") != "INIT"]
    by_q = Counter(_quarter(e["timestamp"]) for e in rebalances)
    max_q = max(by_q.values(), default=0)
    latest = entries[-1] if entries else {}
    target_gap = abs(
        float(latest.get("btc_pct_after", 0.0)) - float(latest.get("btc_pct_target", 0.0))
    ) if latest else 0.0

    print(f"file,{path}")
    print(f"entries,{len(entries)}")
    print(f"rebalances,{len(rebalances)}")
    print(f"max_rebalances_per_quarter,{max_q}")
    print(f"latest_target_gap,{target_gap:.4f}")

    freq_limit = BACKTEST_REBALANCES_PER_QUARTER * 2
    if max_q > freq_limit:
        print(f"ALERT,rebalance_frequency,{max_q}>{freq_limit:.1f}")
    if target_gap > 0.02:
        print(f"ALERT,target_gap,{target_gap:.4f}>0.0200")
    if max_q <= freq_limit and target_gap <= 0.02:
        print("OK,no_degradation_flags")

    print("quarter,rebalances")
    for q, count in sorted(by_q.items()):
        print(f"{q},{count}")


if __name__ == "__main__":
    main()
