"""
Historial de funding rates de OKX para backtesting.

OKX perpetual swaps liquidan funding cada 8 horas (00:00, 08:00, 16:00 UTC).
Este modulo descarga el historico completo al inicio del backtest y expone
get_funding_rate_at(dt) para que BacktestClient lo use en lugar de devolver 0.0.

Fuente: OKX public API — sin autenticacion requerida.
Endpoint: GET /api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=100

Paginacion: cursor-based via parametro 'after' (fundingTime en ms).
Degradacion silenciosa si OKX no responde: devuelve 0.0 (comportamiento anterior).
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from loguru import logger


_FUNDING_RATES: dict[str, float] = {}   # "YYYY-MM-DD" -> media de las 3 liquidaciones del dia
_LOADED_SYMBOL: str = ""

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible)"}
_OKX_URL  = "https://www.okx.com/api/v5/public/funding-rate-history"


# ---------------------------------------------------------------------------
# Fetch interno
# ---------------------------------------------------------------------------

def _fetch_page(inst_id: str, after_ms: int | None) -> list[dict]:
    """Descarga una pagina de hasta 100 registros de funding historico."""
    url = f"{_OKX_URL}?instId={inst_id}&limit=100"
    if after_ms is not None:
        url += f"&after={after_ms}"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if data.get("code") != "0":
            logger.debug("funding_context: OKX codigo={}", data.get("code"))
            return []
        return data.get("data", [])
    except Exception as exc:
        logger.debug("funding_context: error en pagina after={}: {}", after_ms, exc)
        return []


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def load_funding_history(symbol: str, from_dt: datetime, to_dt: datetime) -> None:
    """
    Descarga el historico de funding rates para 'symbol' en el rango dado.

    symbol: e.g. "BTC-USDT" → instId "BTC-USDT-SWAP"
    Llamar una vez antes de _run_backtest, igual que load_macro_context.

    OKX BTC-USDT-SWAP arranco en Oct/Nov 2018. Para backtests anteriores,
    los dias sin datos devuelven 0.0 (neutro — comportamiento anterior).
    """
    global _FUNDING_RATES, _LOADED_SYMBOL

    base    = symbol.split("-")[0].upper()
    inst_id = f"{base}-USDT-SWAP"

    if _LOADED_SYMBOL == inst_id:
        logger.debug("funding_context: cache vigente para {}", inst_id)
        return

    from_ms = int(from_dt.timestamp() * 1000)

    logger.info(
        "Descargando funding rate historico {} ({} -> {}) ...",
        inst_id, from_dt.date(), to_dt.date(),
    )

    daily_sums: dict[str, list[float]] = {}
    after_ms:   int | None = None
    pages       = 0

    while True:
        records = _fetch_page(inst_id, after_ms)
        if not records:
            break

        pages      += 1
        oldest_ms:  int | None = None

        for rec in records:
            try:
                ts_ms  = int(rec["fundingTime"])
                rate   = float(rec["fundingRate"])
                dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                ds     = dt_utc.date().isoformat()
                daily_sums.setdefault(ds, []).append(rate)
                if oldest_ms is None or ts_ms < oldest_ms:
                    oldest_ms = ts_ms
            except (KeyError, ValueError, OSError):
                continue

        # Parar cuando ya cubrimos el inicio solicitado
        if oldest_ms is None or oldest_ms <= from_ms:
            break

        after_ms = oldest_ms
        time.sleep(0.08)   # ~12 req/s — dentro del limite publico de OKX

    if not daily_sums:
        logger.warning(
            "funding_context: sin datos para {} — backtest usa funding=0.0 (sin filtro)",
            inst_id,
        )
        return

    _FUNDING_RATES   = {ds: sum(v) / len(v) for ds, v in daily_sums.items()}
    _LOADED_SYMBOL   = inst_id
    logger.info(
        "Funding rate: {} dias cargados ({} paginas)", len(_FUNDING_RATES), pages,
    )


def get_funding_rate_at(dt: datetime) -> float:
    """
    Devuelve la tasa de funding media del dia ANTERIOR completo.

    OKX liquida 3 veces al dia (00:00, 08:00, 16:00 UTC). El dict almacena la
    media de las 3 liquidaciones del dia. Una barra de, p.ej., las 04:00 UTC
    solo ha visto la liquidacion de las 00:00 — la media del dia completo
    incluiria las de las 08:00 y 16:00 que aun no han ocurrido.
    Para evitar lookahead usamos siempre delta>=1 (dia completo anterior).
    """
    if not _FUNDING_RATES:
        return 0.0
    d = dt.date()
    for delta in range(1, 6):
        candidate = (d - timedelta(days=delta)).isoformat()
        if candidate in _FUNDING_RATES:
            return _FUNDING_RATES[candidate]
    return 0.0
