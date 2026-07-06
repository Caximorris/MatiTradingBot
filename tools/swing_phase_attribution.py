"""Export Swing v5/v6 rebalance attribution by halving phase and cycle.

This is a measurement tool only. It does not change strategy defaults.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.swing_v6_common import (
    cycle_label,
    infer_phase,
    metrics_row,
    parse_config,
    parse_utc_date,
    run_swing_backtest,
    write_csv,
)

logger.remove()


def build_event_rows(run, symbol: str) -> list[dict]:
    rows = []
    for rb in run.strategy._rebalance_log:
        ts = datetime.fromisoformat(rb["timestamp"])
        phase = infer_phase(rb.get("signals"), ts, symbol)
        rows.append({
            "num": rb.get("num"),
            "timestamp": rb.get("timestamp"),
            "cycle": cycle_label(ts),
            "phase": phase,
            "direction": rb.get("direction"),
            "price": rb.get("price"),
            "qty": rb.get("qty"),
            "btc_pct_before": rb.get("btc_pct_before"),
            "btc_pct_target": rb.get("btc_pct_target"),
            "btc_pct_after": rb.get("btc_pct_after"),
            "portfolio_usdt": rb.get("portfolio_usdt"),
            "signals": ";".join(rb.get("signals") or []),
        })
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["direction"] == "INIT":
            continue
        grouped[(row["cycle"], row["phase"])].append(row)

    out = []
    for (cycle, phase), items in sorted(grouped.items()):
        dirs = Counter(x["direction"] for x in items)
        targets = [float(x["btc_pct_target"]) for x in items if x.get("btc_pct_target") is not None]
        afters = [float(x["btc_pct_after"]) for x in items if x.get("btc_pct_after") is not None]
        out.append({
            "cycle": cycle,
            "phase": phase,
            "rebalances": len(items),
            "buys": dirs.get("BUY", 0),
            "sells": dirs.get("SELL", 0),
            "avg_target": f"{sum(targets) / len(targets):.4f}" if targets else "",
            "avg_after": f"{sum(afters) / len(afters):.4f}" if afters else "",
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--from", dest="from_date", default="2015-01-01")
    p.add_argument("--to", dest="to_date", default="2026-01-01")
    p.add_argument("--costs", default="realistic")
    p.add_argument("--config", default="{}")
    p.add_argument("--out", default="data/runtime/swing_v5_phase_attribution.csv")
    p.add_argument("--summary-out", default="data/runtime/swing_v5_phase_summary.csv")
    args = p.parse_args()

    run = run_swing_backtest(
        symbol=args.symbol,
        from_dt=parse_utc_date(args.from_date),
        to_dt=parse_utc_date(args.to_date),
        cost_mode=args.costs,
        config=parse_config(args.config),
    )

    rows = build_event_rows(run, args.symbol)
    summary = summarize(rows)
    write_csv(Path(args.out), rows)
    write_csv(Path(args.summary_out), summary)

    print(",".join(metrics_row("swing_attribution", run).keys()))
    print(",".join(str(v) for v in metrics_row("swing_attribution", run).values()))
    print(f"events_csv,{args.out}")
    print(f"summary_csv,{args.summary_out}")
    for row in summary:
        print(
            "phase_summary,"
            f"{row['cycle']},{row['phase']},{row['rebalances']},"
            f"{row['buys']},{row['sells']},{row['avg_target']},{row['avg_after']}"
        )


if __name__ == "__main__":
    main()
