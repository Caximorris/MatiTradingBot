#!/usr/bin/env python
"""Probe public Bybit order book depth for E9 cost assumptions.

This is N0-lite: no account, no API key, no private execution. It only reads the
public linear-perp order book and estimates market-order crossing cost versus
mid price for the notional sizes relevant to E9.

The output is not a replacement for real fills. It answers a narrower question:
whether the live public book is compatible with the backtest cost assumptions
(`bybit` = 5.5 bps taker fee + 2 bps slippage, `bybit_cons` = +10 bps).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

getcontext().prec = 28

API_URL = "https://api.bybit.com/v5/market/orderbook"
USER_AGENT = "MatiTradingBot/BybitPublicCostProbe"


def _d(value: str | int | float | Decimal) -> Decimal:
    return Decimal(str(value))


def _fetch_orderbook(symbol: str, category: str, limit: int, timeout: float) -> dict:
    params = urlencode({"category": category, "symbol": symbol, "limit": limit})
    req = Request(f"{API_URL}?{params}", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("retCode") != 0:
        raise RuntimeError(f"Bybit retCode={payload.get('retCode')}: {payload.get('retMsg')}")
    return payload["result"]


def _walk_base(levels: list[list[str]], base_qty: Decimal) -> Decimal | None:
    """Return average fill price for base_qty, or None if the book is too shallow."""
    remaining = base_qty
    filled_base = Decimal("0")
    filled_quote = Decimal("0")
    for price_s, qty_s in levels:
        price = _d(price_s)
        qty = _d(qty_s)
        take = min(remaining, qty)
        filled_base += take
        filled_quote += take * price
        remaining -= take
        if remaining <= Decimal("0"):
            break
    if remaining > Decimal("0") or filled_base <= Decimal("0"):
        return None
    return filled_quote / filled_base


def _depth_within(levels: list[list[str]], mid: Decimal, side: str, bps: Decimal) -> Decimal:
    if side == "ask":
        limit_price = mid * (Decimal("1") + bps / Decimal("10000"))
        return sum(_d(p) * _d(q) for p, q in levels if _d(p) <= limit_price)
    limit_price = mid * (Decimal("1") - bps / Decimal("10000"))
    return sum(_d(p) * _d(q) for p, q in levels if _d(p) >= limit_price)


def _pct(values: list[float], percentile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * percentile
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _fmt_bps(value: float) -> str:
    if math.isnan(value):
        return "nan"
    return f"{value:.3f}"


def _fmt_usdt(value: float) -> str:
    if math.isnan(value):
        return "nan"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.0f}"


def _snapshot(symbol: str, category: str, limit: int, sizes: list[Decimal],
              depth_bands: list[Decimal], timeout: float) -> dict:
    raw = _fetch_orderbook(symbol, category, limit, timeout)
    bids = raw.get("b") or []
    asks = raw.get("a") or []
    if not bids or not asks:
        raise RuntimeError("empty order book")

    best_bid = _d(bids[0][0])
    best_ask = _d(asks[0][0])
    mid = (best_bid + best_ask) / Decimal("2")
    spread_bps = (best_ask - best_bid) / mid * Decimal("10000")

    costs = {}
    for size in sizes:
        base_qty = size / mid
        avg_buy = _walk_base(asks, base_qty)
        avg_sell = _walk_base(bids, base_qty)
        if avg_buy is None or avg_sell is None:
            costs[str(size)] = None
            continue
        buy_slip_bps = (avg_buy / mid - Decimal("1")) * Decimal("10000")
        sell_slip_bps = (Decimal("1") - avg_sell / mid) * Decimal("10000")
        costs[str(size)] = {
            "buy_slip_bps": float(buy_slip_bps),
            "sell_slip_bps": float(sell_slip_bps),
            "buy_avg": float(avg_buy),
            "sell_avg": float(avg_sell),
        }

    depth = {}
    for band in depth_bands:
        depth[str(band)] = {
            "ask_usdt": float(_depth_within(asks, mid, "ask", band)),
            "bid_usdt": float(_depth_within(bids, mid, "bid", band)),
        }

    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "bybit_ts": raw.get("ts"),
        "symbol": symbol,
        "category": category,
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "mid": float(mid),
        "spread_bps": float(spread_bps),
        "costs": costs,
        "depth": depth,
    }


def _summarize(samples: list[dict], sizes: list[Decimal],
               depth_bands: list[Decimal], fee_bps: Decimal) -> dict:
    spread = [float(s["spread_bps"]) for s in samples]
    summary = {
        "samples": len(samples),
        "started_at": samples[0]["ts_utc"],
        "ended_at": samples[-1]["ts_utc"],
        "mid_p50": _pct([float(s["mid"]) for s in samples], 0.5),
        "spread_bps_p50": _pct(spread, 0.5),
        "spread_bps_p95": _pct(spread, 0.95),
        "sizes": {},
        "depth": {},
    }

    for size in sizes:
        key = str(size)
        buy = [s["costs"][key]["buy_slip_bps"] for s in samples if s["costs"].get(key)]
        sell = [s["costs"][key]["sell_slip_bps"] for s in samples if s["costs"].get(key)]
        worst_side_p95 = max(_pct(buy, 0.95), _pct(sell, 0.95))
        summary["sizes"][key] = {
            "buy_slip_bps_p50": _pct(buy, 0.5),
            "buy_slip_bps_p95": _pct(buy, 0.95),
            "sell_slip_bps_p50": _pct(sell, 0.5),
            "sell_slip_bps_p95": _pct(sell, 0.95),
            "worst_slip_bps_p95": worst_side_p95,
            "taker_total_bps_p95": float(fee_bps) + worst_side_p95,
        }

    for band in depth_bands:
        key = str(band)
        ask = [s["depth"][key]["ask_usdt"] for s in samples]
        bid = [s["depth"][key]["bid_usdt"] for s in samples]
        summary["depth"][key] = {
            "ask_usdt_p50": _pct(ask, 0.5),
            "bid_usdt_p50": _pct(bid, 0.5),
            "min_side_usdt_p50": min(_pct(ask, 0.5), _pct(bid, 0.5)),
        }
    return summary


def _print_report(summary: dict, fee_bps: Decimal) -> None:
    print(f"# Bybit public order book probe: {summary['started_at']} -> {summary['ended_at']}")
    print(f"samples={summary['samples']} mid_p50={summary['mid_p50']:.2f} "
          f"spread_bps_p50={_fmt_bps(summary['spread_bps_p50'])} "
          f"spread_bps_p95={_fmt_bps(summary['spread_bps_p95'])} "
          f"taker_fee_bps={fee_bps}")

    print("\nDepth within mid +/- band (p50 USDT, weakest side):")
    print("band_bps,ask_p50,bid_p50,min_side_p50")
    for band, row in summary["depth"].items():
        print(f"{band},{_fmt_usdt(row['ask_usdt_p50'])},"
              f"{_fmt_usdt(row['bid_usdt_p50'])},"
              f"{_fmt_usdt(row['min_side_usdt_p50'])}")

    print("\nEstimated market-order cost versus mid:")
    print("notional_usdt,buy_slip_p50,buy_slip_p95,sell_slip_p50,sell_slip_p95,"
          "worst_slip_p95,taker_total_p95")
    max_total = 0.0
    for size, row in summary["sizes"].items():
        max_total = max(max_total, row["taker_total_bps_p95"])
        print(f"{size},{_fmt_bps(row['buy_slip_bps_p50'])},"
              f"{_fmt_bps(row['buy_slip_bps_p95'])},"
              f"{_fmt_bps(row['sell_slip_bps_p50'])},"
              f"{_fmt_bps(row['sell_slip_bps_p95'])},"
              f"{_fmt_bps(row['worst_slip_bps_p95'])},"
              f"{_fmt_bps(row['taker_total_bps_p95'])}")

    print("\nDecision band:")
    if max_total <= 7.0:
        print("<=7 bps p95: compatible with E9 cheap-cost recheck; bybit mode is conservative enough.")
    elif max_total >= 12.0:
        print(">=12 bps p95: compatible with hard-close threshold; bybit_cons or worse should govern.")
    else:
        print("7-12 bps p95: grey zone; keep bybit and bybit_cons sensitivity, do not buy from this alone.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--category", default="linear")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--samples", type=int, default=12)
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--fee-bps", type=Decimal, default=Decimal("5.5"))
    p.add_argument("--sizes", default="1000,3000,6000,12500,25000",
                   help="comma-separated USDT notionals")
    p.add_argument("--depth-bands", default="1,2,5,10",
                   help="comma-separated bps bands around mid")
    p.add_argument("--out", help="optional JSON output path")
    args = p.parse_args(argv)

    sizes = [_d(x.strip()) for x in args.sizes.split(",") if x.strip()]
    bands = [_d(x.strip()) for x in args.depth_bands.split(",") if x.strip()]
    samples: list[dict] = []

    try:
        for i in range(args.samples):
            samples.append(_snapshot(args.symbol, args.category, args.limit, sizes,
                                     bands, args.timeout))
            if i < args.samples - 1:
                time.sleep(args.interval)
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary = _summarize(samples, sizes, bands, args.fee_bps)
    _print_report(summary, args.fee_bps)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "samples": samples}, fh, indent=2)
        print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
