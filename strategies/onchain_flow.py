"""
On-chain exchange-reserve overlay for Swing Allocator v6 research (EXP-014 candidate).

Fuente: CoinMetrics Community API (gratuita, sin auth) — `SplyExNtv` (BTC nativo
manteniendose en exchanges conocidos). Historico completo verificado empiricamente
2026-07-14: cubre 2015-01-01 -> hoy, sin necesidad de clave (a diferencia del
funding de OKX, que solo retiene ~3 meses — ver docs/income/plan.md).

Hipotesis: reservas de exchange CAYENDO con fuerza (ROC 30d trailing en percentil
bajo) = holders retirando BTC a cold storage = menos oferta liquida = señal de
acumulacion. Reservas SUBIENDO con fuerza = señal de distribucion (coins moviendose
hacia exchanges, tipicamente para vender). Estructuralmente distinto de todo lo
probado en EXP-011/012/013 (esos eran timing de precio o funding de perps) — este
es un proxy de comportamiento on-chain de holders, no de precio ni de derivados.

CAVEAT: CoinMetrics marca estos valores como "flash" (preliminares, sujetos a
revision) — el backtest usa el valor ACTUAL (ya revisado), que puede diferir del
valor que habria estado disponible en tiempo real en esa fecha. Limitacion conocida,
igual de aplicable a MVRV en `macro_context.py` (no se ha auditado alli tampoco).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pandas as pd
from loguru import logger

_CM_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
_CM_ASSETS: dict[str, str] = {"BTC": "btc", "ETH": "eth"}


def fetch_exchange_reserve(symbol: str, from_dt: datetime, to_dt: datetime
                            ) -> list[tuple[int, float]]:
    """Descarga `SplyExNtv` diario de CoinMetrics. [] si falla (degradacion silenciosa,
    igual que macro_context.py)."""
    asset = _CM_ASSETS.get(symbol.split("-")[0].upper(), "btc")
    url = (
        f"{_CM_URL}?assets={asset}&metrics=SplyExNtv&frequency=1d&page_size=10000"
        f"&start_time={from_dt.strftime('%Y-%m-%d')}&end_time={to_dt.strftime('%Y-%m-%d')}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MatiTradingBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode())
        out: list[tuple[int, float]] = []
        for row in raw.get("data", []):
            v = row.get("SplyExNtv")
            if v is None:
                continue
            t = row.get("time", "")[:10]
            ts_ms = int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp() * 1000)
            out.append((ts_ms, float(v)))
        return sorted(out)
    except urllib.error.URLError as exc:
        logger.warning("onchain_flow: no se pudo conectar a CoinMetrics ({}).", exc.reason)
        return []
    except Exception as exc:
        logger.warning("onchain_flow: error al cargar SplyExNtv ({}).", exc)
        return []


# ---------------------------------------------------------------------------
# Senales (puras, testeables)
# ---------------------------------------------------------------------------

def build_roc_series(rows: list[tuple[int, float]], window_days: int = 30
                      ) -> list[tuple[int, float]]:
    """[(ts_ms, roc)] — cambio porcentual de la reserva vs `window_days` atras.
    roc < 0: reservas cayendo (posible acumulacion). roc > 0: reservas subiendo."""
    if len(rows) < window_days + 2:
        return []
    df = pd.DataFrame(sorted(rows), columns=["ts", "level"])
    roc = df["level"].pct_change(window_days)
    return [(int(ts), float(r)) for ts, r in zip(df["ts"], roc) if not pd.isna(r)]


def build_flow_overlay_events(
    roc_rows: list[tuple[int, float]],
    pctile_window: int = 180,
    low_pctile: float = 0.10,
    high_pctile: float = 0.90,
    dedup_days: int = 7,
    ttl_days: int = 7,
) -> pd.DataFrame:
    """Eventos por percentil trailing del ROC (mismo patron que swing_funding_overlay).
    Umbral shift(1): el dia t se compara contra los `pctile_window` dias ANTERIORES."""
    if len(roc_rows) < pctile_window + 2:
        return _empty_events()

    df = pd.DataFrame(sorted(roc_rows), columns=["ts", "roc"])
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    r = df["roc"]
    df["low_threshold"] = r.rolling(pctile_window).quantile(low_pctile).shift(1)
    df["high_threshold"] = r.rolling(pctile_window).quantile(high_pctile).shift(1)
    df["signal"] = ""
    df.loc[r < df["low_threshold"], "signal"] = "reserve_falling"
    df.loc[r > df["high_threshold"], "signal"] = "reserve_rising"

    events = df[df["signal"] != ""].copy()
    if events.empty:
        return _empty_events()

    events = _deduplicate(events, dedup_days)
    events["expires_at"] = events["dt"] + pd.to_timedelta(ttl_days, unit="D")
    return events[["ts", "dt", "expires_at", "roc", "signal"]].reset_index(drop=True)


def _deduplicate(events: pd.DataFrame, dedup_days: int) -> pd.DataFrame:
    keep = []
    last_by_signal: dict[str, pd.Timestamp] = {}
    gap = pd.to_timedelta(dedup_days, unit="D")
    for row in events.sort_values("dt").itertuples():
        last = last_by_signal.get(row.signal)
        if last is not None and row.dt - last < gap:
            continue
        keep.append(row.Index)
        last_by_signal[row.signal] = row.dt
    return events.loc[keep].reset_index(drop=True)


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts", "dt", "expires_at", "roc", "signal"])


# ---------------------------------------------------------------------------
# Contexto para backtest/live — carga unica, consulta por fecha
#
# EXP-014 (ver EXPERIMENTS.md): la hipotesis DIRECCIONAL (reserva cayendo=bullish,
# subiendo=bearish) se probo y se rechazo (inconsistente entre ventanas ROC). Lo que
# SI se sostuvo, robusto en 4 ventanas ROC distintas con 11/11 anios de consistencia,
# es que un pico de reserva/stablecoin en percentil alto (p90) precede volatilidad
# realizada 14d elevada — sin importar la direccion. Por eso `flow_vol_adjustment_at`
# solo reacciona al lado "rising" (spike) y aplica un delta NEGATIVO (reduce riesgo),
# nunca un delta positivo por el lado "falling" (esa mitad de la hipotesis no se usa).
# ---------------------------------------------------------------------------

_EVENTS: dict[str, pd.DataFrame] = {}
_LOADED_RANGE: dict[str, tuple] = {}
_ROWS: dict[str, list[tuple[int, float]]] = {}
_MANIFEST_ACCESSES: dict[str, list[datetime]] = {}


def load_flow_context(
    from_dt: datetime, to_dt: datetime, symbol: str = "BTC-USDT",
    roc_window: int = 60, pctile_window: int = 180, high_pctile: float = 0.90,
    dedup_days: int = 14, ttl_days: int = 14,
) -> None:
    """Descarga la reserva de exchange UNA VEZ y precomputa los eventos de spike.
    Llamar una vez antes del backtest, igual que load_macro_context."""
    key = symbol.upper()
    _MANIFEST_ACCESSES[key] = []
    req_range = (from_dt.date(), to_dt.date(), roc_window, pctile_window,
                 high_pctile, dedup_days, ttl_days)
    if _LOADED_RANGE.get(key) == req_range:
        return

    rows = fetch_exchange_reserve(symbol, from_dt, to_dt)
    roc_rows = build_roc_series(rows, window_days=roc_window)
    events = build_flow_overlay_events(
        roc_rows, pctile_window=pctile_window, low_pctile=0.10, high_pctile=high_pctile,
        dedup_days=dedup_days, ttl_days=ttl_days,
    )
    _EVENTS[key] = events[events["signal"] == "reserve_rising"].reset_index(drop=True)
    _ROWS[key] = rows
    _LOADED_RANGE[key] = req_range
    logger.info("onchain_flow[{}]: {} eventos de spike de reserva cargados", key,
                len(_EVENTS[key]))


def flow_vol_adjustment_at(dt: datetime, symbol: str, delta: float) -> tuple[float, str | None]:
    """delta (negativo, reduce riesgo) si hay un spike de reserva ACTIVO (dentro de su
    TTL) en `dt`. 0.0/None si no hay evento cargado o ninguno activo."""
    key = symbol.upper()
    _MANIFEST_ACCESSES.setdefault(key, []).append(dt)
    events = _EVENTS.get(key)
    if events is None or events.empty:
        return 0.0, None
    ts = pd.Timestamp(dt) if dt.tzinfo else pd.Timestamp(dt, tz="UTC")
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    active = events[(events["dt"] < ts) & (events["expires_at"] >= ts)]
    if active.empty:
        return 0.0, None
    row = active.sort_values("dt").iloc[-1]
    return float(delta), f"flow_vol_spike_{float(row.roc):+.3f}"
