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
from typing import Any, Mapping

from loguru import logger
from strategies.funding_coverage import (
    CoverageEvidenceError,
    FundingCoverageEvidence,
    coverage_evidence_for,
    coverage_manifest_record,
)


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
    first_available: datetime
    latest_available: datetime
    history_exhausted: bool
    rates: Mapping[str, float]
    coverage_evidence: FundingCoverageEvidence | None

    def contains(self, start: datetime, end: datetime) -> bool:
        return self.coverage_from <= start and end <= self.coverage_to


_SNAPSHOTS: dict[str, tuple[_FundingSnapshot, ...]] = {}
_CACHE_LOCK = threading.RLock()
_MANIFEST_ACCESSES: dict[str, list[datetime]] = {}


def requires_okx_funding(strategy_name: str, config: Mapping[str, Any] | None = None) -> bool:
    """Whether this strategy configuration consumes the OKX funding context.

    Keep this explicit so callers do not load a data dependency for strategies
    that cannot consume it.  ``disable_external_filters`` disables Pro Trend's
    funding gate alongside its other external inputs.
    """
    return strategy_name == "pro_trend" and not bool(
        (config or {}).get("disable_external_filters", False)
    )


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
    _MANIFEST_ACCESSES[inst_id] = []
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
            rates_by_timestamp, pages, history_exhausted = _paginate(inst_id, coverage_from)
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

        if not daily:
            raise FundingFetchError(
                f"funding snapshot for {inst_id} is empty in requested coverage "
                f"{coverage_from.isoformat()} -> {to_dt.isoformat()}"
            )

        in_coverage = [
            ts_ms
            for ts_ms in rates_by_timestamp
            if coverage_from <= datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) <= to_dt
        ]
        latest_available = datetime.fromtimestamp(
            max(in_coverage) / 1000, tz=timezone.utc
        )
        freshness_cutoff = to_dt - timedelta(days=1)
        if latest_available < freshness_cutoff:
            raise FundingFetchError(
                f"funding snapshot for {inst_id} is stale: latest settlement "
                f"{latest_available.isoformat()} is before {freshness_cutoff.isoformat()}"
            )

        immutable_rates = MappingProxyType(
            {day: sum(values) / len(values) for day, values in sorted(daily.items())}
        )
        try:
            evidence = coverage_evidence_for(inst_id, "OKX")
            if evidence is not None:
                evidence.validate(inst_id, "OKX")
        except CoverageEvidenceError as exc:
            raise FundingFetchError(f"malformed coverage evidence for {inst_id}") from exc
        snapshot = _FundingSnapshot(
            inst_id=inst_id,
            coverage_from=coverage_from,
            coverage_to=to_dt,
            first_available=datetime.fromtimestamp(
                min(rates_by_timestamp) / 1000, tz=timezone.utc
            ),
            latest_available=latest_available,
            history_exhausted=history_exhausted,
            rates=immutable_rates,
            coverage_evidence=evidence,
        )
        for existing in existing_snapshots:
            if existing.coverage_evidence != snapshot.coverage_evidence:
                raise FundingFetchError(f"funding coverage evidence conflicts for {inst_id}")
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


def _paginate(inst_id: str, coverage_from: datetime) -> tuple[dict[int, float], int, bool]:
    from_ms = int(coverage_from.timestamp() * 1000)
    by_timestamp: dict[int, float] = {}
    after_ms: int | None = None
    pages = 0
    history_exhausted = False

    while True:
        records = _fetch_page(inst_id, after_ms)
        if not records:
            history_exhausted = True
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

    return by_timestamp, pages, history_exhausted


def get_funding_rate_at(dt: datetime, symbol: str) -> float:
    """Return the latest complete prior UTC day's average, up to five days back."""
    _require_utc(dt, "dt")
    inst_id = _instrument_id(symbol)
    _MANIFEST_ACCESSES.setdefault(inst_id, []).append(dt)
    with _CACHE_LOCK:
        snapshots = _SNAPSHOTS.get(inst_id, ())
    if not snapshots:
        raise FundingFetchError(
            f"funding has not been loaded for {_instrument_id(symbol)}"
        )

    day = dt.astimezone(timezone.utc).date()
    prior_day = day - timedelta(days=1)
    candidates = [
        snapshot
        for snapshot in snapshots
        if snapshot.coverage_from.date() <= prior_day
        and snapshot.coverage_to.date() >= day
    ]
    if not candidates:
        raise FundingFetchError(
            f"no funding snapshot covers {symbol} on {day.isoformat()}"
        )
    snapshot = min(
        candidates,
        key=lambda item: (item.coverage_to - item.coverage_from, item.coverage_from),
    )
    status, detail = funding_coverage_status(snapshot, dt)
    if status == "proven_pre_listing":
        return 0.0
    if status != "complete_covered_period":
        raise FundingFetchError(
            f"funding snapshot for {snapshot.inst_id} is {status}: {detail}"
        )
    for delta in range(1, _LOOKBACK_DAYS + 1):
        candidate = (day - timedelta(days=delta)).isoformat()
        if candidate in snapshot.rates:
            return snapshot.rates[candidate]
    raise FundingFetchError(
        f"funding snapshot for {snapshot.inst_id} is incomplete_historical_coverage: "
        f"no complete rate within {_LOOKBACK_DAYS} days before {day.isoformat()}"
    )


def funding_coverage_status(snapshot: _FundingSnapshot, dt: datetime) -> tuple[str, str]:
    """Classify coverage for a simulated timestamp without inferring a listing date."""
    _require_utc(dt, "dt")
    prior_day = dt.date() - timedelta(days=1)
    if prior_day >= snapshot.first_available.date():
        return "complete_covered_period", "first available funding precedes the required day"
    evidence = snapshot.coverage_evidence
    if evidence is None:
        return "truncated_snapshot", "unavailable_evidence"
    try:
        evidence.validate(snapshot.inst_id, "OKX")
    except CoverageEvidenceError as exc:
        return "malformed_snapshot", str(exc)
    if dt < evidence.series_start:
        return "proven_pre_listing", evidence.validity_rule
    return "incomplete_historical_coverage", "evidence does not establish pre-listing"


def funding_coverage_manifest(snapshot: _FundingSnapshot, start: datetime) -> dict[str, str]:
    """Return immutable coverage identity for a manifest without querying the network."""
    status, detail = funding_coverage_status(snapshot, start)
    return coverage_manifest_record(snapshot.coverage_evidence, status, detail)


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
