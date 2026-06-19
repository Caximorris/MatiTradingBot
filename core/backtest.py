"""
Motor de backtesting — simula estrategias sobre datos históricos de OKX.

Diseño clave: BacktestClient imita la interfaz de OKXClient al 100%,
por lo que las estrategias se ejecutan sin ningún cambio de código.
"""
from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable

from loguru import logger

from core.exchange import OrderResult
from data.market_data import OHLCVBar

_PAPER_FEE_RATE = Decimal("0.001")  # 0.1% taker fee OKX


# ---------------------------------------------------------------------------
# Resultado de cada trade simulado
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    timestamp: datetime
    symbol: str
    side: str
    price: Decimal
    quantity: Decimal
    fee: Decimal
    pnl: Decimal | None = None
    strategy: str = ""


# ---------------------------------------------------------------------------
# Métricas finales
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    bars_tested: int
    initial_balance: Decimal
    final_balance: Decimal
    total_pnl: Decimal
    total_pnl_pct: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    profit_factor: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal
    buy_hold_pnl_pct: Decimal
    trades: list[BacktestTrade] = field(default_factory=list)

    def summary_rows(self) -> list[tuple[str, str]]:
        """Filas para la tabla de resultados rich."""
        c_pnl = "green" if self.total_pnl >= 0 else "red"
        c_bh  = "green" if self.buy_hold_pnl_pct >= 0 else "red"
        return [
            ("Período", f"{self.start_date.strftime('%d/%m/%Y')} → {self.end_date.strftime('%d/%m/%Y')}"),
            ("Velas analizadas", str(self.bars_tested)),
            ("Balance inicial", f"{self.initial_balance:,.2f} USDT"),
            ("Balance final", f"{self.final_balance:,.2f} USDT"),
            ("P&L total", f"[{c_pnl}]{self.total_pnl:+,.2f} USDT ({self.total_pnl_pct:+.2f}%)[/{c_pnl}]"),
            ("Buy & Hold", f"[{c_bh}]{self.buy_hold_pnl_pct:+.2f}%[/{c_bh}]"),
            ("Total trades", str(self.total_trades)),
            ("Ganadores / Perdedores", f"{self.winning_trades} / {self.losing_trades}"),
            ("Win rate", f"{self.win_rate:.1f}%"),
            ("Profit Factor", f"{self.profit_factor:.2f}"),
            ("Max Drawdown", f"[red]-{self.max_drawdown_pct:.2f}%[/red]"),
            ("Sharpe Ratio (est.)", f"{self.sharpe_ratio:.2f}"),
        ]


# ---------------------------------------------------------------------------
# BacktestClient — imita OKXClient con datos históricos
# ---------------------------------------------------------------------------

