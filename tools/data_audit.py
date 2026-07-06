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

import json
import urllib.request
from datetime import datetime, timezone

from data import ohlcv_cache
from data.market_data import OHLCVBar

# Salto de precio entre velas 1H por encima del cual se marca outlier (mismo espiritu que
# SwingAllocatorConfig.max_price_jump_pct = 0.25, algo mas laxo para no marcar crashes reales).
_JUMP_WARN = 0.30
_JUMP_HARD = 0.60


def _rows_to_bars(meta: dict) -> list[OHLCVBar]:
    from decimal import Decimal
    return [
        OHLCVBar(timestamp=int(r[0]), open=Decimal(r[1]), high=Decimal(r[2]),
                 low=Decimal(r[3]), close=Decimal(r[4]), volume=Decimal(r[5]))
        for r in meta.get("bars", [])
    ]


def _find_duplicates(bars: list[OHLCVBar]) -> list[int]:
    seen: set[int] = set()
    dups: list[int] = []
    for b in bars:
        if b.timestamp in seen:
            dups.append(b.timestamp)
        seen.add(b.timestamp)
    return dups


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


def _monotonic(bars: list[OHLCVBar]) -> int:
    """Numero de pares fuera de orden temporal (deberia ser 0: UTC ascendente)."""
    return sum(1 for a, b in zip(bars, bars[1:]) if b.timestamp <= a.timestamp)


def audit_cache(symbol: str = "BTC-USDT", bar: str = "1H") -> dict:
    """Audita el cache en disco. No red, no escritura."""
    meta = ohlcv_cache.load_meta(symbol, bar)
    if not meta:
        return {"symbol": symbol, "bar": bar, "exists": False,
                "error": "cache no encontrado (data/cache/<symbol>_<bar>.json)"}

    bars = _rows_to_bars(meta)
    n_gaps, max_gap = ohlcv_cache.contiguity_report(bars, bar)
    dups = _find_duplicates(bars)
    outliers = _find_outliers(bars)
    hard = [o for o in outliers if o["kind"] in ("high<low", "non-positive-price", "hard-jump")]
    lo = datetime.fromtimestamp(bars[0].timestamp / 1000, tz=timezone.utc) if bars else None
    hi = datetime.fromtimestamp(bars[-1].timestamp / 1000, tz=timezone.utc) if bars else None

    return {
        "symbol": symbol, "bar": bar, "exists": True,
        "complete": bool(meta.get("complete")),
        "n_bars": len(bars),
        "range": [lo.isoformat() if lo else None, hi.isoformat() if hi else None],
        "n_gaps": n_gaps, "max_gap_bars": max_gap,
        "n_duplicates": len(dups),
        "n_outliers": len(outliers),
        "n_hard_outliers": len(hard),
        "out_of_order_pairs": _monotonic(bars),
        "outlier_samples": outliers[:10],
        "clean": (n_gaps == 0 and not dups and not hard and _monotonic(bars) == 0),
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
        "n_duplicates": len(_find_duplicates(bars)),
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
            f"- Outliers: {cache['n_outliers']} (duros: {cache['n_hard_outliers']})",
            f"- Pares fuera de orden: {cache['out_of_order_pairs']}",
        ]
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
