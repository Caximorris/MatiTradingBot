"""
Basis Carry (cash-and-carry) — EXP-013 (docs/income/plan.md Via D, pre-registro).

Hipotesis: comprar BTC spot y abrir un short SINTETICO de igual cantidad en el
perpetuo (mismo patron que los shorts sinteticos de `prop_swing.py`: solo
backtest, mark-to-market por barra contra el balance USDT via adjust_balance)
deja la exposicion neta al PRECIO de BTC en ~0 — las ganancias/perdidas de
ambas patas se cancelan. El retorno de la estrategia viene SOLO del funding:
cuando el funding es positivo (los longs pagan), el lado corto lo cobra.

A diferencia de `funding_extreme.py` (direccional: entra LONG cuando el
funding esta en un extremo percentil) y de Swing v6 (direccional: apuesta al
precio de BTC), esta estrategia es MARKET-NEUTRAL por construccion — su fuente
de retorno (el spread funding entre longs y shorts) es estructuralmente
distinta de "acertar la direccion de BTC", que es lo que Swing, mr_regime y
funding_extreme comparten y por lo que fallan al compararse contra Swing.

Gate de regimen (evita pagar funding negativo durante bear stretches): solo
mantiene/abre la cesta cuando el promedio movil trailing de `funding_window`
settlements (00/08/16 UTC) es > `funding_min_avg`. El promedio en el momento t
solo usa settlements con ts <= t (ya liquidados, anti-lookahead).

Fuente de funding: Bybit (data/cache/funding_bybit_{SYMBOL}.json, igual que
funding_extreme — ver docs/income/plan.md sobre por que OKX no sirve aqui,
su endpoint publico solo retiene ~3 meses). Solo backtest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from strategies.base_strategy import BaseStrategy
from strategies.funding_extreme import load_funding

if TYPE_CHECKING:
    from core.exchange import OKXClient
    from core.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Senales (puras, testeables)
# ---------------------------------------------------------------------------

def build_avg_funding_series(rows: list[tuple[int, float]], window: int = 90
                              ) -> list[tuple[int, float]]:
    """[(ts_ms, avg_rate)] — media movil trailing de `window` settlements. El
    valor en ts usa ese settlement y los `window-1` anteriores (todos ya
    liquidados en ts), sin mirar futuro."""
    if len(rows) < window:
        return []
    df = pd.DataFrame(sorted(rows), columns=["ts", "rate"])
    avg = df["rate"].rolling(window).mean()
    return [(int(ts), float(a)) for ts, a in zip(df["ts"], avg) if not pd.isna(a)]


def gate_is_open(avg_rate: float, min_avg: float) -> bool:
    """True si el funding trailing promedio justifica mantener/abrir la cesta."""
    return avg_rate > min_avg


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class BasisCarryConfig:
    symbol: str = "BTC-USDT"
    lookback_hours: int = 1000

    # -- Sizing --
    notional_pct: float = 0.90        # % del equity en la pata spot (short sintetico = misma qty)

    # -- Gate de regimen (evita funding negativo prolongado) --
    funding_window: int = 90          # 90 settlements = 30 dias, igual que funding_extreme
    funding_min_avg: float = 0.0      # abre/mantiene solo si avg trailing > este umbral

    # -- Modelo de funding (short sintetico devenga por settlement) --
    model_funding: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "BasisCarryConfig":
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

class BasisCarryBot(BaseStrategy):
    def __init__(self, client: "OKXClient", config: BasisCarryConfig,
                 session, risk_manager: "RiskManager | None" = None) -> None:
        super().__init__(client, config.to_dict(), session, risk_manager)
        self._cfg = config
        self._pos: dict | None = None
        self.realized: list[tuple[datetime, Decimal]] = []
        self._settlements = load_funding(config.symbol)
        self._avg_series = build_avg_funding_series(self._settlements, config.funding_window)
        self._settle_idx = 0
        self._avg_idx = -1
        if not self._settlements:
            logger.warning("[{}] sin cache de funding Bybit — el motor no operara", self.name)

    @property
    def name(self) -> str:
        return f"basis_carry_{self._cfg.symbol.lower().replace('-', '_')}"

    def should_enter(self) -> bool:
        return False

    def should_exit(self) -> bool:
        return False

    # ------------------------------------------------------------------

    def run(self) -> None:
        cfg = self._cfg
        df = self._client.get_ohlcv(cfg.symbol, limit=cfg.lookback_hours)
        if df is None or len(df) < 50 or not self._avg_series:
            return
        last = df.iloc[-1]
        ts_ms = int(last["timestamp"])
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        price = float(last["close"])

        if self._pos is not None:
            self._mtm(price)
            if cfg.model_funding:
                self._accrue_funding(ts_ms, price)
        else:
            self._advance_settle_idx(ts_ms)

        equity = self._equity(price)
        gate_ok = self._gate(ts_ms)

        if self._pos is None and gate_ok:
            self._enter(ts, ts_ms, price, equity)
        elif self._pos is not None and not gate_ok:
            self._exit(ts, price, "funding_gate_closed")

    # ------------------------------------------------------------------
    # Gate de regimen (funding promedio trailing, anti-lookahead)
    # ------------------------------------------------------------------

    def _gate(self, ts_ms: int) -> bool:
        idx = self._avg_idx
        n = len(self._avg_series)
        while idx + 1 < n and self._avg_series[idx + 1][0] <= ts_ms:
            idx += 1
        self._avg_idx = idx
        if idx < 0:
            return False
        return gate_is_open(self._avg_series[idx][1], self._cfg.funding_min_avg)

    # ------------------------------------------------------------------
    # Mark-to-market + funding del short sintetico (patron prop_swing)
    # ------------------------------------------------------------------

    def _mtm(self, price: float) -> None:
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
        """rate>0 => los longs pagan, el short sintetico cobra."""
        pos = self._pos
        while (self._settle_idx < len(self._settlements)
               and self._settlements[self._settle_idx][0] <= ts_ms):
            s_ts, rate = self._settlements[self._settle_idx]
            self._settle_idx += 1
            if s_ts <= pos["entry_ms"]:
                continue
            cost = float(pos["qty"]) * price * rate * -1.0
            if cost:
                self._client.adjust_balance("USDT", Decimal(str(round(-cost, 8))))
                pos["funding_paid"] += cost

    # ------------------------------------------------------------------
    # Entrada: pata spot (real) + pata short sintetica (misma qty)
    # ------------------------------------------------------------------

    def _enter(self, ts: datetime, ts_ms: int, price: float, equity: float) -> None:
        cfg = self._cfg
        notional = equity * cfg.notional_pct
        qty = notional / price
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

        r = self._client.place_order(cfg.symbol, "buy", "market", qty_d, strategy=self.name)
        if r.status != "filled" or not r.filled_price:
            return
        self.log_trade(r)
        spot_entry = float(r.filled_price)

        slip = float(getattr(self._client, "_slippage_bps", 0)) / 10000.0
        fee_rate = float(getattr(self._client, "_fee_rate", Decimal("0.001")))
        q = float(qty_d)
        short_fill = price * (1 - slip)
        fee_open = q * short_fill * fee_rate
        self._client.adjust_balance("USDT", Decimal(str(round(-fee_open, 8))))

        self._pos = {
            "qty": qty_d, "spot_entry": spot_entry, "entry": short_fill,
            "mark": short_fill, "fee_open_unit": (fee_open / q) if q else 0.0,
            "entry_ms": ts_ms, "funding_paid": 0.0,
        }
        self._journal_open(
            side="basis", ts=ts.isoformat(), price=spot_entry,
            invest=q * spot_entry, stop=0.0, qty=q, balance_before=equity,
            ls=0, ss=0, indicators={"short_entry": round(short_fill, 2)},
        )

    # ------------------------------------------------------------------
    # Salida: cierra la pata short sintetica + vende la pata spot (real)
    # ------------------------------------------------------------------

    def _exit(self, ts: datetime, price: float, reason: str) -> None:
        pos = self._pos
        if pos is None:
            return
        slip = float(getattr(self._client, "_slippage_bps", 0)) / 10000.0
        fee_rate = float(getattr(self._client, "_fee_rate", Decimal("0.001")))
        q = float(pos["qty"])

        cover_fill = price * (1 + slip)
        fee_close_short = q * cover_fill * fee_rate
        delta = (pos["mark"] - cover_fill) * q - fee_close_short
        self._client.adjust_balance("USDT", Decimal(str(round(delta, 8))))
        short_pnl = (pos["entry"] - cover_fill) * q - fee_close_short - pos["fee_open_unit"] * q

        r = self._client.place_order(self._cfg.symbol, "sell", "market",
                                     pos["qty"], strategy=self.name)
        if r.status != "filled":
            logger.warning("[{}] cierre spot {} NO ejecutado", self.name, reason)
            return
        spot_fill = float(r.filled_price or price)
        spot_pnl = (spot_fill - pos["spot_entry"]) * q - float(r.fee)
        self.log_trade(r, pnl=Decimal(str(round(spot_pnl, 8))))

        net = spot_pnl + short_pnl - pos["funding_paid"]
        self.realized.append((ts, Decimal(str(round(net, 8)))))
        self._journal_close(
            ts=ts.isoformat(), price=spot_fill, pnl=net, reason=reason,
            holding_hours=(ts.timestamp() * 1000 - pos["entry_ms"]) / 3_600_000,
            balance_after=self._equity(spot_fill), ls=0, ss=0,
            indicators={"funding_net": round(-pos["funding_paid"], 2)},
        )
        self._pos = None

    # ------------------------------------------------------------------

    def _equity(self, price: float) -> float:
        balance = self._client.get_balance()
        usdt = float(balance.get("USDT", Decimal("0")))
        base = float(balance.get(self._cfg.symbol.split("-")[0], Decimal("0")))
        return usdt + base * price
