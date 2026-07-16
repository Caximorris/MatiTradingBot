"""Point-in-time funding overlay for Swing Allocator v6 research and paper runs."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from strategies.funding_coverage import (
    CoverageEvidenceError,
    coverage_evidence_for,
    coverage_manifest_record,
)


_ROOT = Path(__file__).resolve().parents[1]
_MAX_SNAPSHOT_AGE_MS = 26 * 60 * 60 * 1000
_SOURCES = {"bybit": "Bybit", "okx": "OKX"}
_MANIFEST_ACCESSES: dict[str, list[datetime]] = {}
_MANIFEST_COVERAGE: dict[str, dict[str, str]] = {}


class FundingOverlayError(RuntimeError):
    """The enabled funding overlay lacks a usable point-in-time snapshot."""


def funding_source(value: Any = "bybit") -> str:
    """Return a supported source from a config object or an explicit source name."""
    raw = value if isinstance(value, str) else getattr(value, "funding_overlay_source", "bybit")
    source = str(raw or "bybit").strip().lower()
    if source not in _SOURCES:
        raise FundingOverlayError(f"unsupported funding overlay source: {raw!r}")
    return source


def funding_market(symbol: str, source: str = "bybit") -> str:
    """Map the strategy spot symbol to the venue's perpetual funding instrument."""
    source = funding_source(source)
    compact = symbol.upper().replace("_", "-").replace("/", "-")
    base = compact.split("-", maxsplit=1)[0]
    if "-" not in compact and compact.endswith("USDT"):
        base = compact[:-4]
    if not base:
        raise FundingOverlayError(f"cannot derive funding market from {symbol!r}")
    return f"{base}-USDT" if source == "bybit" else f"{base}-USDT-SWAP"


def funding_cache_path(symbol: str, source: str = "bybit") -> Path:
    source = funding_source(source)
    market = funding_market(symbol, source)
    cache_market = market.replace("-", "") if source == "bybit" else market
    return _ROOT / "data" / "cache" / f"funding_{source}_{cache_market}.json"


def _manifest_key(symbol: str, source: str) -> str:
    return f"{funding_source(source)}:{funding_market(symbol, source)}"


def reset_manifest_accesses(symbol: str, source: str = "bybit") -> None:
    key = _manifest_key(symbol, source)
    _MANIFEST_ACCESSES[key] = []
    _MANIFEST_COVERAGE.pop(key, None)


def manifest_accesses(symbol: str, source: str = "bybit") -> list[datetime]:
    return _MANIFEST_ACCESSES.get(_manifest_key(symbol, source), [])


def manifest_coverage(symbol: str, source: str = "bybit") -> dict[str, str] | None:
    return _MANIFEST_COVERAGE.get(_manifest_key(symbol, source))


def _cache_mtime(symbol: str, source: str) -> float:
    path = funding_cache_path(symbol, source)
    return path.stat().st_mtime if path.exists() else 0.0


def load_funding_rows(symbol: str, source: str = "bybit") -> list[tuple[int, float]]:
    source = funding_source(source)
    path = funding_cache_path(symbol, source)
    if not path.exists():
        raise FundingOverlayError(f"{source} funding overlay cache is missing: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            raw_rows = json.load(handle)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FundingOverlayError(f"{source} funding overlay cache is unreadable: {path}") from exc
    if not isinstance(raw_rows, list) or not raw_rows:
        raise FundingOverlayError(f"{source} funding overlay cache is empty: {path}")

    rows: list[tuple[int, float]] = []
    for row in raw_rows:
        try:
            ts_ms, rate = int(row[0]), float(row[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise FundingOverlayError(
                f"{source} funding overlay cache has an invalid row: {path}"
            ) from exc
        if ts_ms <= 0 or not math.isfinite(rate):
            raise FundingOverlayError(f"{source} funding overlay cache has an invalid value: {path}")
        rows.append((ts_ms, rate))
    return sorted(rows)


def last_settlement_ms(symbol: str, source: str = "bybit") -> int | None:
    """Timestamp of the latest cached final settlement, or ``None`` when unavailable."""
    try:
        rows = load_funding_rows(symbol, source)
    except FundingOverlayError:
        return None
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
    source = funding_source(cfg)
    key = _manifest_key(symbol, source)
    _MANIFEST_ACCESSES.setdefault(key, []).append(now)
    rows = load_funding_rows(symbol, source)
    _require_fresh_snapshot(rows, now, symbol, source)
    events = _cached_events(
        source,
        symbol,
        int(getattr(cfg, "funding_overlay_lookback_settlements", 90)),
        float(getattr(cfg, "funding_low_pctile", 0.10)),
        float(getattr(cfg, "funding_high_pctile", 0.90)),
        int(getattr(cfg, "funding_overlay_dedup_days", 7)),
        int(getattr(cfg, "funding_overlay_ttl_days", 7)),
        _cache_mtime(symbol, source),
    )
    return active_overlay_at(
        events,
        now,
        phase,
        str(getattr(cfg, "funding_overlay_phases", "accumulation")),
        float(getattr(cfg, "funding_overlay_delta", 0.05)),
    )


def _require_fresh_snapshot(
    rows: list[tuple[int, float]], now: datetime, symbol: str, source: str = "bybit"
) -> None:
    source = funding_source(source)
    key = _manifest_key(symbol, source)
    market, venue = funding_market(symbol, source), _SOURCES[source]
    now_ms = int(_utc_timestamp(now).timestamp() * 1000)
    settled = [ts_ms for ts_ms, _ in rows if ts_ms <= now_ms]
    if not settled:
        evidence = coverage_evidence_for(market, venue)
        if evidence is None:
            _MANIFEST_COVERAGE[key] = coverage_manifest_record(
                None, "truncated_snapshot", "unavailable_evidence"
            )
            raise FundingOverlayError(
                f"{source} funding overlay snapshot for {market} is truncated_snapshot: "
                "unavailable_evidence"
            )
        try:
            evidence.validate(market, venue)
        except CoverageEvidenceError as exc:
            raise FundingOverlayError(
                f"{source} funding overlay snapshot for {market} is malformed_snapshot: {exc}"
            ) from exc
        if now < evidence.series_start:
            _MANIFEST_COVERAGE[key] = coverage_manifest_record(
                evidence, "proven_pre_listing", evidence.validity_rule
            )
            return
        _MANIFEST_COVERAGE[key] = coverage_manifest_record(
            evidence, "incomplete_historical_coverage", "evidence does not establish pre-listing"
        )
        raise FundingOverlayError(
            f"{source} funding overlay snapshot for {market} is incomplete_historical_coverage"
        )
    latest = max(settled)
    if now_ms - latest > _MAX_SNAPSHOT_AGE_MS:
        raise FundingOverlayError(
            f"{source} funding overlay snapshot for {market} is stale at "
            f"{now.isoformat()}: latest settlement is "
            f"{datetime.fromtimestamp(latest / 1000, tz=timezone.utc).isoformat()}"
        )
    _MANIFEST_COVERAGE[key] = coverage_manifest_record(
        coverage_evidence_for(market, venue), "complete_covered_period",
        "settlement coverage reaches the simulated timestamp",
    )


@lru_cache(maxsize=64)
def _cached_events(
    source: str,
    symbol: str,
    lookback: int,
    low_pctile: float,
    high_pctile: float,
    dedup_days: int,
    ttl_days: int,
    mtime: float,
) -> pd.DataFrame:
    return build_overlay_events(
        load_funding_rows(symbol, source), lookback, low_pctile, high_pctile, dedup_days, ttl_days
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
