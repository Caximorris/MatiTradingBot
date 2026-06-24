"""
Indicadores técnicos puros — sin dependencias externas excepto numpy/pandas.

Todas las funciones reciben Series o arrays y devuelven Series de pandas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Medias móviles
# ---------------------------------------------------------------------------

def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average con ajuste estándar (adjust=False = Wilder/TradingView)."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
         ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Retorna (macd_line, signal_line, histogram).
    macd_line = EMA(fast) - EMA(slow)
    signal_line = EMA(macd_line, signal)
    histogram = macd_line - signal_line
    """
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ---------------------------------------------------------------------------
# ATR — Average True Range
# ---------------------------------------------------------------------------

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ---------------------------------------------------------------------------
# ADX — Average Directional Index
# ---------------------------------------------------------------------------

def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Retorna la línea ADX (0-100). >25 = tendencia fuerte, <20 = mercado lateral.
    """
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_series = atr(high, low, close, period)

    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(
        alpha=1 / period, adjust=False).mean() / tr_series
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(
        alpha=1 / period, adjust=False).mean() / tr_series

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(alpha=1 / period, adjust=False).mean()


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ---------------------------------------------------------------------------
# Resample 1H → Daily
# ---------------------------------------------------------------------------

def resample_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte DataFrame OHLCV de barras 1H (timestamp en ms) a barras diarias.
    Columnas esperadas: timestamp (ms), open, high, low, close, volume.
    """
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    daily = df.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"])
    return daily.reset_index()


# ---------------------------------------------------------------------------
# OBV — On Balance Volume
# ---------------------------------------------------------------------------

def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Volumen acumulado según dirección del precio."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


# ---------------------------------------------------------------------------
# EMA Slope — pendiente normalizada
# ---------------------------------------------------------------------------

