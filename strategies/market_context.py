"""
Contexto de mercado global — DXY (índice dólar) y NASDAQ-100.

Usado como filtros NEGATIVOS en Pro Trend: cuando el dólar se fortalece rápido
o el NASDAQ entra en corrección severa, se bloquean nuevas entradas long
independientemente de la puntuación de la estrategia.

Patrón idéntico a macro_context.py:
  - Fetch único al inicio del backtest (load_market_context)
  - Cache global, consulta O(1) por fecha (get_market_context)
  - Degradación silenciosa si Yahoo Finance no responde

Fuente: Yahoo Finance API pública (sin autenticación, sin requests).
  DXY  → ^DXY  (ICE US Dollar Index)
  NDX  → ^NDX  (NASDAQ-100)
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from loguru import logger


# ---------------------------------------------------------------------------
# Caches globales {date_iso: close_price}
# ---------------------------------------------------------------------------
_DXY_PRICES: dict[str, float] = {}
_NDX_PRICES: dict[str, float] = {}
_VIX_PRICES: dict[str, float] = {}
_LOADED_FROM: datetime | None = None
_LOADED_TO:   datetime | None = None
_MANIFEST_ACCESSES: list[datetime] = []


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json,text/csv,*/*",
}


def _fetch_yahoo_json(symbol: str, p1: int, p2: int) -> dict[str, float]:
    """Intenta descargar via v8 JSON endpoint."""
    encoded = urllib.parse.quote(symbol)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?period1={p1}&period2={p2}&interval=1d"
    )
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=_HEADERS), timeout=20
    ) as resp:
        data = json.loads(resp.read())

    result     = data["chart"]["result"][0]
    timestamps = result["timestamp"]      # puede lanzar KeyError si la estructura cambia
    closes     = result["indicators"]["quote"][0]["close"]
    return {
        datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(): float(c)
        for ts, c in zip(timestamps, closes)
        if c is not None
    }


def _fetch_yahoo_csv(symbol: str, p1: int, p2: int) -> dict[str, float]:
    """Fallback: descarga via v7 CSV download (más estable para indices como ^DXY)."""
    import csv, io
    encoded = urllib.parse.quote(symbol)
    url = (
        f"https://query1.finance.yahoo.com/v7/finance/download/{encoded}"
        f"?period1={p1}&period2={p2}&interval=1d&events=history"
    )
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=_HEADERS), timeout=20
    ) as resp:
        text = resp.read().decode("utf-8")

    result: dict[str, float] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        date_str = row.get("Date", "")
        close    = row.get("Close") or row.get("Adj Close")
        if date_str and close:
            try:
                result[date_str] = float(close)
            except (ValueError, TypeError):
                pass
    return result


def _fetch_yahoo(symbol: str, from_dt: datetime, to_dt: datetime) -> dict[str, float]:
    """
    Descarga cierres diarios de Yahoo Finance.
    Intenta primero v8 JSON; si falla (estructura cambia frecuentemente), cae a v7 CSV.
    Devuelve dict vacío si ambos fallan (modo degradado).
    """
    p1 = int(from_dt.timestamp())
    p2 = int((to_dt + timedelta(days=1)).timestamp())

    try:
        prices = _fetch_yahoo_json(symbol, p1, p2)
        if prices:
            return prices
    except Exception as exc:
        logger.debug("market_context: v8 JSON falló para {} ({}), probando CSV...", symbol, exc)

    try:
        prices = _fetch_yahoo_csv(symbol, p1, p2)
        if prices:
            logger.debug("market_context: {} descargado via CSV fallback ({} sesiones)", symbol, len(prices))
            return prices
    except Exception as exc:
        logger.warning("market_context: error descargando {}: {}", symbol, exc)

    return {}


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def load_market_context(from_dt: datetime, to_dt: datetime) -> None:
    """
    Descarga DXY y NASDAQ para el período indicado + 30 días de margen.
    Llamar una vez antes de iniciar el backtest (como load_macro_context).
    Tiene guard anti-redundancia: no re-descarga si el rango ya está cubierto.
    """
    global _DXY_PRICES, _NDX_PRICES, _VIX_PRICES, _LOADED_FROM, _LOADED_TO, _MANIFEST_ACCESSES
    _MANIFEST_ACCESSES = []

    fetch_from = from_dt - timedelta(days=30)  # margen para el lookback

    if (
        _LOADED_FROM is not None
        and _LOADED_FROM <= fetch_from
        and _LOADED_TO is not None
        and _LOADED_TO >= to_dt
    ):
        logger.debug("market_context: cache vigente, omitiendo descarga.")
        return

    logger.info(
        "Descargando DXY, NASDAQ-100 y VIX ({} -> {}) ...",
        fetch_from.date(), to_dt.date(),
    )
    # ^DXY bloqueado en Yahoo Finance (401/estructura rota) — usar DX-Y.NYB (equivalente)
    _DXY_PRICES = _fetch_yahoo("DX-Y.NYB", fetch_from, to_dt)
    if not _DXY_PRICES:
        _DXY_PRICES = _fetch_yahoo("UUP", fetch_from, to_dt)  # ETF DXY como ultimo fallback
    _NDX_PRICES = _fetch_yahoo("^NDX", fetch_from, to_dt)
    _VIX_PRICES = _fetch_yahoo("^VIX", fetch_from, to_dt)

    if _DXY_PRICES:
        logger.info("DXY: {} sesiones descargadas", len(_DXY_PRICES))
    else:
        logger.warning("DXY no disponible — filtro de dólar desactivado")

    if _NDX_PRICES:
        logger.info("NASDAQ-100: {} sesiones descargadas", len(_NDX_PRICES))
    else:
        logger.warning("NASDAQ-100 no disponible — filtro de riesgo desactivado")

    if _VIX_PRICES:
        logger.info("VIX: {} sesiones descargadas", len(_VIX_PRICES))
    else:
        logger.warning("VIX no disponible — filtro de panico desactivado")

    _LOADED_FROM = fetch_from
    _LOADED_TO   = to_dt


def get_market_context(
    dt: datetime,
    lookback_days:  int   = 10,
    dxy_threshold:  float = 1.5,
    ndx_threshold:  float = -5.0,
) -> dict:
    """
    Devuelve el contexto de mercado global para la fecha dada.

    Returns:
        dxy_headwind  bool         DXY subió > dxy_threshold% en lookback_days → adverso para BTC
        risk_off      bool         NASDAQ bajó > |ndx_threshold|% → entorno risk-off
        dxy_change    float|None   % cambio de DXY en el período
        ndx_change    float|None   % cambio de NASDAQ en el período
        vix_level     float|None   Nivel absoluto del VIX (cierre del día)
        vix_extreme   bool         VIX > 35 → pánico real, bloquear entradas
        vix_elevated  bool         VIX > 22 → miedo elevado, exigir más confirmación
    """
    _MANIFEST_ACCESSES.append(dt)
    date_str = dt.date().isoformat()

    def _spot(prices: dict[str, float]) -> float | None:
        """Cierre de la sesion mas reciente disponible, empezando en el dia anterior.

        VIX cierra a las 21:15 UTC; DXY/NDX a las 22:00 UTC. Una barra 1H de
        cualquier hora del dia corriente no puede haber visto ese cierre aun,
        por lo que siempre se usa delta>=1 (sesion anterior) para evitar lookahead.
        """
        if not prices:
            return None
        d = dt.date()
        for delta in range(1, 6):
            candidate = (d - timedelta(days=delta)).isoformat()
            if candidate in prices:
                return prices[candidate]
        return None

    def _pct(prices: dict[str, float], target: str, lookback: int) -> float | None:
        if not prices:
            return None
        # Resolver fecha mas cercana empezando en el dia anterior (evitar lookahead)
        d = dt.date()
        actual: str | None = None
        for delta in range(1, 5):
            candidate = (d - timedelta(days=delta)).isoformat()
            if candidate in prices:
                actual = candidate
                break
        if actual is None:
            return None

        dates = sorted(prices.keys())
        idx   = dates.index(actual)
        if idx < lookback:
            return None
        past = dates[idx - lookback]
        base = prices[past]
        if base == 0:
            return None
        return (prices[actual] - base) / base * 100

    dxy_chg = _pct(_DXY_PRICES, date_str, lookback_days)
    ndx_chg = _pct(_NDX_PRICES, date_str, lookback_days)
    vix_val = _spot(_VIX_PRICES)

    return {
        "dxy_headwind": bool(dxy_chg is not None and dxy_chg >  dxy_threshold),
        "risk_off":     bool(ndx_chg is not None and ndx_chg <  ndx_threshold),
        "dxy_change":   round(dxy_chg, 2) if dxy_chg is not None else None,
        "ndx_change":   round(ndx_chg, 2) if ndx_chg is not None else None,
        "vix_level":    round(vix_val, 1)  if vix_val is not None else None,
        "vix_extreme":  bool(vix_val is not None and vix_val > 35),
        "vix_elevated": bool(vix_val is not None and vix_val > 22),
    }
