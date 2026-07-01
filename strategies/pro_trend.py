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
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from loguru import logger

from core.database import get_or_create_bot_state, upsert_position, close_position
from core.exchange import OrderResult
from strategies.base_strategy import BaseStrategy
from strategies.macro_context import get_macro_signal
from strategies.market_context import get_market_context
from strategies.indicators import (
    ema, sma as compute_sma, macd as compute_macd, atr as compute_atr,
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
    atr_stop_mult: float = 3.0

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
    entry_score_min:       int = 9   # v11: subido de 7 — todos los ganadores tuvieron score>=9
    adx_min_entry:         float = 15.0  # v12: ADX mínimo en entrada — bloquea mercados sin tendencia
    entry_score_min_short: int = 9   # umbral más alto para shorts (más confirmación)
    entry_score_gap:       int = 2   # ventaja mínima sobre el opuesto para entrar
    exit_score_floor:      int = 3   # cierre si score cae por debajo

    # Sizing adaptativo por score × fase del ciclo
    size_ultra:     Decimal = Decimal("0.90")  # score ≥ 8 en post_halving/bull_peak
    size_high:      Decimal = Decimal("0.80")  # score ≥ 8 fuera de bull phase
    size_mid:       Decimal = Decimal("0.60")  # score < 8
    size_short_cap: Decimal = Decimal("0.15")  # cap absoluto para shorts

    # Filtros de mercado global (DXY / NASDAQ-100)
    dxy_headwind_pct:      float = 1.5   # DXY sube >X% en lookback → bloquear longs
    ndx_risk_off_pct:      float = 5.0   # NASDAQ cae >X% en lookback → entorno risk-off
    market_filter_lookback: int  = 10    # días para calcular el cambio porcentual

    # Trailing stop dinámico. En post_halving/bull_peak usa trailing_stop_pct_bull (mas amplio)
    # para no ser expulsado en las correcciones normales del ciclo (20-28% en bull markets).
    # En bear/accumulation usa trailing_stop_pct (ajustado). 0.0 = desactivado.
    trailing_stop_pct: float = 0.22       # trailing en bear/accumulation o fase desconocida
    trailing_stop_pct_bull: float = 0.28  # trailing en post_halving/bull_peak (mas tolerante)

    # Cooldown tras trailing stop: en bull phase no hay cambio estructural, re-entrada rapida.
    # En bear/accumulation usar cooldown_bear_days (30 dias).
    cooldown_trailing_bull_days: int = 7  # dias cooldown tras trailing en post_halving/bull_peak

    # Cooldown tras ATR stop: 30 dias (evita re-entrada inmediata en el mismo nivel de precio).
    # Aumentado de 5 dias (cooldown_bars) para evitar clusters de ATR stops consecutivos.
    cooldown_atr_stop_days: int = 30

    # Shorts: desactivados por defecto en mercado secular alcista.
    # Para activar: --config '{"allow_shorts": true}'
    allow_shorts: bool = False

    # MACD exit: False = la estrategia solo sale por trailing stop, ATR stop,
    # bear_confirmed y score_floor. Backtest 2018-2026 muestra +203% sin MACD exit
    # vs +117% con el — el MACD cortaba tendencias grandes en multiple trades pequenos.
    # Activar con --config '{"macd_exit_enabled": true}' para reproducir comportamiento anterior.
    macd_exit_enabled: bool = False

    # Pi Cycle Top: accion cuando SMA111D > 2xSMA350D.
    # "exit_full"     → cierra posicion completa (defecto historico)
    # "exit_half"     → vende 50% y deja correr el resto
    # "block_entries" → solo bloquea nuevas entradas, no toca posicion abierta
    pi_cycle_action:   str  = "exit_full"
    pi_cycle_enabled:  bool = True    # False para activos no-BTC (ETH/SOL/BNB)

    # Filtro RSI en entrada: bloquea long si RSI > umbral.
    # 0.0 = desactivado. Activa con entry_rsi_max=72 para evitar entradas sobrecompradas.
    entry_rsi_max: float = 0.0

    # Extension ATR respecto a EMA20D: bloquea long si precio > EMA20D + N×ATR.
    # 0.0 = desactivado. Activa con entry_max_ema20_atr=2.5 para evitar entradas extendidas.
    entry_max_ema20_atr: float = 0.0

    # Cooldown: días sin entrar tras un ATR stop-out normal
    cooldown_bars: int = 5
    # Cooldown extendido: tras bear_confirmed o trailing_stop (mercado giró estructuralmente)
    cooldown_bear_days: int = 30

    # Hard stop: cierra la posición si la pérdida supera este % del precio de entrada,
    # independientemente del ATR stop (red de seguridad contra gaps y rallies violentos).
    max_loss_pct: float = 20.0

    # Partial exit: vende partial_exit_size de la posicion cuando la ganancia no realizada
    # supera partial_exit_pct %. Reduce la concentracion en trades excepcionales.
    # 150.0 confirmado por backtest 2018-2026 y 2015-2026: +1pp CAGR, mejor PF, DD neutro.
    # La posicion restante sigue con trailing stop normal.
    # Ablation: --config '{"partial_exit_pct": 0.0}' para desactivar, '{"partial_exit_pct": 200.0}' neutral.
    partial_exit_pct:  float = 150.0
    partial_exit_size: float = 0.33   # fraccion a vender en el evento (0.33 = 33%)

    # Historial: 625 dias (~87 semanas), suficiente para EMA350D del Pi Cycle Top
    lookback_hours: int = 15000

    # Ablation: deshabilita todos los filtros de datos externos (MVRV, halving, VIX,
    # DXY, NASDAQ, funding, Pi Cycle Top) para aislar el valor de la logica tecnica pura.
    # Uso: --config '{"disable_external_filters": true}'
    disable_external_filters: bool = False

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
            adx_min_entry=float(d.get("adx_min_entry", _c.adx_min_entry)),
            entry_score_min_short=int(d.get("entry_score_min_short", _c.entry_score_min_short)),
            entry_score_gap=int(d.get("entry_score_gap", _c.entry_score_gap)),
            exit_score_floor=int(d.get("exit_score_floor", _c.exit_score_floor)),
            size_ultra=Decimal(str(d.get("size_ultra", str(_c.size_ultra)))),
            size_high=Decimal(str(d.get("size_high", str(_c.size_high)))),
            size_mid=Decimal(str(d.get("size_mid", str(_c.size_mid)))),
            size_short_cap=Decimal(str(d.get("size_short_cap", str(_c.size_short_cap)))),
            dxy_headwind_pct=float(d.get("dxy_headwind_pct", _c.dxy_headwind_pct)),
            ndx_risk_off_pct=float(d.get("ndx_risk_off_pct", _c.ndx_risk_off_pct)),
            market_filter_lookback=int(d.get("market_filter_lookback", _c.market_filter_lookback)),
            cooldown_bars=int(d.get("cooldown_bars", _c.cooldown_bars)),
            cooldown_bear_days=int(d.get("cooldown_bear_days", _c.cooldown_bear_days)),
            max_loss_pct=float(d.get("max_loss_pct", _c.max_loss_pct)),
            lookback_hours=int(d.get("lookback_hours", _c.lookback_hours)),
            trailing_stop_pct=float(d.get("trailing_stop_pct", _c.trailing_stop_pct)),
            trailing_stop_pct_bull=float(d.get("trailing_stop_pct_bull", _c.trailing_stop_pct_bull)),
            cooldown_trailing_bull_days=int(d.get("cooldown_trailing_bull_days", _c.cooldown_trailing_bull_days)),
            cooldown_atr_stop_days=int(d.get("cooldown_atr_stop_days", _c.cooldown_atr_stop_days)),
            allow_shorts=bool(d.get("allow_shorts", _c.allow_shorts)),
            pi_cycle_action=str(d.get("pi_cycle_action", _c.pi_cycle_action)),
            pi_cycle_enabled=bool(d.get("pi_cycle_enabled", _c.pi_cycle_enabled)),
            entry_rsi_max=float(d.get("entry_rsi_max", _c.entry_rsi_max)),
            entry_max_ema20_atr=float(d.get("entry_max_ema20_atr", _c.entry_max_ema20_atr)),
            macd_exit_enabled=bool(d.get("macd_exit_enabled", _c.macd_exit_enabled)),
            partial_exit_pct=float(d.get("partial_exit_pct", _c.partial_exit_pct)),
            partial_exit_size=float(d.get("partial_exit_size", _c.partial_exit_size)),
            disable_external_filters=bool(d.get("disable_external_filters", _c.disable_external_filters)),
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
            "adx_min_entry": self.adx_min_entry,
            "entry_score_min_short": self.entry_score_min_short,
            "entry_score_gap": self.entry_score_gap,
            "exit_score_floor": self.exit_score_floor,
            "size_ultra": str(self.size_ultra),
            "size_high": str(self.size_high),
            "size_mid": str(self.size_mid),
            "size_short_cap": str(self.size_short_cap),
            "dxy_headwind_pct": self.dxy_headwind_pct,
            "ndx_risk_off_pct": self.ndx_risk_off_pct,
            "market_filter_lookback": self.market_filter_lookback,
            "cooldown_bars": self.cooldown_bars,
            "cooldown_bear_days": self.cooldown_bear_days,
            "max_loss_pct": self.max_loss_pct,
            "lookback_hours": self.lookback_hours,
            "trailing_stop_pct": self.trailing_stop_pct,
            "allow_shorts": self.allow_shorts,
            "pi_cycle_action":  self.pi_cycle_action,
            "pi_cycle_enabled": self.pi_cycle_enabled,
            "entry_rsi_max": self.entry_rsi_max,
            "entry_max_ema20_atr": self.entry_max_ema20_atr,
            "macd_exit_enabled": self.macd_exit_enabled,
            "partial_exit_pct": self.partial_exit_pct,
            "partial_exit_size": self.partial_exit_size,
            "disable_external_filters": self.disable_external_filters,
            "trailing_stop_pct_bull": self.trailing_stop_pct_bull,
            "cooldown_trailing_bull_days": self.cooldown_trailing_bull_days,
            "cooldown_atr_stop_days": self.cooldown_atr_stop_days,
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
            "peak_price":   "0",       # máximo desde entrada para trailing stop y MFE
            "trough_price": "0",       # mínimo desde entrada para MAE
            "margin_usdt": "0",
            "half_reduced": False,
            "partial_exited": False,  # True cuando ya se ejecutó la partial exit de ganancias
            "prev_macd_above": None,
            "prev_weekly_up": None,
            "_cooldown_until": None,
            "_consecutive_losses": 0,
            "_consec_cooldown_until": None,
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

        # Pi Cycle Top: SMA111D > 2×SMA350D — señal histórica de techo de ciclo BTC.
        # Solo significativo para BTC. Deshabilitado para ETH/SOL/BNB via cfg.pi_cycle_enabled.
        if cfg.pi_cycle_enabled and len(daily) >= 360:
            sma111d_s = compute_sma(close, 111)
            sma350d_s = compute_sma(close, 350)
            pi_top = bool(
                self._safe_float(sma111d_s.iloc[-1]) > 2 * self._safe_float(sma350d_s.iloc[-1])
            )
        else:
            pi_top = False

        ind = {
            "close":        self._safe_float(close.iloc[-1]),
            "ema_20d":      self._safe_float(ema20d.iloc[-1]),
            "ema_50d":      self._safe_float(ema50d.iloc[-1]),
            "ema_200d":     self._safe_float(ema200d.iloc[-1]),
            "macd_above":   bool(self._safe_float(macd_line.iloc[-1]) > self._safe_float(sig_line.iloc[-1])),
            "atr":          self._safe_float(atr_s.iloc[-1]),
            "rsi":          self._safe_float(rsi_s.iloc[-1]),
            "adx":          self._safe_float(adx_s.iloc[-1]),
            "obv_slope":    obv_sl,
            "ema50_slope":  e50_sl,
            "ema200_slope": e200_sl,
            "vol_last":     self._safe_float(volume.iloc[-1]),
            "vol_ma":       self._safe_float(vol_ma.iloc[-1]),
            "bb_width":     self._safe_float(bb_width_s.iloc[-1]),
            "bb_pct_b":     self._safe_float(bb_pct_b_s.iloc[-1]) if not math.isnan(self._safe_float(bb_pct_b_s.iloc[-1])) else 0.5,
            "swing":        swing,
            "support":      sup,
            "resistance":   res,
            "rsi_div":      rsi_div,
            "vp_poc":       vp_poc,
            "vp_vah":       vp_vah,
            "vp_val":       vp_val,
            "pi_cycle_top": pi_top,
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

        # Excluir el bloque 4H actual si esta incompleto (mismo patron que daily/weekly).
        # La clave h4_key es "YYYY-MM-DD-N" donde N = hora_inicio // 4.
        if len(df4) > 0 and "dt" in df4.columns:
            last_4h_dt = pd.to_datetime(df4.iloc[-1]["dt"])
            last_h4_key = f"{last_4h_dt.date().isoformat()}-{last_4h_dt.hour // 4}"
            if last_h4_key == h4_key:
                df4 = df4.iloc[:-1]

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

    def _size_pct(
        self,
        score: int,
        side: str,
        reduce_risk: bool = False,
        halving_phase: str = "",
        vix_elevated: bool = False,
    ) -> Decimal:
        cfg = self._cfg

        if side == "short":
            return cfg.size_short_cap

        # Fase alcista del ciclo: post_halving (0-180d) y bull_peak (180-540d)
        in_bull_phase = halving_phase in ("post_halving", "bull_peak")

        # Tiers de sizing por fase × score.
        if in_bull_phase and score >= 8:
            base = cfg.size_ultra    # 90%: bull confirmado con señal fuerte
        elif score >= 8:
            base = cfg.size_high     # 80%: señal fuerte fuera de bull phase
        else:
            base = cfg.size_mid      # 60%: señal moderada

        # MVRV en zona de euforia: recortar drásticamente (posible techo de ciclo)
        if reduce_risk:
            base = min(base, Decimal("0.20"))
        elif halving_phase == "bear_onset":
            # Fase de inicio bajista: conservar capital sin penalizar acumulación
            base = (base * Decimal("0.75")).quantize(Decimal("0.01"))

        # Layer 1 — VIX elevado: miedo de mercado real, cap en size_mid (60%)
        if vix_elevated and base > cfg.size_mid:
            base = cfg.size_mid

        return base

    def _size_journal_snapshot(
        self,
        score: int,
        side: str,
        macro: dict,
        market: dict,
        balance_before: float,
        invest: float | None = None,
    ) -> dict:
        """Snapshot de sizing para auditoria; no participa en decisiones."""
        cfg = self._cfg
        phase = macro.get("halving_phase", "")
        reduce_risk = bool(macro.get("long_reduce_risk", False))
        vix_elevated_raw = bool(market.get("vix_elevated", False))
        vix_elevated_for_size = vix_elevated_raw and not cfg.disable_external_filters

        if side == "short":
            tier = "short_cap"
        elif phase in ("post_halving", "bull_peak") and score >= 8:
            tier = "ultra"
        elif score >= 8:
            tier = "high"
        else:
            tier = "mid"

        planned = self._size_pct(
            score, side,
            reduce_risk=reduce_risk,
            halving_phase=phase,
            vix_elevated=vix_elevated_for_size,
        )
        no_vix = self._size_pct(
            score, side,
            reduce_risk=reduce_risk,
            halving_phase=phase,
            vix_elevated=False,
        )

        actual = None
        if invest is not None and balance_before > 0:
            actual = invest / balance_before
        actual_delta_pct = (
            (actual - float(planned)) * 100
            if actual is not None
            else None
        )

        return {
            "size_tier":              tier,
            "planned_size_fraction":  float(planned),
            "planned_size_pct":       round(float(planned) * 100, 2),
            "size_without_vix_pct":   round(float(no_vix) * 100, 2),
            "actual_size_fraction":   round(actual, 6) if actual is not None else None,
            "actual_size_pct":        round(actual * 100, 2) if actual is not None else None,
            "actual_minus_planned_size_pct": round(actual_delta_pct, 2) if actual_delta_pct is not None else None,
            "invest_usdt":            round(invest, 2) if invest is not None else None,
            "balance_before_usdt":    round(balance_before, 2),
            "mvrv_cap_applied":       reduce_risk,
            "bear_onset_reduction":   phase == "bear_onset",
            "vix_cap_expected":       vix_elevated_for_size and planned < no_vix,
            "vix_elevated":           vix_elevated_raw,
            "vix_elevated_for_size":  vix_elevated_for_size,
            "vix_cap_disabled_by_ablation": vix_elevated_raw and cfg.disable_external_filters,
            "vix_extreme":            bool(market.get("vix_extreme", False)),
        }

    # -----------------------------------------------------------------------
    # Acciones — longs
    # -----------------------------------------------------------------------

    def _open_long(
        self,
        price: Decimal,
        score: int,
        atr_val: float,
        vix_elevated: bool | None = None,
    ) -> None:
        cfg  = self._cfg
        usdt = self._client.get_balance().get("USDT", Decimal("0"))
        macro = getattr(self, "_current_macro", {})
        if vix_elevated is None:
            market = getattr(self, "_current_market", {})
            vix_elevated = bool(market.get("vix_elevated", False))
        if cfg.disable_external_filters:
            vix_elevated = False
        invest = (usdt * self._size_pct(
            score, "long",
            reduce_risk=macro.get("long_reduce_risk", False),
            halving_phase=macro.get("halving_phase", ""),
            vix_elevated=vix_elevated,
        )).quantize(Decimal("0.01"))

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
        self._last_open_invest = float(invest)
        self.log_trade(result)
        self._state.update({
            "position":     "long",
            "entry_price":  str(result.filled_price),
            "position_qty": str(result.filled_qty),
            "stop_loss":    str(stop),
            "peak_price":   str(result.filled_price),
            "trough_price": str(result.filled_price),
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
            self._last_close_pnl    = float(pnl)
            self._last_close_reason = reason
            self.log_trade(result, pnl=pnl)
            logger.info(
                "[{}] LONG cerrado ({}) @ {} | PnL={:.2f} USDT",
                self.name, reason, result.filled_price, pnl,
            )
            close_position(self._session, self._cfg.symbol, self.name)
            self._track_loss_streak(float(pnl))
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
        self._last_open_invest = float(margin)

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

        self._last_close_pnl    = float(net_pnl)
        self._last_close_reason = reason
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

    def _reduce_long_partial(self, reason: str) -> None:
        """Vende partial_exit_size de la posicion long abierta. Solo se ejecuta una vez."""
        cfg   = self._cfg
        qty   = Decimal(self._state["position_qty"])
        entry = Decimal(self._state["entry_price"])
        sell  = (qty * Decimal(str(cfg.partial_exit_size))).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )
        if sell <= Decimal("0"):
            return

        result = self._client.place_order(
            cfg.symbol, "sell", "market", sell, strategy=self.name
        )
        if result.status == "filled" and result.filled_price:
            pnl = (result.filled_price - entry) * result.filled_qty - result.fee
            self.log_trade(result, pnl=pnl)
            self._state["position_qty"] = str(qty - sell)
            self._state["partial_exited"] = True
            self._save_state()
            logger.info(
                "[{}] LONG partial exit ({:.0f}%) @ {} | {} | PnL parcial={:.2f} USDT",
                self.name, cfg.partial_exit_size * 100, result.filled_price, reason, pnl,
            )

    # -----------------------------------------------------------------------
    # Reset
    # -----------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._state.update({
            "position":       "none",
            "entry_price":    "0",
            "position_qty":   "0",
            "stop_loss":      "0",
            "peak_price":     "0",
            "trough_price":   "0",
            "margin_usdt":    "0",
            "half_reduced":   False,
            "partial_exited": False,
        })
        self._save_state()

    # -----------------------------------------------------------------------
    # Cooldown post stop-out
    # -----------------------------------------------------------------------

    def _track_loss_streak(self, pnl: float) -> None:
        """Tras 2 perdidas consecutivas activa cooldown extra para evitar re-entradas en pullback."""
        from datetime import timedelta
        if pnl < 0:
            streak = int(self._state.get("_consecutive_losses", 0)) + 1
            self._state["_consecutive_losses"] = streak
            if streak >= 2:
                until = (
                    self._client.current_time().date() + timedelta(days=15)
                ).isoformat()
                self._state["_consec_cooldown_until"] = until
                self._state["_consecutive_losses"] = 0
                logger.info(
                    "[{}] {} perdidas consecutivas — cooldown extra 15 dias hasta {}",
                    self.name, streak, until,
                )
        else:
            self._state["_consecutive_losses"] = 0

    def _set_cooldown(self, days: int | None = None) -> None:
        """Bloquea nuevas entradas durante N días.
        Si days=None, usa cooldown_bars (salidas normales).
        Pasar cooldown_bear_days para salidas estructurales (bear_confirmed, trailing_stop).
        """
        from datetime import timedelta
        n = days if days is not None else self._cfg.cooldown_bars
        if n > 0:
            until = (
                self._client.current_time().date() + timedelta(days=n)
            ).isoformat()
            self._state["_cooldown_until"] = until
            self._save_state()
            logger.debug("[{}] Cooldown {} días activo hasta {}", self.name, n, until)

    # -----------------------------------------------------------------------
    # Gestión de posiciones abiertas
    # -----------------------------------------------------------------------

    def _manage_long(
        self, daily: dict, weekly: dict, h1: dict,
        price: Decimal, ls: int, ss: int,
    ) -> None:
        cfg   = self._cfg
        stop  = Decimal(self._state["stop_loss"])
        entry = Decimal(self._state["entry_price"])
        prev_macd = self._state.get("prev_macd_above")

        # ── Actualizar el máximo y mínimo desde entrada (trailing stop / MAE-MFE) ──
        peak = Decimal(self._state.get("peak_price") or "0")
        if price > peak:
            peak = price
            self._state["peak_price"] = str(peak)
        trough = Decimal(self._state.get("trough_price") or "0") or price
        if price < trough:
            self._state["trough_price"] = str(price)

        # 1. Trailing stop dinámico con pct adaptativo por fase del ciclo.
        #    post_halving/bull_peak: trailing_stop_pct_bull (28%) — aguanta correcciones normales
        #    bear/accumulation: trailing_stop_pct (22%) — proteccion ajustada
        #    Razon: BTC corrige 20-28% regularmente en bull markets sin romper estructura.
        #    Un trailing del 22% expulsa en correcciones validas, el 28% no.
        _macro_ctx  = getattr(self, "_current_macro", {})
        _phase      = _macro_ctx.get("halving_phase", "")
        _in_bull    = _phase in ("post_halving", "bull_peak")
        _trail_pct  = (
            cfg.trailing_stop_pct_bull
            if (_in_bull and cfg.trailing_stop_pct_bull > 0)
            else cfg.trailing_stop_pct
        )
        if _trail_pct > 0 and peak > Decimal("0"):
            trail = peak * (Decimal("1") - Decimal(str(_trail_pct)))
            if price < trail:
                logger.info(
                    "[{}] Trailing stop LONG: {} < {:.2f} ({:.0f}% desde pico {}) | phase={}",
                    self.name, price, trail, _trail_pct * 100, peak, _phase,
                )
                self._close_long(price, "trailing_stop")
                # Cooldown adaptativo: en bull phase no hay cambio estructural → re-entrada rapida.
                # En bear/accumulation esperar consolidacion completa.
                if _in_bull:
                    self._set_cooldown(cfg.cooldown_trailing_bull_days)
                else:
                    self._set_cooldown(cfg.cooldown_bear_days)
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
                self._set_cooldown(15)
                return

        # 3. ATR stop inicial.
        #    Cooldown extendido (30 dias) para evitar re-entrada inmediata en el mismo nivel
        #    de precio — patrón observado en Q2/Q3 2024 (Trade 8 + Trade 9 consecutivos).
        if stop > Decimal("0") and price <= stop:
            logger.info("[{}] ATR stop LONG @ {} <= {}", self.name, price, stop)
            self._close_long(price, "atr_stop")
            self._set_cooldown(cfg.cooldown_atr_stop_days)
            return

        # 3.5. Pi Cycle Top: SMA111D > 2×SMA350D — señal histórica de techo de ciclo BTC.
        # Ha marcado cada ATH dentro de 3 dias. Accion configurable via pi_cycle_action.
        if daily.get("pi_cycle_top", False):
            action = cfg.pi_cycle_action
            if action == "exit_full":
                logger.info("[{}] Pi Cycle Top (SMA111D > 2xSMA350D) — salida total", self.name)
                self._close_long(price, "pi_cycle_top")
                self._set_cooldown(cfg.cooldown_bear_days)
                return
            elif action == "exit_half":
                if not self._state.get("half_reduced", False):
                    logger.info("[{}] Pi Cycle Top — reduccion 50%", self.name)
                    self._reduce_long_half(price)
                # Sigue gestionando la posicion restante con trailing stop
            elif action == "block_entries":
                pass  # Solo bloquea nuevas entradas (gestionado en long_ok); no toca posicion

        # 4. Partial exit: captura ganancias extremas para reducir concentracion.
        #    Vende partial_exit_size una sola vez cuando la ganancia supera partial_exit_pct %.
        #    La posicion restante continua con trailing stop y todas las salidas normales.
        if (cfg.partial_exit_pct > 0 and entry > Decimal("0")
                and not self._state.get("partial_exited", False)):
            gain_pct = float((price - entry) / entry * 100)
            if gain_pct >= cfg.partial_exit_pct:
                logger.info(
                    "[{}] Partial exit: +{:.1f}% >= {:.0f}% umbral — vendiendo {:.0f}% de la posicion",
                    self.name, gain_pct, cfg.partial_exit_pct, cfg.partial_exit_size * 100,
                )
                self._reduce_long_partial("partial_exit_gains")

        # 5. Flip semanal CON confirmación estructural bajista (precio bajo EMA200D)
        #    → No salir en correcciones normales de bull market, solo en bear confirmado
        if weekly.get("weekly_trend_up") is False and float(price) < daily["ema_200d"]:
            logger.info(
                "[{}] Bear confirmado: weekly bajista + precio ({}) bajo EMA200D ({:.0f})",
                self.name, price, daily["ema_200d"],
            )
            self._close_long(price, "bear_confirmed")
            # Cooldown máximo: cambio estructural, el mercado necesita semanas para
            # confirmar si la tendencia reanuda (evita re-entradas prematuras post-ATH)
            self._set_cooldown(cfg.cooldown_bear_days)
            return

        # 6. MACD death cross + precio bajo EMA20D
        #    Se omite si la posicion lleva >10% de ganancia y el weekly sigue alcista:
        #    en ese caso el trailing stop se encargara de proteger la ganancia.
        #    Desactivable con macd_exit_enabled=False para ablation test.
        macd_cross_dn = not daily["macd_above"] and bool(prev_macd)
        if cfg.macd_exit_enabled and macd_cross_dn and price < daily["ema_20d"]:
            profit_pct = float((price - entry) / entry * 100) if entry > Decimal("0") else 0.0
            weekly_still_up = weekly.get("weekly_trend_up") is True
            if profit_pct > 10.0 and weekly_still_up:
                logger.debug(
                    "[{}] MACD exit diferido — ganancia {:.1f}% + weekly bullish, trailing activo",
                    self.name, profit_pct,
                )
            else:
                logger.info("[{}] MACD death cross + precio < EMA20D — cerrando LONG", self.name)
                self._close_long(price, "macd_exit")
                return

        # 7. Score LONG por debajo del piso mínimo
        if ls < cfg.exit_score_floor:
            logger.info("[{}] Score LONG={} < {} — cerrando", self.name, ls, cfg.exit_score_floor)
            self._close_long(price, "score_floor")
            return

        # 8. Recorte parcial RSI: solo cuando ganancia > 40% y RSI extremamente sobrecomprado
        #    (no a +5% — cortaría los mejores trades del ciclo demasiado pronto)
        if entry > Decimal("0"):
            unreal_pct = float((price - entry) / entry * 100)
            if (daily.get("rsi_div") == "bearish"
                    and daily.get("rsi", 0) > 85.0
                    and unreal_pct > 40.0
                    and not self._state.get("half_reduced")):
                logger.info(
                    "[{}] RSI extremo ({:.0f}) con +{:.1f}% ganancia — reduciendo LONG",
                    self.name, daily.get("rsi", 0), unreal_pct,
                )
                self._reduce_long_half(price)

        # 9. Switch a SHORT solo si shorts están activados y señal contraria es fuerte
        if cfg.allow_shorts and ss >= cfg.entry_score_min and ls < cfg.exit_score_floor + 1:
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
            self._set_cooldown(cfg.cooldown_bear_days)
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
        if cfg.macd_exit_enabled and macd_cross_up and price > daily["ema_20d"]:
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

    def _journal_ind_snapshot(
        self, daily: dict, weekly: dict, h4: dict, h1: dict, ls: int, ss: int
    ) -> dict:
        """Construye un snapshot plano de todos los indicadores para el journal."""
        return {
            # Precio y EMAs diarias
            "close":             round(daily.get("close", 0), 2),
            "ema_20d":           round(daily.get("ema_20d", 0), 2),
            "ema_50d":           round(daily.get("ema_50d", 0), 2),
            "ema_200d":          round(daily.get("ema_200d", 0), 2),
            "ema50_slope":       round(daily.get("ema50_slope", 0), 4),
            "ema200_slope":      round(daily.get("ema200_slope", 0), 4),
            # MACD, RSI, ADX, ATR
            "macd_above":        daily.get("macd_above"),
            "rsi":               round(daily.get("rsi", 0), 1),
            "rsi_div":           daily.get("rsi_div"),
            "adx":               round(daily.get("adx", 0), 1),
            "atr":               round(daily.get("atr", 0), 2),
            # OBV y Bollinger
            "obv_slope":         round(daily.get("obv_slope", 0), 6),
            "bb_pct_b":          round(daily.get("bb_pct_b", 0), 3),
            # Estructura y S/R
            "swing":             daily.get("swing"),
            "support_levels":    [round(x, 2) for x in daily.get("support", [])[:3]],
            "resistance_levels": [round(x, 2) for x in daily.get("resistance", [])[:3]],
            # Volume Profile
            "vp_poc":            round(daily.get("vp_poc") or 0, 2),
            "vp_vah":            round(daily.get("vp_vah") or 0, 2),
            "vp_val":            round(daily.get("vp_val") or 0, 2),
            # Pi Cycle Top
            "pi_cycle_top":      daily.get("pi_cycle_top", False),
            # Semanal
            "weekly_trend_up":   weekly.get("weekly_trend_up"),
            # 4H
            "h4_trend_bullish":  h4.get("trend_bullish"),
            "h4_trend_bearish":  h4.get("trend_bearish"),
            "h4_macd_above":     h4.get("macd_above"),
            "h4_swing":          h4.get("swing"),
            # 1H
            "h1_close":          round(h1.get("close", 0), 2),
            "h1_vol_spike_up":   h1.get("vol_spike_up"),
            "h1_vol_spike_dn":   h1.get("vol_spike_dn"),
            "h1_bb_squeeze":     h1.get("bb_squeeze"),
            "h1_bb_breakout_up": h1.get("bb_breakout_up"),
            "h1_bb_breakout_dn": h1.get("bb_breakout_dn"),
            # Scores
            "score_long":        ls,
            "score_short":       ss,
        }

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
        cfg      = self._cfg

        # Contexto macro y mercado global — calculado una vez por tick.
        # Debe ser ANTES de manage_long/short porque _open_long lo usa via _current_macro.
        macro  = get_macro_signal(self._client.current_time())
        market = get_market_context(
            self._client.current_time(),
            lookback_days=cfg.market_filter_lookback,
            dxy_threshold=cfg.dxy_headwind_pct,
            ndx_threshold=-cfg.ndx_risk_off_pct,
        )
        self._current_macro  = macro
        self._current_market = market
        _vix_elevated_raw = bool(market.get("vix_elevated", False))
        _vix_elevated_for_size = _vix_elevated_raw and not cfg.disable_external_filters
        _entry_gates: dict | None = None
        _entry_funding_rate: float | None = None
        _entry_side: str | None = None

        # === Journal: capturar estado PRE-acción ===
        _pos_before      = position
        _balance_before  = float(self._client.get_balance().get("USDT", Decimal("0")))
        _ts_now          = self._client.current_time().isoformat()
        # Guardar peak/trough/entry/stop ANTES de que _reset_state() los borre al cerrar
        _peak_pre   = float(Decimal(self._state.get("peak_price")   or "0") or "0")
        _trough_pre = float(Decimal(self._state.get("trough_price") or "0") or "0")
        _entry_pre  = float(Decimal(self._state.get("entry_price")  or "0") or "0")
        _stop_pre   = float(Decimal(self._state.get("stop_loss")    or "0") or "0")
        _qty_pre    = float(Decimal(self._state.get("position_qty") or "0") or "0")
        _partial_exited_pre = bool(self._state.get("partial_exited", False))
        _half_reduced_pre   = bool(self._state.get("half_reduced", False))

        if position == "long":
            self._manage_long(daily, weekly, h1, price, ls, ss)
        elif position == "short":
            self._manage_short(daily, weekly, h1, price, ls, ss)
        else:
            current_day    = self._client.current_time().date().isoformat()
            cooldown_until = self._state.get("_cooldown_until")
            consec_until   = self._state.get("_consec_cooldown_until")
            in_cooldown    = bool(
                (cooldown_until and current_day < cooldown_until)
                or (consec_until  and current_day < consec_until)
            )

            if not in_cooldown:
                weekly_trend = weekly.get("weekly_trend_up")
                funding      = self._client.get_funding_rate(cfg.symbol)
                _entry_funding_rate = funding

                # Bear técnico: EMA200D declinando + precio por debajo
                ema_bear = (
                    daily.get("ema200_slope", 0.0) < 0
                    and daily["close"] < daily["ema_200d"]
                )

                realized       = macro.get("realized_price")
                above_realized = realized is None or daily["close"] > realized * 1.1

                funding_ok_long  = funding < 0.0005
                funding_ok_short = funding > -0.0005

                # Filtro RSI en entrada: bloquea si sobrecomprado (configurable, 0=desactivado)
                rsi_entry_ok = cfg.entry_rsi_max <= 0 or daily["rsi"] <= cfg.entry_rsi_max

                # Filtro extension ATR: precio demasiado alejado de EMA20D
                atr_units_ext = 0.0
                atr_ext_ok = True
                if cfg.entry_max_ema20_atr > 0 and daily.get("atr", 0) > 0:
                    atr_units_ext = (daily["close"] - daily["ema_20d"]) / daily["atr"]
                    atr_ext_ok = atr_units_ext <= cfg.entry_max_ema20_atr

                # ---- LAYER 1: régimen macro --------------------------------
                # VIX elevado → cap de sizing (en _size_pct), no umbral más alto.
                # MVRV late_bull/euphoria → hard block via _g_mvrv (long_reduce_risk).
                # El umbral de score es fijo: el cap de tamaño es la herramienta correcta.
                _vix_val        = market.get("vix_level")
                _mvrv_regime    = macro.get("mvrv_regime", "unknown")
                _required_score = cfg.entry_score_min

                # ---- LAYER 1 HARD BLOCK: pánico real (VIX > 35) ---------------
                # En crisis severa la correlación BTC/equity se dispara. No entrar.
                _g_vix_panic = not market.get("vix_extreme", False)

                # ---- Gates individuales (facilita logging y ablation tests) ----
                _g_score   = ls >= _required_score
                _g_gap     = ls > ss + cfg.entry_score_gap
                _g_weekly  = weekly_trend is not False
                _g_h4      = h4.get("trend_bullish") is not False
                _g_mvrv    = not macro["long_reduce_risk"]
                _g_funding = funding_ok_long
                _g_dxy     = not market["dxy_headwind"]    # Layer 2
                _g_ndx     = not market["risk_off"]        # Layer 2
                _g_pi      = not daily.get("pi_cycle_top", False)

                # Ablation: deshabilita todos los filtros externos para aislar
                # el valor de la logica tecnica pura (--config '{"disable_external_filters":true}')
                if cfg.disable_external_filters:
                    _g_vix_panic = True
                    _g_mvrv      = True
                    _g_funding   = True
                    _g_dxy       = True
                    _g_ndx       = True
                    _g_pi        = True
                _g_rsi     = rsi_entry_ok
                _g_atr     = atr_ext_ok
                # v12: ADX mínimo — evita entradas en mercados sin tendencia
                _g_adx_min = daily.get("adx", 99) >= cfg.adx_min_entry
                # v12: momentum cruzado — al menos un timeframe (diario o 4H) con MACD alcista
                _g_macd_momentum = daily.get("macd_above", False) or h4.get("h4_macd_above", True)
                _entry_gates = {
                    "g_vix_panic":       bool(_g_vix_panic),
                    "g_score":           bool(_g_score),
                    "g_gap":             bool(_g_gap),
                    "g_weekly":          bool(_g_weekly),
                    "g_h4":              bool(_g_h4),
                    "g_mvrv":            bool(_g_mvrv),
                    "g_funding":         bool(_g_funding),
                    "g_dxy":             bool(_g_dxy),
                    "g_ndx":             bool(_g_ndx),
                    "g_pi":              bool(_g_pi),
                    "g_rsi":             bool(_g_rsi),
                    "g_atr":             bool(_g_atr),
                    "g_adx_min":         bool(_g_adx_min),
                    "g_macd_momentum":   bool(_g_macd_momentum),
                    "required_score":    _required_score,
                    "score_gap":         ls - ss,
                    "entry_score_gap":   cfg.entry_score_gap,
                    "atr_units_ext":     round(atr_units_ext, 3),
                    "vix_elevated_for_size": _vix_elevated_for_size,
                    "vix_cap_disabled_by_ablation": _vix_elevated_raw and cfg.disable_external_filters,
                }

                long_ok = (
                    _g_vix_panic and _g_score and _g_gap and _g_weekly and _g_h4
                    and _g_mvrv and _g_funding and _g_dxy and _g_ndx
                    and _g_pi and _g_rsi and _g_atr
                    and _g_adx_min and _g_macd_momentum
                )
                _entry_gates["long_ok"] = bool(long_ok)

                # Log detallado cuando score cerca del umbral pero bloqueado
                if not long_ok and ls >= cfg.entry_score_min - 1:
                    _blocks = []
                    if not _g_vix_panic:      _blocks.append(f"VIX={_vix_val:.0f}>35(panico)")
                    if not _g_score:          _blocks.append(f"score={ls}<{_required_score}(req={_required_score})")
                    if not _g_gap:            _blocks.append(f"gap={ls-ss}<={cfg.entry_score_gap}")
                    if not _g_weekly:         _blocks.append("weekly=bajista")
                    if not _g_h4:             _blocks.append("4H=bajista")
                    if not _g_mvrv:           _blocks.append(f"MVRV={round(macro['mvrv'], 2) if macro.get('mvrv') else '?'}")
                    if not _g_funding:        _blocks.append(f"funding={funding:.4f}")
                    if not _g_dxy:            _blocks.append(f"DXY={market['dxy_change']:+.1f}%" if market.get("dxy_change") is not None else "DXY=headwind")
                    if not _g_ndx:            _blocks.append(f"NDX={market['ndx_change']:+.1f}%" if market.get("ndx_change") is not None else "NDX=risk_off")
                    if not _g_pi:             _blocks.append("pi_cycle_top")
                    if not _g_rsi:            _blocks.append(f"RSI={daily['rsi']:.0f}>{cfg.entry_rsi_max:.0f}")
                    if not _g_atr:            _blocks.append(f"ext={atr_units_ext:.1f}ATR>{cfg.entry_max_ema20_atr:.1f}")
                    if not _g_adx_min:        _blocks.append(f"ADX={daily.get('adx', 0):.1f}<{cfg.adx_min_entry}")
                    if not _g_macd_momentum:  _blocks.append("macd_momentum=sin_tendencia_xTF")
                    logger.debug(
                        "[{}] Entrada LONG bloqueada ls={} ss={} req={} vix={} mvrv={} @ {} | {}",
                        self.name, ls, ss, _required_score,
                        f"{_vix_val:.0f}" if _vix_val else "N/D",
                        round(macro["mvrv"], 2) if macro.get("mvrv") else "N/D",
                        self._client.current_time().strftime("%Y-%m-%d"),
                        " | ".join(_blocks) if _blocks else "sin causa clara",
                    )

                short_ok = (
                    cfg.allow_shorts
                    and ss >= cfg.entry_score_min_short
                    and ss > ls + cfg.entry_score_gap
                    and weekly_trend is not True
                    and ema_bear
                    and macro["short_allowed"]
                    and above_realized
                    and h4.get("trend_bearish") is not False
                    and funding_ok_short
                )
                _entry_gates["short_ok"] = bool(short_ok)

                if long_ok:
                    _entry_side = "long"
                    size_pct = self._size_pct(
                        ls, "long",
                        reduce_risk=macro["long_reduce_risk"],
                        halving_phase=macro["halving_phase"],
                        vix_elevated=_vix_elevated_for_size,
                    )
                    logger.info(
                        "[{}] ENTRADA LONG score={} (short={}) size={:.0f}% "
                        "mvrv={} phase={} dxy={} ndx={}",
                        self.name, ls, ss, float(size_pct) * 100,
                        round(macro["mvrv"], 2) if macro["mvrv"] else "N/D",
                        macro["halving_phase"],
                        f"{market['dxy_change']:+.1f}%" if market["dxy_change"] is not None else "N/D",
                        f"{market['ndx_change']:+.1f}%" if market["ndx_change"] is not None else "N/D",
                    )
                    self._open_long(
                        price,
                        ls,
                        daily["atr"],
                        vix_elevated=_vix_elevated_for_size,
                    )
                elif short_ok:
                    _entry_side = "short"
                    logger.info(
                        "[{}] ENTRADA SHORT score={} (long={}) mvrv={} phase={} realized={}",
                        self.name, ss, ls,
                        round(macro["mvrv"], 2) if macro["mvrv"] else "N/D",
                        macro["halving_phase"],
                        round(realized, 0) if realized else "N/D",
                    )
                    self._open_short(price, ss, daily["atr"])

        self._state["prev_macd_above"] = daily["macd_above"]
        self._state["prev_weekly_up"]  = weekly.get("weekly_trend_up")
        self._save_state()

        # === Journal: detectar transiciones de posición ===
        _pos_after = self._state.get("position", "none")
        if _pos_before != _pos_after:
            _ind = self._journal_ind_snapshot(daily, weekly, h4, h1, ls, ss)
            # Contexto macro/mercado en el momento del trade
            _ind["mvrv"]                 = round(macro.get("mvrv"), 2) if macro.get("mvrv") else None
            _ind["mvrv_regime"]          = macro.get("mvrv_regime")
            _ind["long_reduce_risk"]     = macro.get("long_reduce_risk")
            _ind["realized_price"]       = round(macro.get("realized_price"), 2) if macro.get("realized_price") else None
            _ind["days_since_halving"]   = macro.get("days_since_halving")
            _ind["halving_phase"]        = macro.get("halving_phase")
            _ind["dxy_change_pct"]       = market.get("dxy_change")
            _ind["ndx_change_pct"]       = market.get("ndx_change")
            _ind["vix_level"]            = market.get("vix_level")
            _ind["vix_elevated"]         = market.get("vix_elevated")
            _ind["vix_elevated_for_size"] = _vix_elevated_for_size
            _ind["vix_cap_disabled_by_ablation"] = _vix_elevated_raw and cfg.disable_external_filters
            _ind["vix_extreme"]          = market.get("vix_extreme")
            _ind["dxy_headwind"]         = market.get("dxy_headwind")
            _ind["ndx_risk_off"]         = market.get("risk_off")
            _ind["funding_rate"]         = _entry_funding_rate
            _ind["partial_exit_triggered"] = _partial_exited_pre
            _ind["half_reduced"]         = _half_reduced_pre
            _ind["partial_exit_pct_config"] = cfg.partial_exit_pct
            _ind["partial_exit_size_config"] = cfg.partial_exit_size
            if _entry_gates is not None:
                _ind["entry_gates"] = _entry_gates
                _ind.update(_entry_gates)
            _bal_after = float(self._client.get_balance().get("USDT", Decimal("0")))

            # peak_gain_pct: maximo no realizado desde entrada (diagnostico ATR stops y trailing losses)
            _ind["peak_gain_pct"] = round(
                (_peak_pre / _entry_pre - 1) * 100, 1
            ) if _entry_pre > 0 and _peak_pre > 0 else 0.0

            if _pos_before in ("long", "short"):
                _open_ts = (self._pending_journal_entry or {}).get("open", {}).get("timestamp")
                if _open_ts:
                    try:
                        _dt_open = datetime.fromisoformat(_open_ts)
                        _dt_now  = datetime.fromisoformat(_ts_now)
                        _hold_h  = (_dt_now - _dt_open).total_seconds() / 3600
                    except Exception:
                        _hold_h  = 0.0
                else:
                    _hold_h = 0.0

                _mae_pct = round(
                    (_entry_pre - _trough_pre) / _entry_pre * 100, 2
                ) if _entry_pre > 0 and _trough_pre > 0 else 0.0
                _mfe_pct = round(
                    (_peak_pre - _entry_pre) / _entry_pre * 100, 2
                ) if _entry_pre > 0 and _peak_pre > _entry_pre else 0.0
                _atr_risk = (_entry_pre - _stop_pre) * _qty_pre
                _r_multiple = round(
                    self._last_close_pnl / _atr_risk, 2
                ) if _atr_risk > 0 else 0.0

                self._journal_close(
                    ts=_ts_now, price=float(price),
                    pnl=self._last_close_pnl, reason=self._last_close_reason,
                    holding_hours=_hold_h, balance_after=_bal_after,
                    ls=ls, ss=ss, indicators=_ind,
                    mae_pct=_mae_pct, mfe_pct=_mfe_pct, r_multiple=_r_multiple,
                )

            if _pos_after in ("long", "short"):
                _stop_val = float(Decimal(self._state.get("stop_loss", "0") or "0"))
                _qty_val  = float(Decimal(self._state.get("position_qty", "0") or "0"))
                _score_for_size = ls if _pos_after == "long" else ss
                _ind["entry_side"] = _entry_side or _pos_after
                _ind["sizing"] = self._size_journal_snapshot(
                    _score_for_size,
                    _pos_after,
                    macro,
                    market,
                    _balance_before,
                    self._last_open_invest,
                )
                self._journal_open(
                    side=_pos_after, ts=_ts_now, price=float(price),
                    invest=self._last_open_invest, stop=_stop_val, qty=_qty_val,
                    balance_before=_balance_before,
                    ls=ls, ss=ss, indicators=_ind,
                )

    # -----------------------------------------------------------------------
    # Señales abstractas
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        return self._state.get("position") == "none"

    def should_exit(self) -> bool:
        return self._state.get("position") != "none"
