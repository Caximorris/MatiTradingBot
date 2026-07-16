"""Auditoria de integridad de datos OHLCV (plan T7.1).

READ-ONLY y DETERMINISTA: nunca re-descarga ni reescribe el cache canonico (regla 4). Audita
el fichero de cache versionado (data/cache/<symbol>_<bar>.json) buscando:
  - huecos de vela (contiguidad)      -> reusa ohlcv_cache.contiguity_report
  - timestamps duplicados
  - velas imposibles / outliers (high<low, precios <=0, saltos absurdos entre velas)
  - orden temporal / monotonia (proxy de consistencia de timezone: todo UTC ascendente)
  - rango cubierto                    -> reusa report_common.cache_bounds

Opcional `--live`: trae UNA pagina reciente del endpoint publico de OKX (sin persistir, sin
tocar el cache) para chequear frescura y huecos/dups de las velas que veria el bot en vivo.

La comparacion cross-exchange (OKX vs Binance/Kraken) es research/audit-only y vive aparte
(plan T7.2, no implementado aqui).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone

from data import ohlcv_cache
from data.market_data import OHLCVBar

# Salto de precio entre velas 1H por encima del cual se marca outlier (mismo espiritu que
# SwingAllocatorConfig.max_price_jump_pct = 0.25, algo mas laxo para no marcar crashes reales).
_JUMP_WARN = 0.30
_JUMP_HARD = 0.60
_DATASET_IDENTITY_SCHEMA = 1


def _rows_to_bars(meta: dict) -> list[OHLCVBar]:
    from decimal import Decimal
    return [
        OHLCVBar(timestamp=int(r[0]), open=Decimal(r[1]), high=Decimal(r[2]),
                 low=Decimal(r[3]), close=Decimal(r[4]), volume=Decimal(r[5]))
        for r in meta.get("bars", [])
    ]


def _bar_record(bar: OHLCVBar) -> tuple[int, str, str, str, str, str]:
    return (
        int(bar.timestamp), str(bar.open), str(bar.high), str(bar.low),
        str(bar.close), str(bar.volume),
    )


def _duplicate_summary(bars: list[OHLCVBar]) -> dict:
    by_timestamp: dict[int, list[tuple[int, str, str, str, str, str]]] = {}
    seen_rows: set[tuple[int, str, str, str, str, str]] = set()
    exact_rows = 0
    for bar in bars:
        record = _bar_record(bar)
        if record in seen_rows:
            exact_rows += 1
        seen_rows.add(record)
        by_timestamp.setdefault(record[0], []).append(record)

    collisions = {
        timestamp: records for timestamp, records in by_timestamp.items()
        if len(records) > 1
    }
    conflicting = {
        timestamp: records for timestamp, records in collisions.items()
        if len(set(records)) > 1
    }
    samples = [
        {
            "timestamp_utc": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat(),
            "rows": len(records),
            "classification": "conflicting_timestamp_collision"
            if timestamp in conflicting else "identical_ohlcv_duplicate",
        }
        for timestamp, records in sorted(collisions.items())[:10]
    ]
    return {
        "timestamp_collisions": sum(len(records) - 1 for records in collisions.values()),
        "identical_ohlcv_rows": exact_rows,
        "conflicting_timestamp_rows": sum(len(records) - 1 for records in conflicting.values()),
        "samples": samples,
    }


def _find_outliers(bars: list[OHLCVBar]) -> list[dict]:
    out: list[dict] = []
    prev_close = None
    for b in bars:
        o, h, l, c = float(b.open), float(b.high), float(b.low), float(b.close)
        iso = datetime.fromtimestamp(b.timestamp / 1000, tz=timezone.utc).isoformat()
        if h < l:
            out.append({"ts": iso, "kind": "high<low", "detail": f"h={h} l={l}"})
        if min(o, h, l, c) <= 0:
            out.append({"ts": iso, "kind": "non-positive-price", "detail": f"ohlc={o},{h},{l},{c}"})
        if prev_close and prev_close > 0:
            jump = abs(c - prev_close) / prev_close
            if jump >= _JUMP_HARD:
                out.append({"ts": iso, "kind": "hard-jump",
                            "detail": f"{jump*100:.0f}% vs prev close"})
            elif jump >= _JUMP_WARN:
                out.append({"ts": iso, "kind": "jump",
                            "detail": f"{jump*100:.0f}% vs prev close"})
        prev_close = c
    return out


def _ordering_summary(bars: list[OHLCVBar]) -> dict:
    """Return non-increasing and strictly descending timestamp defects."""
    non_increasing = 0
    descending = 0
    samples: list[dict] = []
    for index, (previous, current) in enumerate(zip(bars, bars[1:]), start=1):
        if current.timestamp > previous.timestamp:
            continue
        non_increasing += 1
        if current.timestamp < previous.timestamp:
            descending += 1
            kind = "descending_timestamp"
        else:
            kind = "repeated_timestamp"
        if len(samples) < 10:
            samples.append({
                "row_index": index,
                "previous_utc": datetime.fromtimestamp(
                    previous.timestamp / 1000, tz=timezone.utc
                ).isoformat(),
                "current_utc": datetime.fromtimestamp(
                    current.timestamp / 1000, tz=timezone.utc
                ).isoformat(),
                "kind": kind,
            })
    return {
        "non_increasing_pairs": non_increasing,
        "descending_pairs": descending,
        "samples": samples,
    }


def dataset_identity(meta: dict, bars: list[OHLCVBar]) -> dict:
    """Return a deterministic, content-addressed identity without writing data."""
    rows = [_bar_record(bar) for bar in bars]
    content = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamps = json.dumps([row[0] for row in rows], separators=(",", ":")).encode("utf-8")
    first_timestamp = min((row[0] for row in rows), default=None)
    last_timestamp = max((row[0] for row in rows), default=None)
    fingerprint = hashlib.sha256(content).hexdigest()
    return {
        "schema_version": _DATASET_IDENTITY_SCHEMA,
        "dataset_version": f"ohlcv-v{_DATASET_IDENTITY_SCHEMA}-{fingerprint[:12]}",
        "content_sha256": fingerprint,
        "timestamps_sha256": hashlib.sha256(timestamps).hexdigest(),
        "symbol": str(meta.get("symbol", "")),
        "bar": str(meta.get("bar", "")),
        "complete": bool(meta.get("complete")),
        "row_count": len(rows),
        "distinct_timestamp_count": len({row[0] for row in rows}),
        "coverage": {
            "first_timestamp_ms": first_timestamp,
            "last_timestamp_ms": last_timestamp,
            "first_utc": _timestamp_iso(first_timestamp),
            "last_utc": _timestamp_iso(last_timestamp),
        },
    }


def _timestamp_iso(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _comparability(identity: dict, duplicates: dict, ordering: dict, hard_outliers: int) -> dict:
    warnings = [
        "Compare runs only when symbol, bar, and dataset_version are identical."
    ]
    if not identity["complete"]:
        warnings.append("Cache coverage is incomplete; results are not comparable to complete-cache runs.")
    if duplicates["identical_ohlcv_rows"]:
        warnings.append(
            "Identical OHLCV duplicates are retained; duplicate count and dataset_version must match."
        )
    if duplicates["conflicting_timestamp_rows"]:
        warnings.append("Conflicting timestamp collisions invalidate result comparability.")
    if ordering["descending_pairs"]:
        warnings.append("Descending timestamps invalidate result comparability.")
    if hard_outliers:
        warnings.append("Hard OHLCV anomalies invalidate result comparability pending investigation.")

    blocking = (
        not identity["complete"]
        or duplicates["conflicting_timestamp_rows"] > 0
        or ordering["descending_pairs"] > 0
        or hard_outliers > 0
    )
    return {
        "status": "NOT_COMPARABLE" if blocking else "MATCH_DATASET_VERSION_REQUIRED",
        "warnings": warnings,
    }


def audit_cache(symbol: str = "BTC-USDT", bar: str = "1H") -> dict:
    """Audita el cache en disco. No red, no escritura."""
    meta = ohlcv_cache.load_meta(symbol, bar)
    if not meta:
        return {"symbol": symbol, "bar": bar, "exists": False,
                "error": "cache no encontrado (data/cache/<symbol>_<bar>.json)"}

    bars = _rows_to_bars(meta)
    n_gaps, max_gap = ohlcv_cache.contiguity_report(bars, bar)
    duplicates = _duplicate_summary(bars)
    ordering = _ordering_summary(bars)
    outliers = _find_outliers(bars)
    hard = [o for o in outliers if o["kind"] in ("high<low", "non-positive-price", "hard-jump")]
    identity = dataset_identity(meta, bars)
    comparability = _comparability(identity, duplicates, ordering, len(hard))

    return {
        "symbol": symbol, "bar": bar, "exists": True,
        "complete": bool(meta.get("complete")),
        "n_bars": len(bars),
        "range": [identity["coverage"]["first_utc"], identity["coverage"]["last_utc"]],
        "n_gaps": n_gaps, "max_gap_bars": max_gap,
        "n_duplicates": duplicates["timestamp_collisions"],
        "duplicate_summary": duplicates,
        "n_outliers": len(outliers),
        "n_hard_outliers": len(hard),
        "out_of_order_pairs": ordering["non_increasing_pairs"],
        "ordering_summary": ordering,
        "outlier_samples": outliers[:10],
        "dataset_identity": identity,
        "comparability": comparability,
        "read_only": True,
        "clean": (
            n_gaps == 0
            and duplicates["timestamp_collisions"] == 0
            and not hard
            and ordering["non_increasing_pairs"] == 0
        ),
    }


def audit_recent_okx(symbol: str = "BTC-USDT", bar: str = "1H",
                     limit: int = 100, timeout: int = 10) -> dict:
    """Trae la ultima pagina publica de OKX (sin persistir) y la audita. Chequea frescura.

    NO usa fetch_historical_bars (eso mutaria el cache). Llamada directa read-only."""
    url = (f"https://www.okx.com/api/v5/market/candles"
           f"?instId={symbol}&bar={bar}&limit={limit}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows = data.get("data", [])
    except Exception as exc:
        return {"live": True, "ok": False, "error": str(exc)}

    from decimal import Decimal
    # OKX devuelve mas nuevo->mas viejo; [ts, o, h, l, c, vol, ...]
    bars = sorted(
        (OHLCVBar(timestamp=int(r[0]), open=Decimal(r[1]), high=Decimal(r[2]),
                  low=Decimal(r[3]), close=Decimal(r[4]), volume=Decimal(r[5]))
         for r in rows),
        key=lambda b: b.timestamp,
    )
    if not bars:
        return {"live": True, "ok": False, "error": "sin velas devueltas"}
    n_gaps, max_gap = ohlcv_cache.contiguity_report(bars, bar)
    last = datetime.fromtimestamp(bars[-1].timestamp / 1000, tz=timezone.utc)
    age_min = (datetime.now(timezone.utc) - last).total_seconds() / 60
    step_min = ohlcv_cache._BAR_MS.get(bar, 3_600_000) / 60_000
    return {
        "live": True, "ok": True, "n_bars": len(bars),
        "last_candle": last.isoformat(),
        "age_min": round(age_min, 1),
        "stale": age_min > step_min * 2,   # >2 barras sin actualizar = sospechoso
        "n_gaps": n_gaps, "max_gap_bars": max_gap,
        "n_duplicates": _duplicate_summary(bars)["timestamp_collisions"],
    }


def format_report(cache: dict, live: dict | None = None) -> str:
    lines = ["# Data Audit (OHLCV)", ""]
    if not cache.get("exists"):
        lines.append(f"CACHE: {cache.get('error')}")
    else:
        verdict = "LIMPIO" if cache["clean"] else "REVISAR"
        lines += [
            f"## Cache {cache['symbol']}/{cache['bar']} - **{verdict}**",
            f"- Velas: {cache['n_bars']:,} | completo: {cache['complete']}",
            f"- Rango: {(cache['range'][0] or '?')[:10]} -> {(cache['range'][1] or '?')[:10]}",
            f"- Huecos (>3 velas): {cache['n_gaps']} (max {cache['max_gap_bars']} velas)",
            f"- Duplicados: {cache['n_duplicates']}",
            "  "
            f"(filas identicas: {cache['duplicate_summary']['identical_ohlcv_rows']}; "
            f"colisiones conflictivas: {cache['duplicate_summary']['conflicting_timestamp_rows']})",
            f"- Outliers: {cache['n_outliers']} (duros: {cache['n_hard_outliers']})",
            f"- Pares fuera de orden: {cache['out_of_order_pairs']}",
            f"  (descendentes: {cache['ordering_summary']['descending_pairs']})",
            f"- Dataset: {cache['dataset_identity']['dataset_version']}",
            f"- Fingerprint SHA-256: {cache['dataset_identity']['content_sha256']}",
            f"- Comparabilidad: **{cache['comparability']['status']}**",
        ]
        for warning in cache["comparability"]["warnings"]:
            lines.append(f"    - AVISO: {warning}")
        for o in cache.get("outlier_samples", []):
            lines.append(f"    - {o['ts'][:16]} {o['kind']}: {o['detail']}")
    if live is not None:
        lines += ["", "## Velas recientes OKX (en vivo, no cacheadas)"]
        if not live.get("ok"):
            lines.append(f"- fallo: {live.get('error')}")
        else:
            lines += [
                f"- Ultima vela: {live['last_candle'][:16]} (hace {live['age_min']} min) "
                f"{'STALE' if live['stale'] else 'fresca'}",
                f"- Velas: {live['n_bars']} | huecos: {live['n_gaps']} | "
                f"dups: {live['n_duplicates']}",
            ]
    return "\n".join(lines)
