#!/usr/bin/env python
"""Print a compact summary of a backtest journal instead of the raw JSON.

A journal can be up to ~10 MB of pretty-printed JSON. Reading it whole into the model
context is wasteful. This extracts only what a review needs: meta (strategy/window/costs/
resolved config) + the backtest summary block + statistics + trade count. Typical output
is a few hundred tokens instead of millions.

Usage:
    python tools/journal_summary.py backtests/journal_swing_allocator_..._20260701_072040.json
    python tools/journal_summary.py --latest swing      # newest journal matching 'swing'
    python tools/journal_summary.py --trades <path>      # also list per-trade one-liners
"""
from __future__ import annotations

import glob
import json
import os
import sys

BACKTESTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests")


def _resolve_latest(token: str) -> str | None:
    pattern = os.path.join(BACKTESTS_DIR, f"journal_*{token}*.json")
    matches = glob.glob(pattern) if token else glob.glob(os.path.join(BACKTESTS_DIR, "journal_*.json"))
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return v


def _dump_section(title: str, obj) -> None:
    if obj is None:
        return
    print(f"\n== {title} ==")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"  {k}: {json.dumps(v, ensure_ascii=False, default=str)[:400]}")
            else:
                print(f"  {k}: {_fmt(v)}")
    else:
        print(f"  {json.dumps(obj, ensure_ascii=False, default=str)[:800]}")


def main(argv: list[str]) -> int:
    show_trades = False
    args = [a for a in argv if a != "--trades"]
    if "--trades" in argv:
        show_trades = True

    if "--latest" in args:
        i = args.index("--latest")
        token = args[i + 1] if i + 1 < len(args) else ""
        path = _resolve_latest(token)
        if not path:
            print(f"No journal found matching '{token}' in {BACKTESTS_DIR}", file=sys.stderr)
            return 1
    elif args:
        path = args[0]
    else:
        print(__doc__)
        return 1

    if not os.path.exists(path):
        print(f"Not found: {path}", file=sys.stderr)
        return 1

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    size = os.path.getsize(path)
    print(f"# {os.path.basename(path)}  ({size:,} bytes)")

    meta = data.get("meta", {})
    _dump_section("meta", {k: v for k, v in meta.items() if k not in ("resolved_config", "backtest")})
    _dump_section("meta.resolved_config", meta.get("resolved_config"))
    _dump_section("meta.backtest", meta.get("backtest"))
    _dump_section("statistics", data.get("statistics"))

    trades = data.get("trades") or data.get("rebalances") or []
    print(f"\n== entries in trades/rebalances: {len(trades)} ==")
    if show_trades:
        for i, t in enumerate(trades):
            when = t.get("timestamp") or t.get("date") or t.get("open", {}).get("timestamp", "?")
            pnl = t.get("pnl_usdt") or t.get("true_pnl_usdt") or t.get("close", {}).get("pnl_usdt", "")
            print(f"  [{i}] {when}  pnl={pnl}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
