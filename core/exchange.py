"""
Cliente OKX — abstrae REST para trading en vivo y simulación paper.

En paper mode los métodos de lectura intentan llamar a la API pública de OKX
(no requiere credenciales) y degradan graciosamente si no hay conexión.
Los métodos de escritura (place_order, cancel_order) nunca llaman a OKX en paper:
simulan la operación localmente y devuelven la misma estructura que el modo live.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from loguru import logger

from config.settings import Settings

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

try:
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )
    _TENACITY_OK = True
except ImportError:
    _TENACITY_OK = False
    logger.warning("tenacity no instalado — reintentos automáticos deshabilitados")


# ---------------------------------------------------------------------------
# Constantes de rate limiting (OKX: 20 req / 2 s en endpoints privados)
# ---------------------------------------------------------------------------

_RATE_MAX_REQUESTS = 20
_RATE_WINDOW_SECONDS = 2.0

# Comisión simulada en paper mode (taker fee estándar de OKX spot)
_PAPER_FEE_RATE = Decimal("0.001")  # 0.1 %


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

class ExchangeError(Exception):
    """Error retornado por la API de OKX (código != 0)."""


class ExchangeUnavailable(ExchangeError):
    """Exchange no alcanzable: timeout, sin conexión, 5xx."""


# ---------------------------------------------------------------------------
# Tipo de retorno normalizado para órdenes
# ---------------------------------------------------------------------------

@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str
    order_type: str
    size: Decimal
    limit_price: Decimal | None      # None para market orders
    filled_price: Decimal | None     # None si la orden queda pendiente
    filled_qty: Decimal
    fee: Decimal
    fee_currency: str
    status: str                      # "filled" | "open" | "rejected"
    is_paper: bool
    strategy: str
    timestamp: datetime
    error: str = ""


# ---------------------------------------------------------------------------
# Rate limiter (ventana deslizante, thread-safe)
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, max_requests: int, window: float) -> None:
        self._max = max_requests
        self._window = window
        self._times: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._times = [t for t in self._times if now - t < self._window]
            if len(self._times) >= self._max:
                wait = self._window - (now - self._times[0]) + 0.05
                if wait > 0:
                    logger.debug("Rate limit — esperando {:.2f}s", wait)
                    time.sleep(wait)
            self._times.append(time.monotonic())


# ---------------------------------------------------------------------------
# Retry decorator (no-op si tenacity no está instalado)
# ---------------------------------------------------------------------------

def _with_retry(func):
    if not _TENACITY_OK:
        return func
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((ExchangeUnavailable, ConnectionError, TimeoutError)),
        reraise=True,
    )(func)


# ---------------------------------------------------------------------------
# OKXClient
# ---------------------------------------------------------------------------

class OKXClient:
    """
    Interfaz unificada para OKX (REST).

    Las estrategias nunca deben comprobar `is_paper`: llaman a los mismos
    métodos independientemente del modo — la diferencia está encapsulada aquí.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._is_paper = settings.is_paper
        self._flag = "1" if settings.okx_sandbox else "0"
        self._rate = _RateLimiter(_RATE_MAX_REQUESTS, _RATE_WINDOW_SECONDS)

        # Clientes OKX (inicializados si el paquete está instalado)
        self._market_api: Any = None
        self._trade_api: Any = None
        self._account_api: Any = None
        self._available = False

        self._init_apis()

        # Estado paper (thread-safe)
        self._paper_lock = threading.Lock()
        self._paper_balance: dict[str, Decimal] = {"USDT": Decimal("10000")}
        self._paper_orders: dict[str, OrderResult] = {}
        self._paper_counter = 0

        mode = "paper" if self._is_paper else "live"
        logger.info("OKXClient inicializado — modo={}, exchange_disponible={}", mode, self._available)

    # -----------------------------------------------------------------------
    # Inicialización de APIs
    # -----------------------------------------------------------------------

    def _init_apis(self) -> None:
        try:
            from okx.MarketData import MarketAPI  # type: ignore[import]
            self._market_api = MarketAPI(flag=self._flag, debug=False)
            self._available = True

            if not self._is_paper:
                from okx.Trade import TradeAPI      # type: ignore[import]
                from okx.Account import AccountAPI  # type: ignore[import]
                self._trade_api = TradeAPI(
                    self._settings.okx_api_key,
                    self._settings.okx_secret_key,
                    self._settings.okx_passphrase,
                    False,
                    self._flag,
                    debug=False,
                )
                self._account_api = AccountAPI(
                    self._settings.okx_api_key,
                    self._settings.okx_secret_key,
                    self._settings.okx_passphrase,
                    False,
                    self._flag,
                    debug=False,
                )
                logger.info("OKX TradeAPI + AccountAPI activas (live, sandbox={})", self._flag == "1")

        except ImportError:
            logger.warning("python-okx no instalado — get_ticker/get_ohlcv retornarán valores vacíos")
        except Exception as exc:
            logger.warning("No se pudo conectar a OKX: {} — paper trading funciona igual", exc)

    # -----------------------------------------------------------------------
    # Helpers internos
    # -----------------------------------------------------------------------

    @staticmethod
    def _check_okx_response(resp: dict) -> dict:
        if resp.get("code") != "0":
            raise ExchangeError(
                f"OKX error code={resp.get('code')}: {resp.get('msg', 'desconocido')}"
            )
        return resp

    def _call_api(self, method, *args, **kwargs) -> dict:
        """Llama a un método OKX con throttle + retry automáticos."""
        @_with_retry
        def _inner():
            self._rate.acquire()
            try:
                return self._check_okx_response(method(*args, **kwargs))
            except ExchangeError:
                raise
            except Exception as exc:
                raise ExchangeUnavailable(str(exc)) from exc

        return _inner()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def current_time(self) -> datetime:
        """Tiempo actual — en backtest devuelve el timestamp de la barra, en live el reloj real."""
        return datetime.now(timezone.utc)

    # -----------------------------------------------------------------------
    # Métodos de lectura — funcionan en paper Y live
    # -----------------------------------------------------------------------

    def get_ticker(self, symbol: str) -> Decimal:
        """
        Precio último del par.
        Retorna Decimal("0") si el exchange no está disponible.
        """
        if not self._available or self._market_api is None:
            logger.debug("get_ticker({}) — exchange no disponible, retorna 0", symbol)
            return Decimal("0")
        try:
            resp = self._call_api(self._market_api.get_ticker, instId=symbol)
            return Decimal(resp["data"][0]["last"])
        except Exception as exc:
            logger.warning("get_ticker({}) falló: {}", symbol, exc)
            return Decimal("0")

    def get_ohlcv(self, symbol: str, timeframe: str = "1H", limit: int = 100):
        """
        Velas OHLCV como DataFrame [timestamp, open, high, low, close, volume].
        Retorna DataFrame vacío si no hay datos o pandas no está instalado.
        """
        if not _PANDAS_OK:
            logger.warning("pandas no instalado — get_ohlcv retorna lista vacía")
            return []

        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        if not self._available or self._market_api is None:
            return empty

        try:
            resp = self._call_api(
                self._market_api.get_candlesticks,
                instId=symbol,
                bar=timeframe,
                limit=str(limit),
            )
            raw = resp.get("data", [])
            if not raw:
                return empty

            df = pd.DataFrame(
                raw,
                columns=["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"],
            )
            df["timestamp"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
            df = df[["timestamp", "open", "high", "low", "close", "vol"]].copy()
            df.rename(columns={"vol": "volume"}, inplace=True)
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df

        except Exception as exc:
            logger.warning("get_ohlcv({}, {}) falló: {}", symbol, timeframe, exc)
            return empty

    def get_balance(self) -> dict[str, Decimal]:
        """
        Balances disponibles.
        En paper mode devuelve el balance simulado interno.
        """
        if self._is_paper:
            with self._paper_lock:
                return dict(self._paper_balance)

        if not self._available or self._account_api is None:
            logger.warning("get_balance() — exchange no disponible")
            return {}

        try:
            resp = self._call_api(self._account_api.get_account_balance)
            result: dict[str, Decimal] = {}
            for detail in resp["data"][0].get("details", []):
                ccy = detail["ccy"]
                avail = detail.get("availEq") or detail.get("availBal", "0")
                result[ccy] = Decimal(str(avail))
            return result
        except Exception as exc:
            logger.warning("get_balance() falló: {}", exc)
            return {}

    def get_open_orders(self, symbol: str) -> list[dict]:
        """
        Órdenes abiertas para el símbolo.
        En paper mode devuelve las órdenes limit pendientes simuladas.
        """
        if self._is_paper:
            with self._paper_lock:
                return [
                    _order_result_to_dict(o)
                    for o in self._paper_orders.values()
                    if o.symbol == symbol
                ]

        if not self._available or self._trade_api is None:
            return []

        try:
            resp = self._call_api(self._trade_api.get_order_list, instId=symbol)
            return resp.get("data", [])
        except Exception as exc:
            logger.warning("get_open_orders({}) falló: {}", symbol, exc)
            return []

    def get_positions(self) -> list[dict]:
        """
        Posiciones abiertas.
        En paper mode las posiciones se gestionan en DB (via position_tracker).
        """
        if self._is_paper:
            return []

        if not self._available or self._account_api is None:
            return []

        try:
            resp = self._call_api(self._account_api.get_positions)
            return resp.get("data", [])
        except Exception as exc:
            logger.warning("get_positions() falló: {}", exc)
            return []

    def get_order_history(self, symbol: str, limit: int = 100) -> list[dict]:
        """
        Historial de órdenes ejecutadas.
        En paper mode el historial está en la DB (via trade_logger).
        """
        if self._is_paper:
            return []

        if not self._available or self._trade_api is None:
            return []

        try:
            resp = self._call_api(
                self._trade_api.get_orders_history,
                instType="SPOT",
                instId=symbol,
                limit=str(limit),
            )
            return resp.get("data", [])
        except Exception as exc:
            logger.warning("get_order_history({}) falló: {}", symbol, exc)
            return []

    # -----------------------------------------------------------------------
    # Métodos de escritura — paper simula; live llama a OKX
    # -----------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: Decimal,
        price: Decimal | None = None,
        strategy: str = "manual",
    ) -> OrderResult:
        """
        Coloca una orden (compra o venta).

        Args:
            symbol:     Par, e.g. "BTC-USDT"
            side:       "buy" | "sell"
            order_type: "market" | "limit"
            size:       Cantidad de la moneda base
            price:      Precio límite (solo para order_type="limit")
            strategy:   Nombre de la estrategia que origina la orden
        """
        if self._is_paper:
            return self._paper_place_order(symbol, side, order_type, size, price, strategy)
        return self._live_place_order(symbol, side, order_type, size, price, strategy)

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Cancela una orden abierta.
        En paper mode elimina la orden pendiente del registro local.
        Retorna True si la cancelación fue exitosa.
        """
        if self._is_paper:
            return self._paper_cancel_order(order_id, symbol)
        return self._live_cancel_order(order_id, symbol)

    # -----------------------------------------------------------------------
    # Paper trading — lógica de simulación local
    # -----------------------------------------------------------------------

    def _next_paper_id(self) -> str:
        self._paper_counter += 1
        return f"PAPER-{self._paper_counter:06d}-{uuid.uuid4().hex[:6].upper()}"

    def _paper_place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: Decimal,
        price: Decimal | None,
        strategy: str,
    ) -> OrderResult:
        with self._paper_lock:
            order_id = self._next_paper_id()
            base_ccy, quote_ccy = symbol.split("-")

            # Precio de ejecución: market → ticker actual; limit → precio dado
            if order_type == "market" or price is None:
                fill_price = self.get_ticker(symbol)
                if fill_price == Decimal("0") and price is not None:
                    fill_price = price  # fallback al precio proporcionado
            else:
                fill_price = price  # limit: se "llenará" cuando cruce el precio

            quote_amount = size * fill_price
            fee = quote_amount * _PAPER_FEE_RATE

            # Para market orders: ejecutar inmediatamente (verificar balance)
            if order_type == "market":
                ok, reason = self._paper_check_and_deduct(
                    side, base_ccy, quote_ccy, size, quote_amount, fee
                )
                if not ok:
                    result = OrderResult(
                        order_id="", symbol=symbol, side=side, order_type=order_type,
                        size=size, limit_price=price, filled_price=None, filled_qty=Decimal("0"),
                        fee=Decimal("0"), fee_currency=quote_ccy, status="rejected",
                        is_paper=True, strategy=strategy, timestamp=self._utcnow(), error=reason,
                    )
                    logger.warning("[PAPER] Orden rechazada — {}: {}", symbol, reason)
                    return result

                result = OrderResult(
                    order_id=order_id, symbol=symbol, side=side, order_type=order_type,
                    size=size, limit_price=None, filled_price=fill_price, filled_qty=size,
                    fee=fee, fee_currency=quote_ccy, status="filled",
                    is_paper=True, strategy=strategy, timestamp=self._utcnow(),
                )
                logger.info(
                    "[PAPER] {} {} {} qty={} @ {} fee={} {}",
                    side.upper(), order_id, symbol, size, fill_price, fee, quote_ccy,
                )
                return result

            # Para limit orders: reservar balance y quedar pendiente
            if order_type == "limit" and price is not None:
                if side == "buy":
                    reserved = quote_amount + fee
                    available = self._paper_balance.get(quote_ccy, Decimal("0"))
                    if available < reserved:
                        return OrderResult(
                            order_id="", symbol=symbol, side=side, order_type=order_type,
                            size=size, limit_price=price, filled_price=None, filled_qty=Decimal("0"),
                            fee=Decimal("0"), fee_currency=quote_ccy, status="rejected",
                            is_paper=True, strategy=strategy, timestamp=self._utcnow(),
                            error=f"Balance insuficiente: necesita {reserved} {quote_ccy}, tiene {available}",
                        )
                    # Reservar el importe (descontarlo del balance disponible)
                    self._paper_balance[quote_ccy] = available - reserved
                else:  # sell limit
                    available = self._paper_balance.get(base_ccy, Decimal("0"))
                    if available < size:
                        return OrderResult(
                            order_id="", symbol=symbol, side=side, order_type=order_type,
                            size=size, limit_price=price, filled_price=None, filled_qty=Decimal("0"),
                            fee=Decimal("0"), fee_currency=quote_ccy, status="rejected",
                            is_paper=True, strategy=strategy, timestamp=self._utcnow(),
                            error=f"Balance insuficiente: necesita {size} {base_ccy}, tiene {available}",
                        )
                    self._paper_balance[base_ccy] = available - size

                pending = OrderResult(
                    order_id=order_id, symbol=symbol, side=side, order_type=order_type,
                    size=size, limit_price=price, filled_price=None, filled_qty=Decimal("0"),
                    fee=fee, fee_currency=quote_ccy, status="open",
                    is_paper=True, strategy=strategy, timestamp=self._utcnow(),
                )
                self._paper_orders[order_id] = pending
                logger.info(
                    "[PAPER] Limit {} {} @ {} — pendiente (id={})", side, symbol, price, order_id
                )
                return pending

            # Fallback (no debería ocurrir)
            return OrderResult(
                order_id="", symbol=symbol, side=side, order_type=order_type,
                size=size, limit_price=price, filled_price=None, filled_qty=Decimal("0"),
                fee=Decimal("0"), fee_currency=quote_ccy, status="rejected",
                is_paper=True, strategy=strategy, timestamp=self._utcnow(),
                error=f"order_type no soportado: {order_type}",
            )

    def _paper_check_and_deduct(
        self,
        side: str,
        base_ccy: str,
        quote_ccy: str,
        size: Decimal,
        quote_amount: Decimal,
        fee: Decimal,
    ) -> tuple[bool, str]:
        """Verifica y descuenta balance para una market order. Debe llamarse con el lock tomado."""
        if side == "buy":
            total_cost = quote_amount + fee
            available = self._paper_balance.get(quote_ccy, Decimal("0"))
            if available < total_cost:
                return False, f"Balance insuficiente: necesita {total_cost} {quote_ccy}, tiene {available}"
            self._paper_balance[quote_ccy] = available - total_cost
            self._paper_balance[base_ccy] = self._paper_balance.get(base_ccy, Decimal("0")) + size
        else:
            available = self._paper_balance.get(base_ccy, Decimal("0"))
            if available < size:
                return False, f"Balance insuficiente: necesita {size} {base_ccy}, tiene {available}"
            proceeds = quote_amount - fee
            self._paper_balance[base_ccy] = available - size
            self._paper_balance[quote_ccy] = self._paper_balance.get(quote_ccy, Decimal("0")) + proceeds
        return True, ""

    def _paper_cancel_order(self, order_id: str, symbol: str) -> bool:
        with self._paper_lock:
            order = self._paper_orders.pop(order_id, None)
            if order is None:
                logger.warning("[PAPER] cancel_order: {} no encontrada", order_id)
                return False

            # Devolver el balance reservado
            base_ccy, quote_ccy = order.symbol.split("-")
            if order.side == "buy" and order.limit_price is not None:
                reserved = order.size * order.limit_price + order.fee
                self._paper_balance[quote_ccy] = (
                    self._paper_balance.get(quote_ccy, Decimal("0")) + reserved
                )
            elif order.side == "sell":
                self._paper_balance[base_ccy] = (
                    self._paper_balance.get(base_ccy, Decimal("0")) + order.size
                )

            logger.info("[PAPER] Orden {} cancelada ({})", order_id, symbol)
            return True

    def fill_paper_limit_orders(
        self, symbol: str, current_price: Decimal
    ) -> list[OrderResult]:
        """
        Verifica órdenes limit pendientes y ejecuta las que cruzan el precio actual.
        Las estrategias deben llamar a este método en cada tick de precio.
        Retorna la lista de órdenes que se ejecutaron en esta llamada.
        """
        filled: list[OrderResult] = []
        with self._paper_lock:
            for order_id in list(self._paper_orders):
                order = self._paper_orders[order_id]
                if order.symbol != symbol or order.limit_price is None:
                    continue

                crossed = (
                    (order.side == "buy" and current_price <= order.limit_price) or
                    (order.side == "sell" and current_price >= order.limit_price)
                )
                if not crossed:
                    continue

                base_ccy, quote_ccy = symbol.split("-")
                quote_amount = order.size * current_price

                # Acreditar la parte compradora/vendedora (el balance ya fue reservado)
                if order.side == "buy":
                    self._paper_balance[base_ccy] = (
                        self._paper_balance.get(base_ccy, Decimal("0")) + order.size
                    )
                    # La diferencia entre precio de reserva y precio de ejecución
                    reserved_quote = order.size * order.limit_price + order.fee
                    actual_cost = quote_amount + order.fee
                    refund = reserved_quote - actual_cost
                    if refund > Decimal("0"):
                        self._paper_balance[quote_ccy] = (
                            self._paper_balance.get(quote_ccy, Decimal("0")) + refund
                        )
                else:
                    proceeds = quote_amount - order.fee
                    self._paper_balance[quote_ccy] = (
                        self._paper_balance.get(quote_ccy, Decimal("0")) + proceeds
                    )

                executed = OrderResult(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    size=order.size,
                    limit_price=order.limit_price,
                    filled_price=current_price,
                    filled_qty=order.size,
                    fee=order.fee,
                    fee_currency=order.fee_currency,
                    status="filled",
                    is_paper=True,
                    strategy=order.strategy,
                    timestamp=self._utcnow(),
                )
                del self._paper_orders[order_id]
                filled.append(executed)
                logger.info(
                    "[PAPER] Limit {} ejecutada: {} {} @ {} (id={})",
                    order.side, symbol, order.size, current_price, order_id,
                )

        return filled

    # -----------------------------------------------------------------------
    # Live trading — llamadas reales a OKX
    # -----------------------------------------------------------------------

    def _live_place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: Decimal,
        price: Decimal | None,
        strategy: str,
    ) -> OrderResult:
        if not self._available or self._trade_api is None:
            raise ExchangeUnavailable("Trade API no disponible")

        @_with_retry
        def _call() -> OrderResult:
            self._rate.acquire()
            params: dict[str, Any] = {
                "instId": symbol,
                "tdMode": "cash",
                "side": side,
                "ordType": order_type,
                "sz": str(size),
            }
            if order_type == "limit" and price is not None:
                params["px"] = str(price)

            resp = self._check_okx_response(self._trade_api.place_order(**params))
            data = resp["data"][0]
            _, quote_ccy = symbol.split("-")
            return OrderResult(
                order_id=data["ordId"],
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                limit_price=price,
                filled_price=price if order_type == "limit" else None,
                filled_qty=size if order_type == "market" else Decimal("0"),
                fee=Decimal("0"),      # se actualiza cuando llega el fill
                fee_currency=quote_ccy,
                status="open" if order_type == "limit" else "filled",
                is_paper=False,
                strategy=strategy,
                timestamp=self._utcnow(),
            )

        return _call()

    def _live_cancel_order(self, order_id: str, symbol: str) -> bool:
        if not self._available or self._trade_api is None:
            raise ExchangeUnavailable("Trade API no disponible")

        @_with_retry
        def _call() -> bool:
            self._rate.acquire()
            self._check_okx_response(
                self._trade_api.cancel_order(instId=symbol, ordId=order_id)
            )
            return True

        return _call()

    # -----------------------------------------------------------------------
    # Utilidades de paper trading
    # -----------------------------------------------------------------------

    def set_paper_balance(self, currency: str, amount: Decimal) -> None:
        """Establece el balance simulado para una moneda. Útil para tests y backtest."""
        with self._paper_lock:
            self._paper_balance[currency] = amount

    def get_paper_orders(self) -> dict[str, OrderResult]:
        """Retorna copia de las órdenes limit pendientes en paper mode."""
        with self._paper_lock:
            return dict(self._paper_orders)

    # -----------------------------------------------------------------------
    # Propiedades de estado
    # -----------------------------------------------------------------------

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    @property
    def is_available(self) -> bool:
        return self._available


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _order_result_to_dict(order: OrderResult) -> dict:
    return {
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "size": str(order.size),
        "limit_price": str(order.limit_price) if order.limit_price else None,
        "filled_price": str(order.filled_price) if order.filled_price else None,
        "status": order.status,
        "strategy": order.strategy,
        "timestamp": order.timestamp.isoformat(),
        "is_paper": order.is_paper,
    }
