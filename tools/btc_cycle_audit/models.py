"""Immutable-ish schemas for the Bitcoin phase audit.

The audit deliberately uses JSON-compatible records and hashes every source
snapshot.  No object in this package is consumed by the live strategy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class HalvingRecord:
    block_height: int
    block_hash: str
    block_timestamp_utc: str
    confirmation_source: str
    secondary_sources: tuple[str, ...]
    retrieved_at: str
    dataset_hash: str
    status: str = "CONFIRMED"


@dataclass(frozen=True)
class PriceBar:
    source: str
    timestamp_utc: str
    open: str
    high: str
    low: str
    close: str
    volume: str | None
    interval: str = "1d"
    retrieved_at: str = ""
    revision: int = 1

    def validate(self) -> list[str]:
        errors: list[str] = []
        try:
            o, h, low_value, c = (Decimal(v) for v in (self.open, self.high, self.low, self.close))
            if min(o, h, low_value, c) <= 0 or h < max(o, low_value, c) or low_value > min(o, h, c):
                errors.append("impossible_ohlc")
        except Exception:
            errors.append("non_numeric_ohlc")
        if self.volume is not None:
            try:
                if Decimal(self.volume) < 0:
                    errors.append("negative_volume")
            except Exception:
                errors.append("non_numeric_volume")
        return errors


@dataclass(frozen=True)
class SourceSnapshot:
    source: str
    interval: str
    coverage_start_utc: str | None
    coverage_end_utc: str | None
    rows: int
    dataset_hash: str
    retrieved_at: str
    status: str
    errors: tuple[str, ...] = ()
    revisions: int = 0


@dataclass(frozen=True)
class CycleExtreme:
    cycle: str
    kind: str
    method: str
    timestamp_utc: str
    price: str
    days_since_halving: int
    status: str
    source: str


@dataclass(frozen=True)
class BoundaryStats:
    boundary: int
    observations: tuple[int, ...]
    center_median: float | None
    mean: float | None
    mad: float | None
    stdev: float | None
    min_error: int | None
    max_error: int | None
    mean_absolute_error: float | None
    sample_size: int
    confidence: str
    verdict: str


def record_dict(record: Any) -> dict[str, Any]:
    return asdict(record)
