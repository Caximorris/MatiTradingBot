#!/usr/bin/env python
"""Refresh an immutable funding-settlement snapshot for Swing v6 paper runs.

The v6 overlay reads an atomically-written local cache. ``okx`` is the forward
paper source because its public API is reachable from the US-hosted VM; ``bybit``
remains available only for protected historical research inputs.

Usage:
  python tools/funding_refresh.py --source okx
  python tools/funding_refresh.py --source bybit --symbol BTCUSDT
  python tools/funding_refresh.py --source okx --stale-hours 12
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MatiTradingBot funding snapshot)"}
_BYBIT_API = "https://api.bybit.com/v5/market/funding/history"
_OKX_API = "https://www.okx.com/api/v5/public/funding-rate-history"
_SOURCES = {"bybit", "okx"}
_MAX_PAGES = 200


def _source(source: str) -> str:
    normalized = source.strip().lower()
    if normalized not in _SOURCES:
        raise ValueError(f"unsupported funding source: {source!r}")
    return normalized


def _market(symbol: str, source: str) -> str:
    source = _source(source)
    compact = symbol.upper().replace("_", "-").replace("/", "-")
    base = compact.split("-", maxsplit=1)[0]
    if "-" not in compact and compact.endswith("USDT"):
        base = compact[:-4]
    if not base:
        raise ValueError(f"cannot derive funding market from {symbol!r}")
    return f"{base}USDT" if source == "bybit" else f"{base}-USDT-SWAP"


def _cache_path(symbol: str, source: str = "bybit") -> Path:
    source = _source(source)
    return ROOT / "data" / "cache" / f"funding_{source}_{_market(symbol, source)}.json"


def _load(path: Path) -> dict[int, float]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    return {int(ts): float(rate) for ts, rate in rows}


def _fetch_page(symbol: str, cursor_ms: int | None, source: str = "bybit") -> list[tuple[int, float]]:
    """Fetch final settlements ordered by the provider; empty means exhaustion."""
    source = _source(source)
    market = _market(symbol, source)
    if source == "bybit":
        url = f"{_BYBIT_API}?category=linear&symbol={market}&limit=200"
        if cursor_ms is not None:
            url += f"&endTime={cursor_ms}"
    else:
        url = f"{_OKX_API}?instId={market}&limit=100"
        if cursor_ms is not None:
            url += f"&after={cursor_ms}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.loads(response.read())

    if source == "bybit":
        if payload.get("retCode") not in (0, None):
            raise RuntimeError(f"Bybit retCode={payload.get('retCode')}: {payload.get('retMsg')}")
        page = payload.get("result", {}).get("list", [])
        return [(int(row["fundingRateTimestamp"]), float(row["fundingRate"])) for row in page]

    if payload.get("code") != "0":
        raise RuntimeError(f"OKX code={payload.get('code')}: {payload.get('msg')}")
    page = payload.get("data", [])
    return [(int(row["fundingTime"]), float(row["fundingRate"])) for row in page]


def _next_cursor(oldest_ms: int, source: str) -> int:
    return oldest_ms - 1 if _source(source) == "bybit" else oldest_ms


def refresh(symbol: str, source: str = "bybit") -> dict:
    """Fetch, validate, deduplicate, and atomically publish final settlements."""
    source = _source(source)
    path = _cache_path(symbol, source)
    known = _load(path)
    last_ts = max(known) if known else None

    fetched: dict[int, float] = {}
    cursor: int | None = None
    for _ in range(_MAX_PAGES):
        page = _fetch_page(symbol, cursor, source)
        if not page:
            break
        for ts, rate in page:
            if ts <= 0 or not math.isfinite(rate):
                raise RuntimeError(f"{source} returned an invalid funding settlement")
            previous = fetched.get(ts)
            if previous is not None and previous != rate:
                raise RuntimeError(f"{source} returned conflicting funding settlement {ts}")
            fetched[ts] = rate
        oldest = min(ts for ts, _ in page)
        if last_ts is not None and oldest <= last_ts:
            break
        if cursor is not None and oldest >= cursor:
            raise RuntimeError(f"{source} funding pagination made no progress")
        cursor = _next_cursor(oldest, source)
        time.sleep(0.2)

    added = {ts: rate for ts, rate in fetched.items() if ts not in known}
    if added:
        merged = {**known, **added}
        rows = [[ts, merged[ts]] for ts in sorted(merged)]
        temporary = path.with_suffix(".json.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(rows, handle, separators=(",", ":"))
        os.replace(temporary, path)
        total = len(rows)
    else:
        total = len(known)

    new_last = max({**known, **added}) if (known or added) else None
    stale_hours = None
    if new_last is not None:
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(new_last / 1000, tz=timezone.utc)
        stale_hours = age.total_seconds() / 3600.0
    return {
        "source": source,
        "market": _market(symbol, source),
        "added": len(added),
        "total": total,
        "last_settlement": (
            datetime.fromtimestamp(new_last / 1000, tz=timezone.utc).isoformat()
            if new_last is not None else None
        ),
        "stale_hours": stale_hours,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC-USDT")
    parser.add_argument("--source", choices=sorted(_SOURCES), default="okx")
    parser.add_argument(
        "--stale-hours", type=float, default=None,
        help="Exit nonzero when the latest final settlement is older than this threshold.",
    )
    args = parser.parse_args()

    try:
        result = refresh(args.symbol, args.source)
    except Exception as exc:
        print(f"funding_refresh ERROR {args.source} {args.symbol}: {type(exc).__name__}: {exc}")
        return 2

    age = f"{result['stale_hours']:.1f}" if result["stale_hours"] is not None else "n/a"
    print(
        f"funding_refresh {result['source']} {result['market']}: +{result['added']} new, "
        f"total {result['total']}, latest {result['last_settlement']} (stale {age}h)"
    )
    if args.stale_hours is not None:
        if result["stale_hours"] is None:
            print("funding_refresh STALE: no cache data")
            return 3
        if result["stale_hours"] > args.stale_hours:
            print(f"funding_refresh STALE: {result['stale_hours']:.1f}h > {args.stale_hours}h threshold")
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
