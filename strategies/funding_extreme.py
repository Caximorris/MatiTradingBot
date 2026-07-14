"""
Funding Extreme Long — motor N4 del PLAN B prop (HYROTRADER_PLAN seccion 13).

Unico superviviente de los screens N2 (2026-07-03): funding Bybit en percentil extremo
trailing -> LONG a ~72h. Ambas colas son long:
- rate > p95 (longs crowded): mediana f72 +92bps, WR 65%, 6/6 anios. El efecto tarda
  ~1 dia en arrancar (f24 mediana -16) -> entry_delay_hi_hours=24 por defecto.
- rate < p05 (shorts crowded, squeeze): mediana +58bps, 5/6 anios. Entrada inmediata.

Senales por settlement (00/08/16 UTC), percentil trailing de 90 settlements (30d)
SHIFT(1) — el umbral solo usa settlements ANTERIORES (anti-lookahead). Dedup conjunto:
sin senal nueva a menos de dedup_hours de la anterior (leccion N2: deduplicar SIEMPRE).

MODELO N1 (Bybit): correr con --costs bybit|bybit_cons (fee taker 5.5bps). El FUNDING
se devenga aqui por settlement mientras la posicion esta abierta (long paga rate>0,
cobra rate<0) via adjust_balance — critico: la cola p95 entra pagando funding caro.
Fuente: data/cache/funding_bybit_{SYMBOL}.json (tools/alpha_screens.py lo descarga).

Gestion: stop atr_stop_mult x ATR14-4H bajo la entrada (chequeo intrabar 1H, fill al
close — igual que prop_swing), salida por tiempo a hold_hours. Sizing por riesgo con
cap de notional. Limites diarios prop identicos a prop_swing.

`self.realized` = (ts, pnl neto de fees y funding) por cierre — consumido por el
simulador prop. Solo backtest (requiere adjust_balance para el funding).
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
from strategies.indicators import atr as atr_fn, resample_to_4h

if TYPE_CHECKING:
    from core.exchange import OKXClient
    from core.risk_manager import RiskManager

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Senales (pura, testeable)
# ---------------------------------------------------------------------------

def build_funding_signals(rows: list[tuple[int, float]], window: int = 90,
                          p_hi: float = 0.95, p_lo: float = 0.05,
                          use_hi: bool = True, use_lo: bool = True,
                          dedup_hours: int = 72) -> list[tuple[int, str]]:
    """[(ts_ms, "hi"|"lo")] deduplicado. Umbral = percentil trailing shift(1):
    el settlement t se compara contra los `window` settlements t-window..t-1."""
    if len(rows) < window + 2:
        return []
    df = pd.DataFrame(sorted(rows), columns=["ts", "rate"])
    r = df["rate"]
    hi = r.rolling(window).quantile(p_hi).shift(1)
    lo = r.rolling(window).quantile(p_lo).shift(1)
    out: list[tuple[int, str]] = []
    last_ts = None
    dedup_ms = dedup_hours * 3_600_000
    for ts, rate, h, l in zip(df["ts"], r, hi, lo):
        if pd.isna(h) or pd.isna(l):
            continue
        if use_hi and rate > h:
            cola = "hi"
        elif use_lo and rate < l:
            cola = "lo"
        else:
            continue
        if last_ts is not None and ts - last_ts < dedup_ms:
            continue
        out.append((int(ts), cola))
        last_ts = ts
    return out


def load_funding(symbol: str) -> list[tuple[int, float]]:
    """Devuelve settlements ordenados ASCENDENTE por timestamp.

    El cache en disco esta en el orden crudo de paginacion de la API (mas
    reciente primero, `tools/alpha_screens.py` pagina hacia atras con
    `endTime`) — SIN ordenar. `_advance_settle_idx`/`_accrue_funding` (aqui,
    en `prop_swing.py` y en `basis_carry.py`) asumen orden ascendente para su
    puntero monotono; sin el `sorted()` el puntero nunca avanza (el primer
    elemento tiene el timestamp mas reciente) y el funding NUNCA se devenga.
    Bug encontrado 2026-07-14 mientras se depuraba `basis_carry.py`.
    """
    sym = symbol.replace("-", "").upper()
    path = _ROOT / "data" / "cache" / f"funding_bybit_{sym}.json"
    if not path.exists():
        return []
    rows = [(int(ts), float(rate)) for ts, rate in json.load(open(path))]
    return sorted(rows)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class FundingExtremeConfig:
    symbol: str = "BTC-USDT"
    lookback_hours: int = 1000        # ATR14-4H solo necesita ~60 bloques; margen amplio

    # -- Senal --
    pctile_window: int = 90           # 90 settlements = 30 dias
    p_hi: float = 0.95
    p_lo: float = 0.05
    use_hi: bool = True
    use_lo: bool = True
    dedup_hours: int = 72
    entry_delay_hi_hours: int = 24    # p95: el efecto tarda ~1 dia (f24 mediana -16bps)
    entry_delay_lo_hours: int = 0

    # -- Gestion --
    hold_hours: int = 72
    atr_period: int = 14              # ATR en 4H
    atr_stop_mult: float = 2.0

    # -- Riesgo (mismo esquema que prop_swing/E9) --
    risk_per_trade: float = 0.01
    max_notional_pct: float = 0.5     # legal en perps con leverage (E9)

    # -- Modelo N1: funding devengado por settlement mientras hay posicion --
    model_funding: bool = True

    # -- Limites prop internos --
    max_entries_per_day: int = 2
    daily_loss_stop: float = 0.015
    daily_profit_stop: float = 0.025
    daily_flatten: float = 0.025

    @classmethod
    def from_dict(cls, d: dict) -> "FundingExtremeConfig":
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

class FundingExtremeBot(BaseStrategy):
    def __init__(self, client: "OKXClient", config: FundingExtremeConfig,
                 session, risk_manager: "RiskManager | None" = None) -> None:
        super().__init__(client, config.to_dict(), session, risk_manager)
        self._cfg = config
        self._pos: dict | None = None
        self._pending: tuple[int, str] | None = None   # (enter_at_ms, cola)
        self._last_signal_ms: int = 0
        self._day: str = ""
        self._day_start_equity: float = 0.0
        self._entries_today: int = 0
        self.realized: list[tuple[datetime, Decimal]] = []
        # Funding: settlements crudos + senales precomputadas (umbral trailing shift(1),
        # sin lookahead; solo se CONSUMEN los <= ts del tick)
        self._settlements = load_funding(config.symbol)
        self._signals = build_funding_signals(
            self._settlements, config.pctile_window, config.p_hi, config.p_lo,
            config.use_hi, config.use_lo, config.dedup_hours)
        self._sig_idx = 0
        self._settle_idx = 0
        if not self._settlements:
            logger.warning("[{}] sin cache de funding Bybit — el motor no operara",
                           self.name)

    @property
    def name(self) -> str:
        return f"funding_extreme_{self._cfg.symbol.lower().replace('-', '_')}"

    def should_enter(self) -> bool:
        return False

    def should_exit(self) -> bool:
        return False

    # ------------------------------------------------------------------

    def run(self) -> None:
        cfg = self._cfg
        df = self._client.get_ohlcv(cfg.symbol, limit=cfg.lookback_hours)
        if df is None or len(df) < 300 or not self._signals:
            return
        last = df.iloc[-1]
        ts_ms = int(last["timestamp"])
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        price = float(last["close"])

        # Funding devengado por settlements cruzados con posicion abierta
        if self._pos is not None and cfg.model_funding:
            self._accrue_funding(ts_ms, price)
        else:
            self._advance_settle_idx(ts_ms)

        equity = self._equity(price)
        day_key = ts.strftime("%Y-%m-%d")
        if day_key != self._day:
            self._day = day_key
            self._day_start_equity = equity
            self._entries_today = 0
        day_pnl = (equity / self._day_start_equity - 1.0) if self._day_start_equity else 0.0

        if self._pos is not None:
            self._manage(last, ts, ts_ms, price, day_pnl)
        if self._pos is None:
            self._collect_signals(ts_ms)
            self._maybe_enter(df, ts, ts_ms, price, equity, day_pnl)

    # ------------------------------------------------------------------
    # Funding accrual (modelo N1)
    # ------------------------------------------------------------------

    def _advance_settle_idx(self, ts_ms: int) -> None:
        while (self._settle_idx < len(self._settlements)
               and self._settlements[self._settle_idx][0] <= ts_ms):
            self._settle_idx += 1

    def _accrue_funding(self, ts_ms: int, price: float) -> None:
        """Long paga rate>0 / cobra rate<0 sobre el notional en cada settlement."""
        pos = self._pos
        while (self._settle_idx < len(self._settlements)
               and self._settlements[self._settle_idx][0] <= ts_ms):
            s_ts, rate = self._settlements[self._settle_idx]
            self._settle_idx += 1
            if s_ts <= pos["entry_ms"]:
                continue
            cost = float(pos["qty"]) * price * rate
            if cost:
                self._client.adjust_balance("USDT", Decimal(str(round(-cost, 8))))
                pos["funding_paid"] += cost

    # ------------------------------------------------------------------
    # Gestion (cada barra 1H)
    # ------------------------------------------------------------------

    def _manage(self, last, ts: datetime, ts_ms: int, price: float,
                day_pnl: float) -> None:
        pos, cfg = self._pos, self._cfg
        if day_pnl <= -cfg.daily_flatten:
            self._close(ts, price, "daily_flatten")
            return
        if float(last["low"]) <= pos["stop"]:
            self._close(ts, price, "stop_loss")
            return
        if ts_ms >= pos["entry_ms"] + cfg.hold_hours * 3_600_000:
            self._close(ts, price, "time_exit")

    # ------------------------------------------------------------------
    # Senales y entrada
    # ------------------------------------------------------------------

    def _collect_signals(self, ts_ms: int) -> None:
        """Consume senales con settlement <= ts y programa la entrada con su delay."""
        cfg = self._cfg
        while self._sig_idx < len(self._signals) and self._signals[self._sig_idx][0] <= ts_ms:
            s_ts, cola = self._signals[self._sig_idx]
            self._sig_idx += 1
            delay_h = cfg.entry_delay_hi_hours if cola == "hi" else cfg.entry_delay_lo_hours
            enter_at = s_ts + delay_h * 3_600_000
            # Una sola pendiente a la vez; una senal nueva reemplaza a una pendiente
            # anterior no ejecutada (ya viene deduplicada a >=dedup_hours)
            self._pending = (enter_at, cola)

    def _maybe_enter(self, df: pd.DataFrame, ts: datetime, ts_ms: int, price: float,
                     equity: float, day_pnl: float) -> None:
        cfg = self._cfg
        if self._pending is None or ts_ms < self._pending[0]:
            return
        # Caducidad: si la barra llega >8h tarde (huecos), descartar
        if ts_ms > self._pending[0] + 8 * 3_600_000:
            self._pending = None
            return
        if self._entries_today >= cfg.max_entries_per_day:
            return
        if day_pnl <= -cfg.daily_loss_stop or day_pnl >= cfg.daily_profit_stop:
            self._pending = None
            return

        df4 = resample_to_4h(df)
        if len(df4) < cfg.atr_period + 2:
            return
        atr_now = float(atr_fn(df4["high"], df4["low"], df4["close"],
                               cfg.atr_period).iloc[-1])
        if atr_now <= 0 or pd.isna(atr_now):
            return
        _, cola = self._pending

        stop_dist = cfg.atr_stop_mult * atr_now
        stop = price - stop_dist
        if stop <= 0:
            return
        risk_usdt = equity * cfg.risk_per_trade
        qty = risk_usdt / stop_dist
        notional = qty * price
        max_notional = equity * cfg.max_notional_pct
        if notional > max_notional:
            qty = max_notional / price
            notional = max_notional
        usdt = float(self._client.get_balance().get("USDT", Decimal("0")))
        if notional > usdt * 0.99:
            qty = usdt * 0.99 / price
        qty_d = Decimal(str(qty)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty_d <= 0 or float(qty_d) * price < 10:
            self._pending = None
            return
        ok, reason = self.check_risk(cfg.symbol, Decimal(str(notional)))
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        r = self._client.place_order(cfg.symbol, "buy", "market", qty_d,
                                     strategy=self.name)
        if r.status != "filled" or not r.filled_price:
            return
        self.log_trade(r)
        entry = float(r.filled_price)
        self._pos = {
            "qty": r.filled_qty, "entry": entry, "entry_ms": ts_ms,
            "stop": entry - stop_dist, "cola": cola, "funding_paid": 0.0,
        }
        self._pending = None
        self._entries_today += 1
        self._journal_open(
            side="long", ts=ts.isoformat(), price=entry,
            invest=float(r.filled_qty) * entry, stop=self._pos["stop"],
            qty=float(r.filled_qty), balance_before=equity, ls=0, ss=0,
            indicators={"cola": cola, "atr4h": round(atr_now, 2)},
            tp=0.0,
        )

    # ------------------------------------------------------------------

    def _equity(self, price: float) -> float:
        balance = self._client.get_balance()
        usdt = float(balance.get("USDT", Decimal("0")))
        base = float(balance.get(self._cfg.symbol.split("-")[0], Decimal("0")))
        return usdt + base * price

    def _close(self, ts: datetime, price: float, reason: str) -> None:
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
        # PnL neto para el sim: precio + fee de cierre + funding devengado
        net = pnl - float(r.fee) - pos["funding_paid"]
        self.realized.append((ts, Decimal(str(round(net, 8)))))
        self._journal_close(
            ts=ts.isoformat(), price=fill, pnl=pnl, reason=reason,
            holding_hours=(ts.timestamp() * 1000 - pos["entry_ms"]) / 3_600_000,
            balance_after=self._equity(fill), ls=0, ss=0,
            indicators={"cola": pos["cola"],
                        "funding_paid": round(pos["funding_paid"], 2)},
        )
        self._pos = None
