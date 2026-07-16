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

H2 (2026-07-03): `allow_shorts=True` habilita el espejo en regimen bear (EMA50D<EMA200D,
close<EMA200D, ADX>=adx_min). Los shorts son SINTETICOS (solo backtest — requieren
`adjust_balance`; en Bybit real seran perps nativos, P5): mark-to-market barra a barra
contra el balance USDT para que la equity (y el trailing DD del simulador prop) vea el
uPnL en continuo; costes identicos a `_fill_market` (slippage bps + fee sobre notional).
Solo se registran en el journal, no en la DB de ordenes.

`self.realized` acumula (ts, pnl neto de fees) de CADA cierre realizado (TP1 y cierre,
long y short) — fuente de PnL por trade para el simulador prop (los shorts sinteticos
no pasan por el pairing ACB del motor).

NOTA C7 (igual que Swing): la EMA200D sobre lookback_hours=6000 es una EMA truncada.
Filtro de eventos macro (FOMC/CPI) y spread-check son SOLO live — no se modelan aqui.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from strategies.base_strategy import BaseStrategy
from strategies.indicators import (
    adx as adx_fn, atr as atr_fn, ema as ema_fn,
    resample_to_4h, resample_to_daily,
)
from strategies.funding_extreme import load_funding, mark_manifest_funding_consumed
from strategies.macro_context import MacroContext

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
    # -- H2: shorts en regimen bear (espejo; sinteticos, solo backtest hasta P5/Bybit) --
    allow_shorts: bool = False
    # -- N1-lite: funding Bybit por settlement para perps. Default False preserva
    #    resultados E9 historicos; activar via --config en runs de decision.
    model_funding: bool = False
    # -- Phase-router probe: lista CSV de fases halving donde se permiten NUEVAS
    #    entradas. Vacio = sin gate. Ej: "bear_onset,accumulation".
    entry_halving_phases: str = ""
    # -- Operativa CFT/paper: no cambia senales; solo persistencia, journal y monitor.
    persist_live_prop_log: bool = True
    cft_monitor_enabled: bool = False
    cft_account_size: float = 50000.0
    cft_phase: str = "p1"
    cft_daily_dd_pct: float = 0.05
    cft_max_loss_pct: float = 0.10
    cft_warn_buffer_pct: float = 0.01
    cft_halt_buffer_pct: float = 0.003
    # -- H4: squeeze — entrar solo si la vol 4H esta comprimida (breakout tras compresion
    #    tiene mas recorrido; filtra falsos breakouts en chop). ATR14-4H/close en percentil
    #    <= squeeze_max_pctile de los ultimos squeeze_lookback_4h bloques cerrados. --
    use_squeeze: bool = False
    squeeze_lookback_4h: int = 90     # ~15 dias de bloques 4H
    squeeze_max_pctile: float = 0.5   # mediana

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
        # PnL realizado por cierre (ts, Decimal neto de fees) — consumido por el sim prop
        self.realized: list[tuple[datetime, Decimal]] = []
        self._settlements = load_funding(config.symbol)
        self._settle_idx = 0
        self._phase_ctx = MacroContext(config.symbol.split("-")[0].upper())
        self._entry_phases = tuple(
            p.strip() for p in config.entry_halving_phases.split(",") if p.strip()
        )
        self._live_mode = not self._is_backtest_client()
        self._live_state: dict = {
            "pos": None, "day": "", "day_start_equity": 0.0,
            "entries_today": 0, "settle_idx": 0,
        }
        if self._live_mode and self._session is not None:
            self._load_live_state()

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
        # MTM del short ANTES de leer equity: la barra actual ya refleja su uPnL
        if self._pos is not None and self._pos.get("side") == "short":
            self._mtm_short(price)
        if self._cfg.model_funding and self._pos is not None:
            self._accrue_funding(int(last["timestamp"]), price)
        else:
            self._advance_settle_idx(int(last["timestamp"]))
        equity = self._equity(price)

        # -- Rollover de dia UTC --
        day_key = ts.strftime("%Y-%m-%d")
        if day_key != self._day:
            self._day = day_key
            self._day_start_equity = equity
            self._entries_today = 0
        day_pnl = (equity / self._day_start_equity - 1.0) if self._day_start_equity else 0.0
        cft_status = self._update_cft_monitor(ts, price, equity)

        if self._pos is not None and cft_status.get("hard_stop"):
            self._close_all(ts, price, "cft_hard_stop")
            self._save_live_state()
            return
        if self._pos is not None:
            self._manage_position(df, last, ts, price, day_pnl)
        if self._pos is None and ts.hour % 4 == 3 and not self._cft_blocks_entries(cft_status):
            self._try_enter(df, ts, price, equity, day_pnl)
        self._save_live_state()

    # ------------------------------------------------------------------
    # Gestion de la posicion (cada barra 1H)
    # ------------------------------------------------------------------

    def _manage_position(self, df: pd.DataFrame, last, ts: datetime,
                         price: float, day_pnl: float) -> None:
        pos = self._pos
        bar_low = float(last["low"])
        bar_high = float(last["high"])
        short = pos.get("side") == "short"

        # Kill switch diario interno
        if day_pnl <= -self._cfg.daily_flatten:
            self._close_all(ts, price, "daily_flatten")
            return

        # Stop (chequeo intrabar contra el extremo; fill market al close de la barra)
        if (bar_high >= pos["stop"]) if short else (bar_low <= pos["stop"]):
            self._close_all(ts, price, "stop_be" if pos["tp1_done"] else "stop_loss")
            return

        # TP1 parcial + break-even
        if not pos["tp1_done"] and ((bar_low <= pos["tp1"]) if short
                                    else (bar_high >= pos["tp1"])):
            self._take_tp1(ts, price)

        # Trailing chandelier tras TP1 (water_mark: high-water long / low-water short)
        if pos["tp1_done"]:
            if short:
                wm_ref = bar_low if self._cfg.trail_on_high else price
                pos["water_mark"] = min(pos["water_mark"], wm_ref)
                trail = pos["water_mark"] + self._cfg.trail_atr_mult * pos["atr_entry"]
                pos["stop"] = min(pos["stop"], trail)
            else:
                wm_ref = bar_high if self._cfg.trail_on_high else price
                pos["water_mark"] = max(pos["water_mark"], wm_ref)
                trail = pos["water_mark"] - self._cfg.trail_atr_mult * pos["atr_entry"]
                pos["stop"] = max(pos["stop"], trail)

        # Salida por regimen en cierre de bloque 4H
        if ts.hour % 4 == 3 and self._regime(df, ts) != ("bear" if short else "bull"):
            self._close_all(ts, price, "regime_exit")

    def _take_tp1(self, ts: datetime, price: float) -> None:
        pos, cfg = self._pos, self._cfg
        qty_out = (pos["qty"] * Decimal(str(cfg.tp1_size))).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty_out <= 0:
            return
        if pos.get("side") == "short":
            pnl = self._cover_short(qty_out, price)
            if pnl is None:
                return
        else:
            r = self._client.place_order(cfg.symbol, "sell", "market",
                                         qty_out, strategy=self.name)
            if r.status != "filled":
                return
            self.log_trade(r)
            fill = float(r.filled_price or price)
            pnl = Decimal(str(round((fill - pos["entry"]) * float(qty_out)
                                    - float(r.fee), 8)))
        funding_part = self._allocate_funding(pos, qty_out)
        self.realized.append((ts, pnl - funding_part))
        pos["qty"] -= qty_out
        pos["tp1_done"] = True
        if cfg.be_after_tp1:
            pos["stop"] = pos["entry"]          # break-even
        pos["water_mark"] = price
        net = pnl - funding_part
        equity = self._equity(price)
        self._persist_live_event("tp1", ts, {
            "side": pos.get("side", "long"),
            "price": round(price, 2),
            "qty": str(qty_out),
            "pnl": float(net),
            "equity": round(equity, 2),
        })
        self._update_cft_monitor(ts, price, equity, {
            "kind": "tp1", "side": pos.get("side", "long"),
            "qty": str(qty_out), "pnl": float(net),
        })

    # ------------------------------------------------------------------
    # Entrada (solo en cierre de bloque 4H UTC)
    # ------------------------------------------------------------------

    def _try_enter(self, df: pd.DataFrame, ts: datetime, price: float,
                   equity: float, day_pnl: float) -> None:
        cfg = self._cfg
        def skip(reason: str, **extra) -> None:
            self._persist_live_event("signal", ts, {
                "decision": "skip", "reason": reason, "price": round(price, 2),
                "equity": round(equity, 2), "day_pnl": round(day_pnl, 5), **extra,
            })

        if self._entries_today >= cfg.max_entries_per_day:
            return skip("max_entries_per_day")
        if day_pnl <= -cfg.daily_loss_stop or day_pnl >= cfg.daily_profit_stop:
            return skip("daily_guard")
        phase = self._halving_phase(ts)
        if self._entry_phases and phase not in self._entry_phases:
            return skip("phase_block", phase=phase)
        regime = self._regime(df, ts, check_vol=True)
        if regime == "bull":
            side = "long"
        elif regime == "bear" and cfg.allow_shorts:
            side = "short"
        else:
            return skip("no_regime", phase=phase, regime=regime)

        df4 = resample_to_4h(df)
        if len(df4) < cfg.ema_pullback_4h + cfg.pullback_lookback_4h + 2:
            return skip("insufficient_4h", phase=phase, side=side)
        ema4 = ema_fn(df4["close"], cfg.ema_pullback_4h)
        atr4 = atr_fn(df4["high"], df4["low"], df4["close"], cfg.atr_period)

        # Ultimo bloque = recien cerrado (evaluamos en hour % 4 == 3)
        c_now, h_prev = float(df4["close"].iloc[-1]), float(df4["high"].iloc[-2])
        ema_now, atr_now = float(ema4.iloc[-1]), float(atr4.iloc[-1])
        if atr_now <= 0 or pd.isna(atr_now) or pd.isna(ema_now):
            return skip("invalid_atr_or_ema", phase=phase, side=side)

        # H4: filtro squeeze — solo entrar con vol comprimida (percentil del ATR% 4H)
        if cfg.use_squeeze:
            atr_pct = (atr4 / df4["close"]).iloc[-cfg.squeeze_lookback_4h:]
            if len(atr_pct) < cfg.squeeze_lookback_4h or atr_pct.isna().any():
                return skip("insufficient_squeeze", phase=phase, side=side)
            rank = float((atr_pct <= atr_pct.iloc[-1]).mean())
            if rank > cfg.squeeze_max_pctile:
                return skip("squeeze_block", phase=phase, side=side, squeeze_rank=round(rank, 3))

        if cfg.entry_mode == "breakout":
            # E5: breakout Donchian — cierre 4H fuera del rango de los N bloques previos
            n = cfg.breakout_lookback_4h
            if len(df4) < n + 2:
                return skip("insufficient_donchian", phase=phase, side=side)
            if side == "long":
                donchian_high = float(df4["high"].iloc[-(n + 1):-1].max())
                if not (c_now > donchian_high and c_now > ema_now):
                    return skip("breakout_not_triggered", phase=phase, side=side)
            else:
                donchian_low = float(df4["low"].iloc[-(n + 1):-1].min())
                if not (c_now < donchian_low and c_now < ema_now):
                    return skip("breakout_not_triggered", phase=phase, side=side)
        else:
            # v0: pullback a la EMA50-4H + gatillo de reanudacion (espejado para shorts)
            emas = ema4.iloc[-cfg.pullback_lookback_4h:]
            if side == "long":
                lows = df4["low"].iloc[-cfg.pullback_lookback_4h:]
                touched = bool((lows.values <= emas.values).any())
                trigger = c_now > h_prev and c_now > ema_now
            else:
                highs = df4["high"].iloc[-cfg.pullback_lookback_4h:]
                touched = bool((highs.values >= emas.values).any())
                l_prev = float(df4["low"].iloc[-2])
                trigger = c_now < l_prev and c_now < ema_now
            if not (touched and trigger):
                return skip("pullback_not_triggered", phase=phase, side=side)

        # -- Sizing por riesgo: el stop dimensiona la posicion --
        stop_dist = cfg.atr_stop_mult * atr_now
        stop = price - stop_dist if side == "long" else price + stop_dist
        if stop <= 0:
            return skip("invalid_stop", phase=phase, side=side)
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
            return skip("min_notional", phase=phase, side=side)

        ok, reason = self.check_risk(cfg.symbol, Decimal(str(notional)))
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return skip("risk_manager", phase=phase, side=side, risk_reason=reason)

        self._persist_live_event("signal", ts, {
            "decision": "enter", "side": side, "phase": phase,
            "price": round(price, 2), "equity": round(equity, 2),
            "risk_usdt": round(risk_usdt, 2), "notional": round(notional, 2),
            "stop": round(stop, 2),
        })

        if side == "short":
            self._open_short(ts, price, qty_d, stop_dist, atr_now, ema_now, equity)
            return

        r = self._client.place_order(cfg.symbol, "buy", "market", qty_d, strategy=self.name)
        if r.status != "filled" or not r.filled_price:
            return
        self.log_trade(r)
        entry = float(r.filled_price)
        self._pos = {
            "side": "long",
            "qty": r.filled_qty, "entry": entry,
            "stop": entry - stop_dist,
            "tp1": entry + cfg.tp1_r * stop_dist,
            "tp1_done": False, "water_mark": entry,
            "atr_entry": atr_now,
            "entry_ms": int(ts.timestamp() * 1000),
            "funding_paid": 0.0,
        }
        self._entries_today += 1
        self._journal_open(
            side="long", ts=ts.isoformat(), price=entry,
            invest=float(r.filled_qty) * entry, stop=self._pos["stop"],
            qty=float(r.filled_qty), balance_before=equity, ls=0, ss=0,
            indicators={
                "atr4h": round(atr_now, 2),
                "ema50_4h": round(ema_now, 2),
                "halving_phase": phase,
            },
            tp=self._pos["tp1"],
        )
        self._persist_live_event("open", ts, {
            "side": "long", "price": round(entry, 2), "qty": str(r.filled_qty),
            "stop": round(self._pos["stop"], 2), "tp1": round(self._pos["tp1"], 2),
            "equity": round(equity, 2), "phase": phase,
        })
        self._update_cft_monitor(ts, entry, self._equity(entry), {
            "kind": "open", "side": "long", "qty": str(r.filled_qty),
        })

    # ------------------------------------------------------------------
    # Shorts sinteticos (solo backtest — ver docstring del modulo)
    # ------------------------------------------------------------------

    def _open_short(self, ts: datetime, price: float, qty_d: Decimal, stop_dist: float,
                    atr_now: float, ema_now: float, equity: float) -> None:
        cfg, cli = self._cfg, self._client
        if not hasattr(cli, "adjust_balance"):
            logger.warning("[{}] shorts sinteticos requieren adjust_balance; omitido", self.name)
            return
        slip = float(getattr(cli, "_slippage_bps", 0)) / 10000.0
        fee_rate = float(getattr(cli, "_fee_rate", Decimal("0.001")))
        q = float(qty_d)
        fill = price * (1 - slip)                 # sell recibe menos (igual que _fill_market)
        fee_open = q * fill * fee_rate
        cli.adjust_balance("USDT", Decimal(str(round(-fee_open, 8))))
        self._pos = {
            "side": "short",
            "qty": qty_d, "entry": fill,
            "stop": fill + stop_dist,
            "tp1": fill - cfg.tp1_r * stop_dist,
            "tp1_done": False, "water_mark": fill,
            "atr_entry": atr_now,
            "mark": fill,                          # ultimo precio marcado contra balance
            "fee_open_unit": fee_open / q,         # prorrateo del fee de apertura
            "entry_ms": int(ts.timestamp() * 1000),
            "funding_paid": 0.0,
        }
        self._entries_today += 1
        self._journal_open(
            side="short", ts=ts.isoformat(), price=fill,
            invest=q * fill, stop=self._pos["stop"],
            qty=q, balance_before=equity, ls=0, ss=0,
            indicators={
                "atr4h": round(atr_now, 2),
                "ema50_4h": round(ema_now, 2),
                "halving_phase": self._halving_phase(ts),
            },
            tp=self._pos["tp1"],
        )
        self._persist_live_event("open", ts, {
            "side": "short", "price": round(fill, 2), "qty": str(qty_d),
            "stop": round(self._pos["stop"], 2), "tp1": round(self._pos["tp1"], 2),
            "equity": round(equity, 2), "phase": self._halving_phase(ts),
        })
        self._update_cft_monitor(ts, fill, self._equity(fill), {
            "kind": "open", "side": "short", "qty": str(qty_d),
        })

    def _mtm_short(self, price: float) -> None:
        """Marca el uPnL del short contra el balance USDT (equity continua para el DD)."""
        pos = self._pos
        delta = (pos["mark"] - price) * float(pos["qty"])
        if delta:
            self._client.adjust_balance("USDT", Decimal(str(round(delta, 8))))
        pos["mark"] = price

    def _advance_settle_idx(self, ts_ms: int) -> None:
        while (self._settle_idx < len(self._settlements)
               and self._settlements[self._settle_idx][0] <= ts_ms):
            self._settle_idx += 1

    def _accrue_funding(self, ts_ms: int, price: float) -> None:
        """Devenga funding Bybit por settlement.

        Lineal USDT: rate>0 => long paga / short cobra. Usamos precio de barra como
        proxy de mark settlement; el dato de funding solo se aplica cuando el settlement
        ya quedo atras, sin mirar futuro.
        """
        pos = self._pos
        if pos is None:
            self._advance_settle_idx(ts_ms)
            return
        side_mult = 1.0 if pos.get("side") != "short" else -1.0
        while (self._settle_idx < len(self._settlements)
               and self._settlements[self._settle_idx][0] <= ts_ms):
            s_ts, rate = self._settlements[self._settle_idx]
            self._settle_idx += 1
            if s_ts <= pos.get("entry_ms", 0):
                continue
            mark_manifest_funding_consumed(self._cfg.symbol, s_ts)
            cost = float(pos["qty"]) * price * rate * side_mult
            if cost:
                self._client.adjust_balance("USDT", Decimal(str(round(-cost, 8))))
                pos["funding_paid"] += cost

    @staticmethod
    def _allocate_funding(pos: dict, qty_out: Decimal) -> Decimal:
        """Prorratea funding acumulado al tramo cerrado y lo descuenta del realized."""
        funding = float(pos.get("funding_paid", 0.0))
        qty_before = float(pos.get("qty", Decimal("0")))
        if not funding or qty_before <= 0:
            return Decimal("0")
        ratio = min(1.0, float(qty_out) / qty_before)
        part = funding * ratio
        pos["funding_paid"] = funding - part
        return Decimal(str(round(part, 8)))

    def _cover_short(self, qty: Decimal, price: float) -> Decimal | None:
        """Recompra sintetica de `qty` a mercado (slippage+fee como _fill_market).
        Devuelve el PnL neto realizado del tramo (incluye fee de apertura prorrateado)."""
        pos, cli = self._pos, self._client
        slip = float(getattr(cli, "_slippage_bps", 0)) / 10000.0
        fee_rate = float(getattr(cli, "_fee_rate", Decimal("0.001")))
        q = float(qty)
        fill = price * (1 + slip)                 # buy paga mas
        fee_close = q * fill * fee_rate
        # El uPnL ya esta marcado hasta pos["mark"]; ajustar el tramo mark->fill y el fee
        delta = (pos["mark"] - fill) * q - fee_close
        cli.adjust_balance("USDT", Decimal(str(round(delta, 8))))
        pnl = (pos["entry"] - fill) * q - fee_close - pos["fee_open_unit"] * q
        return Decimal(str(round(pnl, 8)))

    # ------------------------------------------------------------------
    # Operativa live/paper: estado persistente, journal y monitor CFT
    # ------------------------------------------------------------------

    def _is_backtest_client(self) -> bool:
        return self._client.__class__.__name__ == "BacktestClient"

    @staticmethod
    def _json_pos(pos: dict | None) -> dict | None:
        if pos is None:
            return None
        out = dict(pos)
        if isinstance(out.get("qty"), Decimal):
            out["qty"] = str(out["qty"])
        return out

    @staticmethod
    def _load_pos(pos: dict | None) -> dict | None:
        if pos is None:
            return None
        out = dict(pos)
        if "qty" in out:
            out["qty"] = Decimal(str(out["qty"]))
        return out

    def _load_live_state(self) -> None:
        try:
            from core.database import get_or_create_bot_state
            bot_state = get_or_create_bot_state(
                self._session, strategy_name="prop_swing", symbol=self._cfg.symbol,
            )
            self._live_state = {**self._live_state, **bot_state.get_config()}
        except Exception as exc:
            logger.warning("[{}] No se pudo cargar estado live: {}", self.name, exc)
            return
        self._pos = self._load_pos(self._live_state.get("pos"))
        self._day = str(self._live_state.get("day") or "")
        self._day_start_equity = float(self._live_state.get("day_start_equity") or 0.0)
        self._entries_today = int(self._live_state.get("entries_today") or 0)
        self._settle_idx = int(self._live_state.get("settle_idx") or 0)

    def _save_live_state(self) -> None:
        if not self._live_mode or self._session is None:
            return
        self._live_state.update({
            "pos": self._json_pos(self._pos),
            "day": self._day,
            "day_start_equity": self._day_start_equity,
            "entries_today": self._entries_today,
            "settle_idx": self._settle_idx,
        })
        try:
            from core.database import get_or_create_bot_state
            bot_state = get_or_create_bot_state(
                self._session, strategy_name="prop_swing", symbol=self._cfg.symbol,
            )
            bot_state.set_config(self._live_state)
        except Exception as exc:
            logger.warning("[{}] No se pudo guardar estado live: {}", self.name, exc)

    def _persist_live_event(self, kind: str, ts: datetime, payload: dict) -> None:
        if self._is_backtest_client() or not self._cfg.persist_live_prop_log:
            return
        try:
            out_dir = Path("data") / "runtime"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / "prop_live_journal.jsonl"
            event = {
                "ts": ts.isoformat(),
                "strategy": self.name,
                "symbol": self._cfg.symbol,
                "kind": kind,
                **payload,
            }
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=True) + "\n")
        except Exception as exc:
            logger.warning("[{}] No se pudo persistir evento prop: {}", self.name, exc)

    def _cft_cfg(self):
        from core.cft_monitor import CFTMonitorConfig
        return CFTMonitorConfig(
            account_size=self._cfg.cft_account_size,
            phase=self._cfg.cft_phase,
            daily_dd_pct=self._cfg.cft_daily_dd_pct,
            max_loss_pct=self._cfg.cft_max_loss_pct,
            warn_buffer_pct=self._cfg.cft_warn_buffer_pct,
            halt_buffer_pct=self._cfg.cft_halt_buffer_pct,
        )

    def _update_cft_monitor(
        self, ts: datetime, price: float, equity: float, trade_event: dict | None = None,
    ) -> dict:
        if self._is_backtest_client() or not self._cfg.cft_monitor_enabled:
            return {}
        try:
            from core.cft_monitor import update_status
            return update_status(
                strategy=self.name, symbol=self._cfg.symbol, ts=ts, equity=equity,
                cfg=self._cft_cfg(), trade_event=trade_event,
            )
        except Exception as exc:
            logger.warning("[{}] Monitor CFT fallo: {}", self.name, exc)
            return {}

    def _cft_blocks_entries(self, status: dict) -> bool:
        if not status:
            return False
        if status.get("hard_stop"):
            self._persist_live_event("cft_block", datetime.now(timezone.utc), {
                "rule_state": status.get("rule_state"),
                "min_cushion_pct": status.get("min_cushion_pct"),
            })
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _regime(self, df: pd.DataFrame, ts: datetime,
                check_vol: bool = False) -> str | None:
        """Regimen en diario CERRADO (dias < hoy UTC): "bull" | "bear" | None.
        Bear = espejo exacto del bull. check_vol añade el filtro ATR% (ambos lados)."""
        daily = resample_to_daily(df)
        daily = daily[daily["dt"].dt.date < ts.date()]
        if len(daily) < 210:
            return None
        close = daily["close"]
        ema50 = float(ema_fn(close, 50).iloc[-1])
        ema200 = float(ema_fn(close, 200).iloc[-1])
        adx_d = float(adx_fn(daily["high"], daily["low"], close, 14).iloc[-1])
        c = float(close.iloc[-1])
        if adx_d < self._cfg.adx_min or c <= 0:
            return None
        if check_vol:
            atr_d = float(atr_fn(daily["high"], daily["low"], close, 14).iloc[-1])
            if atr_d / c > self._cfg.vol_max_atr_pct_d:
                return None
        if ema50 > ema200 and c > ema200:
            return "bull"
        if ema50 < ema200 and c < ema200:
            return "bear"
        return None

    def _halving_phase(self, ts: datetime) -> str:
        return self._phase_ctx.halving_phase(ts)[1]

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
        if pos.get("side") == "short":
            pnl_d = self._cover_short(pos["qty"], price)
            if pnl_d is None:
                return
            funding_part = self._allocate_funding(pos, pos["qty"])
            net = pnl_d - funding_part
            self.realized.append((ts, net))
            self._journal_close(
                ts=ts.isoformat(), price=price, pnl=float(net), reason=reason,
                holding_hours=0.0, balance_after=self._equity(price), ls=0, ss=0,
                indicators={"funding_paid": float(funding_part)},
            )
            equity = self._equity(price)
            self._persist_live_event("close", ts, {
                "side": "short", "price": round(price, 2), "qty": str(pos["qty"]),
                "pnl": float(net), "reason": reason, "equity": round(equity, 2),
            })
            self._update_cft_monitor(ts, price, equity, {
                "kind": "close", "side": "short", "qty": str(pos["qty"]),
                "pnl": float(net), "reason": reason,
            })
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
        funding_part = self._allocate_funding(pos, pos["qty"])
        net = Decimal(str(round(pnl - float(r.fee), 8))) - funding_part
        self.realized.append((ts, net))
        self._journal_close(
            ts=ts.isoformat(), price=fill, pnl=float(net), reason=reason,
            holding_hours=0.0, balance_after=self._equity(fill), ls=0, ss=0,
            indicators={"funding_paid": float(funding_part)},
        )
        equity = self._equity(fill)
        self._persist_live_event("close", ts, {
            "side": "long", "price": round(fill, 2), "qty": str(pos["qty"]),
            "pnl": float(net), "reason": reason, "equity": round(equity, 2),
        })
        self._update_cft_monitor(ts, fill, equity, {
            "kind": "close", "side": "long", "qty": str(pos["qty"]),
            "pnl": float(net), "reason": reason,
        })
        self._pos = None
