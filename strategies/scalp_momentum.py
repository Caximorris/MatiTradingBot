"""
Scalp Momentum — day trading en barras de 15 minutos con contexto de 1 hora.

SEÑALES (sistema de puntuación, máx 10 pts por lado):
  +2  tendencia 1H alcista (EMA20 > EMA50 en 1H)          ← hard-gate también
  +1  EMA9 > EMA21 en 15m
  +1  EMA21 > EMA50 en 15m
  +2  MACD(5,13,3) crossover alcista (+1 si solo histograma > 0)
  +1  RSI(9) en zona 50-72 (momentum alcista sin solapamiento con short)
  +1  precio > VWAP diario
  +1  precio > BB mid (SMA20 en 15m)
  +1  volumen expandido + vela ALCISTA (vol_spike_up — direccional)

Zonas RSI NO se solapan: long 50-72, short 28-50.

HARD GATES para entrada (además del score):
  - 1H trend_up Y 1H MACD positivo para longs
  - 1H trend_down Y 1H MACD negativo para shorts

HOLDING MÍNIMO: min_hold_bars (defecto 8 = 2h) para evitar microwhipsaws.
Solo se evalúan exits suaves (TP, RSI, MACD cross, score floor) tras ese tiempo.
Hard stop y ATR stop siguen activos desde el primer bar.

SHORTS SINTÉTICOS: mismo mecanismo que Pro Trend (adjust_balance).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from core.database import get_or_create_bot_state, upsert_position, close_position
from core.exchange import OrderResult
from strategies.base_strategy import BaseStrategy
from strategies.indicators import (
    ema, macd as compute_macd, atr as compute_atr,
    rsi as compute_rsi, adx as compute_adx, bb_bands, resample_to_1h,
    resample_to_4h, resample_to_daily, resample_to_weekly,
)
from strategies.macro_context import get_macro_signal
from strategies.market_context import get_market_context

if TYPE_CHECKING:
    from core.exchange import OKXClient
    from core.risk_manager import RiskManager


_FEE_RATE = Decimal("0.001")   # 0.1 % OKX taker


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

@dataclass
class ScalpMomentumConfig:
    symbol: str = "BTC-USDT"

    # EMAs en 15m
    ema_fast: int = 9
    ema_mid:  int = 21
    ema_slow: int = 50

    # MACD rápido (optimizado para 15m)
    macd_fast:   int = 5
    macd_slow:   int = 13
    macd_signal: int = 3

    # RSI rápido
    rsi_period: int = 9

    # ATR
    atr_period:    int   = 14
    atr_stop_mult: float = 3.0
    atr_tp_mult:   float = 5.0

    # Bollinger Bands en 15m
    bb_period: int   = 20
    bb_std:    float = 2.0

    # Volumen
    vol_ma_period:   int   = 20
    vol_expand_mult: float = 1.2

    # Scoring
    # Subidos respecto a v1: se necesita alineación fuerte para no operar en ruido.
    entry_score_min:  int = 7   # 7/10 pts para entrar (era 6)
    entry_score_gap:  int = 3   # ventaja mínima sobre el lado opuesto (era 2)
    exit_score_floor: int = 1

    # Tiempo mínimo en posición antes de evaluar exits suaves (bars de 15m).
    # 8 bars = 2 horas. Evita microwhipsaws y muertes por comisión.
    min_hold_bars: int = 8

    # Régimen diario: ADX(14) mínimo para considerar que el mercado está tendiendo.
    # 0 = desactivado. Con 20, filtra mercados laterales donde la estrategia pierde.
    daily_adx_min: int = 20

    # Filtro semanal: solo operar longs cuando EMA10W > EMA20W (tendencia alcista macro).
    # Mismo gate que Pro Trend. Requiere lookback_bars >= 4320 (180 días).
    weekly_trend_filter: bool = True

    # Filtros externos (macro + mercado global) — datos ya cargados en memoria por _run_backtest.
    # Macro (MVRV): bloquea longs cuando MVRV >= 2.5 (late_bull / euphoria).
    use_macro_filter: bool = True
    # Mercado (DXY + NASDAQ): bloquea longs en rally del dólar o crash de índices.
    use_market_filter: bool = True

    # Trailing stop — activo solo tras min_hold_bars y si la ganancia supera min_profit.
    # 0.0 = desactivado. 0.07 = cierra si el precio cae 7% desde el pico post-entrada.
    trailing_stop_pct: float = 0.07
    trailing_min_profit: float = 0.03  # activar solo si precio ya subió > 3% desde entrada

    # Shorts desactivados por defecto — pierden 4x más que longs en BTC
    allow_shorts: bool = False

    # Sizing — conservador para day trading (se ajusta según resultados)
    size_long:  Decimal = Decimal("0.15")
    size_short: Decimal = Decimal("0.10")

    # Cooldown tras close: 8 barras = 2 horas (era 4 = 1h)
    cooldown_bars: int = 8

    # Hard stop (% desde entrada)
    max_loss_pct: float = 6.0

    # Barras 1H a cargar — 4320 = 180 días ≈ 25 semanas (necesario para EMA20W semanal)
    lookback_bars: int = 4320

    def __post_init__(self):
        if self.ema_fast >= self.ema_mid:
            raise ValueError("ema_fast debe ser < ema_mid")
        if self.ema_mid >= self.ema_slow:
            raise ValueError("ema_mid debe ser < ema_slow")

    @classmethod
    def from_dict(cls, d: dict) -> "ScalpMomentumConfig":
        _c = cls(symbol=d.get("symbol", "BTC-USDT"))
        return cls(
            symbol=d.get("symbol", _c.symbol),
            ema_fast=int(d.get("ema_fast", _c.ema_fast)),
            ema_mid=int(d.get("ema_mid", _c.ema_mid)),
            ema_slow=int(d.get("ema_slow", _c.ema_slow)),
            macd_fast=int(d.get("macd_fast", _c.macd_fast)),
            macd_slow=int(d.get("macd_slow", _c.macd_slow)),
            macd_signal=int(d.get("macd_signal", _c.macd_signal)),
            rsi_period=int(d.get("rsi_period", _c.rsi_period)),
            atr_period=int(d.get("atr_period", _c.atr_period)),
            atr_stop_mult=float(d.get("atr_stop_mult", _c.atr_stop_mult)),
            atr_tp_mult=float(d.get("atr_tp_mult", _c.atr_tp_mult)),
            bb_period=int(d.get("bb_period", _c.bb_period)),
            bb_std=float(d.get("bb_std", _c.bb_std)),
            vol_ma_period=int(d.get("vol_ma_period", _c.vol_ma_period)),
            vol_expand_mult=float(d.get("vol_expand_mult", _c.vol_expand_mult)),
            entry_score_min=int(d.get("entry_score_min", _c.entry_score_min)),
            entry_score_gap=int(d.get("entry_score_gap", _c.entry_score_gap)),
            exit_score_floor=int(d.get("exit_score_floor", _c.exit_score_floor)),
            min_hold_bars=int(d.get("min_hold_bars", _c.min_hold_bars)),
            allow_shorts=bool(d.get("allow_shorts", _c.allow_shorts)),
            size_long=Decimal(str(d.get("size_long", str(_c.size_long)))),
            size_short=Decimal(str(d.get("size_short", str(_c.size_short)))),
            cooldown_bars=int(d.get("cooldown_bars", _c.cooldown_bars)),
            max_loss_pct=float(d.get("max_loss_pct", _c.max_loss_pct)),
            lookback_bars=int(d.get("lookback_bars", _c.lookback_bars)),
            daily_adx_min=int(d.get("daily_adx_min", _c.daily_adx_min)),
            weekly_trend_filter=bool(d.get("weekly_trend_filter", _c.weekly_trend_filter)),
            use_macro_filter=bool(d.get("use_macro_filter", _c.use_macro_filter)),
            use_market_filter=bool(d.get("use_market_filter", _c.use_market_filter)),
            trailing_stop_pct=float(d.get("trailing_stop_pct", _c.trailing_stop_pct)),
            trailing_min_profit=float(d.get("trailing_min_profit", _c.trailing_min_profit)),
        )

    def to_dict(self) -> dict:
        return {
            "symbol":           self.symbol,
            "ema_fast":         self.ema_fast,
            "ema_mid":          self.ema_mid,
            "ema_slow":         self.ema_slow,
            "macd_fast":        self.macd_fast,
            "macd_slow":        self.macd_slow,
            "macd_signal":      self.macd_signal,
            "rsi_period":       self.rsi_period,
            "atr_period":       self.atr_period,
            "atr_stop_mult":    self.atr_stop_mult,
            "atr_tp_mult":      self.atr_tp_mult,
            "bb_period":        self.bb_period,
            "bb_std":           self.bb_std,
            "vol_ma_period":    self.vol_ma_period,
            "vol_expand_mult":  self.vol_expand_mult,
            "entry_score_min":  self.entry_score_min,
            "entry_score_gap":  self.entry_score_gap,
            "exit_score_floor": self.exit_score_floor,
            "min_hold_bars":    self.min_hold_bars,
            "allow_shorts":     self.allow_shorts,
            "size_long":        str(self.size_long),
            "size_short":       str(self.size_short),
            "cooldown_bars":    self.cooldown_bars,
            "max_loss_pct":         self.max_loss_pct,
            "lookback_bars":        self.lookback_bars,
            "daily_adx_min":        self.daily_adx_min,
            "weekly_trend_filter":  self.weekly_trend_filter,
            "use_macro_filter":     self.use_macro_filter,
            "use_market_filter":    self.use_market_filter,
            "trailing_stop_pct":    self.trailing_stop_pct,
            "trailing_min_profit":  self.trailing_min_profit,
        }


# ---------------------------------------------------------------------------
# Estrategia
# ---------------------------------------------------------------------------

class ScalpMomentumBot(BaseStrategy):
    """
    Day trading en 15m con contexto de 1H.

    Estado persistido:
    {
        "position":    "none" | "long" | "short",
        "entry_price": "0",
        "position_qty":"0",
        "stop_loss":   "0",
        "take_profit": "0",
        "margin_usdt": "0",
        "bars_held":   0,          # barras en la posición actual (para min_hold)
        "_cooldown_bars_left": 0,
        "_1h_cache":   null,       # {"key": "YYYY-MM-DDTHH", "ind": {...}}
    }
    """

    def __init__(
        self,
        client: "OKXClient",
        config: dict | ScalpMomentumConfig,
        session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        cfg = ScalpMomentumConfig.from_dict(config) if isinstance(config, dict) else config
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._cfg = cfg
        self._state = self._load_state()

    @property
    def name(self) -> str:
        sym = self._cfg.symbol.lower().replace("-", "_")
        return f"scalp_momentum_{sym}"

    # -----------------------------------------------------------------------
    # Persistencia
    # -----------------------------------------------------------------------

    def _load_state(self) -> dict:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="scalp_momentum",
            symbol=self._cfg.symbol,
            config=self._cfg.to_dict(),
        )
        saved = bot_state.get_config()
        defaults: dict = {
            "position":            "none",
            "entry_price":         "0",
            "position_qty":        "0",
            "stop_loss":           "0",
            "take_profit":         "0",
            "margin_usdt":         "0",
            "bars_held":           0,
            "_cooldown_bars_left": 0,
            "_1h_cache":           None,
            "_4h_cache":           None,
            "_daily_cache":        None,
            "_weekly_cache":       None,
            "_peak_price":         "0",
        }
        return {**defaults, **saved}

    def _save_state(self) -> None:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="scalp_momentum",
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
                "timestamp": b["timestamp"] if isinstance(b, dict) else b.timestamp,
                "open":   float(b["open"]   if isinstance(b, dict) else b.open),
                "high":   float(b["high"]   if isinstance(b, dict) else b.high),
                "low":    float(b["low"]    if isinstance(b, dict) else b.low),
                "close":  float(b["close"]  if isinstance(b, dict) else b.close),
                "volume": float(b["volume"] if isinstance(b, dict) else b.volume),
            }
            for b in raw
        ])

    def _fetch_raw(self) -> pd.DataFrame | None:
        cfg = self._cfg
        raw = self._client.get_ohlcv(cfg.symbol, timeframe="15m", limit=cfg.lookback_bars)
        if raw is None or (hasattr(raw, "__len__") and len(raw) < cfg.ema_slow + 30):
            return None
        return self._to_df(raw)

    def _safe_float(self, val) -> float:
        f = float(val)
        return 0.0 if math.isnan(f) or math.isinf(f) else f

    # -----------------------------------------------------------------------
    # VWAP diario (reset a las 00:00 UTC)
    # -----------------------------------------------------------------------

    def _compute_vwap(self, df: pd.DataFrame) -> float:
        df = df.copy()
        df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        today = df["dt"].iloc[-1].date()
        today_bars = df[df["dt"].dt.date == today]
        if len(today_bars) < 8:
            today_bars = df.tail(96)
        typical  = (today_bars["high"] + today_bars["low"] + today_bars["close"]) / 3
        vol      = today_bars["volume"]
        total    = vol.sum()
        if total == 0:
            return self._safe_float(df["close"].iloc[-1])
        return self._safe_float((typical * vol).sum() / total)

    # -----------------------------------------------------------------------
    # Contexto 1H: EMA20/50 + MACD(12,26,9) — cache por hora UTC
    # -----------------------------------------------------------------------

    def _build_1h_context(self, raw_df: pd.DataFrame) -> dict:
        now    = self._client.current_time()
        h1_key = f"{now.date().isoformat()}T{now.hour:02d}"

        cached = self._state.get("_1h_cache")
        if cached and cached.get("key") == h1_key and cached.get("ind") is not None:
            return cached["ind"]

        null_ind: dict = {"trend_up": None, "trend_down": None, "macd_above": None}

        h1 = resample_to_1h(raw_df)
        if len(h1) < 55:
            self._state["_1h_cache"] = {"key": h1_key, "ind": null_ind}
            return null_ind

        close1    = h1["close"].astype(float)
        ema20_1h  = ema(close1, 20)
        ema50_1h  = ema(close1, 50)
        _, _, h1_hist = compute_macd(close1, 12, 26, 9)

        last_e20  = self._safe_float(ema20_1h.iloc[-1])
        last_e50  = self._safe_float(ema50_1h.iloc[-1])
        last_hist = self._safe_float(h1_hist.iloc[-1])

        ind: dict = {
            "trend_up":   bool(last_e20 > last_e50),
            "trend_down": bool(last_e20 < last_e50),
            "macd_above": bool(last_hist > 0),
        }
        self._state["_1h_cache"] = {"key": h1_key, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Contexto 4H: EMA20/50 — cache por bloque de 4h
    # -----------------------------------------------------------------------

    def _build_4h_context(self, raw_df: pd.DataFrame) -> dict:
        now    = self._client.current_time()
        h4_key = f"{now.date().isoformat()}-{now.hour // 4}"

        cached = self._state.get("_4h_cache")
        if cached and cached.get("key") == h4_key and cached.get("ind") is not None:
            return cached["ind"]

        null_ind: dict = {"trend_up": None}

        h4 = resample_to_4h(raw_df)
        if len(h4) < 55:
            self._state["_4h_cache"] = {"key": h4_key, "ind": null_ind}
            return null_ind

        close4  = h4["close"].astype(float)
        ema20_4 = ema(close4, 20)
        ema50_4 = ema(close4, 50)

        ind: dict = {
            "trend_up": bool(self._safe_float(ema20_4.iloc[-1]) > self._safe_float(ema50_4.iloc[-1])),
        }
        self._state["_4h_cache"] = {"key": h4_key, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Contexto diario: EMA20D (precio tendencia macro) — cache por día
    # -----------------------------------------------------------------------

    def _build_daily_context(self, raw_df: pd.DataFrame) -> dict:
        now     = self._client.current_time()
        day_key = now.date().isoformat()

        cached = self._state.get("_daily_cache")
        if cached and cached.get("date") == day_key and cached.get("ind") is not None:
            return cached["ind"]

        null_ind: dict = {"trend_up": None, "ema20d": 0.0, "adx": 0.0}

        daily = resample_to_daily(raw_df)
        # Excluir el día en curso (incompleto)
        if len(daily) > 0 and "dt" in daily.columns:
            if pd.to_datetime(daily.iloc[-1]["dt"]).date().isoformat() == day_key:
                daily = daily.iloc[:-1]

        if len(daily) < 55:   # necesitamos ≥50 días para EMA50D (filtro más robusto que EMA20D)
            self._state["_daily_cache"] = {"date": day_key, "ind": null_ind}
            return null_ind

        close_d  = daily["close"].astype(float)
        high_d   = daily["high"].astype(float)
        low_d    = daily["low"].astype(float)
        ema50d_s = ema(close_d, 50)
        adx_s    = compute_adx(high_d, low_d, close_d, 14)

        last_c   = self._safe_float(close_d.iloc[-1])
        last_e50 = self._safe_float(ema50d_s.iloc[-1])
        last_adx = self._safe_float(adx_s.iloc[-1])

        ind: dict = {
            "trend_up": bool(last_c > last_e50),
            "ema20d":   last_e50,   # clave mantenida por compatibilidad con journal
            "adx":      last_adx,
        }
        self._state["_daily_cache"] = {"date": day_key, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Contexto semanal: EMA10W / EMA20W — cache por semana ISO
    # Necesita lookback_bars >= 4320 (180 días ≈ 25 semanas) para EMA20W.
    # -----------------------------------------------------------------------

    def _build_weekly_context(self, raw_df: pd.DataFrame) -> dict:
        now      = self._client.current_time()
        week_key = now.strftime("%G-W%V")  # ISO week, e.g. "2024-W03"

        cached = self._state.get("_weekly_cache")
        if cached and cached.get("week") == week_key and cached.get("ind") is not None:
            return cached["ind"]

        null_ind: dict = {"weekly_trend_up": None}

        weekly = resample_to_weekly(raw_df)
        if len(weekly) < 0 and "dt" in weekly.columns:
            pass  # no excluir la semana en curso — puede estar incompleta pero usamos su cierre parcial

        if len(weekly) < 22:  # mínimo 22 semanas para EMA20W convergida
            self._state["_weekly_cache"] = {"week": week_key, "ind": null_ind}
            return null_ind

        close_w  = weekly["close"].astype(float)
        ema10w_s = ema(close_w, 10)
        ema20w_s = ema(close_w, 20)

        last_c    = self._safe_float(close_w.iloc[-1])
        last_e10  = self._safe_float(ema10w_s.iloc[-1])
        last_e20  = self._safe_float(ema20w_s.iloc[-1])

        ind: dict = {
            "weekly_trend_up": bool(last_e10 > last_e20 and last_c > last_e20),
        }
        self._state["_weekly_cache"] = {"week": week_key, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Indicadores primarios (15m) — calculados cada barra
    # -----------------------------------------------------------------------

    def _build_indicators(self) -> dict | None:
        raw_df = self._fetch_raw()
        if raw_df is None or len(raw_df) < self._cfg.ema_slow + 30:
            return None

        cfg = self._cfg
        df  = raw_df.reset_index(drop=True)

        close  = df["close"].astype(float)
        open_  = df["open"].astype(float)
        high   = df["high"].astype(float)
        low    = df["low"].astype(float)
        volume = df["volume"].astype(float)

        e_fast = ema(close, cfg.ema_fast)
        e_mid  = ema(close, cfg.ema_mid)
        e_slow = ema(close, cfg.ema_slow)

        _, _, hist_s = compute_macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        rsi_s        = compute_rsi(close, cfg.rsi_period)
        atr_s        = compute_atr(high, low, close, cfg.atr_period)
        _, bb_mid_s, _, _, _ = bb_bands(close, cfg.bb_period, cfg.bb_std)

        vol_ma = volume.rolling(cfg.vol_ma_period).mean()
        vwap    = self._compute_vwap(df)
        h1_ctx  = self._build_1h_context(raw_df)
        h4_ctx  = self._build_4h_context(raw_df)
        d_ctx   = self._build_daily_context(raw_df)
        w_ctx   = self._build_weekly_context(raw_df)

        price     = self._safe_float(close.iloc[-1])
        last_open = self._safe_float(open_.iloc[-1])
        curr_hist = self._safe_float(hist_s.iloc[-1])
        prev_hist = self._safe_float(hist_s.iloc[-2]) if len(hist_s) >= 2 else 0.0

        last_vol    = self._safe_float(volume.iloc[-1])
        last_vol_ma = self._safe_float(vol_ma.iloc[-1])
        vol_expands = last_vol_ma > 0 and last_vol > last_vol_ma * cfg.vol_expand_mult

        candle_bull = price > last_open
        candle_bear = price < last_open

        return {
            "price":           price,
            "ema_fast":        self._safe_float(e_fast.iloc[-1]),
            "ema_mid":         self._safe_float(e_mid.iloc[-1]),
            "ema_slow":        self._safe_float(e_slow.iloc[-1]),
            "macd_hist":       curr_hist,
            "macd_cross_up":   bool(curr_hist > 0 and prev_hist <= 0),
            "macd_cross_down": bool(curr_hist < 0 and prev_hist >= 0),
            "rsi":             self._safe_float(rsi_s.iloc[-1]),
            "atr":             self._safe_float(atr_s.iloc[-1]),
            "bb_mid":          self._safe_float(bb_mid_s.iloc[-1]),
            "vwap":            vwap,
            # Volumen DIRECCIONAL: solo cuenta si la vela va en la misma dirección
            "vol_spike_up":    bool(vol_expands and candle_bull),
            "vol_spike_dn":    bool(vol_expands and candle_bear),
            # Contexto 1H
            "h1_trend_up":    bool(h1_ctx.get("trend_up")),
            "h1_trend_down":  bool(h1_ctx.get("trend_down")),
            "h1_macd_above":  bool(h1_ctx.get("macd_above")),
            # Contexto 4H, diario y semanal (filtros de tendencia superior)
            "h4_trend_up":       bool(h4_ctx.get("trend_up")),
            "daily_trend_up":    bool(d_ctx.get("trend_up")),
            "daily_ema20d":      d_ctx.get("ema20d", 0.0),
            "daily_adx":         d_ctx.get("adx", 0.0),
            "weekly_trend_up":   w_ctx.get("weekly_trend_up"),  # None = sin datos = no bloquear
        }

    # -----------------------------------------------------------------------
    # Puntuación (máx 10 pts por lado)
    # -----------------------------------------------------------------------

    def _long_score(self, ind: dict) -> int:
        score = 0

        if ind["h1_trend_up"]:               score += 2  # tendencia 1H alcista
        if ind["ema_fast"] > ind["ema_mid"]:  score += 1  # EMA9 > EMA21
        if ind["ema_mid"]  > ind["ema_slow"]: score += 1  # EMA21 > EMA50

        if ind["macd_cross_up"]:              score += 2  # crossover alcista
        elif ind["macd_hist"] > 0:            score += 1  # solo histograma positivo

        # Zona RSI exclusiva alcista (50-72): NO solapamiento con short (28-50)
        rsi = ind["rsi"]
        if 50.0 <= rsi <= 72.0:              score += 1

        if ind["vwap"] > 0 and ind["price"] > ind["vwap"]:     score += 1
        if ind["bb_mid"] > 0 and ind["price"] > ind["bb_mid"]:  score += 1
        if ind["vol_spike_up"]:              score += 1   # vela alcista con volumen

        return score

    def _short_score(self, ind: dict) -> int:
        score = 0

        if ind["h1_trend_down"]:              score += 2  # tendencia 1H bajista
        if ind["ema_fast"] < ind["ema_mid"]:  score += 1  # EMA9 < EMA21
        if ind["ema_mid"]  < ind["ema_slow"]: score += 1  # EMA21 < EMA50

        if ind["macd_cross_down"]:            score += 2  # crossover bajista
        elif ind["macd_hist"] < 0:            score += 1  # solo histograma negativo

        # Zona RSI exclusiva bajista (28-50): NO solapamiento con long (50-72)
        rsi = ind["rsi"]
        if 28.0 <= rsi <= 50.0:             score += 1

        if ind["vwap"] > 0 and ind["price"] < ind["vwap"]:     score += 1
        if ind["bb_mid"] > 0 and ind["price"] < ind["bb_mid"]:  score += 1
        if ind["vol_spike_dn"]:             score += 1   # vela bajista con volumen

        return score

    # -----------------------------------------------------------------------
    # Registro de operaciones (cortos sintéticos)
    # -----------------------------------------------------------------------

    def _log_short_trade(
        self, side: str, price: Decimal, qty: Decimal, fee: Decimal,
        pnl: Decimal | None = None,
    ) -> None:
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

    # -----------------------------------------------------------------------
    # Acciones — longs
    # -----------------------------------------------------------------------

    def _open_long(self, price: Decimal, atr_val: float) -> None:
        cfg    = self._cfg
        usdt   = self._client.get_balance().get("USDT", Decimal("0"))
        invest = (usdt * cfg.size_long).quantize(Decimal("0.01"))

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

        atr_d = Decimal(str(atr_val))
        stop  = result.filled_price - atr_d * Decimal(str(cfg.atr_stop_mult))
        tp    = result.filled_price + atr_d * Decimal(str(cfg.atr_tp_mult))

        self._last_open_invest = float(invest)
        self.log_trade(result)
        self._state.update({
            "position":     "long",
            "entry_price":  str(result.filled_price),
            "position_qty": str(result.filled_qty),
            "stop_loss":    str(stop),
            "take_profit":  str(tp),
            "margin_usdt":  "0",
            "bars_held":    0,
            "_peak_price":  str(result.filled_price),
        })
        self._save_state()
        upsert_position(
            self._session, symbol=cfg.symbol, strategy=self.name,
            side="long", entry_price=result.filled_price,
            quantity=result.filled_qty, current_price=result.filled_price,
            unrealized_pnl=Decimal("0"),
        )
        logger.info(
            "[{}] LONG @ {} | stop={:.2f} | tp={:.2f} | invest={} USDT",
            self.name, result.filled_price, stop, tp, invest,
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
            self._last_close_pnl    = float(pnl)
            self._last_close_reason = reason
            self.log_trade(result, pnl=pnl)
            logger.info(
                "[{}] LONG cerrado ({}) @ {} | PnL={:.2f} USDT | held={}bars",
                self.name, reason, result.filled_price, pnl, self._state.get("bars_held", 0),
            )
            close_position(self._session, self._cfg.symbol, self.name)
        self._reset_state()

    # -----------------------------------------------------------------------
    # Acciones — shorts sintéticos
    # -----------------------------------------------------------------------

    def _open_short(self, price: Decimal, atr_val: float) -> None:
        cfg    = self._cfg
        usdt   = self._client.get_balance().get("USDT", Decimal("0"))
        margin = (usdt * cfg.size_short).quantize(Decimal("0.01"))

        ok, reason = self.check_risk(cfg.symbol, margin)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        qty = (margin / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty <= Decimal("0"):
            return

        open_fee = qty * price * _FEE_RATE
        self._client.adjust_balance("USDT", -(margin + open_fee))
        self._last_open_invest = float(margin)
        self._log_short_trade("sell", price, qty, open_fee)

        atr_d = Decimal(str(atr_val))
        stop  = price + atr_d * Decimal(str(cfg.atr_stop_mult))
        tp    = price - atr_d * Decimal(str(cfg.atr_tp_mult))

        self._state.update({
            "position":     "short",
            "entry_price":  str(price),
            "position_qty": str(qty),
            "stop_loss":    str(stop),
            "take_profit":  str(tp),
            "margin_usdt":  str(margin),
            "bars_held":    0,
        })
        self._save_state()
        upsert_position(
            self._session, symbol=cfg.symbol, strategy=self.name,
            side="short", entry_price=price,
            quantity=qty, current_price=price,
            unrealized_pnl=Decimal("0"),
        )
        logger.info(
            "[{}] SHORT @ {} | stop={:.2f} | tp={:.2f} | margin={} USDT",
            self.name, price, stop, tp, margin,
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

        returned = max(Decimal("0"), margin + net_pnl)
        self._client.adjust_balance("USDT", returned)
        self._last_close_pnl    = float(net_pnl)
        self._last_close_reason = reason
        self._log_short_trade("buy", price, qty, close_fee, pnl=net_pnl)
        logger.info(
            "[{}] SHORT cerrado ({}) | entrada={} salida={} | PnL={:.2f} USDT | held={}bars",
            self.name, reason, entry, price, net_pnl, self._state.get("bars_held", 0),
        )
        close_position(self._session, self._cfg.symbol, self.name)
        self._reset_state()

    # -----------------------------------------------------------------------
    # Reset
    # -----------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._state.update({
            "position":     "none",
            "entry_price":  "0",
            "position_qty": "0",
            "stop_loss":    "0",
            "take_profit":  "0",
            "margin_usdt":  "0",
            "bars_held":    0,
            "_peak_price":  "0",
        })
        self._save_state()

    # -----------------------------------------------------------------------
    # Cooldown
    # -----------------------------------------------------------------------

    def _set_cooldown(self) -> None:
        bars = self._cfg.cooldown_bars
        if bars > 0:
            self._state["_cooldown_bars_left"] = bars
            self._save_state()
            logger.debug("[{}] Cooldown: {} barras ({}h)", self.name, bars, bars * 15 // 60)

    def _in_cooldown(self) -> bool:
        return int(self._state.get("_cooldown_bars_left", 0)) > 0

    def _tick_cooldown(self) -> None:
        left = int(self._state.get("_cooldown_bars_left", 0))
        if left > 0:
            self._state["_cooldown_bars_left"] = left - 1

    # -----------------------------------------------------------------------
    # Gestión de posición — con min_hold_bars
    # -----------------------------------------------------------------------

    def _manage_long(self, price: Decimal, ind: dict) -> None:
        cfg        = self._cfg
        entry      = Decimal(self._state["entry_price"])
        stop       = Decimal(self._state["stop_loss"])
        tp         = Decimal(self._state["take_profit"])
        bars_held  = int(self._state.get("bars_held", 0))

        # ── EXITS DUROS: activos desde el primer bar ──────────────────────
        # Hard stop — red de seguridad vs gaps
        if entry > Decimal("0"):
            loss_pct = float((price - entry) / entry * 100)
            if loss_pct < -cfg.max_loss_pct:
                logger.info("[{}] Hard stop LONG: {:.1f}%", self.name, loss_pct)
                self._close_long(price, "hard_stop")
                self._set_cooldown()
                return

        # ATR stop
        if stop > Decimal("0") and price <= stop:
            logger.info("[{}] ATR stop LONG @ {} <= {}", self.name, price, stop)
            self._close_long(price, "atr_stop")
            self._set_cooldown()
            return

        # TP también es salida DURA — no bloqueado por min_hold.
        # Es la salida más importante: captura el objetivo antes de que el precio revierta.
        if tp > Decimal("0") and price >= tp:
            logger.info("[{}] Take profit LONG @ {}", self.name, price)
            self._close_long(price, "take_profit")
            return

        # ── EXITS SUAVES: solo tras el período mínimo de holding ──────────
        if bars_held < cfg.min_hold_bars:
            return

        # Trailing stop: actualizar pico y cerrar si cae X% desde el máximo post-entrada.
        if cfg.trailing_stop_pct > 0 and entry > Decimal("0"):
            peak = Decimal(str(self._state.get("_peak_price", "0") or "0"))
            if price > peak:
                peak = price
                self._state["_peak_price"] = str(peak)
            profit_pct = float((price - entry) / entry)
            if (peak > entry
                    and profit_pct >= cfg.trailing_min_profit
                    and float((price - peak) / peak) < -cfg.trailing_stop_pct):
                logger.info(
                    "[{}] Trailing stop LONG: pico={} actual={} ({:.1f}% desde pico)",
                    self.name, float(peak), float(price),
                    float((price - peak) / peak * 100),
                )
                self._close_long(price, "trailing_stop")
                self._set_cooldown()
                return

        # RSI exit: si RSI > 75 y posicion en ganancia — captura el momentum sobrecomprado.
        # Esta logica tenia 98%+ WR en v1 (15m). Se recupera aqui para 1H.
        rsi = ind.get("rsi", 50.0)
        if rsi > 75.0 and entry > Decimal("0") and price > entry:
            logger.info(
                "[{}] RSI sobrecomprado ({:.1f}) con ganancia — cerrando LONG", self.name, rsi
            )
            self._close_long(price, "rsi_exit")
            return

        ls = self._long_score(ind)
        if ls < cfg.exit_score_floor:
            logger.info("[{}] Score LONG={} < {} — cerrando", self.name, ls, cfg.exit_score_floor)
            self._close_long(price, "score_floor")

    def _manage_short(self, price: Decimal, ind: dict) -> None:
        cfg        = self._cfg
        entry      = Decimal(self._state["entry_price"])
        stop       = Decimal(self._state["stop_loss"])
        tp         = Decimal(self._state["take_profit"])
        bars_held  = int(self._state.get("bars_held", 0))

        # ── EXITS DUROS: activos desde el primer bar ──────────────────────
        if entry > Decimal("0"):
            loss_pct = float((entry - price) / entry * 100)
            if loss_pct < -cfg.max_loss_pct:
                logger.info("[{}] Hard stop SHORT: {:.1f}%", self.name, loss_pct)
                self._close_short(price, "hard_stop")
                self._set_cooldown()
                return

        if stop > Decimal("0") and price >= stop:
            logger.info("[{}] ATR stop SHORT @ {} >= {}", self.name, price, stop)
            self._close_short(price, "atr_stop")
            self._set_cooldown()
            return

        # TP salida dura — capturar objetivo antes de reversión
        if tp > Decimal("0") and price <= tp:
            logger.info("[{}] Take profit SHORT @ {}", self.name, price)
            self._close_short(price, "take_profit")
            return

        # ── EXITS SUAVES: solo tras el período mínimo de holding ──────────
        if bars_held < cfg.min_hold_bars:
            return

        ss = self._short_score(ind)
        if ss < cfg.exit_score_floor:
            logger.info("[{}] Score SHORT={} < {} — cerrando", self.name, ss, cfg.exit_score_floor)
            self._close_short(price, "score_floor")

    # -----------------------------------------------------------------------
    # Tick principal
    # -----------------------------------------------------------------------

    def run(self) -> None:
        ind = self._build_indicators()
        if ind is None:
            return

        self._tick_cooldown()

        price = Decimal(str(ind["price"]))
        pos   = self._state["position"]
        ls    = self._long_score(ind)
        ss    = self._short_score(ind)

        # === Journal: capturar estado PRE-acción ===
        _pos_before     = pos
        _balance_before = float(self._client.get_balance().get("USDT", Decimal("0")))
        _ts_now         = self._client.current_time().isoformat()

        if pos == "long":
            self._state["bars_held"] = int(self._state.get("bars_held", 0)) + 1
            self._manage_long(price, ind)
        elif pos == "short":
            self._state["bars_held"] = int(self._state.get("bars_held", 0)) + 1
            self._manage_short(price, ind)
        else:
            if not self._in_cooldown():
                cfg = self._cfg
                # Hard gates: 1H + 4H + diario deben estar alineados con la dirección.
                # Esto elimina las operaciones contra la tendencia estructural,
                # que son el principal origen de pérdidas en mercados trending.
                now    = self._client.current_time()
                macro  = get_macro_signal(now)
                market = get_market_context(now)

                adx_ok = (
                    cfg.daily_adx_min <= 0
                    or ind["daily_adx"] >= cfg.daily_adx_min
                )
                weekly_ok = (
                    not cfg.weekly_trend_filter
                    or ind["weekly_trend_up"] is not False  # None = sin datos → no bloquear
                )
                macro_ok = (
                    not cfg.use_macro_filter
                    or not macro["long_reduce_risk"]  # bloquear si MVRV >= 2.5
                )
                market_ok = (
                    not cfg.use_market_filter
                    or (not market["dxy_headwind"] and not market["risk_off"])
                )
                long_ok  = (
                    ls >= cfg.entry_score_min
                    and ls >= ss + cfg.entry_score_gap
                    and ind["h1_trend_up"]
                    and ind["h1_macd_above"]
                    and ind["h4_trend_up"]            # 4H también alcista
                    and ind["daily_trend_up"]         # precio sobre EMA50D diaria
                    and adx_ok                        # ADX > 20: mercado tendiendo
                    and weekly_ok                     # EMA10W > EMA20W: macro alcista
                    and macro_ok                      # MVRV < 2.5: no euforia
                    and market_ok                     # DXY y NASDAQ sin señal adversa
                )
                short_ok = (
                    cfg.allow_shorts
                    and ss >= cfg.entry_score_min
                    and ss >= ls + cfg.entry_score_gap
                    and ind["h1_trend_down"]
                    and not ind["h1_macd_above"]
                    and not ind["h4_trend_up"]        # 4H bajista
                    and not ind["daily_trend_up"]     # precio bajo EMA50D
                    and adx_ok
                )

                if long_ok:
                    logger.info(
                        "[{}] Señal LONG — score={}/{} | 1H={} 4H={} D={} W={} adx={:.0f} mvrv={}",
                        self.name, ls, ss,
                        "bull" if ind["h1_trend_up"] else "bear",
                        "bull" if ind["h4_trend_up"] else "bear",
                        f"{ind['daily_ema20d']:.0f}",
                        "bull" if ind["weekly_trend_up"] else "bear",
                        ind["daily_adx"],
                        round(macro.get("mvrv", 0), 2),
                    )
                    self._open_long(price, ind["atr"])
                elif short_ok:
                    logger.info(
                        "[{}] Señal SHORT — score={}/{} | 1H={} 4H={} D={}",
                        self.name, ss, ls,
                        "bear" if ind["h1_trend_down"] else "bull",
                        "bear" if not ind["h4_trend_up"] else "bull",
                        f"{ind['daily_ema20d']:.0f}",
                    )
                    self._open_short(price, ind["atr"])

        self._save_state()

        # === Journal: detectar transiciones de posición ===
        _pos_after = self._state["position"]
        if _pos_before != _pos_after:
            _ind_snap = {
                "price":           round(ind["price"], 2),
                "ema_fast":        round(ind["ema_fast"], 2),
                "ema_mid":         round(ind["ema_mid"], 2),
                "ema_slow":        round(ind["ema_slow"], 2),
                "macd_hist":       round(ind["macd_hist"], 4),
                "macd_cross_up":   ind["macd_cross_up"],
                "macd_cross_down": ind["macd_cross_down"],
                "rsi":             round(ind["rsi"], 1),
                "atr":             round(ind["atr"], 2),
                "bb_mid":          round(ind["bb_mid"], 2),
                "vwap":            round(ind["vwap"], 2),
                "vol_spike_up":    ind["vol_spike_up"],
                "vol_spike_dn":    ind["vol_spike_dn"],
                "h1_trend_up":     ind["h1_trend_up"],
                "h1_trend_down":   ind["h1_trend_down"],
                "h1_macd_above":   ind["h1_macd_above"],
                "h4_trend_up":     ind["h4_trend_up"],
                "daily_trend_up":  ind["daily_trend_up"],
                "daily_ema20d":    round(ind["daily_ema20d"], 2),
                "score_long":      ls,
                "score_short":     ss,
            }
            _bal_after = float(self._client.get_balance().get("USDT", Decimal("0")))

            if _pos_before in ("long", "short"):
                _open_ts = (self._pending_journal_entry or {}).get("open", {}).get("timestamp")
                if _open_ts:
                    try:
                        _hold_h = (
                            datetime.fromisoformat(_ts_now)
                            - datetime.fromisoformat(_open_ts)
                        ).total_seconds() / 3600
                    except Exception:
                        _hold_h = 0.0
                else:
                    _hold_h = 0.0
                self._journal_close(
                    ts=_ts_now, price=float(price),
                    pnl=self._last_close_pnl, reason=self._last_close_reason,
                    holding_hours=_hold_h, balance_after=_bal_after,
                    ls=ls, ss=ss, indicators=_ind_snap,
                )

            if _pos_after in ("long", "short"):
                _stop_val = float(Decimal(self._state.get("stop_loss",   "0") or "0"))
                _tp_val   = float(Decimal(self._state.get("take_profit", "0") or "0"))
                _qty_val  = float(Decimal(self._state.get("position_qty","0") or "0"))
                self._journal_open(
                    side=_pos_after, ts=_ts_now, price=float(price),
                    invest=self._last_open_invest, stop=_stop_val, tp=_tp_val, qty=_qty_val,
                    balance_before=_balance_before,
                    ls=ls, ss=ss, indicators=_ind_snap,
                )

    # -----------------------------------------------------------------------
    # Abstractos requeridos
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        if self._state.get("position") != "none" or self._in_cooldown():
            return False
        ind = self._build_indicators()
        if ind is None:
            return False
        cfg = self._cfg
        ls  = self._long_score(ind)
        ss  = self._short_score(ind)
        adx_ok    = cfg.daily_adx_min <= 0 or ind["daily_adx"] >= cfg.daily_adx_min
        weekly_ok = not cfg.weekly_trend_filter or ind["weekly_trend_up"] is not False
        now       = self._client.current_time()
        macro_ok  = not cfg.use_macro_filter or not get_macro_signal(now)["long_reduce_risk"]
        mkt       = get_market_context(now)
        market_ok = not cfg.use_market_filter or (not mkt["dxy_headwind"] and not mkt["risk_off"])
        return (
            (ls >= cfg.entry_score_min and ls >= ss + cfg.entry_score_gap
             and ind["h1_trend_up"] and ind["h1_macd_above"]
             and ind["h4_trend_up"] and ind["daily_trend_up"]
             and adx_ok and weekly_ok and macro_ok and market_ok)
            or
            (cfg.allow_shorts
             and ss >= cfg.entry_score_min and ss >= ls + cfg.entry_score_gap
             and ind["h1_trend_down"] and not ind["h1_macd_above"]
             and not ind["h4_trend_up"] and not ind["daily_trend_up"] and adx_ok)
        )

    def should_exit(self) -> bool:
        return self._state.get("position") == "none"
