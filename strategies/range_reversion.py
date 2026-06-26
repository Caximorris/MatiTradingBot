"""
Range Reversion — Mean reversion en mercados laterales.

Filosofia opuesta a Pro Trend y Adaptive: NO opera en tendencias,
SOLO cuando el mercado esta en rango (ADX < 22 en diario Y en 4H).

Logica:
1. GATE DE REGIMEN (diario + 4H):
   ranging = ADX(14)D < adx_max  AND  ADX(14)4H < adx_max
   Si alguno supera el umbral la estrategia se mantiene fuera.

2. ENTRADA (extremos BB en 4H):
   Long : precio <= BB_lower(20,2) + RSI(14)4H < 35 + precio > EMA200D
   Short: precio >= BB_upper(20,2) + RSI(14)4H > 65 + precio < EMA200D
          (requiere allow_shorts=True; desactivado por defecto)

3. SALIDA:
   - Primera mitad: precio alcanza BB_mid (mean reversion target)
   - Resto: RSI cruza 50 (vuelta a neutralidad)
   - Hard stop: perdida > max_loss_pct desde entrada
   - ATR stop: 1.5x ATR(14)4H desde entrada
   - Cooldown de cooldown_bars tras cualquier stop

4. SIZING: size_pct fijo del capital disponible (12% por defecto).

Edge documentado: PF ~1.62 en ADX < 20, PF -0.74 en ADX > 30.
El gate de regimen es la pieza critica.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from core.database import get_or_create_bot_state, upsert_position, close_position
from core.exchange import OKXClient, OrderResult
from strategies.base_strategy import BaseStrategy
from strategies.indicators import (
    ema,
    atr as compute_atr,
    rsi as compute_rsi,
    adx as compute_adx,
    bb_bands,
    resample_to_daily,
    resample_to_4h,
)

if TYPE_CHECKING:
    from core.risk_manager import RiskManager


@dataclass
class RangeReversionConfig:
    symbol: str

    # Regime gate — ambos timeframes deben confirmar lateralizacion
    adx_period: int = 14
    adx_max: float = 22.0

    # Senales de entrada (4H)
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_oversold: float = 35.0
    rsi_overbought: float = 65.0

    # Filtro estructural diario
    ema_trend: int = 200           # solo long si precio > EMA200D

    # Sizing
    size_pct: Decimal = Decimal("0.12")

    # Gestion de riesgo
    atr_stop_mult: float = 1.5
    atr_period: int = 14
    max_loss_pct: float = 8.0

    # Salida parcial: vende mitad en BB_mid, resto cuando RSI cruza partial_exit_rsi
    partial_exit_rsi: float = 50.0

    allow_shorts: bool = False
    cooldown_bars: int = 8
    lookback_hours: int = 5760     # 240 dias x 24h — cubre EMA200D con margen

    @classmethod
    def from_dict(cls, d: dict) -> "RangeReversionConfig":
        _d = cls(symbol=d["symbol"])
        return cls(
            symbol=d["symbol"],
            adx_period=int(d.get("adx_period", _d.adx_period)),
            adx_max=float(d.get("adx_max", _d.adx_max)),
            bb_period=int(d.get("bb_period", _d.bb_period)),
            bb_std=float(d.get("bb_std", _d.bb_std)),
            rsi_period=int(d.get("rsi_period", _d.rsi_period)),
            rsi_oversold=float(d.get("rsi_oversold", _d.rsi_oversold)),
            rsi_overbought=float(d.get("rsi_overbought", _d.rsi_overbought)),
            ema_trend=int(d.get("ema_trend", _d.ema_trend)),
            size_pct=Decimal(str(d.get("size_pct", str(_d.size_pct)))),
            atr_stop_mult=float(d.get("atr_stop_mult", _d.atr_stop_mult)),
            atr_period=int(d.get("atr_period", _d.atr_period)),
            max_loss_pct=float(d.get("max_loss_pct", _d.max_loss_pct)),
            partial_exit_rsi=float(d.get("partial_exit_rsi", _d.partial_exit_rsi)),
            allow_shorts=bool(d.get("allow_shorts", _d.allow_shorts)),
            cooldown_bars=int(d.get("cooldown_bars", _d.cooldown_bars)),
            lookback_hours=int(d.get("lookback_hours", _d.lookback_hours)),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "adx_period": self.adx_period,
            "adx_max": self.adx_max,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "ema_trend": self.ema_trend,
            "size_pct": str(self.size_pct),
            "atr_stop_mult": self.atr_stop_mult,
            "atr_period": self.atr_period,
            "max_loss_pct": self.max_loss_pct,
            "partial_exit_rsi": self.partial_exit_rsi,
            "allow_shorts": self.allow_shorts,
            "cooldown_bars": self.cooldown_bars,
            "lookback_hours": self.lookback_hours,
        }


class RangeReversionBot(BaseStrategy):
    """
    Mean reversion con gate de regimen ADX.

    Estado persistido:
    {
        "is_in_position": false,
        "side": null,           # "long" | "short"
        "entry_price": "0",
        "position_qty": "0",
        "stop_loss": "0",
        "partial_done": false,
        "bar_index": 0,
        "cooldown_bar": 0,
        "_daily_cache": null,
        "_4h_cache": null,
        "_last_entry_key": ""
    }
    """

    def __init__(
        self,
        client: OKXClient,
        config: dict | RangeReversionConfig,
        session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        cfg = RangeReversionConfig.from_dict(config) if isinstance(config, dict) else config
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._cfg = cfg
        self._state = self._load_state()

    @property
    def name(self) -> str:
        sym = self._cfg.symbol.lower().replace("-", "_")
        return f"range_reversion_{sym}"

    # -----------------------------------------------------------------------
    # Persistencia
    # -----------------------------------------------------------------------

    def _load_state(self) -> dict:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="range_reversion",
            symbol=self._cfg.symbol,
            config=self._cfg.to_dict(),
        )
        saved = bot_state.get_config()
        defaults: dict = {
            "is_in_position": False,
            "side": None,
            "entry_price": "0",
            "position_qty": "0",
            "stop_loss": "0",
            "partial_done": False,
            "bar_index": 0,
            "cooldown_bar": 0,
            "_last_entry_key": "",
        }
        return {**defaults, **saved}

    def _save_state(self) -> None:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="range_reversion",
            symbol=self._cfg.symbol,
        )
        bot_state.set_config(self._state)

    # -----------------------------------------------------------------------
    # Indicadores
    # -----------------------------------------------------------------------

    def _build_daily_indicators(self) -> dict | None:
        cfg = self._cfg
        current_day = self._client.current_time().date().isoformat()
        cached = self._state.get("_daily_cache")
        if cached and cached.get("date") == current_day:
            return cached.get("ind")

        raw = self._client.get_ohlcv(cfg.symbol, timeframe="1H", limit=cfg.lookback_hours)
        if raw is None or len(raw) < cfg.ema_trend * 24:
            return None

        if not isinstance(raw, pd.DataFrame):
            raw = pd.DataFrame([
                {"timestamp": b.timestamp, "open": float(b.open), "high": float(b.high),
                 "low": float(b.low), "close": float(b.close), "volume": float(b.volume)}
                for b in raw
            ])

        daily = resample_to_daily(raw)
        if "dt" in daily.columns and len(daily) > 1:
            last_day = pd.to_datetime(daily.iloc[-1]["dt"]).date().isoformat()
            if last_day == current_day:
                daily = daily.iloc[:-1]

        if len(daily) < cfg.ema_trend + cfg.adx_period + 10:
            return None

        close = daily["close"].astype(float)
        high  = daily["high"].astype(float)
        low   = daily["low"].astype(float)

        ema200_s = ema(close, cfg.ema_trend)
        adx_s    = compute_adx(high, low, close, cfg.adx_period)

        last_adx = float(adx_s.iloc[-1])
        ind = {
            "ema200": float(ema200_s.iloc[-1]),
            "adx":    last_adx if not math.isnan(last_adx) else 999.0,
            "close":  float(close.iloc[-1]),
        }
        self._state["_daily_cache"] = {"date": current_day, "ind": ind}
        return ind

    def _build_4h_indicators(self) -> dict | None:
        cfg = self._cfg
        ct = self._client.current_time()
        cache_key = f"{ct.date().isoformat()}-{ct.hour // 4}"
        cached = self._state.get("_4h_cache")
        if cached and cached.get("key") == cache_key:
            return cached.get("ind")

        raw = self._client.get_ohlcv(cfg.symbol, timeframe="1H", limit=cfg.lookback_hours)
        if raw is None or len(raw) < (cfg.bb_period + cfg.adx_period) * 4 + 20:
            return None

        if not isinstance(raw, pd.DataFrame):
            raw = pd.DataFrame([
                {"timestamp": b.timestamp, "open": float(b.open), "high": float(b.high),
                 "low": float(b.low), "close": float(b.close), "volume": float(b.volume)}
                for b in raw
            ])

        df4 = resample_to_4h(raw)
        # Descarta la barra 4H actual (puede estar incompleta)
        if len(df4) > 1:
            df4 = df4.iloc[:-1]
        if len(df4) < cfg.bb_period + cfg.adx_period:
            return None

        close = df4["close"].astype(float)
        high  = df4["high"].astype(float)
        low   = df4["low"].astype(float)

        bb_upper, bb_mid, bb_lower, _, _ = bb_bands(close, cfg.bb_period, cfg.bb_std)
        rsi_s = compute_rsi(close, cfg.rsi_period)
        adx_s = compute_adx(high, low, close, cfg.adx_period)
        atr_s = compute_atr(high, low, close, cfg.atr_period)

        last_adx = float(adx_s.iloc[-1])
        last_atr = float(atr_s.iloc[-1])
        ind = {
            "close":    float(close.iloc[-1]),
            "bb_upper": float(bb_upper.iloc[-1]),
            "bb_mid":   float(bb_mid.iloc[-1]),
            "bb_lower": float(bb_lower.iloc[-1]),
            "rsi":      float(rsi_s.iloc[-1]),
            "adx":      last_adx if not math.isnan(last_adx) else 999.0,
            "atr":      last_atr if not math.isnan(last_atr) else 0.0,
        }
        self._state["_4h_cache"] = {"key": cache_key, "ind": ind}
        return ind

    # -----------------------------------------------------------------------
    # Tick principal
    # -----------------------------------------------------------------------

    def run(self) -> None:
        daily = self._build_daily_indicators()
        h4    = self._build_4h_indicators()
        if daily is None or h4 is None:
            return

        self._state["bar_index"] = self._state.get("bar_index", 0) + 1
        bar_idx       = self._state["bar_index"]
        current_price = Decimal(str(h4["close"]))
        in_pos        = self._state["is_in_position"]

        if in_pos:
            self._manage_position(current_price, h4, bar_idx)
        else:
            if bar_idx <= self._state.get("cooldown_bar", 0):
                self._save_state()
                return

            # Gate de regimen: ambos timeframes deben confirmar rango
            if daily["adx"] >= self._cfg.adx_max or h4["adx"] >= self._cfg.adx_max:
                self._save_state()
                return

            # Solo actuar en nueva barra 4H (evita multiples entradas por barra 1H)
            h4_key   = (self._state.get("_4h_cache") or {}).get("key", "")
            last_key = self._state.get("_last_entry_key", "")
            if h4_key == last_key:
                self._save_state()
                return
            self._state["_last_entry_key"] = h4_key

            self._seek_entry(current_price, daily, h4, bar_idx)

        self._save_state()

    def _seek_entry(
        self, price: Decimal, daily: dict, h4: dict, bar_idx: int
    ) -> None:
        cfg = self._cfg
        p = float(price)

        long_ok = (
            p <= h4["bb_lower"]
            and h4["rsi"] < cfg.rsi_oversold
            and p > daily["ema200"]
        )
        short_ok = (
            cfg.allow_shorts
            and p >= h4["bb_upper"]
            and h4["rsi"] > cfg.rsi_overbought
            and p < daily["ema200"]
        )

        if long_ok:
            atr_val = Decimal(str(h4["atr"])) if h4["atr"] > 0 else price * Decimal("0.02")
            stop = price - atr_val * Decimal(str(cfg.atr_stop_mult))
            logger.info(
                "[{}] ENTRADA LONG: precio={:.0f} <= BB_lower={:.0f} RSI={:.1f} ADX_D={:.1f} ADX_4H={:.1f}",
                self.name, p, h4["bb_lower"], h4["rsi"], daily["adx"], h4["adx"],
            )
            self._open_position(price, stop, "long")
        elif short_ok:
            atr_val = Decimal(str(h4["atr"])) if h4["atr"] > 0 else price * Decimal("0.02")
            stop = price + atr_val * Decimal(str(cfg.atr_stop_mult))
            logger.info(
                "[{}] ENTRADA SHORT: precio={:.0f} >= BB_upper={:.0f} RSI={:.1f}",
                self.name, p, h4["bb_upper"], h4["rsi"],
            )
            self._open_position(price, stop, "short")

    def _manage_position(
        self, price: Decimal, h4: dict, bar_idx: int
    ) -> None:
        cfg   = self._cfg
        side  = self._state["side"]
        entry = Decimal(self._state["entry_price"])
        stop  = Decimal(self._state["stop_loss"])
        p     = float(price)

        if side == "long":
            pnl_pct = float((price - entry) / entry * 100)

            if pnl_pct <= -cfg.max_loss_pct:
                self._close_position(price, "hard_stop", bar_idx)
                return
            if stop > Decimal("0") and price <= stop:
                self._close_position(price, "atr_stop", bar_idx)
                return
            if not self._state.get("partial_done") and p >= h4["bb_mid"]:
                self._reduce_position_half(price)
                return
            if self._state.get("partial_done") and h4["rsi"] >= cfg.partial_exit_rsi:
                self._close_position(price, "rsi_neutral")
                return

        elif side == "short":
            pnl_pct = float((entry - price) / entry * 100)

            if pnl_pct <= -cfg.max_loss_pct:
                self._close_position(price, "hard_stop", bar_idx)
                return
            if stop > Decimal("0") and price >= stop:
                self._close_position(price, "atr_stop", bar_idx)
                return
            if not self._state.get("partial_done") and p <= h4["bb_mid"]:
                self._reduce_position_half(price)
                return
            if self._state.get("partial_done") and h4["rsi"] <= (100.0 - cfg.partial_exit_rsi):
                self._close_position(price, "rsi_neutral")
                return

    # -----------------------------------------------------------------------
    # Acciones
    # -----------------------------------------------------------------------

    def _open_position(self, price: Decimal, stop: Decimal, side: str) -> None:
        cfg = self._cfg
        balance      = self._client.get_balance()
        usdt_avail   = balance.get("USDT", Decimal("0"))
        invest_usdt  = (usdt_avail * cfg.size_pct).quantize(Decimal("0.01"))

        ok, reason = self.check_risk(cfg.symbol, invest_usdt)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        qty = (invest_usdt / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty <= Decimal("0"):
            return

        result = self._client.place_order(
            cfg.symbol, "buy" if side == "long" else "sell",
            "market", qty, strategy=self.name,
        )
        if result.status == "filled" and result.filled_price:
            self.log_trade(result)
            self._state.update({
                "is_in_position": True,
                "side":           side,
                "entry_price":    str(result.filled_price),
                "position_qty":   str(result.filled_qty),
                "stop_loss":      str(stop),
                "partial_done":   False,
            })
            upsert_position(
                self._session, symbol=cfg.symbol, strategy=self.name,
                side=side, entry_price=result.filled_price,
                quantity=result.filled_qty, current_price=result.filled_price,
                unrealized_pnl=Decimal("0"),
            )
            logger.info(
                "[{}] Posicion abierta ({}) {} @ {} | stop={} | {:.0f} USDT",
                self.name, side, result.filled_qty, result.filled_price,
                stop, float(invest_usdt),
            )

    def _close_position(
        self, price: Decimal, reason: str, bar_idx: int | None = None
    ) -> None:
        cfg   = self._cfg
        side  = self._state["side"]
        qty   = Decimal(self._state["position_qty"])
        entry = Decimal(self._state["entry_price"])

        if qty <= Decimal("0"):
            self._reset_state()
            return

        close_side = "sell" if side == "long" else "buy"
        result = self._client.place_order(
            cfg.symbol, close_side, "market", qty, strategy=self.name,
        )
        if result.status == "filled" and result.filled_price:
            if side == "long":
                pnl = (result.filled_price - entry) * result.filled_qty - result.fee
            else:
                pnl = (entry - result.filled_price) * result.filled_qty - result.fee
            self.log_trade(result, pnl=pnl)
            logger.info(
                "[{}] Posicion cerrada ({}) @ {} | razon={} | PnL={:.2f} USDT",
                self.name, side, result.filled_price, reason, float(pnl),
            )
            close_position(self._session, cfg.symbol, self.name)
            if bar_idx is not None and reason in ("hard_stop", "atr_stop"):
                self._state["cooldown_bar"] = bar_idx + cfg.cooldown_bars
            self._reset_state()

    def _reduce_position_half(self, price: Decimal) -> None:
        cfg   = self._cfg
        side  = self._state["side"]
        qty   = Decimal(self._state["position_qty"])
        entry = Decimal(self._state["entry_price"])
        sell_qty = (qty / 2).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if sell_qty <= Decimal("0"):
            return

        close_side = "sell" if side == "long" else "buy"
        result = self._client.place_order(
            cfg.symbol, close_side, "market", sell_qty, strategy=self.name,
        )
        if result.status == "filled" and result.filled_price:
            if side == "long":
                pnl = (result.filled_price - entry) * result.filled_qty - result.fee
            else:
                pnl = (entry - result.filled_price) * result.filled_qty - result.fee
            self.log_trade(result, pnl=pnl)
            self._state["position_qty"] = str(qty - sell_qty)
            self._state["partial_done"] = True
            self._save_state()
            logger.info(
                "[{}] Salida parcial (BB_mid) @ {} | PnL parcial={:.2f}",
                self.name, price, float(pnl),
            )

    def _reset_state(self) -> None:
        self._state.update({
            "is_in_position": False,
            "side":           None,
            "entry_price":    "0",
            "position_qty":   "0",
            "stop_loss":      "0",
            "partial_done":   False,
        })
        self._save_state()

    # -----------------------------------------------------------------------
    # Señales abstractas
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        return not self._state["is_in_position"]

    def should_exit(self) -> bool:
        return self._state["is_in_position"]
