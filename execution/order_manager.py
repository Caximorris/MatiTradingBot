"""Gestión y seguimiento de órdenes activas."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from core.exchange import OKXClient, OrderResult


@dataclass
class TrackedOrder:
    order_id: str
    symbol: str
    side: str
    order_type: str
    size: Decimal
    limit_price: Decimal | None
    strategy: str
    created_at: datetime
    status: str = "open"


class OrderManager:
    """
    Registra y consulta el estado de las órdenes abiertas.
    Thread-safe. Funciona tanto en modo paper como en live.
    """

    def __init__(self, client: "OKXClient") -> None:
        self._client = client
        self._orders: dict[str, TrackedOrder] = {}
        self._lock = threading.Lock()

    def register(self, result: "OrderResult") -> None:
        if result.status not in ("open", "filled"):
            return
        with self._lock:
            self._orders[result.order_id] = TrackedOrder(
                order_id=result.order_id,
                symbol=result.symbol,
                side=result.side,
                order_type=result.order_type,
                size=result.size,
                limit_price=result.limit_price,
                strategy=result.strategy,
                created_at=result.timestamp,
                status=result.status,
            )

    def mark_filled(self, order_id: str) -> None:
        with self._lock:
            if order_id in self._orders:
                self._orders[order_id].status = "filled"

    def remove(self, order_id: str) -> None:
        with self._lock:
            self._orders.pop(order_id, None)

    def get_open(self, symbol: str | None = None) -> list[TrackedOrder]:
        with self._lock:
            orders = [o for o in self._orders.values() if o.status == "open"]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def cancel_all(self, symbol: str | None = None) -> int:
        """Cancela todas las órdenes abiertas. Retorna el número cancelado."""
        targets = self.get_open(symbol)
        cancelled = 0
        for order in targets:
            try:
                self._client.cancel_order(order.symbol, order.order_id)
                self.remove(order.order_id)
                cancelled += 1
            except Exception as exc:
                logger.warning("OrderManager: error cancelando {}: {}", order.order_id, exc)
        return cancelled

    def sync_with_exchange(self) -> None:
        """Sincroniza el estado local con las órdenes reales del exchange."""
        try:
            live_orders = self._client.get_open_orders()
            live_ids = {o.order_id for o in live_orders}
            with self._lock:
                for oid, order in list(self._orders.items()):
                    if order.status == "open" and oid not in live_ids:
                        order.status = "filled"
                        logger.debug("OrderManager: {} marcado como filled por sync", oid)
        except Exception as exc:
            logger.warning("OrderManager: error en sync_with_exchange: {}", exc)

    @property
    def open_count(self) -> int:
        return len(self.get_open())
