"""Cache en disco de OHLCV historico para backtests DETERMINISTAS.

Problema que resuelve
---------------------
`fetch_historical_bars` truncaba la paginacion en silencio ante cualquier
transitorio de red (una pagina de OKX = 300 velas). Dos runs de la misma ventana
devolvian datasets distintos (ej. 96805 vs 97105 velas) y los backtests NO eran
reproducibles: el mismo default daba PF 2.40 en un run y 4.33 en otro.

Estrategia
----------
La primera descarga de un (symbol, bar) se persiste a disco como dataset
canonico junto con el RANGO solicitado (no el rango de los datos: OKX no tiene
BTC antes de ~2017, el dato empieza despues del `from` pedido). Runs posteriores
cuyo rango este cubierto se sirven por slice del archivo -> mismos bytes, mismo
resultado. Solo se cachean descargas marcadas como completas: un run truncado
por transitorio no congela el bug.

Formato en disco (JSON, Decimal como string para exactitud):
    {
      "symbol": "BTC-USDT", "bar": "1H",
      "range_from_ms": int, "range_to_ms": int, "complete": bool,
      "bars": [[ts_ms, "open", "high", "low", "close", "volume"], ...]
    }
"""
from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

from loguru import logger

from data.market_data import OHLCVBar

_CACHE_DIR = Path(__file__).resolve().parent / "cache"

# Gap tolerado antes de avisar de datos no contiguos (multiplos del bar).
_GAP_WARN_MULT = 3

_BAR_MS: dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1H": 3_600_000, "4H": 14_400_000, "1D": 86_400_000, "1W": 604_800_000,
}


def _cache_path(symbol: str, bar: str) -> Path:
    safe = symbol.replace("/", "-").replace("\\", "-")
    return _CACHE_DIR / f"{safe}_{bar}.json"


def load_meta(symbol: str, bar: str) -> dict | None:
    """Lee el cache de disco. Devuelve el dict crudo (con bars serializadas) o None."""
    path = _cache_path(symbol, bar)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("Cache OHLCV corrupto en {} ({}), se ignora", path, exc)
        return None


def _rows_to_bars(rows: list) -> list[OHLCVBar]:
    return [
        OHLCVBar(
            timestamp=int(r[0]),
            open=Decimal(r[1]), high=Decimal(r[2]),
            low=Decimal(r[3]), close=Decimal(r[4]), volume=Decimal(r[5]),
        )
        for r in rows
    ]


def _bars_to_rows(bars: list[OHLCVBar]) -> list:
    return [
        [b.timestamp, str(b.open), str(b.high), str(b.low), str(b.close), str(b.volume)]
        for b in bars
    ]


def covers(meta: dict | None, from_ms: int, to_ms: int) -> bool:
    """True si el cache es completo y su rango solicitado cubre [from_ms, to_ms]."""
    if not meta or not meta.get("complete"):
        return False
    return meta.get("range_from_ms", 1 << 62) <= from_ms and meta.get("range_to_ms", 0) >= to_ms


def slice_range(bars: list[OHLCVBar], from_ms: int, to_ms: int) -> list[OHLCVBar]:
    """Barras con from_ms <= ts <= to_ms (asume `bars` ordenada)."""
    return [b for b in bars if from_ms <= b.timestamp <= to_ms]


def contiguity_report(bars: list[OHLCVBar], bar: str) -> tuple[int, int]:
    """Devuelve (n_huecos, hueco_max_en_velas) para diagnostico. No filtra nada."""
    step = _BAR_MS.get(bar)
    if not step or len(bars) < 2:
        return (0, 0)
    n_gaps = 0
    max_gap = 0
    for prev, cur in zip(bars, bars[1:]):
        missing = (cur.timestamp - prev.timestamp) // step - 1
        if missing > _GAP_WARN_MULT:
            n_gaps += 1
            max_gap = max(max_gap, missing)
    return (n_gaps, max_gap)


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, path)  # atomico en Windows y POSIX
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def merge_and_save(
    symbol: str,
    bar: str,
    bars: list[OHLCVBar],
    from_ms: int,
    to_ms: int,
    complete: bool,
) -> list[OHLCVBar]:
    """
    Une `bars` con lo ya cacheado (dedup por timestamp), extiende el rango cubierto
    a la union, y persiste si `complete`. Devuelve la lista completa ya mergeada.

    Si `complete=False` (descarga truncada) NO escribe a disco: no congela un run malo.
    """
    existing = load_meta(symbol, bar)
    if existing:
        old_bars = _rows_to_bars(existing.get("bars", []))
        seen = {b.timestamp for b in bars}
        merged = bars + [b for b in old_bars if b.timestamp not in seen]
        merged.sort(key=lambda b: b.timestamp)
        new_from = min(existing.get("range_from_ms", from_ms), from_ms)
        new_to = max(existing.get("range_to_ms", to_ms), to_ms)
        new_complete = bool(existing.get("complete")) and complete
    else:
        merged = sorted(bars, key=lambda b: b.timestamp)
        new_from, new_to, new_complete = from_ms, to_ms, complete

    if not complete:
        logger.warning(
            "Descarga {}/{} incompleta — NO se cachea (evita congelar dataset truncado)",
            symbol, bar,
        )
        return merged

    n_gaps, max_gap = contiguity_report(merged, bar)
    if n_gaps:
        logger.warning(
            "Cache {}/{}: {} huecos (max {} velas) — outages reales de exchange, se cachea igual",
            symbol, bar, n_gaps, max_gap,
        )

    _atomic_write(_cache_path(symbol, bar), {
        "symbol": symbol, "bar": bar,
        "range_from_ms": new_from, "range_to_ms": new_to,
        "complete": new_complete,
        "bars": _bars_to_rows(merged),
    })
    logger.info(
        "Cache {}/{} guardado: {} velas, rango {}..{}",
        symbol, bar, len(merged), new_from, new_to,
    )
    return merged


def try_serve(symbol: str, bar: str, from_ms: int, to_ms: int) -> list[OHLCVBar] | None:
    """Sirve el rango desde cache si esta cubierto y completo. None si hay que descargar."""
    meta = load_meta(symbol, bar)
    if not covers(meta, from_ms, to_ms):
        return None
    bars = _rows_to_bars(meta["bars"])
    served = slice_range(bars, from_ms, to_ms)
    logger.info(
        "Cache HIT {}/{}: {} velas servidas de {} cacheadas (deterministico)",
        symbol, bar, len(served), len(bars),
    )
    return served
