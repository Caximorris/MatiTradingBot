"""
Pro Trend Following — multi-timeframe con longs y shorts sintéticos.

SEÑALES (sistema de puntuación, max ~14 pts por lado):
  +2  tendencia semanal (EMA20W vs EMA50W + slope)
  +1  EMA50D > EMA200D
  +1  precio > EMA200D
  +1  slope EMA50D positivo
  +1  swing structure HH/HL
  +2  MACD crossover (+1 si solo positivo sin cruce)
  +2  divergencia RSI
  +1  OBV slope en dirección
  +1  ADX > umbral + EMA50D en dirección
  +1  precio cerca de S/R clave
  +1  FVG no rellenado en dirección y cercano
  +1  volumen expandido + vela en dirección

Entrada: score >= 5 con ventaja de > 1 sobre el score opuesto.
Salida:  flip semanal, ATR stop, MACD cross contrario + EMA20D, score < 2.

SHORTS SINTÉTICOS: el margen USDT se reserva via adjust_balance() al abrir
y se liquida con P&L neto al cerrar. No se generan órdenes reales de venta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from loguru import logger

from core.database import get_or_create_bot_state, upsert_position, close_position
from core.exchange import OrderResult
from strategies.base_strategy import BaseStrategy
from strategies.macro_context import get_macro_signal
from strategies.indicators import (
    ema, macd as compute_macd, atr as compute_atr,
    rsi as compute_rsi, adx as compute_adx,
    resample_to_daily, resample_to_weekly, resample_to_4h,
    obv, ema_slope, bb_bands, swing_structure, sr_levels,
    fvg_zones, rsi_divergence, volume_profile,
)

if TYPE_CHECKING:
    from core.exchange import OKXClient
    from core.risk_manager import RiskManager


_FEE_RATE = Decimal("0.001")   # 0.1 % OKX taker


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

@dataclass
class ProTrendConfig:
    symbol: str

    # EMAs diarias
    ema_20d:  int = 20
    ema_50d:  int = 50
    ema_200d: int = 200

    # EMAs semanales
    ema_20w: int = 20
    ema_50w: int = 50

    # MACD diario
    macd_fast:   int = 12
    macd_slow:   int = 26
    macd_signal: int = 9

    # Riesgo
    atr_period:    int   = 14
    atr_stop_mult: float = 2.5

    # RSI / ADX
    rsi_period:    int   = 14
    adx_threshold: float = 20.0

    # Bollinger Bands
    bb_period: int   = 20
    bb_std:    float = 2.0

    # Swing / S/R
    swing_lookback:  int   = 20
    sr_lookback:     int   = 60
    sr_proximity_pct: float = 0.02   # ±2 % alrededor del nivel

    # FVG
    fvg_lookback:     int   = 30
    fvg_proximity_pct: float = 0.03  # dentro del 3 % del precio actual

    # Volumen
    vol_ma_period:   int   = 20
    vol_expand_mult: float = 1.3

    # Slopes
    obv_slope_period: int = 5
    ema_slope_period: int = 5

    # Scoring
    entry_score_min:       int = 7   # umbral para longs (~50% del máximo ~14pts)
    entry_score_min_short: int = 9   # umbral más alto para shorts (más confirmación)
    entry_score_gap:       int = 2   # ventaja mínima sobre el opuesto para entrar
    exit_score_floor:      int = 3   # cierre si score cae por debajo

    # Sizing — conservador para sobrevivir rachas de stop-outs
    size_high:      Decimal = Decimal("0.20")
    size_mid:       Decimal = Decimal("0.12")
    size_short_cap: Decimal = Decimal("0.15")

    # Cooldown: días sin entrar tras un ATR stop-out
    cooldown_bars: int = 5

    # Hard stop: cierra la posición si la pérdida supera este % del precio de entrada,
    # independientemente del ATR stop (red de seguridad contra gaps y rallies violentos).
    max_loss_pct: float = 20.0

    # Historial: 365 días = ~52 semanas, suficiente para EMA50W
    lookback_hours: int = 8760

    def __post_init__(self) -> None:
        if self.ema_50d >= self.ema_200d:
            raise ValueError("ema_50d debe ser menor que ema_200d")

    @classmethod
    def from_dict(cls, d: dict) -> "ProTrendConfig":
        _c = cls(symbol=d["symbol"])
        return cls(
            symbol=d["symbol"],
            ema_20d=int(d.get("ema_20d", _c.ema_20d)),
            ema_50d=int(d.get("ema_50d", _c.ema_50d)),
            ema_200d=int(d.get("ema_200d", _c.ema_200d)),
            ema_20w=int(d.get("ema_20w", _c.ema_20w)),
            ema_50w=int(d.get("ema_50w", _c.ema_50w)),
            macd_fast=int(d.get("macd_fast", _c.macd_fast)),
            macd_slow=int(d.get("macd_slow", _c.macd_slow)),
            macd_signal=int(d.get("macd_signal", _c.macd_signal)),
            atr_period=int(d.get("atr_period", _c.atr_period)),
            atr_stop_mult=float(d.get("atr_stop_mult", _c.atr_stop_mult)),
            rsi_period=int(d.get("rsi_period", _c.rsi_period)),
            adx_threshold=float(d.get("adx_threshold", _c.adx_threshold)),
            bb_period=int(d.get("bb_period", _c.bb_period)),
            bb_std=float(d.get("bb_std", _c.bb_std)),
            swing_lookback=int(d.get("swing_lookback", _c.swing_lookback)),
            sr_lookback=int(d.get("sr_lookback", _c.sr_lookback)),
            sr_proximity_pct=float(d.get("sr_proximity_pct", _c.sr_proximity_pct)),
            fvg_lookback=int(d.get("fvg_lookback", _c.fvg_lookback)),
            fvg_proximity_pct=float(d.get("fvg_proximity_pct", _c.fvg_proximity_pct)),
            vol_ma_period=int(d.get("vol_ma_period", _c.vol_ma_period)),
            vol_expand_mult=float(d.get("vol_expand_mult", _c.vol_expand_mult)),
            obv_slope_period=int(d.get("obv_slope_period", _c.obv_slope_period)),
            ema_slope_period=int(d.get("ema_slope_period", _c.ema_slope_period)),
            entry_score_min=int(d.get("entry_score_min", _c.entry_score_min)),
            entry_score_min_short=int(d.get("entry_score_min_short", _c.entry_score_min_short)),
            entry_score_gap=int(d.get("entry_score_gap", _c.entry_score_gap)),
            exit_score_floor=int(d.get("exit_score_floor", _c.exit_score_floor)),
            size_high=Decimal(str(d.get("size_high", str(_c.size_high)))),
            size_mid=Decimal(str(d.get("size_mid", str(_c.size_mid)))),
            size_short_cap=Decimal(str(d.get("size_short_cap", str(_c.size_short_cap)))),
            cooldown_bars=int(d.get("cooldown_bars", _c.cooldown_bars)),
            max_loss_pct=float(d.get("max_loss_pct", _c.max_loss_pct)),
            lookback_hours=int(d.get("lookback_hours", _c.lookback_hours)),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "ema_20d": self.ema_20d,
            "ema_50d": self.ema_50d,
            "ema_200d": self.ema_200d,
            "ema_20w": self.ema_20w,
            "ema_50w": self.ema_50w,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "atr_period": self.atr_period,
            "atr_stop_mult": self.atr_stop_mult,
            "rsi_period": self.rsi_period,
            "adx_threshold": self.adx_threshold,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "swing_lookback": self.swing_lookback,
            "sr_lookback": self.sr_lookback,
            "sr_proximity_pct": self.sr_proximity_pct,
            "fvg_lookback": self.fvg_lookback,
            "fvg_proximity_pct": self.fvg_proximity_pct,
            "vol_ma_period": self.vol_ma_period,
            "vol_expand_mult": self.vol_expand_mult,
            "obv_slope_period": self.obv_slope_period,
            "ema_slope_period": self.ema_slope_period,
            "entry_score_min": self.entry_score_min,
            "entry_score_min_short": self.entry_score_min_short,
            "entry_score_gap": self.entry_score_gap,
            "exit_score_floor": self.exit_score_floor,
            "size_high": str(self.size_high),
            "size_mid": str(self.size_mid),
            "size_short_cap": str(self.size_short_cap),
            "cooldown_bars": self.cooldown_bars,
            "max_loss_pct": self.max_loss_pct,
            "lookback_hours": self.lookback_hours,
        }


# ---------------------------------------------------------------------------
# Estrategia
# ---------------------------------------------------------------------------

class ProTrendBot(BaseStrategy):
    """
    Estrategia multi-timeframe con señales ricas y cortos sintéticos.

    Estado persistido:
    {
        "position":       "none" | "long" | "short",
        "entry_price":    "0",
        "position_qty":   "0",
        "stop_loss":      "0",
        "margin_usdt":    "0",       # USDT reservado como margen para cortos
        "half_reduced":   false,
        "prev_macd_above": null,
        "prev_weekly_up":  null,
        "_cooldown_until": null,     # "YYYY-MM-DD" — no entrar hasta esta fecha tras ATR stop
        "_daily_cache":   null,      # {"date": "YYYY-MM-DD", "ind": {...} | null}
        "_weekly_cache":  null,      # {"week": "YYYY-Www",   "ind": {...} | null}
    }
    """

    def __init__(
        self,
        client: "OKXClient",
        config: dict | ProTrendConfig,
        session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        cfg = ProTrendConfig.from_dict(config) if isinstance(config, dict) else config
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._cfg = cfg
        self._state = self._load_state()

    @property
    def name(self) -> str:
        sym = self._cfg.symbol.lower().replace("-", "_")
        return f"pro_trend_{sym}"

    # -----------------------------------------------------------------------
    # Persistencia
    # -----------------------------------------------------------------------

    def _load_state(self) -> dict:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="pro_trend",
            symbol=self._cfg.symbol,
            config=self._cfg.to_dict(),
        )
        saved = bot_state.get_config()
        defaults: dict = {
            "position": "none",
            "entry_price": "0",
            "position_qty": "0",
            "stop_loss": "0",
            "margin_usdt": "0",
            "half_reduced": False,
            "prev_macd_above": None,
            "prev_weekly_up": None,
            "_cooldown_until": None,
            "_daily_cache": None,
            "_weekly_cache": None,
            "_4h_cache":    None,
        }
        return {**defaults, **saved}

    def _save_state(self) -> None:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="pro_trend",
            symbol=self._cfg.symbol,
        )
        bot_state.set_config(self._state)

    # -----------------------------------------------------------------------
    # Helpers de datos
    # -----------------------------------------------------------------------

    def _to_df(self, raw) -> pd.DataFrame:
        if isinstance(raw, pd.DataFrame):
            return raw
        return pd.DataFrame([
            {
                "timestamp": b.timestamp,
                "open":   float(b.open),
                "high":   float(b.high),
                "low":    float(b.low),
                "close":  float(b.close),
                "volume": float(b.volume),
            }
            for b in raw
        ])

    def _fetch_raw(self) -> pd.DataFrame | None:
        cfg = self._cfg
        raw = self._client.get_ohlcv(cfg.symbol, timeframe="1H", limit=cfg.lookback_hours)
        if raw is None or (hasattr(raw, "__len__") and len(raw) < cfg.ema_200d * 24):
            return None
        return self._to_df(raw)

    def _safe_float(self, val) -> float:
        f = float(val)
        return 0.0 if math.isnan(f) or math.isinf(f) else f

    # -----------------------------------------------------------------------
    # Indicadores diarios (cache por fecha)
    # -----------------------------------------------------------------------

    def _build_daily_indicators(self, raw_df: pd.DataFrame) -> dict | None:
        cfg = self._cfg
        current_day = self._client.current_time().date().isoformat()

        cached = self._state.get("_daily_cache")
        if cached and cached.get("date") == current_day:
            return cached.get("ind")

        daily = resample_to_daily(raw_df)

        # Excluir el día actual si está incompleto
        if len(daily) > 0 and "dt" in daily.columns:
            last_day = pd.to_datetime(daily.iloc[-1]["dt"]).date().isoformat()
            if last_day == current_day:
                daily = daily.iloc[:-1]

        if len(daily) < cfg.ema_200d + 10:
            self._state["_daily_cache"] = {"date": current_day, "ind": None}
            return None

        close  = daily["close"].astype(float)
        high   = daily["high"].astype(float)
        low    = daily["low"].astype(float)
        volume = daily["volume"].astype(float)

        ema20d  = ema(close, cfg.ema_20d)
        ema50d  = ema(close, cfg.ema_50d)
        ema200d = ema(close, cfg.ema_200d)

        macd_line, sig_line, _ = compute_macd(
            close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
        )
        atr_s = compute_atr(high, low, close, cfg.atr_period)
        rsi_s = compute_rsi(close, cfg.rsi_period)
        adx_s = compute_adx(high, low, close, cfg.atr_period)

        obv_s    = obv(close, volume)
        obv_sl   = self._safe_float(ema_slope(obv_s,   cfg.obv_slope_period).iloc[-1])
        e50_sl   = self._safe_float(ema_slope(ema50d,  cfg.ema_slope_period).iloc[-1])
        e200_sl  = self._safe_float(ema_slope(ema200d, cfg.ema_slope_period).iloc[-1])

        vol_ma = volume.rolling(cfg.vol_ma_period).mean()

        _, _, _, bb_width_s, bb_pct_b_s = bb_bands(close, cfg.bb_period, cfg.bb_std)

        swing = swing_structure(high, low, cfg.swing_lookback)
        sup, res = sr_levels(high, low, cfg.sr_lookback)
        rsi_div = rsi_divergence(close, rsi_s, 14)
        vp_poc, vp_vah, vp_val = volume_profile(close, volume, high, low, lookback=100)

        ind = {
            "close":       self._safe_float(close.iloc[-1]),
            "ema_20d":     self._safe_float(ema20d.iloc[-1]),
            "ema_50d":     self._safe_float(ema50d.iloc[-1]),
            "ema_200d":    self._safe_float(ema200d.iloc[-1]),
            "macd_above":  bool(self._safe_float(macd_line.iloc[-1]) > self._safe_float(sig_line.iloc[-1])),
            "atr":         self._safe_float(atr_s.iloc[-1]),
            "rsi":         self._safe_float(rsi_s.iloc[-1]),
            "adx":         self._safe_float(adx_s.iloc[-1]),
            "obv_slope":    obv_sl,
            "ema50_slope":  e50_sl,
            "ema200_slope": e200_sl,
            "vol_last":    self._safe_float(volume.iloc[-1]),
            "vol_ma":      self._safe_float(vol_ma.iloc[-1]),
            "bb_width":    self._safe_float(bb_width_s.iloc[-1]),
            "bb_pct_b":    self._safe_float(bb_pct_b_s.iloc[-1]) if not math.isnan(self._safe_float(bb_pct_b_s.iloc[-1])) else 0.5,
            "swing":       swing,
            "support":     sup,
            "resistance":  res,
            "rsi_div":     rsi_div,
            "vp_poc":      vp_poc,
            "vp_vah":      vp_vah,
            "vp_val":      vp_val,
        }
        self._state["_daily_cache"] = {"date": current_day, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Contexto semanal (cache por semana ISO)
    # -----------------------------------------------------------------------

    def _build_weekly_context(self, raw_df: pd.DataFrame) -> dict:
        cfg = self._cfg
        now = self._client.current_time()
        iso = now.isocalendar()
        week_key = f"{iso[0]}-W{iso[1]:02d}"

        cached = self._state.get("_weekly_cache")
        if cached and cached.get("week") == week_key:
            return cached.get("ind") or {"weekly_trend_up": None}

        weekly = resample_to_weekly(raw_df)

        # Excluir la semana actual (incompleta)
        if len(weekly) > 0:
            last_dt = pd.to_datetime(weekly.iloc[-1]["dt"])
            last_iso = last_dt.isocalendar()
            last_key = f"{last_iso[0]}-W{last_iso[1]:02d}"
            if last_key == week_key:
                weekly = weekly.iloc[:-1]

        null_ind: dict = {"weekly_trend_up": None}

        if len(weekly) < cfg.ema_20w + 5:
            self._state["_weekly_cache"] = {"week": week_key, "ind": null_ind}
            return null_ind

        close_w  = weekly["close"].astype(float)
        ema20w_s = ema(close_w, cfg.ema_20w)
        ema20w_val  = self._safe_float(ema20w_s.iloc[-1])
        last_close_w = self._safe_float(close_w.iloc[-1])
        slope_val   = self._safe_float(
            ema_slope(ema20w_s, min(3, cfg.ema_slope_period)).iloc[-1]
        )

        if len(weekly) >= cfg.ema_50w + 5:
            ema50w_val = self._safe_float(ema(close_w, cfg.ema_50w).iloc[-1])
            weekly_up = (
                ema20w_val > ema50w_val
                and last_close_w > ema20w_val
                and slope_val > 0
            )
        else:
            # Fallback: solo EMA20W y su slope
            weekly_up = last_close_w > ema20w_val and slope_val > 0

        ind: dict = {
            "weekly_trend_up": bool(weekly_up),
            "ema_20w":         ema20w_val,
            "slope":           slope_val,
            "close_w":         last_close_w,
        }
        self._state["_weekly_cache"] = {"week": week_key, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Contexto 4H (cache por bloque de 4 horas)
    # -----------------------------------------------------------------------

    def _build_4h_context(self, raw_df: pd.DataFrame) -> dict:
        cfg = self._cfg
        now  = self._client.current_time()
        h4_key = f"{now.date().isoformat()}-{now.hour // 4}"

        cached = self._state.get("_4h_cache")
        if cached and cached.get("key") == h4_key:
            return cached.get("ind") or {"trend_bullish": None, "trend_bearish": None}

        null_ind: dict = {"trend_bullish": None, "trend_bearish": None,
                          "macd_above": None, "swing": "unknown", "close": 0.0}

        df4 = resample_to_4h(raw_df)
        if len(df4) < 60:
            self._state["_4h_cache"] = {"key": h4_key, "ind": null_ind}
            return null_ind

        close4  = df4["close"].astype(float)
        high4   = df4["high"].astype(float)
        low4    = df4["low"].astype(float)

        ema20_4h = ema(close4, 20)
        ema50_4h = ema(close4, 50)
        macd4, sig4, _ = compute_macd(close4, 12, 26, 9)

        last_e20 = self._safe_float(ema20_4h.iloc[-1])
        last_e50 = self._safe_float(ema50_4h.iloc[-1])
        last_m   = self._safe_float(macd4.iloc[-1])
        last_s   = self._safe_float(sig4.iloc[-1])
        swing4   = swing_structure(high4, low4, 20)

        ind: dict = {
            "close":         self._safe_float(close4.iloc[-1]),
            "ema20":         last_e20,
            "ema50":         last_e50,
            "trend_bullish": bool(last_e20 > last_e50),
            "trend_bearish": bool(last_e20 < last_e50),
            "macd_above":    bool(last_m > last_s),
            "swing":         swing4,
        }
        self._state["_4h_cache"] = {"key": h4_key, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Contexto 1H (no se cachea — barato de recalcular)
    # -----------------------------------------------------------------------

    def _build_1h_context(self, raw_df: pd.DataFrame) -> dict:
        cfg = self._cfg
        df = raw_df.tail(100).reset_index(drop=True)

        empty: dict = {
            "bull_fvgs": [], "bear_fvgs": [],
            "vol_spike_up": False, "vol_spike_dn": False,
            "bb_squeeze": False,
            "bb_breakout_up": False, "bb_breakout_dn": False,
        }
        if len(df) < 30:
            return empty

        o = df["open"].astype(float)
        h = df["high"].astype(float)
        lo = df["low"].astype(float)
        c  = df["close"].astype(float)
        v  = df["volume"].astype(float)

        bull_fvgs, bear_fvgs = fvg_zones(o, h, lo, c, cfg.fvg_lookback)

        vol_ma_1h   = v.rolling(20).mean()
        last_vol    = self._safe_float(v.iloc[-1])
        last_vol_ma = self._safe_float(vol_ma_1h.iloc[-1])
        last_close  = self._safe_float(c.iloc[-1])
        last_open   = self._safe_float(o.iloc[-1])
        vol_expand  = last_vol > last_vol_ma * cfg.vol_expand_mult and last_vol_ma > 0

        _, _, _, bb_w_s, bb_pb_s = bb_bands(c, cfg.bb_period, cfg.bb_std)
        last_width = self._safe_float(bb_w_s.iloc[-1])
        last_pct_b = self._safe_float(bb_pb_s.iloc[-1]) if not math.isnan(self._safe_float(bb_pb_s.iloc[-1])) else 0.5
        recent_w = bb_w_s.dropna().tail(50).values
        bb_squeeze = bool(len(recent_w) >= 10 and last_width < float(np.percentile(recent_w, 20)))

        return {
            "close":          last_close,
            "bull_fvgs":      bull_fvgs,
            "bear_fvgs":      bear_fvgs,
            "vol_spike_up":   bool(vol_expand and last_close > last_open),
            "vol_spike_dn":   bool(vol_expand and last_close < last_open),
            "bb_squeeze":     bb_squeeze,
            "bb_breakout_up": last_pct_b > 1.0,
            "bb_breakout_dn": last_pct_b < 0.0,
        }

    # -----------------------------------------------------------------------
    # Puntuación de señales
    # -----------------------------------------------------------------------

    def _score_long(
        self, daily: dict, weekly: dict, h1: dict, prev_macd_above,
    ) -> int:
        score = 0
        close = daily["close"]
        cfg   = self._cfg

        # Weekly (2 pts)
        if weekly.get("weekly_trend_up") is True:
            score += 2

        # Estructura daily (3 pts)
        if daily["ema_50d"] > daily["ema_200d"]:
            score += 1
        if close > daily["ema_200d"]:
            score += 1
        if daily["ema50_slope"] > 0:
            score += 1

        # Swing structure (1 pt)
        if daily["swing"] == "uptrend":
            score += 1

        # MACD (2 pts crossover, 1 pt si positivo)
        macd_cross_up = daily["macd_above"] and not prev_macd_above
        if macd_cross_up:
            score += 2
        elif daily["macd_above"]:
            score += 1

        # RSI divergence (2 pts)
        if daily.get("rsi_div") == "bullish":
            score += 2

        # OBV (1 pt)
        if daily["obv_slope"] > 0:
            score += 1

        # ADX en dirección (1 pt)
        if daily["adx"] >= cfg.adx_threshold and daily["ema_50d"] > daily["ema_200d"]:
            score += 1

        # Precio cerca de soporte S/R clasico o VAL del Volume Profile (1 pt)
        prox = cfg.sr_proximity_pct
        vp_val = daily.get("vp_val", 0.0)
        near_vp_support = vp_val > 0 and close <= vp_val * (1 + prox) and close >= vp_val * (1 - prox)
        if near_vp_support:
            score += 1
        else:
            for sup in daily["support"]:
                if sup < close <= sup * (1 + prox):
                    score += 1
                    break

        # FVG alcista cercano (1 pt)
        fvg_prox = cfg.fvg_proximity_pct
        for (top, bot) in h1["bull_fvgs"]:
            if bot < close and (close - bot) / close <= fvg_prox:
                score += 1
                break

        # Volumen expandido + precio al alza (1 pt)
        if h1.get("vol_spike_up"):
            score += 1

        # BB: compra el dip en tendencia alcista o ruptura tras squeeze (1 pt)
        if weekly.get("weekly_trend_up") and daily["bb_pct_b"] < 0.2:
            score += 1
        elif h1.get("bb_squeeze") and h1.get("bb_breakout_up"):
            score += 1

        return score

    def _score_short(
        self, daily: dict, weekly: dict, h1: dict, prev_macd_above,
    ) -> int:
        score = 0
        close = daily["close"]
        cfg   = self._cfg

        # Weekly (2 pts)
        if weekly.get("weekly_trend_up") is False:
            score += 2

        # Estructura daily (3 pts)
        if daily["ema_50d"] < daily["ema_200d"]:
            score += 1
        if close < daily["ema_200d"]:
            score += 1
        if daily["ema50_slope"] < 0:
            score += 1

        # Swing structure (1 pt)
        if daily["swing"] == "downtrend":
            score += 1

        # MACD (2 pts crossover, 1 pt si negativo)
        macd_cross_dn = not daily["macd_above"] and bool(prev_macd_above)
        if macd_cross_dn:
            score += 2
        elif not daily["macd_above"]:
            score += 1

        # RSI divergence (1 pt — en bull market las divs bajistas son ruido frecuente)
        if daily.get("rsi_div") == "bearish":
            score += 1

        # EMA200 diaria declinando: confirma tendencia bajista estructural (1 pt)
        if daily.get("ema200_slope", 0.0) < 0:
            score += 1

        # OBV (1 pt)
        if daily["obv_slope"] < 0:
            score += 1

        # ADX en dirección bajista (1 pt)
        if daily["adx"] >= cfg.adx_threshold and daily["ema_50d"] < daily["ema_200d"]:
            score += 1

        # Precio cerca de resistencia S/R clasico o VAH del Volume Profile (1 pt)
        prox = cfg.sr_proximity_pct
        vp_vah = daily.get("vp_vah", 0.0)
        near_vp_resist = vp_vah > 0 and close >= vp_vah * (1 - prox) and close <= vp_vah * (1 + prox)
        if near_vp_resist:
            score += 1
        else:
            for res in daily["resistance"]:
                if res * (1 - prox) <= close < res:
                    score += 1
                    break

        # FVG bajista cercano (1 pt)
        fvg_prox = cfg.fvg_proximity_pct
        for (top, bot) in h1["bear_fvgs"]:
            if top > close and (top - close) / close <= fvg_prox:
                score += 1
                break

        # Volumen expandido + precio a la baja (1 pt)
        if h1.get("vol_spike_dn"):
            score += 1

        # BB: precio sobre upper en tendencia bajista o ruptura bajista tras squeeze (1 pt)
        if weekly.get("weekly_trend_up") is False and daily["bb_pct_b"] > 0.8:
            score += 1
        elif h1.get("bb_squeeze") and h1.get("bb_breakout_dn"):
            score += 1

        return score

    def _log_short_trade(
        self, side: str, price: Decimal, qty: Decimal, fee: Decimal,
        pnl: Decimal | None = None,
    ) -> None:
        """Crea un OrderResult sintético para registrar operaciones de cortos en la DB."""
        result = OrderResult(
            order_id=f"short_{side}_{self.name}_{int(price)}",
            symbol=self._cfg.symbol,
            side=side,
            order_type="market",
            size=qty,
            limit_price=None,
            filled_qty=qty,
            filled_price=price,
            fee=fee,
            fee_currency="USDT",
            status="filled",
            is_paper=True,
            strategy=self.name,
            timestamp=self._client.current_time(),
        )
        self.log_trade(result, pnl=pnl)

    def _size_pct(self, score: int, side: str, reduce_risk: bool = False) -> Decimal:
        cfg = self._cfg
        pct = cfg.size_high if score >= 8 else cfg.size_mid
        if side == "short":
            pct = min(pct, cfg.size_short_cap)
        if reduce_risk:
            pct = min(pct, cfg.size_mid)   # cap en size_mid cuando MVRV sugiere techo
        return pct

    # -----------------------------------------------------------------------
    # Acciones — longs
    # -----------------------------------------------------------------------

    def _open_long(self, price: Decimal, score: int, atr_val: float) -> None:
        cfg = self._cfg
        usdt = self._client.get_balance().get("USDT", Decimal("0"))
        invest = (usdt * self._size_pct(score, "long")).quantize(Decimal("0.01"))

        ok, reason = self.check_risk(cfg.symbol, invest)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        qty = (invest / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty <= Decimal("0"):
            return

        result = self._client.place_order(cfg.symbol, "buy", "market", qty, strategy=self.name)
        if result.status != "filled" or not result.filled_price:
            return

        stop = result.filled_price - Decimal(str(atr_val)) * Decimal(str(cfg.atr_stop_mult))
        self.log_trade(result)
        self._state.update({
            "position":     "long",
            "entry_price":  str(result.filled_price),
            "position_qty": str(result.filled_qty),
            "stop_loss":    str(stop),
            "margin_usdt":  "0",
            "half_reduced": False,
        })
        self._save_state()
        upsert_position(
            self._session, symbol=cfg.symbol, strategy=self.name,
            side="long", entry_price=result.filled_price,
            quantity=result.filled_qty, current_price=result.filled_price,
            unrealized_pnl=Decimal("0"),
        )
        logger.info(
            "[{}] LONG @ {} | qty={} | stop={} | score={} | invest={} USDT",
            self.name, result.filled_price, result.filled_qty, stop, score, invest,
        )

    def _close_long(self, price: Decimal, reason: str) -> None:
        qty   = Decimal(self._state["position_qty"])
        entry = Decimal(self._state["entry_price"])
        if qty <= Decimal("0"):
            self._reset_state()
            return

        result = self._client.place_order(
            self._cfg.symbol, "sell", "market", qty, strategy=self.name
        )
        if result.status == "filled" and result.filled_price:
            pnl = (result.filled_price - entry) * result.filled_qty - result.fee
            self.log_trade(result, pnl=pnl)
            logger.info(
                "[{}] LONG cerrado ({}) @ {} | PnL={:.2f} USDT",
                self.name, reason, result.filled_price, pnl,
            )
            close_position(self._session, self._cfg.symbol, self.name)
        self._reset_state()

    def _reduce_long_half(self, price: Decimal) -> None:
        qty   = Decimal(self._state["position_qty"])
        sell  = (qty / 2).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if sell <= Decimal("0"):
            return

        entry  = Decimal(self._state["entry_price"])
        result = self._client.place_order(
            self._cfg.symbol, "sell", "market", sell, strategy=self.name
        )
        if result.status == "filled" and result.filled_price:
            pnl = (result.filled_price - entry) * result.filled_qty - result.fee
            self.log_trade(result, pnl=pnl)
            self._state["position_qty"] = str(qty - sell)
            self._state["half_reduced"] = True
            self._save_state()
            logger.info(
                "[{}] LONG reducido al 50% @ {} | PnL parcial={:.2f}", self.name, price, pnl
            )

    # -----------------------------------------------------------------------
    # Acciones — shorts sintéticos
    # -----------------------------------------------------------------------

    def _open_short(self, price: Decimal, score: int, atr_val: float) -> None:
        cfg    = self._cfg
        usdt   = self._client.get_balance().get("USDT", Decimal("0"))
        margin = (usdt * self._size_pct(score, "short")).quantize(Decimal("0.01"))

        ok, reason = self.check_risk(cfg.symbol, margin)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        qty = (margin / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty <= Decimal("0"):
            return

        # Reservar margen + comisión de apertura
        open_fee = qty * price * _FEE_RATE
        self._client.adjust_balance("USDT", -(margin + open_fee))

        self._log_short_trade("sell", price, qty, open_fee)

        stop = price + Decimal(str(atr_val)) * Decimal(str(cfg.atr_stop_mult))

        self._state.update({
            "position":     "short",
            "entry_price":  str(price),
            "position_qty": str(qty),
            "stop_loss":    str(stop),
            "margin_usdt":  str(margin),
            "half_reduced": False,
        })
        self._save_state()
        upsert_position(
            self._session, symbol=cfg.symbol, strategy=self.name,
            side="short", entry_price=price,
            quantity=qty, current_price=price,
            unrealized_pnl=Decimal("0"),
        )
        logger.info(
            "[{}] SHORT @ {} | qty={} | stop={} | score={} | margin={} USDT",
            self.name, price, qty, stop, score, margin,
        )

    def _close_short(self, price: Decimal, reason: str) -> None:
        entry  = Decimal(self._state["entry_price"])
        qty    = Decimal(self._state["position_qty"])
        margin = Decimal(self._state["margin_usdt"])

        if qty <= Decimal("0"):
            self._reset_state()
            return

        gross_pnl = (entry - price) * qty
        close_fee = qty * price * _FEE_RATE
        net_pnl   = gross_pnl - close_fee

        # Devolver margen + P&L (mínimo 0 USDT)
        returned = max(Decimal("0"), margin + net_pnl)
        self._client.adjust_balance("USDT", returned)

        self._log_short_trade("buy", price, qty, close_fee, pnl=net_pnl)
        logger.info(
            "[{}] SHORT cerrado ({}) | entrada={} salida={} | PnL={:.2f} USDT",
            self.name, reason, entry, price, net_pnl,
        )
        close_position(self._session, self._cfg.symbol, self.name)
        self._reset_state()

    def _reduce_short_half(self, price: Decimal) -> None:
        qty    = Decimal(self._state["position_qty"])
        entry  = Decimal(self._state["entry_price"])
        margin = Decimal(self._state["margin_usdt"])

        close_qty = (qty / 2).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if close_qty <= Decimal("0"):
            return

        partial_margin = (margin * close_qty / qty).quantize(Decimal("0.01"))
        gross_pnl = (entry - price) * close_qty
        close_fee = close_qty * price * _FEE_RATE
        net_pnl   = gross_pnl - close_fee
        returned  = max(Decimal("0"), partial_margin + net_pnl)

        self._client.adjust_balance("USDT", returned)

        self._state["position_qty"] = str(qty - close_qty)
        self._state["margin_usdt"]  = str(margin - partial_margin)
        self._state["half_reduced"] = True
        self._save_state()
        logger.info(
            "[{}] SHORT reducido al 50% @ {} | PnL parcial={:.2f}", self.name, price, net_pnl
        )

    # -----------------------------------------------------------------------
    # Reset
    # -----------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._state.update({
            "position":     "none",
            "entry_price":  "0",
            "position_qty": "0",
            "stop_loss":    "0",
            "margin_usdt":  "0",
            "half_reduced": False,
        })
        self._save_state()

    # -----------------------------------------------------------------------
    # Cooldown post stop-out
    # -----------------------------------------------------------------------

    def _set_cooldown(self) -> None:
        """Bloquea nuevas entradas durante cooldown_bars días tras un ATR stop-out."""
        from datetime import timedelta
        days = self._cfg.cooldown_bars
        if days > 0:
            until = (
                self._client.current_time().date() + timedelta(days=days)
            ).isoformat()
            self._state["_cooldown_until"] = until
            self._save_state()
            logger.debug("[{}] Cooldown activo hasta {}", self.name, until)

    # -----------------------------------------------------------------------
    # Gestión de posiciones abiertas
    # -----------------------------------------------------------------------

    def _manage_long(
        self, daily: dict, weekly: dict, h1: dict,
        price: Decimal, ls: int, ss: int,
    ) -> None:
        cfg  = self._cfg
        stop = Decimal(self._state["stop_loss"])
        entry = Decimal(self._state["entry_price"])
        prev_macd = self._state.get("prev_macd_above")

        # 1. Flip semanal → bajista
        if weekly.get("weekly_trend_up") is False:
            logger.info("[{}] Tendencia semanal BAJISTA — cerrando LONG", self.name)
            self._close_long(price, "weekly_flip_bear")
            self._set_cooldown()
            return

        # 2. Hard cap: pérdida > max_loss_pct desde entrada (red de seguridad vs gaps)
        if entry > Decimal("0"):
            loss_pct = float((price - entry) / entry * 100)
            if loss_pct < -cfg.max_loss_pct:
                logger.info(
                    "[{}] Hard stop LONG: -{:.1f}% desde entrada @ {}",
                    self.name, abs(loss_pct), entry,
                )
                self._close_long(price, "hard_stop")
                self._set_cooldown()
                return

        # 3. ATR stop (basado en precio horario actual)
        if stop > Decimal("0") and price <= stop:
            logger.info("[{}] ATR stop LONG @ {} <= {}", self.name, price, stop)
            self._close_long(price, "atr_stop")
            self._set_cooldown()
            return

        # 4. MACD death cross + precio horario bajo EMA20D
        macd_cross_dn = not daily["macd_above"] and bool(prev_macd)
        if macd_cross_dn and price < daily["ema_20d"]:
            logger.info("[{}] MACD death cross + precio < EMA20D — cerrando LONG", self.name)
            self._close_long(price, "macd_exit")
            return

        # 5. Score LONG por debajo del piso mínimo
        if ls < cfg.exit_score_floor:
            logger.info("[{}] Score LONG={} < {} — cerrando", self.name, ls, cfg.exit_score_floor)
            self._close_long(price, "score_floor")
            return

        # 6. Divergencia bajista RSI con ganancia > 5 % → recorte parcial
        if entry > Decimal("0"):
            unreal_pct = float((price - entry) / entry * 100)
            if (daily.get("rsi_div") == "bearish"
                    and unreal_pct > 5.0
                    and not self._state.get("half_reduced")):
                logger.info(
                    "[{}] RSI div bajista con +{:.1f}% ganancia — reduciendo LONG",
                    self.name, unreal_pct,
                )
                self._reduce_long_half(price)

        # 7. Switch a SHORT si señal contraria fuerte
        if ss >= cfg.entry_score_min and ls < cfg.exit_score_floor + 1:
            logger.info("[{}] Switch LONG → SHORT (ls={}, ss={})", self.name, ls, ss)
            self._close_long(price, "switch_to_short")
            self._open_short(price, ss, daily["atr"])

    def _manage_short(
        self, daily: dict, weekly: dict, h1: dict,
        price: Decimal, ls: int, ss: int,
    ) -> None:
        cfg  = self._cfg
        stop = Decimal(self._state["stop_loss"])
        entry = Decimal(self._state["entry_price"])
        prev_macd = self._state.get("prev_macd_above")

        # 1. Flip semanal → alcista
        if weekly.get("weekly_trend_up") is True:
            logger.info("[{}] Tendencia semanal ALCISTA — cerrando SHORT", self.name)
            self._close_short(price, "weekly_flip_bull")
            self._set_cooldown()
            return

        # 2. Hard cap: pérdida > max_loss_pct desde entrada (red de seguridad vs rallies violentos)
        if entry > Decimal("0"):
            loss_pct = float((entry - price) / entry * 100)
            if loss_pct < -cfg.max_loss_pct:
                logger.info(
                    "[{}] Hard stop SHORT: -{:.1f}% desde entrada @ {}",
                    self.name, abs(loss_pct), entry,
                )
                self._close_short(price, "hard_stop")
                self._set_cooldown()
                return

        # 3. ATR stop (basado en precio horario actual)
        if stop > Decimal("0") and price >= stop:
            logger.info("[{}] ATR stop SHORT @ {} >= {}", self.name, price, stop)
            self._close_short(price, "atr_stop")
            self._set_cooldown()
            return

        # 4. MACD golden cross + precio horario sobre EMA20D
        macd_cross_up = daily["macd_above"] and not prev_macd
        if macd_cross_up and price > daily["ema_20d"]:
            logger.info("[{}] MACD golden cross + precio > EMA20D — cerrando SHORT", self.name)
            self._close_short(price, "macd_exit")
            return

        # 5. Score SHORT por debajo del piso mínimo
        if ss < cfg.exit_score_floor:
            logger.info("[{}] Score SHORT={} < {} — cerrando", self.name, ss, cfg.exit_score_floor)
            self._close_short(price, "score_floor")
            return

        # 6. Divergencia alcista RSI con beneficio > 5 % en el corto → recorte parcial
        if entry > Decimal("0"):
            unreal_pct = float((entry - price) / entry * 100)
            if (daily.get("rsi_div") == "bullish"
                    and unreal_pct > 5.0
                    and not self._state.get("half_reduced")):
                logger.info(
                    "[{}] RSI div alcista con +{:.1f}% ganancia corto — reduciendo SHORT",
                    self.name, unreal_pct,
                )
                self._reduce_short_half(price)

        # 7. Switch a LONG si señal contraria fuerte
        if ls >= cfg.entry_score_min and ss < cfg.exit_score_floor + 1:
            logger.info("[{}] Switch SHORT → LONG (ls={}, ss={})", self.name, ls, ss)
            self._close_short(price, "switch_to_long")
            self._open_long(price, ls, daily["atr"])

    # -----------------------------------------------------------------------
    # Tick principal
    # -----------------------------------------------------------------------

    def run(self) -> None:
        raw = self._fetch_raw()
        if raw is None:
            return

        daily = self._build_daily_indicators(raw)
        if daily is None:
            return

        weekly = self._build_weekly_context(raw)
        h4     = self._build_4h_context(raw)
        h1     = self._build_1h_context(raw)

        prev_macd = self._state.get("prev_macd_above")
        ls = self._score_long(daily, weekly, h1, prev_macd)
        ss = self._score_short(daily, weekly, h1, prev_macd)

        price    = Decimal(str(h1["close"]))   # precio real de la barra horaria actual
        position = self._state.get("position", "none")

        if position == "long":
            self._manage_long(daily, weekly, h1, price, ls, ss)
        elif position == "short":
            self._manage_short(daily, weekly, h1, price, ls, ss)
        else:
            current_day = self._client.current_time().date().isoformat()
            cooldown_until = self._state.get("_cooldown_until")
            in_cooldown = bool(cooldown_until and current_day < cooldown_until)

            if not in_cooldown:
                cfg          = self._cfg
                weekly_trend = weekly.get("weekly_trend_up")
                macro        = get_macro_signal(self._client.current_time())
                funding      = self._client.get_funding_rate(cfg.symbol)

                # Macro bear tecnico: EMA200 diaria declinando + precio por debajo
                ema_bear = (
                    daily.get("ema200_slope", 0.0) < 0
                    and daily["close"] < daily["ema_200d"]
                )

                # Realized Price: no shortear si precio esta cerca/bajo el coste base del mercado
                realized = macro.get("realized_price")
                above_realized = realized is None or daily["close"] > realized * 1.1

                # Funding rate alto = mercado sobrecomprado en derivados = no entrar long
                # Threshold: 0.05% por 8h = 0.0005 (niveles historicos de exceso)
                funding_ok_long  = funding < 0.0005
                funding_ok_short = funding > -0.0005  # funding muy negativo = sobrevendido

                long_ok = (
                    ls >= cfg.entry_score_min
                    and ls > ss + cfg.entry_score_gap
                    and weekly_trend is not False
                    and h4.get("trend_bullish") is not False   # 4H alineado con long
                    and not macro["long_reduce_risk"]           # no entrar en euforia MVRV
                    and funding_ok_long                        # mercado no sobrecomprado en derivados
                )
                short_ok = (
                    ss >= cfg.entry_score_min_short
                    and ss > ls + cfg.entry_score_gap
                    and weekly_trend is not True
                    and ema_bear
                    and macro["short_allowed"]                 # MVRV y halving no bloquean
                    and above_realized                         # precio suficientemente sobre Realized
                    and h4.get("trend_bearish") is not False   # 4H alineado con short
                    and funding_ok_short
                )

                if long_ok:
                    logger.info(
                        "[{}] ENTRADA LONG score={} (short={}) mvrv={} phase={} 4H={} funding={:.4f}",
                        self.name, ls, ss,
                        round(macro["mvrv"], 2) if macro["mvrv"] else "N/D",
                        macro["halving_phase"],
                        "bull" if h4.get("trend_bullish") else "?",
                        funding,
                    )
                    self._open_long(price, ls, daily["atr"])
                elif short_ok:
                    logger.info(
                        "[{}] ENTRADA SHORT score={} (long={}) mvrv={} phase={} realized={} 4H={}",
                        self.name, ss, ls,
                        round(macro["mvrv"], 2) if macro["mvrv"] else "N/D",
                        macro["halving_phase"],
                        round(realized, 0) if realized else "N/D",
                        "bear" if h4.get("trend_bearish") else "?",
                    )
                    self._open_short(price, ss, daily["atr"])

        self._state["prev_macd_above"] = daily["macd_above"]
        self._state["prev_weekly_up"]  = weekly.get("weekly_trend_up")
        self._save_state()

    # -----------------------------------------------------------------------
    # Señales abstractas
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        return self._state.get("position") == "none"

    def should_exit(self) -> bool:
        return self._state.get("position") != "none"
