"""Screen funding-extreme events for possible Swing v6 allocation overlay.

The screen uses closed funding settlements only, rolling percentile thresholds
shifted by one settlement, and event deduplication before measuring forward spot
returns. It does not change the Swing strategy.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.swing_v6_common import halving_phase_at, parse_utc_date, write_csv

logger.remove()


def load_ohlcv(symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    raw = json.load(open(ROOT / "data" / "cache" / f"{symbol}_1H.json", encoding="utf-8"))
    bars = raw["bars"] if isinstance(raw, dict) else raw
    df = pd.DataFrame(bars, columns=["ts", "o", "h", "l", "c", "v"])
    for col in ("o", "h", "l", "c", "v"):
        df[col] = df[col].astype(float)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df[(df["dt"] >= from_date) & (df["dt"] < to_date)].reset_index(drop=True)
    close = df["c"].to_numpy()
    for hours in (24, 72, 168):
        fwd = np.full(len(close), np.nan)
        fwd[:-hours] = (close[hours:] / close[:-hours] - 1.0) * 1e4
        df[f"f{hours}"] = fwd
    df["year"] = df["dt"].dt.year
    return df


def fetch_bybit_funding(symbol: str) -> pd.DataFrame:
    sym = symbol.replace("-", "")
    cache = ROOT / "data" / "cache" / f"funding_bybit_{sym}.json"
    if cache.exists():
        rows = json.load(open(cache, encoding="utf-8"))
    else:
        rows, end = [], None
        url0 = f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={sym}&limit=200"
        for _ in range(200):
            url = url0 + (f"&endTime={end}" if end else "")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            page = data.get("result", {}).get("list", [])
            if not page:
                break
            rows += [(int(r["fundingRateTimestamp"]), float(r["fundingRate"])) for r in page]
            end = int(page[-1]["fundingRateTimestamp"]) - 1
            time.sleep(0.2)
        json.dump(rows, open(cache, "w", encoding="utf-8"))
    df = pd.DataFrame(rows, columns=["ts", "rate"]).sort_values("ts").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def mark_extremes(
    funding: pd.DataFrame,
    lookback: int,
    low_pctile: float,
    high_pctile: float,
) -> pd.DataFrame:
    out = funding.copy()
    rates = out["rate"]
    out["low_threshold"] = rates.rolling(lookback).quantile(low_pctile).shift(1)
    out["high_threshold"] = rates.rolling(lookback).quantile(high_pctile).shift(1)
    out["signal"] = ""
    out.loc[rates < out["low_threshold"], "signal"] = "funding_low"
    out.loc[rates > out["high_threshold"], "signal"] = "funding_high"
    return out[out["signal"] != ""].copy()


def deduplicate_events(events: pd.DataFrame, dedup_days: int) -> pd.DataFrame:
    keep = []
    last_by_signal: dict[str, pd.Timestamp] = {}
    gap = pd.Timedelta(timedelta(days=int(dedup_days)))
    for row in events.sort_values("dt").itertuples():
        last = last_by_signal.get(row.signal)
        if last is not None and row.dt - last < gap:
            continue
        keep.append(row.Index)
        last_by_signal[row.signal] = row.dt
    return events.loc[keep].reset_index(drop=True)


def attach_forward_returns(events: pd.DataFrame, prices: pd.DataFrame, symbol: str) -> pd.DataFrame:
    px = prices[["dt", "year", "f24", "f72", "f168"]].sort_values("dt")
    out = pd.merge_asof(events.sort_values("dt"), px, on="dt", direction="forward")
    out["phase"] = out["dt"].map(lambda dt: halving_phase_at(dt.to_pydatetime(), symbol))
    return out


def consistency(sub: pd.DataFrame, col: str) -> str:
    yearly = sub.groupby("year")[col].mean().dropna()
    if yearly.empty:
        return "0/0"
    return f"{int((yearly > 0).sum())}/{len(yearly)}"


def summarize(events: pd.DataFrame) -> list[dict]:
    rows = []
    for (signal, phase), sub in events.groupby(["signal", "phase"], dropna=False):
        row = {"signal": signal, "phase": phase, "events": int(len(sub))}
        for col in ("f24", "f72", "f168"):
            row[f"{col}_mean_bps"] = f"{float(sub[col].mean()):.2f}"
            row[f"{col}_consistency"] = consistency(sub, col)
        rows.append(row)
    return sorted(rows, key=lambda r: (r["signal"], r["phase"]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--from", dest="from_date", default="2018-01-01")
    p.add_argument("--to", dest="to_date", default="2026-01-01")
    p.add_argument("--lookback-settlements", type=int, default=90)
    p.add_argument("--low-pctile", type=float, default=0.05)
    p.add_argument("--high-pctile", type=float, default=0.95)
    p.add_argument("--dedup-days", type=int, default=7)
    p.add_argument("--phases", default="all")
    p.add_argument("--out", default="data/runtime/swing_funding_overlay_screen.csv")
    args = p.parse_args()

    from_dt = parse_utc_date(args.from_date)
    to_dt = parse_utc_date(args.to_date)
    prices = load_ohlcv(args.symbol, from_dt.isoformat(), to_dt.isoformat())
    funding = fetch_bybit_funding(args.symbol.replace("-USDT", "USDT"))
    funding = funding[(funding["dt"] >= from_dt.isoformat()) & (funding["dt"] < to_dt.isoformat())]

    events = mark_extremes(funding, args.lookback_settlements, args.low_pctile, args.high_pctile)
    events = deduplicate_events(events, args.dedup_days)
    events = attach_forward_returns(events, prices, args.symbol)
    if args.phases != "all":
        allowed = {x.strip() for x in args.phases.split(",") if x.strip()}
        events = events[events["phase"].isin(allowed)].reset_index(drop=True)

    rows = summarize(events)
    write_csv(Path(args.out), rows)
    print("signal,phase,events,f24_mean_bps,f24_consistency,f72_mean_bps,f72_consistency,f168_mean_bps,f168_consistency")
    for row in rows:
        print(",".join(str(row.get(k, "")) for k in (
            "signal", "phase", "events", "f24_mean_bps", "f24_consistency",
            "f72_mean_bps", "f72_consistency", "f168_mean_bps", "f168_consistency",
        )))
    print(f"csv,{args.out}")


if __name__ == "__main__":
    main()
