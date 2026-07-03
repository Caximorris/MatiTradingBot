"""
Prop Swing — trend-pullback discreto en 4H para prop firm (HyroTrader).

P3 de HYROTRADER_PLAN.md (FASE 3). Estrategia de trades discretos con stop SIEMPRE:
- Regimen en 1D CERRADO (dias estrictamente anteriores a hoy UTC — anti-lookahead F8):
  EMA50D > EMA200D, close > EMA200D, ADX14D >= adx_min. Solo long.
- Entrada en cierre de bloque 4H UTC (hora % 4 == 3): pullback reciente a la EMA50-4H
  + gatillo de reanudacion (cierre 4H > high del 4H previo, y cierre > EMA50-4H).
- Stop: atr_stop_mult x ATR14-4H bajo la entrada. El stop dimensiona la posicion:
  qty = equity * risk_per_trade / stop_dist, con cap de notional.
- Gestion: TP1 vende tp1_size en +tp1_r R y mueve stop a break-even; el resto trailing
  chandelier (high-water close - trail_atr_mult x ATR4H de entrada). Salida por perdida
  de regimen en cierre 4H.
- Limites prop internos: max entradas/dia, no entrar si el dia va peor que -daily_loss_stop
  o mejor que +daily_profit_stop (proteger trailing DD y Profit Distribution 40%),
  flatten total si el dia toca -daily_flatten (kill switch).

Stops y TP se chequean en CADA barra 1H contra high/low (el fill es market al close de esa
barra — modela gap/slippage de forma honesta, no fill exacto en el nivel).

NOTA C7 (igual que Swing): la EMA200D sobre lookback_hours=6000 es una EMA truncada.
Filtro de eventos macro (FOMC/CPI) y spread-check son SOLO live — no se modelan aqui.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from strategies.base_strategy import BaseStrategy
from strategies.indicators import (
    adx as adx_fn, atr as atr_fn, ema as ema_fn,
    resample_to_4h, resample_to_daily,
)

if TYPE_CHECKING:
    from core.exchange import OKXClient
    from core.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class PropSwingConfig:
    symbol: str = "BTC-USDT"
    lookback_hours: int = 6000        # ~250 dias 1H (EMA200D truncada — caveat C7)

    # -- Regimen diario (cerrado) --
    adx_min: float = 15.0

    # -- Entrada 4H --
    entry_mode: str = "pullback"      # "pullback" (v0) | "breakout" (E5: Donchian 4H)
    ema_pullback_4h: int = 50         # EMA de la zona de pullback en 4H
    pullback_lookback_4h: int = 6     # nº de bloques 4H cerrados donde buscar el toque
    breakout_lookback_4h: int = 20    # E5: cierre 4H > max high de los N bloques previos

    # -- Riesgo por trade --
    risk_per_trade: float = 0.005     # fraccion del equity actual (plan: 0.5%)
    atr_period: int = 14              # ATR en 4H
    atr_stop_mult: float = 2.0
    tp1_r: float = 1.0                # TP1 en +1R
    tp1_size: float = 0.5             # vende 50% en TP1, stop a break-even
    trail_atr_mult: float = 3.0       # chandelier tras TP1
    # -- Flags P4 (defaults = comportamiento v0 exacto; cambiar via --config, AISLADOS) --
    be_after_tp1: bool = True         # False: el stop NO sube a BE tras TP1 (solo chandelier)
    trail_on_high: bool = False       # True: high-water usa el high de la barra, no el close
    max_notional_pct: float = 0.25    # cap duro de notional (funded: margen 25%)

    # -- Filtros --
    vol_max_atr_pct_d: float = 0.06   # no entrar si ATR14D/close > 6% (vol explosiva)

    # -- Limites prop internos (fracciones del equity de inicio de dia UTC) --
    max_entries_per_day: int = 2
    daily_loss_stop: float = 0.015    # dia <= -1.5% -> no mas entradas
    daily_profit_stop: float = 0.025  # dia >= +2.5% -> no mas entradas
    daily_flatten: float = 0.025      # dia <= -2.5% -> cerrar todo

    @classmethod
    def from_dict(cls, d: dict) -> "PropSwingConfig":
        c = cls()
        for k, v in d.items():
            if not hasattr(c, k):
                continue
            attr = getattr(c, k)
            if isinstance(attr, bool):
                setattr(c, k, bool(v) if not isinstance(v, str)
                        else v.lower() not in ("false", "0", ""))
            elif isinstance(attr, int):
                setattr(c, k, int(v))
            elif isinstance(attr, float):
                setattr(c, k, float(v))
            else:
                setattr(c, k, v)
        return c

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class PropSwingBot(BaseStrategy):
    def __init__(self, client: "OKXClient", config: PropSwingConfig,
                 session, risk_manager: "RiskManager | None" = None) -> None:
        super().__init__(client, config.to_dict(), session, risk_manager)
        self._cfg = config
        # Posicion abierta (None = flat)
        self._pos: dict | None = None
        # Dia UTC en curso
        self._day: str = ""
        self._day_start_equity: float = 0.0
        self._entries_today: int = 0

    @property
    def name(self) -> str:
        return f"prop_swing_{self._cfg.symbol.lower().replace('-', '_')}"

    # Interfaz abstracta — la logica real vive en run()
    def should_enter(self) -> bool:
        return False

    def should_exit(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Tick principal
    # ------------------------------------------------------------------

    def run(self) -> None:
        df = self._client.get_ohlcv(self._cfg.symbol, limit=self._cfg.lookback_hours)
        if df is None or len(df) < 1000:
            logger.warning("[{}] OHLCV insuficiente; tick omitido", self.name)
            return

        last = df.iloc[-1]
        ts = datetime.fromtimestamp(int(last["timestamp"]) / 1000, tz=timezone.utc)
        price = float(last["close"])
        equity = self._equity(price)

        # -- Rollover de dia UTC --
        day_key = ts.strftime("%Y-%m-%d")
        if day_key != self._day:
            self._day = day_key
            self._day_start_equity = equity
            self._entries_today = 0
        day_pnl = (equity / self._day_start_equity - 1.0) if self._day_start_equity else 0.0

        if self._pos is not None:
            self._manage_position(df, last, ts, price, day_pnl)
        if self._pos is None and ts.hour % 4 == 3:
            self._try_enter(df, ts, price, equity, day_pnl)

    # ------------------------------------------------------------------
    # Gestion de la posicion (cada barra 1H)
    # ------------------------------------------------------------------

    def _manage_position(self, df: pd.DataFrame, last, ts: datetime,
                         price: float, day_pnl: float) -> None:
        pos = self._pos
        bar_low = float(last["low"])
        bar_high = float(last["high"])

        # Kill switch diario interno
        if day_pnl <= -self._cfg.daily_flatten:
            self._close_all(ts, price, "daily_flatten")
            return

        # Stop (chequeo intrabar contra el low; fill market al close de la barra)
        if bar_low <= pos["stop"]:
            self._close_all(ts, price, "stop_be" if pos["tp1_done"] else "stop_loss")
            return

        # TP1 parcial + break-even
        if not pos["tp1_done"] and bar_high >= pos["tp1"]:
            qty_out = (pos["qty"] * Decimal(str(self._cfg.tp1_size))).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN)
            if qty_out > 0:
                r = self._client.place_order(self._cfg.symbol, "sell", "market",
                                             qty_out, strategy=self.name)
                if r.status == "filled":
                    self.log_trade(r)
                    pos["qty"] -= qty_out
                    pos["tp1_done"] = True
                    if self._cfg.be_after_tp1:
                        pos["stop"] = pos["entry"]      # break-even
                    pos["high_water"] = price

        # Trailing chandelier tras TP1
        if pos["tp1_done"]:
            hw_ref = bar_high if self._cfg.trail_on_high else price
            pos["high_water"] = max(pos["high_water"], hw_ref)
            trail = pos["high_water"] - self._cfg.trail_atr_mult * pos["atr_entry"]
            pos["stop"] = max(pos["stop"], trail)

        # Salida por regimen en cierre de bloque 4H
        if ts.hour % 4 == 3 and not self._regime_ok(df, ts):
            self._close_all(ts, price, "regime_exit")

    # ------------------------------------------------------------------
    # Entrada (solo en cierre de bloque 4H UTC)
    # ------------------------------------------------------------------

    def _try_enter(self, df: pd.DataFrame, ts: datetime, price: float,
                   equity: float, day_pnl: float) -> None:
        cfg = self._cfg
        if self._entries_today >= cfg.max_entries_per_day:
            return
        if day_pnl <= -cfg.daily_loss_stop or day_pnl >= cfg.daily_profit_stop:
            return
        if not self._regime_ok(df, ts, check_vol=True):
            return

        df4 = resample_to_4h(df)
        if len(df4) < cfg.ema_pullback_4h + cfg.pullback_lookback_4h + 2:
            return
        ema4 = ema_fn(df4["close"], cfg.ema_pullback_4h)
        atr4 = atr_fn(df4["high"], df4["low"], df4["close"], cfg.atr_period)

        # Ultimo bloque = recien cerrado (evaluamos en hour % 4 == 3)
        c_now, h_prev = float(df4["close"].iloc[-1]), float(df4["high"].iloc[-2])
        ema_now, atr_now = float(ema4.iloc[-1]), float(atr4.iloc[-1])
        if atr_now <= 0 or pd.isna(atr_now) or pd.isna(ema_now):
            return

        if cfg.entry_mode == "breakout":
            # E5: breakout Donchian — cierre 4H sobre el max high de los N bloques previos
            n = cfg.breakout_lookback_4h
            if len(df4) < n + 2:
                return
            donchian_high = float(df4["high"].iloc[-(n + 1):-1].max())
            if not (c_now > donchian_high and c_now > ema_now):
                return
        else:
            # v0: pullback — algun low de los ultimos N bloques cerrados toco la EMA50-4H
            lows = df4["low"].iloc[-cfg.pullback_lookback_4h:]
            emas = ema4.iloc[-cfg.pullback_lookback_4h:]
            touched = bool((lows.values <= emas.values).any())
            # Gatillo: reanudacion sobre el high del 4H previo, por encima de la EMA
            trigger = c_now > h_prev and c_now > ema_now
            if not (touched and trigger):
                return

        # -- Sizing por riesgo: el stop dimensiona la posicion --
        stop_dist = cfg.atr_stop_mult * atr_now
        stop = price - stop_dist
        if stop <= 0:
            return
        risk_usdt = equity * cfg.risk_per_trade
        qty = risk_usdt / stop_dist
        notional = qty * price
        max_notional = equity * cfg.max_notional_pct
        if notional > max_notional:                     # cap duro (funded 25%)
            qty = max_notional / price
            notional = max_notional

        balance = self._client.get_balance()
        usdt = float(balance.get("USDT", Decimal("0")))
        if notional > usdt * 0.99:
            qty = usdt * 0.99 / price
        qty_d = Decimal(str(qty)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty_d <= 0 or float(qty_d) * price < 10:
            return

        ok, reason = self.check_risk(cfg.symbol, Decimal(str(notional)))
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        r = self._client.place_order(cfg.symbol, "buy", "market", qty_d, strategy=self.name)
        if r.status != "filled" or not r.filled_price:
            return
        self.log_trade(r)
        entry = float(r.filled_price)
        self._pos = {
            "qty": r.filled_qty, "entry": entry,
            "stop": entry - stop_dist,
            "tp1": entry + cfg.tp1_r * stop_dist,
            "tp1_done": False, "high_water": entry,
            "atr_entry": atr_now,
        }
        self._entries_today += 1
        self._journal_open(
            side="long", ts=ts.isoformat(), price=entry,
            invest=float(r.filled_qty) * entry, stop=self._pos["stop"],
            qty=float(r.filled_qty), balance_before=equity, ls=0, ss=0,
            indicators={"atr4h": round(atr_now, 2), "ema50_4h": round(ema_now, 2)},
            tp=self._pos["tp1"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _regime_ok(self, df: pd.DataFrame, ts: datetime, check_vol: bool = False) -> bool:
        """Regimen bull en diario CERRADO (dias < hoy UTC). check_vol añade el filtro ATR%."""
        daily = resample_to_daily(df)
        daily = daily[daily["dt"].dt.date < ts.date()]
        if len(daily) < 210:
            return False
        close = daily["close"]
        ema50 = float(ema_fn(close, 50).iloc[-1])
        ema200 = float(ema_fn(close, 200).iloc[-1])
        adx_d = float(adx_fn(daily["high"], daily["low"], close, 14).iloc[-1])
        c = float(close.iloc[-1])
        if not (ema50 > ema200 and c > ema200 and adx_d >= self._cfg.adx_min):
            return False
        if check_vol:
            atr_d = float(atr_fn(daily["high"], daily["low"], close, 14).iloc[-1])
            if c <= 0 or atr_d / c > self._cfg.vol_max_atr_pct_d:
                return False
        return True

    def _equity(self, price: float) -> float:
        balance = self._client.get_balance()
        usdt = float(balance.get("USDT", Decimal("0")))
        base = float(balance.get(self._cfg.symbol.split("-")[0], Decimal("0")))
        return usdt + base * price

    def _close_all(self, ts: datetime, price: float, reason: str) -> None:
        pos = self._pos
        if pos is None or pos["qty"] <= 0:
            self._pos = None
            return
        r = self._client.place_order(self._cfg.symbol, "sell", "market",
                                     pos["qty"], strategy=self.name)
        if r.status != "filled":
            logger.warning("[{}] cierre {} NO ejecutado", self.name, reason)
            return
        fill = float(r.filled_price or price)
        pnl = (fill - pos["entry"]) * float(pos["qty"])
        self.log_trade(r, pnl=Decimal(str(round(pnl, 8))))
        self._journal_close(
            ts=ts.isoformat(), price=fill, pnl=pnl, reason=reason,
            holding_hours=0.0, balance_after=self._equity(fill), ls=0, ss=0,
            indicators={},
        )
        self._pos = None
