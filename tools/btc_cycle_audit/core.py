"""Pure calculations for cycle labels, consensus, statistics, and causal state."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .models import BoundaryStats, CycleExtreme, PriceBar


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_records(records: Iterable[object]) -> str:
    return sha256_bytes(canonical_json(list(records)))


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(timezone.utc)


def day_key(value: str | datetime) -> date:
    if isinstance(value, str) and len(value) == 10:
        return date.fromisoformat(value)
    return parse_utc(value).date()


def days_since(halving: str | date, observed: str | date) -> int:
    h = halving if isinstance(halving, date) else day_key(halving)
    o = observed if isinstance(observed, date) else day_key(observed)
    return (o - h).days


def validate_bars(bars: Iterable[PriceBar], stale_after_days: int = 3) -> tuple[list[str], dict[str, int]]:
    rows = list(bars)
    errors: list[str] = []
    counts = {"duplicates": 0, "gaps": 0, "impossible": 0, "stale": 0}
    seen: set[tuple[str, str]] = set()
    by_source: dict[str, list[PriceBar]] = defaultdict(list)
    for bar in rows:
        key = (bar.source, bar.timestamp_utc)
        if key in seen:
            counts["duplicates"] += 1
        seen.add(key)
        bad = bar.validate()
        counts["impossible"] += len(bad)
        errors.extend(f"{bar.source}:{bar.timestamp_utc}:{item}" for item in bad)
        by_source[bar.source].append(bar)
    for source, source_rows in by_source.items():
        dates = sorted({day_key(row.timestamp_utc) for row in source_rows})
        for left, right in zip(dates, dates[1:]):
            if (right - left).days > 1:
                counts["gaps"] += (right - left).days - 1
                errors.append(f"{source}:{left}:{right}:gap")
    if rows:
        latest = max(day_key(row.timestamp_utc) for row in rows)
        if (datetime.now(timezone.utc).date() - latest).days > stale_after_days:
            counts["stale"] = 1
            errors.append(f"latest_data_stale:{latest}")
    return errors, counts


def consensus_daily(bars: Iterable[PriceBar], tolerance_days: int = 3) -> list[dict]:
    by_day: dict[date, list[PriceBar]] = defaultdict(list)
    for bar in bars:
        if bar.interval == "1d":
            by_day[day_key(bar.timestamp_utc)].append(bar)
    output: list[dict] = []
    for d in sorted(by_day):
        rows = by_day[d]
        closes = [Decimal(row.close) for row in rows]
        highs = [Decimal(row.high) for row in rows]
        lows = [Decimal(row.low) for row in rows]
        median_close = statistics.median(closes)
        dispersion = (max(closes) - min(closes)) / median_close if median_close else Decimal("0")
        status = "CONFIRMED" if len(rows) >= 3 and dispersion <= Decimal("0.01") else "PROVISIONAL"
        if len(rows) < 2:
            status = "INSUFFICIENT_COVERAGE"
        elif dispersion > Decimal("0.02"):
            status = "SOURCE_DISAGREEMENT"
        output.append({
            "date_utc": d.isoformat(),
            "median_close": str(median_close),
            "minimum_low": str(min(lows)),
            "maximum_high": str(max(highs)),
            "minimum_close": str(min(closes)),
            "maximum_close": str(max(closes)),
            "dispersion_pct": str(dispersion * 100),
            "available_sources": sorted({row.source for row in rows}),
            "source_count": len(rows),
            "confidence_status": status,
        })
    return output


def _extreme(rows: list[dict], field: str, mode: str) -> dict:
    return (max if mode == "max" else min)(rows, key=lambda row: Decimal(row[field]))


def retrospective_extremes(
    consensus: list[dict], halvings: list[dict], *, include_incomplete: bool = True
) -> list[CycleExtreme]:
    result: list[CycleExtreme] = []
    for index, halving in enumerate(halvings[:-1] if not include_incomplete else halvings):
        start = date.fromisoformat(halving["block_timestamp_utc"][:10])
        end = date.fromisoformat(halvings[index + 1]["block_timestamp_utc"][:10]) if index + 1 < len(halvings) else None
        rows = [row for row in consensus if date.fromisoformat(row["date_utc"]) >= start and (end is None or date.fromisoformat(row["date_utc"]) < end)]
        if not rows:
            continue
        if date.fromisoformat(rows[0]["date_utc"]) > start:
            # Do not turn a partially covered early cycle into a false extreme.
            continue
        cycle = f"{start.year}_cycle"
        top_close = _extreme(rows, "maximum_close", "max")
        top_intraday = _extreme(rows, "maximum_high", "max")
        top_day = date.fromisoformat(top_close["date_utc"])
        after_top = [row for row in rows if date.fromisoformat(row["date_utc"]) >= top_day]
        bottom_close = _extreme(after_top, "minimum_close", "min")
        bottom_intraday = _extreme(after_top, "minimum_low", "min")
        for kind, method, row, field in (
            ("top", "close", top_close, "maximum_close"),
            ("top", "intraday", top_intraday, "maximum_high"),
            ("bottom", "close", bottom_close, "minimum_close"),
            ("bottom", "intraday", bottom_intraday, "minimum_low"),
        ):
            result.append(CycleExtreme(cycle, kind, method, row["date_utc"] + "T00:00:00Z", row[field], days_since(start, row["date_utc"]), "PROVISIONAL" if end is None else "RETROSPECTIVE", "canonical_consensus"))
    return result


def causal_confirmations(
    rows: list[dict], *, drawdown_pct: Decimal = Decimal("0.20"), recovery_pct: Decimal = Decimal("0.20"), confirmation_days: int = 60
) -> list[dict]:
    """One-pass causal state machine; only rows at or before confirmation are used."""
    if not rows:
        return []
    peak = Decimal(rows[0]["maximum_high"])
    peak_date = rows[0]["date_utc"]
    confirmed_top: dict | None = None
    trough = Decimal(rows[0]["minimum_low"])
    trough_date = rows[0]["date_utc"]
    output: list[dict] = []
    for i, row in enumerate(rows):
        high = Decimal(row["maximum_high"])
        low = Decimal(row["minimum_low"])
        if high >= peak:
            peak, peak_date = high, row["date_utc"]
        if confirmed_top is None and low <= peak * (Decimal("1") - drawdown_pct):
            peak_index = next((j for j, x in enumerate(rows[: i + 1]) if x["date_utc"] == peak_date), i)
            if i - peak_index >= confirmation_days:
                confirmed_top = {"timestamp_utc": peak_date, "confirmed_at": row["date_utc"], "price": str(peak)}
        if confirmed_top is not None:
            if low < trough:
                trough, trough_date = low, row["date_utc"]
            if high >= trough * (Decimal("1") + recovery_pct):
                output.append({"type": "bottom", "timestamp_utc": trough_date, "confirmed_at": row["date_utc"], "price": str(trough)})
                break
    if confirmed_top:
        output.insert(0, {"type": "top", **confirmed_top})
    return output


def boundary_stats(days: Iterable[int], boundary: int, *, modern: bool = False) -> BoundaryStats:
    values = list(days)
    errors = [value - boundary for value in values]
    if not errors:
        return BoundaryStats(boundary, (), None, None, None, None, None, None, None, 0, "VERY_LOW", "INSUFFICIENT_EVIDENCE")
    med = statistics.median(errors)
    mad = statistics.median([abs(value - med) for value in errors])
    stdev = statistics.stdev(errors) if len(errors) > 1 else 0.0
    confidence = "VERY_LOW" if len(errors) < 4 else ("LOW" if len(errors) < 6 else "MEDIUM")
    verdict = "SUPPORTED_AS_APPROXIMATE_CENTER" if len(errors) >= 2 and abs(med) <= 60 else "INSUFFICIENT_EVIDENCE"
    return BoundaryStats(boundary, tuple(errors), med, statistics.mean(errors), mad, stdev, min(errors), max(errors), statistics.mean([abs(e) for e in errors]), len(errors), confidence, verdict)


def bootstrap_centers(values: list[int], boundary: int, iterations: int = 2000, seed: int = 42) -> dict:
    if not values:
        return {"sample_size": 0, "center": None, "lower": None, "upper": None, "seed": seed}
    rng = __import__("random").Random(seed)
    centers = [statistics.median([rng.choice(values) for _ in values]) for _ in range(iterations)]
    centers.sort()
    return {"sample_size": len(values), "center": statistics.median(values), "lower": centers[int(iterations * .025)], "upper": centers[int(iterations * .975)], "seed": seed, "boundary": boundary}


def immutable_snapshot(path: Path, payload: dict) -> str:
    data = canonical_json(payload)
    digest = sha256_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = path.read_bytes()
        if old != data:
            raise FileExistsError(f"immutable snapshot already exists: {path}")
    else:
        path.write_bytes(data)
    return digest