def ema_slope(series: pd.Series, period: int) -> pd.Series:
    """Cambio porcentual de la EMA sobre N barras (proxy de pendiente)."""
    e = ema(series, period)
    return e.pct_change(period) * 100


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def bb_bands(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Retorna (upper, middle, lower, width_pct, pct_b).
    width_pct: ancho como % de la media (squeeze = valor bajo).
    pct_b: posición del precio dentro de las bandas (0=lower, 1=upper).
    """
    mid = sma(close, period)
    std = close.rolling(period).std(ddof=0)
    band = std_dev * std
    upper = mid + band
    lower = mid - band
    denom = (upper - lower).replace(0, np.nan)
    width_pct = (upper - lower) / mid.replace(0, np.nan) * 100
    pct_b = (close - lower) / denom
    return upper, mid, lower, width_pct, pct_b


# ---------------------------------------------------------------------------
# Swing Structure — HH/HL vs LH/LL
# ---------------------------------------------------------------------------

def swing_structure(high: pd.Series, low: pd.Series, lookback: int = 20) -> str:
    """
    Detecta estructura de mercado usando los últimos N barras.
    Retorna 'uptrend' (HH+HL), 'downtrend' (LH+LL), 'range' o 'unknown'.
    """
    h = high.iloc[-lookback:].values
    lo = low.iloc[-lookback:].values
    if len(h) < 6:
        return "unknown"
    sh = [h[i] for i in range(1, len(h) - 1) if h[i] > h[i - 1] and h[i] > h[i + 1]]
    sl = [lo[i] for i in range(1, len(lo) - 1) if lo[i] < lo[i - 1] and lo[i] < lo[i + 1]]
    if len(sh) >= 2 and len(sl) >= 2:
        if sh[-1] > sh[-2] and sl[-1] > sl[-2]:
            return "uptrend"
        if sh[-1] < sh[-2] and sl[-1] < sl[-2]:
            return "downtrend"
        return "range"
    return "unknown"


# ---------------------------------------------------------------------------
# Soporte / Resistencia — niveles clave por clustering
# ---------------------------------------------------------------------------

def sr_levels(
    high: pd.Series, low: pd.Series,
    lookback: int = 60, zone_pct: float = 0.015,
) -> tuple[list[float], list[float]]:
    """
    Encuentra niveles de soporte y resistencia agrupando máximos/mínimos locales.
    Retorna (soportes, resistencias) ordenados ascendentemente.
    """
    h = high.iloc[-lookback:].values
    lo = low.iloc[-lookback:].values
    peaks   = [float(h[i])  for i in range(1, len(h)  - 1) if h[i]  >= h[i-1]  and h[i]  >= h[i+1]]
    troughs = [float(lo[i]) for i in range(1, len(lo) - 1) if lo[i] <= lo[i-1] and lo[i] <= lo[i+1]]

    def _cluster(levels: list[float]) -> list[float]:
        if not levels:
            return []
        lvl = sorted(levels)
        groups = [[lvl[0]]]
        for v in lvl[1:]:
            ref = groups[-1][-1]
            if ref > 0 and (v - ref) / ref <= zone_pct:
                groups[-1].append(v)
            else:
                groups.append([v])
        return [float(np.mean(g)) for g in groups]

    return _cluster(troughs), _cluster(peaks)


# ---------------------------------------------------------------------------
# Fair Value Gaps (FVG)
# ---------------------------------------------------------------------------

def fvg_zones(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    lookback: int = 30,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """
    Detecta Fair Value Gaps (patrón de 3 velas) en los últimas N barras.
    Bullish FVG: low[i] > high[i-2]  → gap alcista no rellenado
    Bearish FVG: high[i] < low[i-2] → gap bajista no rellenado
    Usa iloc[:-1] para excluir la vela actual (sin look-ahead).
    Retorna (bull_fvgs, bear_fvgs) como listas de (top, bottom).
    """
    n = min(lookback + 2, len(close) - 1)
    h  = high.iloc[-n:-1].values
    lo = low.iloc[-n:-1].values
    last_close = float(close.iloc[-1])
    bull: list[tuple[float, float]] = []
    bear: list[tuple[float, float]] = []
    for i in range(2, len(h)):
        if lo[i] > h[i - 2]:
            top, bot = float(lo[i]), float(h[i - 2])
            if last_close > bot:
                bull.append((top, bot))
        elif h[i] < lo[i - 2]:
            top, bot = float(lo[i - 2]), float(h[i])
            if last_close < top:
                bear.append((top, bot))
    return bull[-5:], bear[-5:]


# ---------------------------------------------------------------------------
# Point of Control (POC)
# ---------------------------------------------------------------------------

def poc_level(close: pd.Series, volume: pd.Series, n_bins: int = 20) -> float:
    """Nivel de precio con mayor volumen acumulado (aproximación con histograma)."""
    c = close.values.astype(float)
    v = volume.values.astype(float)
    n_bins = max(1, min(n_bins, max(1, len(c) // 2)))
    counts, edges = np.histogram(c, bins=n_bins, weights=v)
    idx = int(np.argmax(counts))
    return float((edges[idx] + edges[idx + 1]) / 2)


# ---------------------------------------------------------------------------
# RSI Divergence
# ---------------------------------------------------------------------------

def rsi_divergence(
    close: pd.Series, rsi_series: pd.Series, lookback: int = 14
) -> str | None:
    """
    Detecta divergencias regulares de RSI en los últimos N barras.
    Alcista: precio hace mínimo menor, RSI hace mínimo mayor.
    Bajista: precio hace máximo mayor, RSI hace máximo menor.
    Retorna 'bullish', 'bearish' o None. Umbral mínimo: 2 puntos de RSI.
    """
    if len(close) < lookback:
        return None
    c = close.tail(lookback).values
    r = rsi_series.tail(lookback).values
    if len(c) < 4 or np.any(np.isnan(r)):
        return None
    lows_i  = [i for i in range(1, len(c) - 1) if c[i] < c[i - 1] and c[i] < c[i + 1]]
    highs_i = [i for i in range(1, len(c) - 1) if c[i] > c[i - 1] and c[i] > c[i + 1]]
    result = None
    if len(highs_i) >= 2:
        i1, i2 = highs_i[-2], highs_i[-1]
        if c[i2] > c[i1] and r[i2] < r[i1] - 2:
            result = "bearish"
    if len(lows_i) >= 2:
        i1, i2 = lows_i[-2], lows_i[-1]
        if c[i2] < c[i1] and r[i2] > r[i1] + 2:
            return "bullish"
    return result


# ---------------------------------------------------------------------------
# Resample 1H → Weekly
# ---------------------------------------------------------------------------

def resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte DataFrame OHLCV de 1H a barras semanales (cierra el domingo).
    Columnas esperadas: timestamp (ms), open, high, low, close, volume.
    La columna 'dt' contiene el timestamp del domingo de cierre de cada semana.
    """
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    weekly = df.resample("W").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"])
    return weekly.reset_index()


# ---------------------------------------------------------------------------
# Detector de régimen
# ---------------------------------------------------------------------------

def detect_regime(daily_df: pd.DataFrame,
                  ema_fast: int = 50,
                  ema_slow: int = 200,
                  adx_period: int = 14,
                  adx_threshold: float = 20.0) -> str:
    """
    Clasifica el régimen actual del mercado usando el último bar diario.

    Retorna:
      "bull"  — precio > EMA200 Y EMA50 > EMA200 (tendencia alcista confirmada)
      "bear"  — precio < EMA200 O EMA50 < EMA200 (tendencia bajista)
      "range" — bull estructural pero ADX < threshold (mercado lateral)
      "data_insufficient" — no hay suficientes barras para calcular indicadores
    """
    min_bars = ema_slow + 10
    if len(daily_df) < min_bars:
        return "data_insufficient"

    close = daily_df["close"].astype(float)
    high  = daily_df["high"].astype(float)
    low   = daily_df["low"].astype(float)

    ema_f = ema(close, ema_fast)
    ema_s = ema(close, ema_slow)
    adx_val = adx(high, low, close, adx_period)

    last_close = float(close.iloc[-1])
    last_ema_f = float(ema_f.iloc[-1])
    last_ema_s = float(ema_s.iloc[-1])
    last_adx   = float(adx_val.iloc[-1]) if not np.isnan(adx_val.iloc[-1]) else 0.0

    golden_cross = last_ema_f > last_ema_s
    price_above  = last_close > last_ema_s

    if not golden_cross or not price_above:
        return "bear"
    if last_adx < adx_threshold:
        return "range"
    return "bull"


# ---------------------------------------------------------------------------
# Resample 1H -> 4H
# ---------------------------------------------------------------------------

def resample_to_1h(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte DataFrame OHLCV de 15m a barras de 1 hora.
    Columnas esperadas: timestamp (ms), open, high, low, close, volume.
    """
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    h1 = df.resample("1h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"])
    return h1.reset_index()


def resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte DataFrame OHLCV de 1H a barras de 4 horas.
    Columnas esperadas: timestamp (ms), open, high, low, close, volume.
    """
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    h4 = df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"])
    return h4.reset_index()


# ---------------------------------------------------------------------------
# Volume Profile — POC, VAH, VAL
# ---------------------------------------------------------------------------

def volume_profile(
    close: pd.Series,
    volume: pd.Series,
    high: pd.Series,
    low: pd.Series,
    lookback: int = 100,
    n_buckets: int = 40,
    value_area_pct: float = 0.70,
) -> tuple[float, float, float]:
    """
    Calcula el perfil de volumen sobre las ultimas N barras.

    Retorna (poc, vah, val):
      poc  — Point of Control: precio con mayor volumen acumulado
      vah  — Value Area High: limite superior del 70% del volumen centrado en POC
      val  — Value Area Low:  limite inferior del 70% del volumen centrado en POC
    """
    n = min(lookback, len(close))
    c = close.iloc[-n:].values.astype(float)
    v = volume.iloc[-n:].values.astype(float)
    h = high.iloc[-n:].values.astype(float)
    lo = low.iloc[-n:].values.astype(float)

    price_min = float(lo.min())
    price_max = float(h.max())
    if price_min >= price_max:
        mid = float(c[-1])
        return mid, mid, mid

    n_b = max(5, min(n_buckets, n // 2))
    edges = np.linspace(price_min, price_max, n_b + 1)
    buckets = np.zeros(n_b)

    for i in range(n):
        bar_lo = lo[i]
        bar_hi = h[i]
        bar_v  = v[i]
        for j in range(n_b):
            overlap = min(bar_hi, edges[j + 1]) - max(bar_lo, edges[j])
            if overlap > 0:
                bar_range = bar_hi - bar_lo
                weight = overlap / bar_range if bar_range > 0 else 1.0 / n_b
                buckets[j] += bar_v * weight

    poc_idx  = int(np.argmax(buckets))
    poc      = float((edges[poc_idx] + edges[poc_idx + 1]) / 2)
    total_v  = buckets.sum()
    target_v = total_v * value_area_pct

    # Expandir desde POC hacia arriba y abajo hasta cubrir el value_area_pct
    lo_idx = hi_idx = poc_idx
    covered = buckets[poc_idx]
    while covered < target_v:
        add_lo = buckets[lo_idx - 1] if lo_idx > 0         else 0.0
        add_hi = buckets[hi_idx + 1] if hi_idx < n_b - 1   else 0.0
        if add_lo == 0 and add_hi == 0:
            break
        if add_hi >= add_lo:
            hi_idx += 1
            covered += buckets[hi_idx]
        else:
            lo_idx -= 1
            covered += buckets[lo_idx]

    vah = float(edges[hi_idx + 1])
    val = float(edges[lo_idx])
    return poc, vah, val
