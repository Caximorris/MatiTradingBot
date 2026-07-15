"""Point-in-time OKX funding history for deterministic backtests.

Funding settlements are aggregated by UTC day. A simulated tick can only use a
complete prior day, with a five-day sparse-data lookup window. Cache entries are
immutable, symbol-specific coverage snapshots and are committed only after a
clean pagination run.
"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Mapping

from loguru import logger


_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible)"}
_OKX_URL = "https://www.okx.com/api/v5/public/funding-rate-history"
_LOOKBACK_DAYS = 5
_PAGINATION_DELAY_S = 0.08


class FundingFetchError(RuntimeError):
    """The venue response could not establish a complete requested snapshot."""


@dataclass(frozen=True)
class _FundingSnapshot:
    inst_id: str
    coverage_from: datetime
    coverage_to: datetime
    rates: Mapping[str, float]

    def contains(self, start: datetime, end: datetime) -> bool:
        return self.coverage_from <= start and end <= self.coverage_to


_SNAPSHOTS: dict[str, tuple[_FundingSnapshot, ...]] = {}
_CACHE_LOCK = threading.RLock()


def _fetch_page(inst_id: str, after_ms: int | None) -> list[dict]:
    """Fetch one successful page; an empty list means clean exhaustion."""
    url = f"{_OKX_URL}?instId={inst_id}&limit=100"
    if after_ms is not None:
        url += f"&after={after_ms}"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:
        raise FundingFetchError(f"funding request failed after={after_ms}") from exc

    if payload.get("code") != "0":
        raise FundingFetchError(
            f"funding API returned code={payload.get('code')} after={after_ms}"
        )
    records = payload.get("data")
    if not isinstance(records, list):
        raise FundingFetchError("funding API response has no list data field")
    return records


def load_funding_history(symbol: str, from_dt: datetime, to_dt: datetime) -> None:
    """Load an atomic symbol/window snapshot, including five prior UTC days."""
    _require_utc(from_dt, "from_dt")
    _require_utc(to_dt, "to_dt")
    if from_dt >= to_dt:
        raise ValueError("funding window must have from_dt < to_dt")

    inst_id = _instrument_id(symbol)
    coverage_from = from_dt - timedelta(days=_LOOKBACK_DAYS)

    with _CACHE_LOCK:
        existing_snapshots = _SNAPSHOTS.get(inst_id, ())
        if any(snapshot.contains(coverage_from, to_dt) for snapshot in existing_snapshots):
            logger.debug(
                "funding_context: cache {} contiene {} -> {}",
                inst_id,
                coverage_from.isoformat(),
                to_dt.isoformat(),
            )
            return

        logger.info(
            "Descargando funding rate historico {} ({} -> {}) ...",
            inst_id,
            coverage_from.date(),
            to_dt.date(),
        )
        try:
            rates_by_timestamp, pages = _paginate(inst_id, coverage_from)
        except FundingFetchError:
            logger.exception(
                "funding_context: snapshot {} no actualizado; se conserva el anterior",
                inst_id,
            )
            raise

        daily: dict[str, list[float]] = {}
        for ts_ms, rate in sorted(rates_by_timestamp.items()):
            dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            if coverage_from <= dt_utc <= to_dt:
                daily.setdefault(dt_utc.date().isoformat(), []).append(rate)

        immutable_rates = MappingProxyType(
            {day: sum(values) / len(values) for day, values in sorted(daily.items())}
        )
        snapshot = _FundingSnapshot(
            inst_id=inst_id,
            coverage_from=coverage_from,
            coverage_to=to_dt,
            rates=immutable_rates,
        )
        for existing in existing_snapshots:
            for day in existing.rates.keys() & snapshot.rates.keys():
                if existing.rates[day] != snapshot.rates[day]:
                    raise FundingFetchError(
                        f"funding snapshots conflict for {inst_id} on {day}"
                    )
        _SNAPSHOTS[inst_id] = tuple(
            sorted(
                (*existing_snapshots, snapshot),
                key=lambda item: (item.coverage_from, item.coverage_to),
            )
        )
        logger.info(
            "Funding rate: {} dias cargados para {} ({} paginas)",
            len(immutable_rates),
            inst_id,
            pages,
        )


def _paginate(inst_id: str, coverage_from: datetime) -> tuple[dict[int, float], int]:
    from_ms = int(coverage_from.timestamp() * 1000)
    by_timestamp: dict[int, float] = {}
    after_ms: int | None = None
    pages = 0

    while True:
        records = _fetch_page(inst_id, after_ms)
        if not records:
            break
        pages += 1

        valid_timestamps: list[int] = []
        for record in records:
            try:
                ts_ms = int(record["fundingTime"])
                rate = float(record["fundingRate"])
            except (KeyError, TypeError, ValueError) as exc:
                raise FundingFetchError("funding page contains an invalid record") from exc
            if not math.isfinite(rate):
                raise FundingFetchError("funding page contains a non-finite rate")
            valid_timestamps.append(ts_ms)
            previous = by_timestamp.get(ts_ms)
            if previous is not None and previous != rate:
                raise FundingFetchError(
                    f"conflicting funding rates for settlement {ts_ms}"
                )
            by_timestamp[ts_ms] = rate

        oldest_ms = min(valid_timestamps)
        if after_ms is not None and oldest_ms >= after_ms:
            raise FundingFetchError(
                f"funding pagination made no progress: after={after_ms}, oldest={oldest_ms}"
            )
        if oldest_ms <= from_ms:
            break
        after_ms = oldest_ms
        if _PAGINATION_DELAY_S:
            time.sleep(_PAGINATION_DELAY_S)

    return by_timestamp, pages


def get_funding_rate_at(dt: datetime, symbol: str) -> float:
    """Return the latest complete prior UTC day's average, up to five days back."""
    _require_utc(dt, "dt")
    with _CACHE_LOCK:
        snapshots = _SNAPSHOTS.get(_instrument_id(symbol), ())
    if not snapshots:
        return 0.0

    day = dt.astimezone(timezone.utc).date()
    prior_day = day - timedelta(days=1)
    candidates = [
        snapshot
        for snapshot in snapshots
        if snapshot.coverage_from.date() <= prior_day
        and snapshot.coverage_to.date() >= day
    ]
    if not candidates:
        return 0.0
    snapshot = min(
        candidates,
        key=lambda item: (item.coverage_to - item.coverage_from, item.coverage_from),
    )
    for delta in range(1, _LOOKBACK_DAYS + 1):
        candidate = (day - timedelta(days=delta)).isoformat()
        if candidate in snapshot.rates:
            return snapshot.rates[candidate]
    return 0.0


def _instrument_id(symbol: str) -> str:
    base = symbol.split("-")[0].strip().upper()
    if not base:
        raise ValueError("symbol must contain a base currency")
    return f"{base}-USDT-SWAP"


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
