"""
MR-Regimen 1H — EXP-012 (docs/income/plan.md Via B, pre-registro).

Hipotesis: los dips bruscos 1H en BTC revierten SOLO cuando el regimen macro
diario es alcista (compradores de dip + tendencia de fondo); en regimen
bajista la misma señal es un cuchillo cayendo. El edge esta en el
CONDICIONAMIENTO por regimen, no en el oscilador — distinto de
`mean_reversion.py` (sin condicionar, ya fallo y se borro del repo).

Filtro maestro (diario, dia UTC ANTERIOR cerrado — mismo criterio que
regime_bull del Swing, recalculado aqui sin tocar swing_allocator.py):
EMA50D > EMA200D AND close_D > EMA200D AND ADX14D > adx_min.

Senal 1H: close < SMA20 - entry_mult * ATR14 -> BUY al close de esa vela.
Salidas: reversion (close >= SMA20 actual), time-stop, o stop atr_mult * ATR14
bajo la entrada (chequeo intrabar low, patron funding_extreme). Long-only
spot, sin piramidar. Solo backtest — split IS/OOS y gates en docs/income/plan.md.
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
    adx as adx_fn, atr as atr_fn, ema as ema_fn, resample_to_daily, sma as sma_fn,
)

if TYPE_CHECKING:
    from core.exchange import OKXClient
    from core.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Senales (puras, testeables)
# ---------------------------------------------------------------------------

def regime_is_bullish(ema50: float, ema200: float, close: float, adx_val: float,
                       adx_min: float = 15.0) -> bool:
    """Filtro maestro: mismo criterio que regime_bull del Swing Allocator."""
    return ema50 > ema200 and close > ema200 and adx_val > adx_min


def dip_entry_signal(close: float, sma20: float, atr14: float, entry_mult: float) -> bool:
    """close_1H < SMA20_1H - entry_mult * ATR14_1H."""
    return close < sma20 - entry_mult * atr14


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class MrRegimeConfig:
    symbol: str = "BTC-USDT"
    lookback_hours: int = 5760        # 240 dias x 24h — cubre EMA200D con margen

    # -- Filtro maestro diario --
    adx_min: float = 15.0

    # -- Senal 1H --
    sma_period: int = 20
    atr_period: int = 14
    entry_mult: float = 2.0
    cooldown_hours: int = 24

    # -- Gestion --
    time_stop_hours: int = 72
    stop_mult: float = 3.0

    # -- Riesgo --
    risk_per_trade: float = 0.01

    @classmethod
    def from_dict(cls, d: dict) -> "MrRegimeConfig":
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

class MrRegimeBot(BaseStrategy):
    def __init__(self, client: "OKXClient", config: MrRegimeConfig,
                 session, risk_manager: "RiskManager | None" = None) -> None:
        super().__init__(client, config.to_dict(), session, risk_manager)
        self._cfg = config
        self._pos: dict | None = None
        self._last_entry_ms: int = 0
        self._daily_cache: dict = {}
        self.realized: list[tuple[datetime, Decimal]] = []

    @property
    def name(self) -> str:
        return f"mr_regime_{self._cfg.symbol.lower().replace('-', '_')}"

    def should_enter(self) -> bool:
        return False

    def should_exit(self) -> bool:
        return False

    # ------------------------------------------------------------------

    def run(self) -> None:
        cfg = self._cfg
        df = self._client.get_ohlcv(cfg.symbol, limit=cfg.lookback_hours)
        if df is None or len(df) < 300:
            return
        last = df.iloc[-1]
        ts_ms = int(last["timestamp"])
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        price = float(last["close"])

        closes = df["close"].astype(float)
        highs  = df["high"].astype(float)
        lows   = df["low"].astype(float)
        sma20  = float(sma_fn(closes, cfg.sma_period).iloc[-1])
        atr14  = float(atr_fn(highs, lows, closes, cfg.atr_period).iloc[-1])
        if pd.isna(sma20) or pd.isna(atr14) or atr14 <= 0:
            return

        if self._pos is not None:
            self._manage(last, ts, ts_ms, price, sma20)
            return

        if ts_ms - self._last_entry_ms < cfg.cooldown_hours * 3_600_000:
            return
        if not self._get_daily_regime(df, ts):
            return
        if not dip_entry_signal(price, sma20, atr14, cfg.entry_mult):
            return
        self._enter(ts, ts_ms, price, atr14)

    # ------------------------------------------------------------------
    # Filtro maestro diario (anti-lookahead: solo dias UTC cerrados)
    # ------------------------------------------------------------------

    def _get_daily_regime(self, df: pd.DataFrame, ts: datetime) -> bool:
        cfg = self._cfg
        date_key = ts.strftime("%Y-%m-%d")
        if self._daily_cache.get("date") == date_key:
            return self._daily_cache["ok"]

        daily = resample_to_daily(df)
        current_day = pd.Timestamp(ts.date(), tz="UTC")
        closed_daily = daily[daily["dt"] < current_day]
        ok = False
        if len(closed_daily) >= 201:
            d_closes = closed_daily["close"]
            d_highs  = closed_daily["high"]
            d_lows   = closed_daily["low"]
            ema50  = float(ema_fn(d_closes, 50).iloc[-1])
            ema200 = float(ema_fn(d_closes, 200).iloc[-1])
            adx_val = float(adx_fn(d_highs, d_lows, d_closes, 14).iloc[-1])
            last_close = float(d_closes.iloc[-1])
            ok = regime_is_bullish(ema50, ema200, last_close, adx_val, cfg.adx_min)
        self._daily_cache = {"date": date_key, "ok": ok}
        return ok

    # ------------------------------------------------------------------
    # Gestion (cada barra 1H)
    # ------------------------------------------------------------------

    def _manage(self, last, ts: datetime, ts_ms: int, price: float, sma20: float) -> None:
        pos, cfg = self._pos, self._cfg
        if float(last["low"]) <= pos["stop"]:
            self._close(ts, price, "stop_loss")
            return
        if price >= sma20:
            self._close(ts, price, "reversion")
            return
        if ts_ms >= pos["entry_ms"] + cfg.time_stop_hours * 3_600_000:
            self._close(ts, price, "time_exit")

    # ------------------------------------------------------------------
    # Entrada
    # ------------------------------------------------------------------

    def _enter(self, ts: datetime, ts_ms: int, price: float, atr14: float) -> None:
        cfg = self._cfg
        equity = self._equity(price)
        stop_dist = cfg.stop_mult * atr14
        stop = price - stop_dist
        if stop <= 0:
            return
        risk_usdt = equity * cfg.risk_per_trade
        qty = risk_usdt / stop_dist
        usdt = float(self._client.get_balance().get("USDT", Decimal("0")))
        if qty * price > usdt * 0.99:
            qty = usdt * 0.99 / price
        qty_d = Decimal(str(qty)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty_d <= 0 or float(qty_d) * price < 10:
            return
        ok, reason = self.check_risk(cfg.symbol, Decimal(str(float(qty_d) * price)))
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        r = self._client.place_order(cfg.symbol, "buy", "market", qty_d,
                                     strategy=self.name)
        if r.status != "filled" or not r.filled_price:
            return
        self.log_trade(r)
        entry = float(r.filled_price)
        self._pos = {"qty": r.filled_qty, "entry": entry, "entry_ms": ts_ms,
                     "stop": entry - stop_dist}
        self._last_entry_ms = ts_ms
        self._journal_open(
            side="long", ts=ts.isoformat(), price=entry,
            invest=float(r.filled_qty) * entry, stop=self._pos["stop"],
            qty=float(r.filled_qty), balance_before=equity, ls=0, ss=0,
            indicators={"atr14_1h": round(atr14, 2)},
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
        net = pnl - float(r.fee)
        self.realized.append((ts, Decimal(str(round(net, 8)))))
        self._journal_close(
            ts=ts.isoformat(), price=fill, pnl=pnl, reason=reason,
            holding_hours=(ts.timestamp() * 1000 - pos["entry_ms"]) / 3_600_000,
            balance_after=self._equity(fill), ls=0, ss=0,
            indicators={},
        )
        self._pos = None
