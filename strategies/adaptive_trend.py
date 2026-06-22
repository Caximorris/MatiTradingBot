"""
Adaptive Trend Following con detección de régimen.

Lógica en tres capas:

1. RÉGIMEN (barras diarias, ventana de 210 días):
   bull  = EMA50_D > EMA200_D  Y  precio > EMA200_D  Y  ADX > 20
   bear  = EMA50_D < EMA200_D  O  precio < EMA200_D
   range = bull estructural pero ADX < 20 (mercado lateral)

2. ENTRADA (solo en régimen bull):
   - MACD(12,26,9) diario cruza al alza (MACD > signal)
   - RSI(14) diario entre 40 y 70 (no sobrecomprado ni en caída libre)
   - Volumen del día > 1.2× media 20 días
   Tamaño: 80% del saldo disponible en USDT

3. SALIDA:
   - Régimen cambia a "bear" → salida inmediata (señal más fuerte)
   - MACD diario cruza a la baja Y precio < EMA50_D → salida tendencial
   - RSI > 80 (sobrecompra extrema) → reducir posición a la mitad
   - ATR stop: precio cae > 2.5 × ATR(14) diario desde el precio de entrada

La clave sobre buy-and-hold:
  En 2018 y 2022 la EMA50 cruza por debajo de la EMA200 pocas semanas después del techo.
  El bot sale limpio antes de que ocurra el -65%/-80%. Ese capital se mantiene en USDT
  y se reinvierte cuando vuelve el golden cross. Evitar dos crashes de -65% y -80%
  compensa con creces perder el primer 15-20% de cada bull run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from core.database import get_or_create_bot_state, set_bot_active, upsert_position, close_position
from core.exchange import OKXClient
from strategies.base_strategy import BaseStrategy
from strategies.indicators import (
    ema, macd as compute_macd, atr as compute_atr,
    rsi as compute_rsi, resample_to_daily, detect_regime,
)

if TYPE_CHECKING:
    from core.risk_manager import RiskManager


@dataclass
class AdaptiveTrendConfig:
    symbol: str
    # Régimen
    ema_fast: int = 50           # días
    ema_slow: int = 200          # días
    adx_threshold: float = 20.0

    # MACD de entrada
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Filtros de entrada — amplios para no perder entradas en tendencia fuerte
    rsi_min: float = 25.0    # evitar entrar en caída libre
    rsi_max: float = 85.0    # en bull fuerte el RSI puede estar 60-80 semanas seguidas
    volume_mult: float = 0.5  # solo excluir días de volumen extremadamente bajo

    # Gestión de posición
    position_pct: Decimal = Decimal("0.80")   # % del saldo en bull fuerte
    range_position_pct: Decimal = Decimal("0.40")  # % en régimen lateral
    rsi_overbought: float = 90.0              # umbral para recorte parcial
    atr_stop_mult: float = 2.5                # ATR × este valor = stop loss
    atr_period: int = 14

    # Historial de barras necesario para calcular EMA200 diaria
    lookback_hours: int = 5760   # 240 días × 24h (margen sobre los 200 días de EMA)

    def __post_init__(self) -> None:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast debe ser menor que ema_slow")

    @classmethod
    def from_dict(cls, d: dict) -> "AdaptiveTrendConfig":
        _cls = cls(symbol=d["symbol"])   # instanciar con defaults del dataclass
        return cls(
            symbol=d["symbol"],
            ema_fast=int(d.get("ema_fast", _cls.ema_fast)),
            ema_slow=int(d.get("ema_slow", _cls.ema_slow)),
            adx_threshold=float(d.get("adx_threshold", _cls.adx_threshold)),
            macd_fast=int(d.get("macd_fast", _cls.macd_fast)),
            macd_slow=int(d.get("macd_slow", _cls.macd_slow)),
            macd_signal=int(d.get("macd_signal", _cls.macd_signal)),
            rsi_min=float(d.get("rsi_min", _cls.rsi_min)),
            rsi_max=float(d.get("rsi_max", _cls.rsi_max)),
            volume_mult=float(d.get("volume_mult", _cls.volume_mult)),
            position_pct=Decimal(str(d.get("position_pct", str(_cls.position_pct)))),
            range_position_pct=Decimal(str(d.get("range_position_pct", str(_cls.range_position_pct)))),
            rsi_overbought=float(d.get("rsi_overbought", _cls.rsi_overbought)),
            atr_stop_mult=float(d.get("atr_stop_mult", _cls.atr_stop_mult)),
            atr_period=int(d.get("atr_period", _cls.atr_period)),
            lookback_hours=int(d.get("lookback_hours", _cls.lookback_hours)),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "adx_threshold": self.adx_threshold,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "rsi_min": self.rsi_min,
            "rsi_max": self.rsi_max,
            "volume_mult": self.volume_mult,
            "position_pct": str(self.position_pct),
            "range_position_pct": str(self.range_position_pct),
            "rsi_overbought": self.rsi_overbought,
            "atr_stop_mult": self.atr_stop_mult,
            "atr_period": self.atr_period,
            "lookback_hours": self.lookback_hours,
        }


class AdaptiveTrendBot(BaseStrategy):
    """
    Trend follower con régimen adaptativo.

    Estado persistido:
    {
        "is_in_position": false,
        "entry_price": "0",
        "position_qty": "0",
        "stop_loss": "0",
        "regime": "data_insufficient",
        "prev_macd_above": null   # bool: si el último tick tenía MACD > signal
    }
    """

    def __init__(
        self,
        client: OKXClient,
        config: dict | AdaptiveTrendConfig,
        session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        cfg = AdaptiveTrendConfig.from_dict(config) if isinstance(config, dict) else config
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._cfg = cfg
        self._state = self._load_state()

    @property
    def name(self) -> str:
        sym = self._cfg.symbol.lower().replace("-", "_")
        return f"adaptive_trend_{sym}"

    # -----------------------------------------------------------------------
    # Persistencia
    # -----------------------------------------------------------------------

    def _load_state(self) -> dict:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="adaptive_trend",
            symbol=self._cfg.symbol,
            config=self._cfg.to_dict(),
        )
        saved = bot_state.get_config()
        defaults: dict = {
            "is_in_position": False,
            "entry_price": "0",
            "position_qty": "0",
            "stop_loss": "0",
            "regime": "data_insufficient",
            "prev_macd_above": None,
        }
        return {**defaults, **saved}

    def _save_state(self) -> None:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="adaptive_trend",
            symbol=self._cfg.symbol,
        )
        bot_state.set_config(self._state)

    # -----------------------------------------------------------------------
    # Cálculo de indicadores
    # -----------------------------------------------------------------------

    def _build_daily_indicators(self) -> dict | None:
        """
        Descarga barras 1H, las resamplea a diario (excluyendo el día incompleto actual)
        y calcula todos los indicadores. Solo recalcula una vez por día.
        Retorna dict con los valores del último día completo, o None si hay pocos datos.
        """
        cfg = self._cfg
        current_day = self._client.current_time().date().isoformat()
        cached = self._state.get("_indicator_cache")
        if cached and cached.get("date") == current_day:
            return cached.get("ind")

        raw = self._client.get_ohlcv(cfg.symbol, timeframe="1H", limit=cfg.lookback_hours)
        if raw is None or (hasattr(raw, "__len__") and len(raw) < cfg.ema_slow * 24):
            return None

        if not isinstance(raw, pd.DataFrame):
            raw = pd.DataFrame([
                {"timestamp": b.timestamp, "open": float(b.open), "high": float(b.high),
                 "low": float(b.low), "close": float(b.close), "volume": float(b.volume)}
                for b in raw
            ])

        daily = resample_to_daily(raw)
        # Descartar el último bar diario si es el día actual (puede estar incompleto)
        if len(daily) > 0:
            last_ts = daily.iloc[-1].get("dt", None) if hasattr(daily.iloc[-1], "get") else None
            if last_ts is None and "dt" in daily.columns:
                last_ts = daily.iloc[-1]["dt"]
            if last_ts is not None:
                last_day = pd.to_datetime(last_ts).date().isoformat()
                if last_day == current_day:
                    daily = daily.iloc[:-1]

        if len(daily) < cfg.ema_slow + 10:
            self._state["_indicator_cache"] = {"date": current_day, "ind": None}
            return None

        close  = daily["close"].astype(float)
        high   = daily["high"].astype(float)
        low    = daily["low"].astype(float)
        volume = daily["volume"].astype(float)

        ema_f = ema(close, cfg.ema_fast)
        ema_s = ema(close, cfg.ema_slow)
        macd_line, sig_line, _ = compute_macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        atr_series = compute_atr(high, low, close, cfg.atr_period)
        rsi_series = compute_rsi(close, 14)
        vol_ma = volume.rolling(20).mean()

        regime = detect_regime(
            daily,
            ema_fast=cfg.ema_fast,
            ema_slow=cfg.ema_slow,
            adx_threshold=cfg.adx_threshold,
        )

        ind = {
            "close": float(close.iloc[-1]),
            "ema_fast": float(ema_f.iloc[-1]),
            "ema_slow": float(ema_s.iloc[-1]),
            "macd": float(macd_line.iloc[-1]),
            "macd_signal": float(sig_line.iloc[-1]),
            "macd_above": float(macd_line.iloc[-1]) > float(sig_line.iloc[-1]),
            "atr": float(atr_series.iloc[-1]),
            "rsi": float(rsi_series.iloc[-1]),
            "volume": float(volume.iloc[-1]),
            "volume_ma": float(vol_ma.iloc[-1]),
            "regime": regime,
        }
        self._state["_indicator_cache"] = {"date": current_day, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Tick principal
    # -----------------------------------------------------------------------

    def run(self) -> None:
        ind = self._build_daily_indicators()
        if ind is None:
            return

        regime = ind["regime"]
        prev_regime = self._state.get("regime", "data_insufficient")
        self._state["regime"] = regime

        in_pos = self._state["is_in_position"]
        current_price = Decimal(str(ind["close"]))

        # ── Gestión de posición abierta ──────────────────────────────────
        if in_pos:
            stop = Decimal(self._state["stop_loss"])
            entry = Decimal(self._state["entry_price"])

            # 1. Cambio a bear → salida inmediata
            if regime == "bear":
                logger.info("[{}] Régimen → BEAR — cerrando posición", self.name)
                self._close_position(current_price, reason="regime_bear")
                return

            # 2. ATR stop
            if stop > Decimal("0") and current_price <= stop:
                logger.info("[{}] ATR stop hit @ {} (stop={}) — cerrando", self.name, current_price, stop)
                self._close_position(current_price, reason="atr_stop")
                return

            # 3. MACD death cross + precio bajo EMA50
            prev_macd_was_above = self._state.get("prev_macd_above") is True
            macd_cross_down = not ind["macd_above"] and prev_macd_was_above
            price_below_ema50 = ind["close"] < ind["ema_fast"]
            if macd_cross_down and price_below_ema50:
                logger.info("[{}] MACD death cross + precio < EMA50 — cerrando", self.name)
                self._close_position(current_price, reason="macd_exit")
                return

            # 4. Sobrecompra extrema → recortar posición a la mitad
            if ind["rsi"] > self._cfg.rsi_overbought and not self._state.get("half_reduced"):
                logger.info("[{}] RSI={:.1f} sobrecomprado — reduciendo posición a la mitad", self.name, ind["rsi"])
                self._reduce_position_half(current_price)

        # ── Buscar entrada ───────────────────────────────────────────────
        else:
            # Solo entrar si hay estructura alcista (precio y EMA50 sobre EMA200)
            # "bull" = tendencia fuerte (ADX > 20); "range" = lateral pero estructura alcista
            if regime not in ("bull", "range"):
                self._state["prev_macd_above"] = ind["macd_above"]
                self._save_state()
                return

            # MACD diario cruza al alza (None inicial = nunca hubo señal → tratar como False)
            prev_macd = self._state.get("prev_macd_above")
            macd_cross_up = ind["macd_above"] and not prev_macd
            rsi_ok = self._cfg.rsi_min <= ind["rsi"] <= self._cfg.rsi_max
            volume_ok = (ind["volume_ma"] <= 0 or
                         ind["volume"] >= ind["volume_ma"] * self._cfg.volume_mult)

            if macd_cross_up and rsi_ok and volume_ok:
                cfg = self._cfg
                pos_pct = cfg.position_pct if regime == "bull" else cfg.range_position_pct
                logger.info(
                    "[{}] SEÑAL ENTRADA: regime={} MACD={:.2f}>{:.2f} RSI={:.1f} pos_pct={}",
                    self.name, regime, ind["macd"], ind["macd_signal"],
                    ind["rsi"], pos_pct,
                )
                atr_val = Decimal(str(ind["atr"]))
                stop = current_price - atr_val * Decimal(str(cfg.atr_stop_mult))
                self._open_position(current_price, stop, position_pct=pos_pct)

        self._state["prev_macd_above"] = ind["macd_above"]
        self._save_state()

    # -----------------------------------------------------------------------
    # Acciones
    # -----------------------------------------------------------------------

    def _open_position(self, price: Decimal, stop_loss: Decimal,
                       position_pct: Decimal | None = None) -> None:
        cfg = self._cfg
        balance = self._client.get_balance()
        usdt_available = balance.get("USDT", Decimal("0"))
        pct = position_pct if position_pct is not None else cfg.position_pct
        invest_usdt = (usdt_available * pct).quantize(Decimal("0.01"))

        ok, reason = self.check_risk(cfg.symbol, invest_usdt)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        qty = (invest_usdt / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty <= Decimal("0"):
            return

        result = self._client.place_order(cfg.symbol, "buy", "market", qty, strategy=self.name)
        if result.status == "filled" and result.filled_price:
            self.log_trade(result)
            self._state.update({
                "is_in_position": True,
                "entry_price": str(result.filled_price),
                "position_qty": str(result.filled_qty),
                "stop_loss": str(stop_loss),
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
                "[{}] Posición abierta: {} {} @ {} | stop={} | invest={} USDT",
                self.name, result.filled_qty, cfg.symbol.split("-")[0],
                result.filled_price, stop_loss, invest_usdt,
            )

    def _close_position(self, price: Decimal, reason: str = "") -> None:
        qty = Decimal(self._state["position_qty"])
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
                "[{}] Posición cerrada ({}): {} {} @ {} | PnL={:.2f} USDT",
                self.name, reason, qty, self._cfg.symbol.split("-")[0],
                result.filled_price, pnl,
            )
            close_position(self._session, self._cfg.symbol, self.name)
            self._reset_state()

    def _reduce_position_half(self, price: Decimal) -> None:
        qty = Decimal(self._state["position_qty"])
        sell_qty = (qty / 2).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if sell_qty <= Decimal("0"):
            return

        entry = Decimal(self._state["entry_price"])
        result = self._client.place_order(
            self._cfg.symbol, "sell", "market", sell_qty, strategy=self.name
        )
        if result.status == "filled" and result.filled_price:
            pnl = (result.filled_price - entry) * result.filled_qty - result.fee
            self.log_trade(result, pnl=pnl)
            self._state["position_qty"] = str(qty - sell_qty)
            self._state["half_reduced"] = True
            self._save_state()
            logger.info("[{}] Posición reducida al 50% @ {} | PnL parcial={:.2f}", self.name, price, pnl)

    def _reset_state(self) -> None:
        self._state.update({
            "is_in_position": False,
            "entry_price": "0",
            "position_qty": "0",
            "stop_loss": "0",
            "half_reduced": False,
        })
        self._save_state()

    # -----------------------------------------------------------------------
    # Señales abstractas
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        return self._state.get("regime") == "bull" and not self._state["is_in_position"]

    def should_exit(self) -> bool:
        return self._state.get("regime") == "bear" and self._state["is_in_position"]