class BacktestClient:
    """
    Reemplaza OKXClient durante el backtest.
    Las estrategias llaman exactamente los mismos métodos — sin cambios.
    """

    is_paper: bool = True

    def __init__(
        self,
        symbol: str,
        bars: list[OHLCVBar],
        initial_balance: Decimal = Decimal("10000"),
    ) -> None:
        self._symbol = symbol
        self._bars = bars
        self._idx = 0
        self._balance: dict[str, Decimal] = {"USDT": initial_balance}
        self._paper_orders: dict[str, dict] = {}
        self._executed: list[BacktestTrade] = []
        self.initial_balance = initial_balance

    # ---- Control de barra actual ----

    def advance(self, idx: int) -> list[OrderResult]:
        """
        Mueve el cursor a la barra idx.
        Chequea qué órdenes límite se habrían ejecutado con el high/low de esa barra.
        Retorna los OrderResult de las órdenes llenadas.
        """
        self._idx = idx
        return self._check_limit_fills()

    @property
    def current_bar(self) -> OHLCVBar:
        return self._bars[self._idx]

    # ---- Interfaz pública (= OKXClient) ----

    def get_ticker(self, symbol: str) -> Decimal:
        return self.current_bar.close

    def get_ohlcv(self, symbol: str, bar: str = "1H", limit: int = 100) -> list[OHLCVBar]:
        start = max(0, self._idx - limit + 1)
        return self._bars[start : self._idx + 1]

    def get_balance(self) -> dict[str, Decimal]:
        return dict(self._balance)

    def get_open_orders(self, symbol: str | None = None) -> list:
        orders = list(self._paper_orders.values())
        if symbol:
            orders = [o for o in orders if o["symbol"] == symbol]
        return orders

    def get_positions(self) -> list:
        return []

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: Decimal,
        price: Decimal | None = None,
        strategy: str = "",
        **_kwargs,
    ) -> OrderResult:
        order_id = f"BT-{uuid.uuid4().hex[:8]}"

        if order_type == "market":
            return self._fill_market(order_id, symbol, side, size, strategy)

        # Limit order → queda pendiente
        self._paper_orders[order_id] = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price or self.current_bar.close,
            "strategy": strategy,
        }
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            order_type=order_type, size=size,
            limit_price=price, filled_price=None, filled_qty=Decimal("0"),
            fee=Decimal("0"), fee_currency="USDT",
            status="open", is_paper=True,
            strategy=strategy, timestamp=self.current_bar_ts(),
        )

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        order = self._paper_orders.pop(order_id, None)
        if order and order["side"] == "buy":
            cost = order["size"] * order["price"]
            self._balance["USDT"] = self._balance.get("USDT", Decimal("0")) + cost
        return True

    def fill_paper_limit_orders(
        self, symbol: str, current_price: Decimal
    ) -> list[OrderResult]:
        """Llamado por estrategias para comprobar fills. En backtest, ya se llama internamente en advance()."""
        return []

    # ---- Helpers internos ----

    def current_bar_ts(self) -> datetime:
        return datetime.fromtimestamp(self.current_bar.timestamp / 1000, tz=timezone.utc)

    def _fill_market(
        self, order_id: str, symbol: str, side: str, size: Decimal, strategy: str
    ) -> OrderResult:
        price = self.current_bar.close
        fee = (size * price * _PAPER_FEE_RATE).quantize(Decimal("0.00000001"))
        base = symbol.split("-")[0]
        ts = self.current_bar_ts()

        if side == "buy":
            cost = size * price + fee
            if self._balance.get("USDT", Decimal("0")) < cost:
                return self._rejected(order_id, symbol, side, size, strategy, ts)
            self._balance["USDT"] = self._balance.get("USDT", Decimal("0")) - cost
            self._balance[base] = self._balance.get(base, Decimal("0")) + size
        else:
            if self._balance.get(base, Decimal("0")) < size:
                return self._rejected(order_id, symbol, side, size, strategy, ts)
            proceeds = size * price - fee
            self._balance[base] = self._balance.get(base, Decimal("0")) - size
            self._balance["USDT"] = self._balance.get("USDT", Decimal("0")) + proceeds

        self._executed.append(BacktestTrade(
            timestamp=ts, symbol=symbol, side=side, price=price,
            quantity=size, fee=fee, strategy=strategy,
        ))
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            order_type="market", size=size,
            limit_price=None, filled_price=price, filled_qty=size,
            fee=fee, fee_currency="USDT",
            status="filled", is_paper=True,
            strategy=strategy, timestamp=ts,
        )

    def _check_limit_fills(self) -> list[OrderResult]:
        bar = self.current_bar
        filled_results: list[OrderResult] = []

        for order_id, order in list(self._paper_orders.items()):
            lp = order["price"]
            side = order["side"]
            fills = (side == "buy" and bar.low <= lp) or (side == "sell" and bar.high >= lp)
            if not fills:
                continue

            size = order["size"]
            fee = (size * lp * _PAPER_FEE_RATE).quantize(Decimal("0.00000001"))
            base = order["symbol"].split("-")[0]
            ts = self.current_bar_ts()

            if side == "buy":
                cost = size * lp + fee
                if self._balance.get("USDT", Decimal("0")) < cost:
                    continue
                self._balance["USDT"] -= cost
                self._balance[base] = self._balance.get(base, Decimal("0")) + size
            else:
                if self._balance.get(base, Decimal("0")) < size:
                    continue
                proceeds = size * lp - fee
                self._balance[base] -= size
                self._balance["USDT"] = self._balance.get("USDT", Decimal("0")) + proceeds

            self._executed.append(BacktestTrade(
                timestamp=ts, symbol=order["symbol"], side=side,
                price=lp, quantity=size, fee=fee, strategy=order["strategy"],
            ))
            result = OrderResult(
                order_id=order_id, symbol=order["symbol"], side=side,
                order_type="limit", size=size,
                limit_price=lp, filled_price=lp, filled_qty=size,
                fee=fee, fee_currency="USDT",
                status="filled", is_paper=True,
                strategy=order["strategy"], timestamp=ts,
            )
            filled_results.append(result)
            del self._paper_orders[order_id]

        return filled_results

    @staticmethod
    def _rejected(order_id, symbol, side, size, strategy, ts) -> OrderResult:
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            order_type="market", size=size,
            limit_price=None, filled_price=None, filled_qty=Decimal("0"),
            fee=Decimal("0"), fee_currency="USDT",
            status="rejected", is_paper=True,
            strategy=strategy, timestamp=ts,
            error="Saldo insuficiente",
        )


