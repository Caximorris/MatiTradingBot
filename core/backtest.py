"""
Motor de backtesting — simula estrategias sobre datos históricos de OKX.

Diseño clave: BacktestClient imita la interfaz de OKXClient al 100%,
por lo que las estrategias se ejecutan sin ningún cambio de código.
"""
from __future__ import annotations

import math
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from loguru import logger

from core.exchange import OrderResult
from data import ohlcv_cache
from data.market_data import OHLCVBar

# Reintentos de paginacion OKX: evita truncar el dataset en silencio ante un
# transitorio (una pagina perdida = 300 velas = backtest no reproducible).
_OKX_MAX_RETRIES = 4
_OKX_BACKOFF_S   = 1.5

_PAPER_FEE_RATE = Decimal("0.001")  # 0.1% taker fee OKX por defecto

# Modos de coste para BacktestClient
COST_MODE_IDEAL       = "ideal"        # fee=0.001, slippage=0
COST_MODE_REALISTIC   = "realistic"    # fee=0.001, slippage=5bps (0.05%)
COST_MODE_CONSERVATIVE = "conservative" # fee=0.001, slippage=15bps (0.15%)
# N1 (HYROTRADER_PLAN seccion 13): modelo Bybit perps lineales, taker VIP0 = 5.5bps.
# Slippage 2bps = supuesto base para ordenes $3-6k en BTCUSDT (book profundo, spread ~1bp);
# bybit_cons = 10bps hasta que N0 (testnet) lo mida. El funding NO va aqui: lo devenga la
# estrategia por settlement (adjust_balance), igual que el MTM de los shorts sinteticos.
COST_MODE_BYBIT       = "bybit"        # fee=0.00055, slippage=2bps
COST_MODE_BYBIT_CONS  = "bybit_cons"   # fee=0.00055, slippage=10bps


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
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    # Métricas adicionales (con defaults para compatibilidad)
    cagr: Decimal = Decimal("0")
    calmar: Decimal = Decimal("0")          # CAGR / MaxDD — trade-off riesgo/retorno en un numero
    max_dd_duration_days: int = 0           # duracion del peor drawdown, solo peak->trough
    underwater_days: int = 0                # dias maximos bajo el agua reales (peak->recovery)
    sortino: Decimal = Decimal("0")
    expectancy: Decimal = Decimal("0")
    median_trade: Decimal = Decimal("0")   # mediana del P&L por trade — robusta a monstruos/outliers
    avg_win: Decimal = Decimal("0")
    avg_loss: Decimal = Decimal("0")
    max_consec_losses: int = 0
    time_in_market_pct: Decimal = Decimal("0")
    cost_mode: str = COST_MODE_IDEAL

    def summary_rows(self) -> list[tuple[str, str]]:
        """Filas para la tabla de resultados rich."""
        c_pnl = "green" if self.total_pnl >= 0 else "red"
        c_bh  = "green" if self.buy_hold_pnl_pct >= 0 else "red"
        c_cagr = "green" if self.cagr >= 0 else "red"
        return [
            ("Periodo", f"{self.start_date.strftime('%d/%m/%Y')} -> {self.end_date.strftime('%d/%m/%Y')}"),
            ("Velas analizadas", str(self.bars_tested)),
            ("Balance inicial", f"{self.initial_balance:,.2f} USDT"),
            ("Balance final", f"{self.final_balance:,.2f} USDT"),
            ("P&L total", f"[{c_pnl}]{self.total_pnl:+,.2f} USDT ({self.total_pnl_pct:+.2f}%)[/{c_pnl}]"),
            ("CAGR", f"[{c_cagr}]{self.cagr:+.1f}%/ano[/{c_cagr}]"),
            ("Buy & Hold", f"[{c_bh}]{self.buy_hold_pnl_pct:+.2f}%[/{c_bh}]"),
            ("Total trades", str(self.total_trades)),
            ("Ganadores / Perdedores", f"{self.winning_trades} / {self.losing_trades}"),
            ("Win rate", f"{self.win_rate:.1f}%"),
            ("Avg Win / Avg Loss", f"+{self.avg_win:.0f} / -{self.avg_loss:.0f} USDT"),
            ("Expectancy/trade", f"{self.expectancy:+.2f} USDT"),
            ("Median trade", f"{self.median_trade:+.2f} USDT"),
            ("Profit Factor", f"{self.profit_factor:.2f}"),
            ("Max Drawdown", f"[red]-{self.max_drawdown_pct:.2f}%[/red]"),
            ("Max DD duracion (peak->trough)", f"{self.max_dd_duration_days} dias"),
            ("Underwater max (peak->recovery)", f"{self.underwater_days} dias"),
            ("Max racha perdedoras", str(self.max_consec_losses)),
            ("Calmar (CAGR/MaxDD)", f"{self.calmar:.2f}"),
            ("Sharpe Ratio", f"{self.sharpe_ratio:.2f}"),
            ("Sortino Ratio", f"{self.sortino:.2f}"),
            ("Tiempo en mercado", f"{self.time_in_market_pct:.1f}%"),
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
        fee_rate: Decimal = Decimal("0.001"),
        slippage_bps: float = 0.0,
        cost_mode: str = COST_MODE_IDEAL,
        fill_next_open: bool = False,
    ) -> None:
        self._symbol = symbol
        self._bars = bars
        self._idx = 0
        self._balance: dict[str, Decimal] = {"USDT": initial_balance}
        self._paper_orders: dict[str, dict] = {}
        self._reserved_usdt: dict[str, Decimal] = {}
        self._reserved_base: dict[str, Decimal] = {}
        self._pending_fills: list[OrderResult] = []
        self._executed: list[BacktestTrade] = []
        self._ohlcv_df: Any | None = None
        self.initial_balance = initial_balance

        # Costes configurables
        if cost_mode == COST_MODE_REALISTIC:
            self._fee_rate = Decimal("0.001")
            self._slippage_bps = Decimal("5")     # 0.05%
        elif cost_mode == COST_MODE_CONSERVATIVE:
            self._fee_rate = Decimal("0.001")
            self._slippage_bps = Decimal("15")    # 0.15%
        elif cost_mode == COST_MODE_BYBIT:
            self._fee_rate = Decimal("0.00055")
            self._slippage_bps = Decimal("2")
        elif cost_mode == COST_MODE_BYBIT_CONS:
            self._fee_rate = Decimal("0.00055")
            self._slippage_bps = Decimal("10")
        else:
            self._fee_rate = fee_rate
            self._slippage_bps = Decimal(str(slippage_bps))
        self.cost_mode = cost_mode
        self.fill_next_open = fill_next_open

    # ---- Control de barra actual ----

    def advance(self, idx: int) -> list[OrderResult]:
        """
        Mueve el cursor a la barra idx.
        Chequea qué órdenes límite se habrían ejecutado con el high/low de esa barra.
        Los fills se almacenan en _pending_fills para que la estrategia los recoja
        via fill_paper_limit_orders() en el mismo tick.
        """
        self._idx = idx
        self._pending_fills = self._check_limit_fills()
        return self._pending_fills

    @property
    def current_bar(self) -> OHLCVBar:
        return self._bars[self._idx]

    # ---- Interfaz pública (= OKXClient) ----

    def get_ticker(self, symbol: str) -> Decimal:
        return self.current_bar.close

    def get_ohlcv(self, symbol: str, timeframe: str = "1H", limit: int = 100, bar: str = "1H"):
        """Devuelve un DataFrame OHLCV igual que OKXClient.get_ohlcv para compatibilidad."""
        try:
            import pandas as pd
        except ImportError:
            return None
        if self._ohlcv_df is None:
            self._ohlcv_df = pd.DataFrame([
                {
                    "timestamp": b.timestamp,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
                for b in self._bars
            ])
        start = max(0, self._idx - limit + 1)
        return self._ohlcv_df.iloc[start : self._idx + 1]

    def get_balance(self) -> dict[str, Decimal]:
        """Return funds available for new orders, matching the execution clients."""
        return dict(self._balance)

    def _get_total_balance(self) -> dict[str, Decimal]:
        """Return available plus reserved funds for mark-to-market accounting."""
        result = self.get_balance()
        reserved_usdt = sum(self._reserved_usdt.values(), Decimal("0"))
        if reserved_usdt:
            result["USDT"] = result.get("USDT", Decimal("0")) + reserved_usdt
        for order_id, qty in self._reserved_base.items():
            order = self._paper_orders.get(order_id, {})
            base = order.get("symbol", "BTC-USDT").split("-")[0]
            result[base] = result.get(base, Decimal("0")) + qty
        return result

    def adjust_balance(self, currency: str, delta: Decimal) -> None:
        """Ajusta directamente el saldo — usado para liquidar P&L de cortos sintéticos."""
        self._balance[currency] = self._balance.get(currency, Decimal("0")) + delta

    def get_open_orders(self, symbol: str | None = None) -> list:
        orders = list(self._paper_orders.values())
        if symbol:
            orders = [o for o in orders if o["symbol"] == symbol]
        return orders

    def get_positions(self) -> list:
        return []

    def get_funding_rate(self, symbol: str) -> float:
        """Devuelve el funding rate historico del dia actual de la simulacion."""
        from strategies.funding_context import get_funding_rate_at
        return get_funding_rate_at(self.current_time(), symbol)

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

        lp = price or self.current_bar.close
        base = symbol.split("-")[0]

        # Reservar saldo para órdenes límite (igual que hace OKXClient paper)
        if side == "buy":
            estimated_fee = (size * lp * self._fee_rate).quantize(Decimal("0.00000001"))
            cost = size * lp + estimated_fee
            available = self._balance.get("USDT", Decimal("0"))
            if available < cost:
                return self._rejected(
                    order_id, symbol, side, size, strategy, self.current_bar_ts(),
                    order_type=order_type, limit_price=lp,
                )
            self._balance["USDT"] = available - cost
            self._reserved_usdt[order_id] = cost
        else:  # sell
            estimated_fee = (size * lp * self._fee_rate).quantize(Decimal("0.00000001"))
            available_base = self._balance.get(base, Decimal("0"))
            if available_base < size:
                return self._rejected(
                    order_id, symbol, side, size, strategy, self.current_bar_ts(),
                    order_type=order_type, limit_price=lp,
                )
            self._balance[base] = available_base - size
            self._reserved_base[order_id] = size

        self._paper_orders[order_id] = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": lp,
            "strategy": strategy,
        }
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            order_type=order_type, size=size,
            limit_price=lp, filled_price=None, filled_qty=Decimal("0"),
            fee=estimated_fee, fee_currency="USDT",
            status="open", is_paper=True,
            strategy=strategy, timestamp=self.current_bar_ts(),
        )

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        order = self._paper_orders.pop(order_id, None)
        if order is None:
            return False
        base = order["symbol"].split("-")[0]
        if order["side"] == "buy":
            reserved = self._reserved_usdt.pop(order_id, Decimal("0"))
            self._balance["USDT"] = self._balance.get("USDT", Decimal("0")) + reserved
        else:
            reserved = self._reserved_base.pop(order_id, Decimal("0"))
            self._balance[base] = self._balance.get(base, Decimal("0")) + reserved
        return True

    def fill_paper_limit_orders(
        self, symbol: str | None = None, current_price: Decimal | None = None
    ) -> list[OrderResult]:
        """
        Devuelve los fills generados en el último advance() para que la estrategia
        pueda procesar contra-órdenes (e.g. el GridBot coloca sell tras cada buy fill).
        Se vacía tras la primera lectura del mismo tick.
        """
        fills = self._pending_fills
        self._pending_fills = []
        if symbol:
            fills = [f for f in fills if f.symbol == symbol]
        return fills

    # ---- Helpers internos ----

    def current_bar_ts(self) -> datetime:
        return datetime.fromtimestamp(self.current_bar.timestamp / 1000, tz=timezone.utc)

    def current_time(self) -> datetime:
        return self.current_bar_ts()

    def _fill_market(
        self, order_id: str, symbol: str, side: str, size: Decimal, strategy: str
    ) -> OrderResult:
        fill_bar = self.current_bar
        if self.fill_next_open and self._idx + 1 < len(self._bars):
            fill_bar = self._bars[self._idx + 1]
            raw_price = fill_bar.open
        else:
            raw_price = self.current_bar.close
        # Aplica slippage: buy paga más, sell recibe menos
        if self._slippage_bps > 0:
            slip = self._slippage_bps / Decimal("10000")
            price = raw_price * (1 + slip) if side == "buy" else raw_price * (1 - slip)
            price = price.quantize(Decimal("0.01"))
        else:
            price = raw_price
        fee = (size * price * self._fee_rate).quantize(Decimal("0.00000001"))
        base = symbol.split("-")[0]
        ts = datetime.fromtimestamp(fill_bar.timestamp / 1000, tz=timezone.utc)

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
            triggers = (side == "buy" and bar.low <= lp) or (side == "sell" and bar.high >= lp)
            if not triggers:
                continue

            size = order["size"]
            fee = (size * lp * self._fee_rate).quantize(Decimal("0.00000001"))
            base = order["symbol"].split("-")[0]
            ts = self.current_bar_ts()

            # El saldo ya fue reservado en place_order — solo aplicar el fill
            if side == "buy":
                # Teníamos reservado: size*lp USDT. Ahora recibimos size BTC y pagamos fee
                reserved = self._reserved_usdt.pop(order_id, size * lp)
                # Devolvemos el exceso (diferencia entre reserva y coste real + fee)
                net_cost = size * lp + fee
                surplus = reserved - net_cost
                self._balance["USDT"] = self._balance.get("USDT", Decimal("0")) + surplus
                self._balance[base] = self._balance.get(base, Decimal("0")) + size
            else:
                # Teníamos reservado: size base. Recibimos size*lp - fee USDT
                self._reserved_base.pop(order_id, None)
                proceeds = size * lp - fee
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
    def _rejected(
        order_id, symbol, side, size, strategy, ts,
        order_type: str = "market", limit_price: Decimal | None = None,
    ) -> OrderResult:
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            order_type=order_type, size=size,
            limit_price=limit_price, filled_price=None, filled_qty=Decimal("0"),
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
        timeframe: str = "1H",
        trade_pnl_method: str = "acb",
    ) -> None:
        if trade_pnl_method not in {"acb", "legacy_fifo"}:
            raise ValueError(f"trade_pnl_method invalido: {trade_pnl_method}")
        self._client = bt_client
        self._factory = strategy_factory
        self._warmup = warmup_bars
        self._timeframe = timeframe
        self._trade_pnl_method = trade_pnl_method
        self.last_strategy: Any = None   # expuesto tras run() para acceder al journal

    def run(
        self,
        on_tick: Callable[[int, int], None] | None = None,
        tick_interval: int = 500,
    ) -> BacktestResult:
        """
        Ejecuta el backtest barra a barra.

        on_tick(done, total): callback opcional llamado cada `tick_interval` barras
                              para actualizar una barra de progreso externa.
        """
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

        # Balance para buy&hold: precio primera y última barra después del warmup.
        # Con coste de entrada (fee + slippage del modo activo) para comparar en igualdad
        # de condiciones — la estrategia paga sus fills, el benchmark paga su unica compra.
        start_price = bars[self._warmup].close
        end_price = bars[-1].close
        _slip = self._client._slippage_bps / Decimal("10000")
        _entry_cost = (1 + _slip) * (1 + self._client._fee_rate)
        buy_hold_pct = (
            (end_price / (start_price * _entry_cost) - 1) * 100
        ).quantize(Decimal("0.01"))

        # Historial de valor del portfolio con timestamps (para drawdown, sharpe y análisis externo)
        equity_curve: list[tuple[datetime, Decimal]] = []

        logger.info(
            "BACKTEST: get_funding_rate() usa funding_context historico; "
            "si no hay datos cargados para la fecha retorna 0.0 como fallback"
        )

        total_ticks = n - self._warmup
        base_token = symbol.split("-")[0]
        bars_in_market = 0

        try:
            strategy = self._factory(self._client, session)
            self.last_strategy = strategy   # expuesto para acceso al journal tras run()

            for i in range(self._warmup, n):
                self._client.advance(i)

                try:
                    strategy.run()
                except Exception:
                    logger.exception(
                        "Backtest abortado: strategy={} tick={}/{} timestamp_utc={}",
                        getattr(strategy, "name", type(strategy).__name__),
                        i,
                        n,
                        self._client.current_bar_ts().isoformat(),
                    )
                    raise

                balance = self._client._get_total_balance()
                usdt = balance.get("USDT", Decimal("0"))
                base_qty = balance.get(base_token, Decimal("0"))
                total = usdt + base_qty * self._client.current_bar.close
                equity_curve.append((self._client.current_bar_ts(), total))
                if base_qty > Decimal("0"):
                    bars_in_market += 1

                done = i - self._warmup + 1
                if on_tick and (done % tick_interval == 0 or done == total_ticks):
                    on_tick(done, total_ticks)
        finally:
            session.close()

        equity_values = [v for _, v in equity_curve]
        final_balance = equity_values[-1] if equity_values else self._client.initial_balance
        total_pnl = final_balance - self._client.initial_balance
        total_pnl_pct = (total_pnl / self._client.initial_balance * 100).quantize(Decimal("0.01"))

        trades = self._client._executed
        pnl_trades = (
            self._compute_trade_pnl_legacy_fifo(trades)
            if self._trade_pnl_method == "legacy_fifo"
            else self._compute_trade_pnl_acb(trades)
        )

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

        avg_win  = (gross_profit / Decimal(str(len(wins)))).quantize(Decimal("0.01")) if wins else Decimal("0")
        avg_loss = (gross_loss  / Decimal(str(len(losses)))).quantize(Decimal("0.01")) if losses else Decimal("0")

        wr_d   = Decimal(str(len(wins)))   / Decimal(str(len(pnl_trades))) if pnl_trades else Decimal("0")
        lr_d   = Decimal("1") - wr_d
        expectancy = (wr_d * avg_win - lr_d * avg_loss).quantize(Decimal("0.01"))

        # Mediana del P&L por trade: menos sensible a los pocos trades monstruo que la media/PF
        all_pnls = sorted(t.pnl for t in pnl_trades if t.pnl is not None)
        median_trade = (
            Decimal(str(statistics.median(all_pnls))).quantize(Decimal("0.01"))
            if all_pnls else Decimal("0")
        )

        max_consec = 0
        cur_consec  = 0
        for t in pnl_trades:
            if t.pnl and t.pnl < 0:
                cur_consec += 1
                max_consec = max(max_consec, cur_consec)
            else:
                cur_consec = 0

        time_in_mkt = (
            Decimal(str(bars_in_market / total_ticks * 100)).quantize(Decimal("0.1"))
            if total_ticks > 0 else Decimal("0")
        )

        bars_per_year = {
            "1H": 8760, "4H": 2190, "1D": 365, "15m": 35040, "5m": 105120,
        }.get(self._timeframe, 8760)

        start_dt = datetime.fromtimestamp(bars[self._warmup].timestamp / 1000, tz=timezone.utc)
        end_dt   = datetime.fromtimestamp(bars[-1].timestamp / 1000, tz=timezone.utc)

        _maxdd  = self._max_drawdown(equity_values)
        _cagr   = self._cagr(equity_values, start_dt, end_dt, self._client.initial_balance)
        _calmar = (_cagr / _maxdd).quantize(Decimal("0.01")) if _maxdd > 0 else Decimal("0")
        _dd_dur = self._max_dd_duration(equity_curve)
        _uw_days = self._max_underwater_days(equity_curve)

        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy.name,
            timeframe=self._timeframe,
            start_date=start_dt,
            end_date=end_dt,
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
            max_drawdown_pct=_maxdd,
            sharpe_ratio=self._sharpe(equity_values, bars_per_year=bars_per_year),
            buy_hold_pnl_pct=buy_hold_pct,
            trades=pnl_trades,
            equity_curve=equity_curve,
            cagr=_cagr,
            calmar=_calmar,
            max_dd_duration_days=_dd_dur,
            underwater_days=_uw_days,
            sortino=self._sortino(equity_values, bars_per_year=bars_per_year),
            expectancy=expectancy,
            median_trade=median_trade,
            avg_win=avg_win,
            avg_loss=avg_loss,
            max_consec_losses=max_consec,
            time_in_market_pct=time_in_mkt,
            cost_mode=self._client.cost_mode,
        )

    # ---- Métricas ----

    @staticmethod
    def _compute_trade_pnl(trades: list[BacktestTrade]) -> list[BacktestTrade]:
        """Alias de compatibilidad: desde 2026-07-02 el default es ACB."""
        return BacktestEngine._compute_trade_pnl_acb(trades)

    @staticmethod
    def _compute_trade_pnl_acb(trades: list[BacktestTrade]) -> list[BacktestTrade]:
        """
        P&L por trade con coste medio ponderado (average cost basis).

        Cada BUY actualiza el coste medio de la posicion (fee de compra incluida en el coste).
        Cada SELL cierra un trade: PnL = qty * (precio - coste_medio) - fee de venta.
        Correcto para rebalanceos parciales de tamanos arbitrarios (Swing Allocator);
        para estrategias todo-in/todo-out equivale al pairing clasico por lotes.
        Fix auditoria 2026-07-02 (hallazgo B3): el pairing anterior emparejaba ventas con
        compras SIN igualar cantidades — PF/WR/expectancy eran ruido para el allocator.
        El metodo antiguo queda en _compute_trade_pnl_legacy_fifo para comparaciones.
        """
        pos: dict[str, tuple[Decimal, Decimal]] = {}   # symbol -> (qty_abierta, coste_medio)
        closed: list[BacktestTrade] = []

        for t in trades:
            qty_open, avg_cost = pos.get(t.symbol, (Decimal("0"), Decimal("0")))
            if t.side == "buy":
                total_cost = qty_open * avg_cost + t.quantity * t.price + t.fee
                qty_open += t.quantity
                avg_cost = total_cost / qty_open if qty_open > 0 else Decimal("0")
                pos[t.symbol] = (qty_open, avg_cost)
            elif t.side == "sell":
                if qty_open <= 0:
                    continue   # venta sin posicion registrada (cortos sinteticos van aparte)
                qty = min(t.quantity, qty_open)
                sell_fee = t.fee
                if t.quantity > 0 and qty != t.quantity:
                    sell_fee = (t.fee * qty / t.quantity)
                pnl = qty * (t.price - avg_cost) - sell_fee
                pos[t.symbol] = (qty_open - qty, avg_cost)
                closed.append(BacktestTrade(
                    timestamp=t.timestamp, symbol=t.symbol, side="sell",
                    price=t.price, quantity=qty, fee=sell_fee,
                    pnl=pnl.quantize(Decimal("0.01")), strategy=t.strategy,
                ))

        return closed

    @staticmethod
    def _compute_trade_pnl_legacy_fifo(trades: list[BacktestTrade]) -> list[BacktestTrade]:
        """
        Pairing antiguo (pre-auditoria 2026-07-02): asocia cada venta con la compra abierta
        mas ANTIGUA (FIFO) sin igualar cantidades. Solo para reproducir metricas historicas.
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
    def _max_underwater_days(curve: list[tuple[datetime, Decimal]]) -> int:
        """
        Dias maximos bajo el agua: desde un peak hasta RECUPERARLO (o hasta el fin de datos
        si no se recupera). Complementa a _max_dd_duration, que solo mide peak->trough y
        infrarreporta ~4x el tiempo real bajo el agua (auditoria 2026-07-02, hallazgo C4).
        """
        if len(curve) < 2:
            return 0
        peak_v = curve[0][1]
        peak_dt = curve[0][0]
        worst = 0
        for dt, v in curve:
            if v >= peak_v:
                worst = max(worst, (dt - peak_dt).days)
                peak_v = v
                peak_dt = dt
        worst = max(worst, (curve[-1][0] - peak_dt).days)   # tramo final sin recuperar
        return worst

    @staticmethod
    def _max_dd_duration(curve: list[tuple[datetime, Decimal]]) -> int:
        """Dias bajo el agua del peor drawdown: de su peak a su trough (no la recuperacion)."""
        if len(curve) < 2:
            return 0
        peak_v = curve[0][1]
        peak_dt = curve[0][0]
        worst_dd = Decimal("0")
        worst_days = 0
        for dt, v in curve:
            if v > peak_v:
                peak_v = v
                peak_dt = dt
            dd = (peak_v - v) / peak_v if peak_v > 0 else Decimal("0")
            if dd > worst_dd:
                worst_dd = dd
                worst_days = (dt - peak_dt).days
        return worst_days

    @staticmethod
    def _sharpe(
        equity: list[Decimal],
        bars_per_year: int = 8760,
        risk_free_annual: float = 0.04,
    ) -> Decimal:
        if len(equity) < 2:
            return Decimal("0")
        returns = [
            float(equity[i] - equity[i - 1]) / float(equity[i - 1])
            for i in range(1, len(equity))
        ]
        if not returns:
            return Decimal("0")
        mean_r = statistics.mean(returns)
        std_r  = statistics.stdev(returns) if len(returns) > 1 else 0.0
        if std_r == 0:
            return Decimal("0")
        rf_bar = risk_free_annual / bars_per_year
        sharpe = (mean_r - rf_bar) / std_r * math.sqrt(bars_per_year)
        return Decimal(str(round(sharpe, 2)))

    @staticmethod
    def _sortino(
        equity: list[Decimal],
        bars_per_year: int = 8760,
        risk_free_annual: float = 0.04,
    ) -> Decimal:
        if len(equity) < 4:
            return Decimal("0")
        returns = [
            float(equity[i] - equity[i - 1]) / float(equity[i - 1])
            for i in range(1, len(equity))
        ]
        rf_bar  = risk_free_annual / bars_per_year
        excess  = [r - rf_bar for r in returns]
        neg     = [r for r in excess if r < 0]
        if len(neg) < 2:
            return Decimal("0")
        downside_std = statistics.stdev(neg)
        if downside_std == 0:
            return Decimal("0")
        mean_excess = statistics.mean(excess)
        sortino = mean_excess / downside_std * math.sqrt(bars_per_year)
        return Decimal(str(round(sortino, 2)))

    @staticmethod
    def _cagr(
        equity: list[Decimal],
        start_dt: datetime,
        end_dt: datetime,
        initial_balance: Decimal,
    ) -> Decimal:
        if not equity or initial_balance <= 0:
            return Decimal("0")
        total_days = (end_dt - start_dt).days
        if total_days < 30:
            return Decimal("0")
        years = total_days / 365.25
        ratio = float(equity[-1]) / float(initial_balance)
        if ratio <= 0:
            return Decimal("0")
        cagr = (ratio ** (1.0 / years) - 1.0) * 100
        return Decimal(str(round(cagr, 2)))


# ---------------------------------------------------------------------------
# Descarga de datos históricos desde OKX (endpoint público)
# ---------------------------------------------------------------------------

def _fetch_binance_bars(
    symbol: str,
    bar: str,
    from_dt: datetime,
    to_dt: datetime,
    on_page: Callable[[int], None] | None = None,
) -> list[OHLCVBar]:
    """
    Fallback: descarga OHLCV desde Binance API publica (sin auth).
    Usado cuando OKX no tiene datos para el par/periodo solicitado.
    symbol: "ETH-USDT" → "ETHUSDT"
    bar:    "1H" → "1h", "4H" → "4h", "1D" → "1d", "15m" → "15m"
    """
    import json as _json
    import urllib.request as _req

    _HEADERS = {"User-Agent": "MatiTradingBot/1.0"}

    def _okx_bar_to_binance(b: str) -> str:
        return b.replace("H", "h").replace("D", "d").replace("W", "w")

    binance_symbol = symbol.replace("-", "").upper()
    binance_bar    = _okx_bar_to_binance(bar)
    from_ms = int(from_dt.timestamp() * 1000)
    to_ms   = int(to_dt.timestamp()   * 1000)

    bars: list[OHLCVBar] = []
    end_ms = to_ms

    logger.info("Binance fallback: descargando {}/{} desde {} hasta {}",
                binance_symbol, binance_bar, from_dt.date(), to_dt.date())

    while end_ms > from_ms:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={binance_symbol}&interval={binance_bar}&limit=1000&endTime={end_ms}"
        )
        try:
            with _req.urlopen(_req.Request(url, headers=_HEADERS), timeout=20) as resp:
                chunk = _json.loads(resp.read())
        except Exception as exc:
            logger.error("Binance fallback error: {}", exc)
            break

        if not chunk:
            break

        for row in chunk:
            ts_ms = int(row[0])
            if ts_ms < from_ms:
                continue
            bars.append(OHLCVBar(
                timestamp=ts_ms,
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
            ))

        if on_page:
            on_page(len(bars))

        oldest_ms = int(chunk[0][0])
        if oldest_ms <= from_ms or len(chunk) < 1000:
            break
        end_ms = oldest_ms - 1

    bars.sort(key=lambda b: b.timestamp)
    logger.info("Binance fallback: {} velas descargadas", len(bars))
    return bars


def _fetch_bitstamp_bars(
    symbol: str,
    bar: str,
    from_dt: datetime,
    to_dt: datetime,
    on_page: Callable[[int], None] | None = None,
) -> list[OHLCVBar]:
    """
    Fallback: descarga OHLCV desde Bitstamp API publica (sin auth).
    BTC/USD desde enero 2012, ETH/USD desde agosto 2016.
    Trata USD como USDT — diferencia negligible historicamente.
    symbol: "BTC-USDT" → "btcusd", "ETH-USDT" → "ethusd"
    bar:    "1H" → step=3600, "4H" → step=14400, "1D" → step=86400
    """
    import json as _json
    import urllib.request as _req

    _HEADERS = {"User-Agent": "MatiTradingBot/1.0"}

    _SYMBOL_MAP: dict[str, str] = {
        "BTC-USDT": "btcusd", "BTC-USD": "btcusd",
        "ETH-USDT": "ethusd", "ETH-USD": "ethusd",
        "SOL-USDT": "solusd", "SOL-USD": "solusd",
        "XRP-USDT": "xrpusd", "LTC-USDT": "ltcusd",
    }

    _BAR_MAP: dict[str, int] = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1H": 3600, "4H": 14400, "1D": 86400,
    }

    pair = _SYMBOL_MAP.get(symbol)
    if not pair:
        logger.warning("Bitstamp fallback: par {} no soportado", symbol)
        return []

    step = _BAR_MAP.get(bar)
    if not step:
        logger.warning("Bitstamp fallback: timeframe {} no soportado", bar)
        return []

    from_ts = int(from_dt.timestamp())
    to_ts   = int(to_dt.timestamp())

    bars: list[OHLCVBar] = []
    start = from_ts

    logger.info("Bitstamp fallback: descargando {}/{} desde {} hasta {}",
                pair, step, from_dt.date(), to_dt.date())

    while start < to_ts:
        end = min(start + step * 1000, to_ts)
        url = (
            f"https://www.bitstamp.net/api/v2/ohlc/{pair}/"
            f"?step={step}&limit=1000&start={start}&end={end}"
        )
        try:
            with _req.urlopen(_req.Request(url, headers=_HEADERS), timeout=30) as resp:
                data = _json.loads(resp.read())
        except Exception as exc:
            logger.error("Bitstamp fallback error: {}", exc)
            break

        chunk = data.get("data", {}).get("ohlc", [])
        if not chunk:
            break

        for row in chunk:
            ts_s = int(row["timestamp"])
            if ts_s >= to_ts:
                continue
            bars.append(OHLCVBar(
                timestamp=ts_s * 1000,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row["volume"]),
            ))

        if on_page:
            on_page(len(bars))

        if len(chunk) < 1000:
            break
        start = int(chunk[-1]["timestamp"]) + step

    bars.sort(key=lambda b: b.timestamp)
    logger.info("Bitstamp fallback: {} velas descargadas", len(bars))
    return bars


def _merge_bars(primary: list[OHLCVBar], supplement: list[OHLCVBar]) -> list[OHLCVBar]:
    """Une dos listas de barras, deduplica por timestamp y ordena cronologicamente."""
    seen: set[int] = {b.timestamp for b in primary}
    merged = primary + [b for b in supplement if b.timestamp not in seen]
    merged.sort(key=lambda b: b.timestamp)
    return merged


def fetch_historical_bars(
    symbol: str,
    bar: str,
    from_dt: datetime,
    to_dt: datetime,
    on_page: Callable[[int], None] | None = None,
    use_cache: bool = True,
) -> list[OHLCVBar]:
    """
    Descarga datos OHLCV históricos desde la API pública de OKX.
    No requiere autenticación. Pagina automáticamente si el rango es grande.

    on_page(n_bars): callback opcional llamado tras cada página descargada.
    use_cache: sirve desde cache en disco si el rango esta cubierto (deterministico).
               Las descargas se persisten para que runs futuros sean reproducibles.
    """
    from_ms = int(from_dt.timestamp() * 1000)
    to_ms   = int(to_dt.timestamp() * 1000)

    if use_cache:
        cached = ohlcv_cache.try_serve(symbol, bar, from_ms, to_ms)
        if cached is not None:
            return cached

    try:
        from okx.MarketData import MarketAPI
    except ImportError:
        logger.error("python-okx no instalado. Ejecuta: pip install python-okx")
        return []

    api = MarketAPI(flag="0")  # 0 = mainnet, sin auth
    bars: list[OHLCVBar] = []
    before_ts = str(int(to_dt.timestamp() * 1000))
    after_ts  = str(int(from_dt.timestamp() * 1000))
    complete  = True  # se pone False si una pagina no se recupera tras reintentos

    logger.info("Descargando {}/{} desde {} hasta {}", symbol, bar, from_dt.date(), to_dt.date())

    while True:
        resp = None
        for attempt in range(_OKX_MAX_RETRIES):
            try:
                resp = api.get_history_candlesticks(
                    instId=symbol,
                    bar=bar,
                    before=after_ts,
                    after=before_ts,
                    limit="300",
                )
                if resp.get("code") == "0" and resp.get("data") is not None:
                    break
                # code != "0" (rate limit, etc.) — reintentar con backoff
                logger.warning(
                    "OKX pagina code={} (intento {}/{})",
                    resp.get("code"), attempt + 1, _OKX_MAX_RETRIES,
                )
                resp = None
            except Exception as exc:
                logger.warning(
                    "OKX pagina fallo (intento {}/{}): {}",
                    attempt + 1, _OKX_MAX_RETRIES, exc,
                )
                resp = None
            time.sleep(_OKX_BACKOFF_S * (attempt + 1))

        if resp is None:
            logger.error(
                "OKX: pagina no recuperable tras {} intentos — descarga INCOMPLETA, no se cachea",
                _OKX_MAX_RETRIES,
            )
            complete = False
            break

        if not resp.get("data"):
            break  # fin normal de datos

        chunk = resp["data"]
        for row in chunk:
            ts, o, h, l, c, vol = row[0], row[1], row[2], row[3], row[4], row[5]
            bars.append(OHLCVBar(
                timestamp=int(ts),
                open=Decimal(o), high=Decimal(h),
                low=Decimal(l), close=Decimal(c),
                volume=Decimal(vol),
            ))

        if on_page:
            on_page(len(bars))

        if len(chunk) < 300:
            break

        before_ts = chunk[-1][0]
        if int(before_ts) <= int(after_ts):
            break

    bars.sort(key=lambda b: b.timestamp)
    logger.info("Descargadas {} velas", len(bars))

    if not bars:
        logger.warning("OKX no devolvio datos para {}/{} — intentando Binance fallback", symbol, bar)
        bars = _fetch_binance_bars(symbol, bar, from_dt, to_dt, on_page)

    # Rellenar gap al inicio con Kraken si los datos no llegan hasta from_dt
    from datetime import timezone as _tz
    _bar_ms = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
        "1H": 3_600_000, "4H": 14_400_000, "1D": 86_400_000,
    }
    _from_ms    = int(from_dt.timestamp() * 1000)
    _threshold  = _bar_ms.get(bar, 3_600_000) * 2
    _has_gap    = not bars or (bars[0].timestamp - _from_ms) > _threshold

    if _has_gap:
        _gap_end = (
            datetime.fromtimestamp(bars[0].timestamp / 1000, tz=_tz.utc)
            if bars else to_dt
        )
        logger.info("Gap detectado antes de {} — intentando Kraken para rellenar", _gap_end.date())
        bitstamp_bars = _fetch_bitstamp_bars(symbol, bar, from_dt, _gap_end, on_page)
        if bitstamp_bars:
            bars = _merge_bars(bars, bitstamp_bars)

    if use_cache and bars:
        # Persistir y servir el slice desde el dataset canonico mergeado, de forma
        # que este run y los futuros vean exactamente las mismas velas.
        merged = ohlcv_cache.merge_and_save(
            symbol, bar, bars, from_ms, to_ms, complete=complete,
        )
        if complete:
            return ohlcv_cache.slice_range(merged, from_ms, to_ms)

    return bars
