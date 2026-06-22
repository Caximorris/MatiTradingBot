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