# ---------------------------------------------------------------------------
# BacktestEngine — orquesta la simulación
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Ejecuta una estrategia sobre datos históricos barra a barra.
    Usa un SQLite en memoria para que la estrategia pueda leer/escribir BotState.
    """

    def __init__(
        self,
        bt_client: BacktestClient,
        strategy_factory: Callable,
        warmup_bars: int = 20,
    ) -> None:
        self._client = bt_client
        self._factory = strategy_factory
        self._warmup = warmup_bars

    def run(self) -> BacktestResult:
        bars = self._client._bars
        symbol = self._client._symbol
        n = len(bars)

        if n < self._warmup + 1:
            raise ValueError(f"Datos insuficientes: se necesitan al menos {self._warmup + 1} velas.")

        # DB en memoria para el backtest
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from core.database import Base

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()

        # Balance para buy&hold: precio primera y última barra después del warmup
        start_price = bars[self._warmup].close
        end_price = bars[-1].close
        buy_hold_pct = ((end_price - start_price) / start_price * 100).quantize(Decimal("0.01"))

        # Historial de valor del portfolio (para drawdown y sharpe)
        equity_curve: list[Decimal] = []

        strategy = self._factory(self._client, session)

        for i in range(self._warmup, n):
            # Avanza la barra (chequea fills de límite antes del tick)
            self._client.advance(i)

            try:
                strategy.run()
            except Exception as exc:
                logger.warning("Backtest tick {}/{}: {}", i, n, exc)

            # Valorar el portfolio a precio de cierre
            balance = self._client.get_balance()
            usdt = balance.get("USDT", Decimal("0"))
            base_token = symbol.split("-")[0]
            base_qty = balance.get(base_token, Decimal("0"))
            total = usdt + base_qty * self._client.current_bar.close
            equity_curve.append(total)

        session.close()

        final_balance = equity_curve[-1] if equity_curve else self._client.initial_balance
        total_pnl = final_balance - self._client.initial_balance
        total_pnl_pct = (total_pnl / self._client.initial_balance * 100).quantize(Decimal("0.01"))

        trades = self._client._executed
        pnl_trades = self._compute_trade_pnl(trades)

        wins = [t for t in pnl_trades if t.pnl and t.pnl > 0]
        losses = [t for t in pnl_trades if t.pnl and t.pnl < 0]
        gross_profit = sum((t.pnl for t in wins), Decimal("0"))
        gross_loss = abs(sum((t.pnl for t in losses), Decimal("0")))

        win_rate = (
            Decimal(str(len(wins) / len(pnl_trades) * 100)).quantize(Decimal("0.1"))
            if pnl_trades else Decimal("0")
        )
        profit_factor = (
            (gross_profit / gross_loss).quantize(Decimal("0.01"))
            if gross_loss > 0 else Decimal("0")
        )

        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy.name,
            timeframe="histórico",
            start_date=datetime.fromtimestamp(bars[self._warmup].timestamp / 1000, tz=timezone.utc),
            end_date=datetime.fromtimestamp(bars[-1].timestamp / 1000, tz=timezone.utc),
            bars_tested=n - self._warmup,
            initial_balance=self._client.initial_balance,
            final_balance=final_balance,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            total_trades=len(pnl_trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown_pct=self._max_drawdown(equity_curve),
            sharpe_ratio=self._sharpe(equity_curve),
            buy_hold_pnl_pct=buy_hold_pct,
            trades=pnl_trades,
        )

    # ---- Métricas ----

    @staticmethod
    def _compute_trade_pnl(trades: list[BacktestTrade]) -> list[BacktestTrade]:
        """
        Asocia cada venta con su compra más reciente (LIFO simplificado para backtest).
        Calcula el PnL neto de cada par cerrado.
        """
        open_lots: dict[str, list[BacktestTrade]] = {}
        closed: list[BacktestTrade] = []

        for t in trades:
            if t.side == "buy":
                open_lots.setdefault(t.symbol, []).append(t)
            elif t.side == "sell":
                lots = open_lots.get(t.symbol, [])
                if lots:
                    buy = lots.pop(0)
                    pnl = (t.price - buy.price) * t.quantity - t.fee - buy.fee
                    closed_trade = BacktestTrade(
                        timestamp=t.timestamp, symbol=t.symbol, side="sell",
                        price=t.price, quantity=t.quantity, fee=t.fee,
                        pnl=pnl.quantize(Decimal("0.01")), strategy=t.strategy,
                    )
                    closed.append(closed_trade)

        return closed

    @staticmethod
    def _max_drawdown(equity: list[Decimal]) -> Decimal:
        if len(equity) < 2:
            return Decimal("0")
        peak = equity[0]
        max_dd = Decimal("0")
        for v in equity:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else Decimal("0")
            if dd > max_dd:
                max_dd = dd
        return max_dd.quantize(Decimal("0.01"))

    @staticmethod
    def _sharpe(equity: list[Decimal], risk_free_annual: float = 0.04) -> Decimal:
        if len(equity) < 2:
            return Decimal("0")
        returns = [
            float(equity[i] - equity[i - 1]) / float(equity[i - 1])
            for i in range(1, len(equity))
        ]
        if not returns:
            return Decimal("0")
        mean_r = statistics.mean(returns)
        std_r = statistics.stdev(returns) if len(returns) > 1 else 0
        if std_r == 0:
            return Decimal("0")
        # Anualizamos asumiendo que cada elemento = 1 día
        rf_daily = risk_free_annual / 252
        sharpe = (mean_r - rf_daily) / std_r * math.sqrt(252)
        return Decimal(str(round(sharpe, 2)))


# ---------------------------------------------------------------------------
# Descarga de datos históricos desde OKX (endpoint público)
# ---------------------------------------------------------------------------

def fetch_historical_bars(
    symbol: str,
    bar: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[OHLCVBar]:
    """
    Descarga datos OHLCV históricos desde la API pública de OKX.
    No requiere autenticación. Pagina automáticamente si el rango es grande.
    """
    try:
        from okx.MarketData import MarketAPI
    except ImportError:
        logger.error("python-okx no instalado. Ejecuta: pip install python-okx")
        return []

    api = MarketAPI(flag="0")  # 0 = mainnet, sin auth
    bars: list[OHLCVBar] = []
    before_ts = str(int(to_dt.timestamp() * 1000))
    after_ts  = str(int(from_dt.timestamp() * 1000))

    logger.info("Descargando {}/{} desde {} hasta {}…", symbol, bar, from_dt.date(), to_dt.date())

    while True:
        try:
            resp = api.get_candlesticks(
                instId=symbol,
                bar=bar,
                before=after_ts,
                after=before_ts,
                limit="300",
            )
        except Exception as exc:
            logger.error("Error descargando datos: {}", exc)
            break

        if resp.get("code") != "0" or not resp.get("data"):
            break

        chunk = resp["data"]
        for row in chunk:
            ts, o, h, l, c, vol = row[0], row[1], row[2], row[3], row[4], row[5]
            bars.append(OHLCVBar(
                timestamp=int(ts),
                open=Decimal(o), high=Decimal(h),
                low=Decimal(l), close=Decimal(c),
                volume=Decimal(vol),
            ))

        if len(chunk) < 300:
            break

        # La siguiente página termina donde empezó esta
        before_ts = chunk[-1][0]
        if int(before_ts) <= int(after_ts):
            break

    # OKX devuelve las barras de más reciente a más antigua — invertir
    bars.sort(key=lambda b: b.timestamp)
    logger.info("Descargadas {} velas", len(bars))
    return bars
