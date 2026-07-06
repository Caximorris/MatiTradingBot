"""Funding-extreme overlay for Swing Allocator v6 research."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]


def funding_cache_path(symbol: str) -> Path:
    sym = symbol.replace("-", "").upper()
    return _ROOT / "data" / "cache" / f"funding_bybit_{sym}.json"


def _cache_mtime(symbol: str) -> float:
    path = funding_cache_path(symbol)
    return path.stat().st_mtime if path.exists() else 0.0


def load_funding_rows(symbol: str) -> list[tuple[int, float]]:
    path = funding_cache_path(symbol)
    if not path.exists():
        return []
    return [(int(ts), float(rate)) for ts, rate in json.load(open(path, encoding="utf-8"))]


def last_settlement_ms(symbol: str) -> int | None:
    """Timestamp (ms) del ultimo settlement cacheado, o None si no hay datos.
    Sirve para vigilar frescura del cache: en vivo el overlay solo puede disparar
    si el pipeline (tools/funding_refresh.py) mantiene este archivo al dia."""
    rows = load_funding_rows(symbol)
    return max((ts for ts, _ in rows), default=None)


def build_overlay_events(
    funding: pd.DataFrame | list[tuple[int, float]],
    lookback: int = 90,
    low_pctile: float = 0.10,
    high_pctile: float = 0.90,
    dedup_days: int = 7,
    ttl_days: int = 7,
) -> pd.DataFrame:
    df = _funding_frame(funding)
    if len(df) < int(lookback) + 2:
        return _empty_events()

    rates = df["rate"]
    df["low_threshold"] = rates.rolling(int(lookback)).quantile(float(low_pctile)).shift(1)
    df["high_threshold"] = rates.rolling(int(lookback)).quantile(float(high_pctile)).shift(1)
    df["signal"] = ""
    df.loc[rates < df["low_threshold"], "signal"] = "funding_low"
    df.loc[rates > df["high_threshold"], "signal"] = "funding_high"

    events = df[df["signal"] != ""].copy()
    if events.empty:
        return _empty_events()

    events = _deduplicate(events, int(dedup_days))
    events["expires_at"] = events["dt"] + pd.to_timedelta(int(ttl_days), unit="D")
    return events[["ts", "dt", "expires_at", "rate", "signal"]].reset_index(drop=True)


def active_overlay_at(
    events: pd.DataFrame,
    now: datetime,
    phase: str,
    allowed_phases: str,
    delta: float,
) -> tuple[float, str | None]:
    allowed = _parse_phases(allowed_phases)
    if events.empty or (allowed is not None and phase not in allowed):
        return 0.0, None

    ts = _utc_timestamp(now)
    active = events[(events["dt"] < ts) & (events["expires_at"] >= ts)]
    if active.empty:
        return 0.0, None

    row = active.sort_values("dt").iloc[-1]
    side = "low" if row.signal == "funding_low" else "high"
    return float(delta), f"funding_overlay_{side}_{float(row.rate):.5f}"


def funding_overlay_adjustment(symbol: str, now: datetime, phase: str, cfg: Any) -> tuple[float, str | None]:
    # El mtime del cache entra en la clave del lru_cache: un proceso live que corre
    # semanas debe recomputar cuando el pipeline refresca el archivo de funding.
    # Sin esto, _cached_events congelaria los eventos calculados en el primer tick.
    events = _cached_events(
        symbol,
        int(getattr(cfg, "funding_overlay_lookback_settlements", 90)),
        float(getattr(cfg, "funding_low_pctile", 0.10)),
        float(getattr(cfg, "funding_high_pctile", 0.90)),
        int(getattr(cfg, "funding_overlay_dedup_days", 7)),
        int(getattr(cfg, "funding_overlay_ttl_days", 7)),
        _cache_mtime(symbol),
    )
    return active_overlay_at(
        events,
        now,
        phase,
        str(getattr(cfg, "funding_overlay_phases", "accumulation")),
        float(getattr(cfg, "funding_overlay_delta", 0.05)),
    )


@lru_cache(maxsize=64)
def _cached_events(
    symbol: str,
    lookback: int,
    low_pctile: float,
    high_pctile: float,
    dedup_days: int,
    ttl_days: int,
    mtime: float,  # solo para invalidar la cache cuando cambia el archivo
) -> pd.DataFrame:
    return build_overlay_events(
        load_funding_rows(symbol), lookback, low_pctile, high_pctile, dedup_days, ttl_days
    )


def _funding_frame(funding: pd.DataFrame | list[tuple[int, float]]) -> pd.DataFrame:
    if isinstance(funding, pd.DataFrame):
        df = funding.copy()
        if "ts" not in df.columns:
            df["ts"] = pd.to_datetime(df["dt"], utc=True).astype("int64") // 1_000_000
        if "dt" not in df.columns:
            df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    else:
        df = pd.DataFrame(funding, columns=["ts", "rate"])
        if df.empty:
            return pd.DataFrame(columns=["ts", "dt", "rate"])
        df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)

    df["ts"] = df["ts"].astype("int64")
    df["rate"] = df["rate"].astype(float)
    return df.sort_values("ts").reset_index(drop=True)


def _deduplicate(events: pd.DataFrame, dedup_days: int) -> pd.DataFrame:
    keep = []
    last_by_signal: dict[str, pd.Timestamp] = {}
    gap = pd.to_timedelta(int(dedup_days), unit="D")
    for row in events.sort_values("dt").itertuples():
        last = last_by_signal.get(row.signal)
        if last is not None and row.dt - last < gap:
            continue
        keep.append(row.Index)
        last_by_signal[row.signal] = row.dt
    return events.loc[keep].copy()


def _parse_phases(value: str) -> set[str] | None:
    if value.lower().strip() == "all":
        return None
    normalized = value.replace("+", ",")
    return {p.strip() for p in normalized.split(",") if p.strip()}


def _utc_timestamp(now: datetime) -> pd.Timestamp:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return pd.Timestamp(now).tz_convert("UTC")


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts", "dt", "expires_at", "rate", "signal"])
