"""Cálculo de indicadores técnicos sobre datos OHLCV."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from data.market_data import OHLCVBar


@dataclass
class BollingerBands:
    upper: Decimal
    middle: Decimal
    lower: Decimal


@dataclass
class IndicatorResult:
    bb: BollingerBands | None
    rsi: Decimal | None
    volume_mean: Decimal | None
    last_close: Decimal | None


def compute_indicators(
    bars: list["OHLCVBar"],
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
) -> IndicatorResult:
    """
    Calcula BB y RSI sobre la lista de velas proporcionada.
    Intenta usar pandas-ta; si no está disponible, usa implementación pura.
    Retorna IndicatorResult con None en los campos que no se puedan calcular.
    """
    if not bars:
        return IndicatorResult(bb=None, rsi=None, volume_mean=None, last_close=None)

    closes = [float(b.close) for b in bars]
    volumes = [float(b.volume) for b in bars]
    last_close = bars[-1].close
    volume_mean = Decimal(str(sum(volumes) / len(volumes))) if volumes else None

    bb = _compute_bb(closes, bb_period, bb_std)
    rsi = _compute_rsi(closes, rsi_period)

    return IndicatorResult(bb=bb, rsi=rsi, volume_mean=volume_mean, last_close=last_close)


def _compute_bb(closes: list[float], period: int, std_mult: float) -> BollingerBands | None:
    if len(closes) < period:
        return None
    try:
        import pandas as pd
        import pandas_ta as ta
        s = pd.Series(closes)
        bb = ta.bbands(s, length=period, std=std_mult)
        if bb is None or bb.empty:
            return None
        row = bb.iloc[-1]
        cols = bb.columns.tolist()
        lower_col = next((c for c in cols if c.startswith("BBL")), None)
        mid_col = next((c for c in cols if c.startswith("BBM")), None)
        upper_col = next((c for c in cols if c.startswith("BBU")), None)
        if not all([lower_col, mid_col, upper_col]):
            return None
        return BollingerBands(
            upper=Decimal(str(round(row[upper_col], 8))),
            middle=Decimal(str(round(row[mid_col], 8))),
            lower=Decimal(str(round(row[lower_col], 8))),
        )
    except ImportError:
        return _compute_bb_pure(closes, period, std_mult)
    except Exception as exc:
        logger.warning("Error calculando BB con pandas-ta: {} — usando implementación pura", exc)
        return _compute_bb_pure(closes, period, std_mult)


def _compute_bb_pure(closes: list[float], period: int, std_mult: float) -> BollingerBands | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std = variance ** 0.5
    return BollingerBands(
        upper=Decimal(str(round(mean + std_mult * std, 8))),
        middle=Decimal(str(round(mean, 8))),
        lower=Decimal(str(round(mean - std_mult * std, 8))),
    )


def _compute_rsi(closes: list[float], period: int) -> Decimal | None:
    if len(closes) < period + 1:
        return None
    try:
        import pandas as pd
        import pandas_ta as ta
        s = pd.Series(closes)
        rsi_series = ta.rsi(s, length=period)
        if rsi_series is None or rsi_series.empty:
            return None
        val = rsi_series.iloc[-1]
        if val != val:  # NaN check
            return None
        return Decimal(str(round(float(val), 4)))
    except ImportError:
        return _compute_rsi_pure(closes, period)
    except Exception as exc:
        logger.warning("Error calculando RSI con pandas-ta: {} — usando implementación pura", exc)
        return _compute_rsi_pure(closes, period)


def _compute_rsi_pure(closes: list[float], period: int) -> Decimal | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas[-period:]]
    losses = [abs(min(d, 0.0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return Decimal("100")
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return Decimal(str(round(rsi, 4)))
