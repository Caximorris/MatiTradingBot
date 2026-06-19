"""
Punto único de escritura para todos los trades del sistema.
Cada módulo que ejecute una orden debe pasar por aquí.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from core.database import Trade, create_trade

if TYPE_CHECKING:
    from core.exchange import OrderResult


class TradeLogger:
    def __init__(self, session: Session, is_paper: bool = True) -> None:
        self._session = session
        self._is_paper = is_paper

    def log(
        self,
        symbol: str,
        side: str,
        order_type: str,
        strategy: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
        fee_currency: str = "USDT",
        order_id: str = "",
        pnl: Decimal | None = None,
        notes: str = "",
    ) -> Trade:
        trade = create_trade(
            self._session,
            symbol=symbol,
            side=side,
            order_type=order_type,
            strategy=strategy,
            quantity=quantity,
            price=price,
            fee=fee,
            fee_currency=fee_currency,
            order_id=order_id,
            is_paper=self._is_paper,
            pnl=pnl,
            notes=notes,
        )
        logger.info(
            "[{}] {} {} {} qty={} @ {} | fee={} | pnl={}",
            "PAPER" if self._is_paper else "LIVE",
            strategy,
            side.upper(),
            symbol,
            quantity,
            price,
            fee,
            pnl,
        )
        return trade

    @classmethod
    def from_order_result(
        cls,
        session: Session,
        order: "OrderResult",
        strategy: str,
        pnl: Decimal | None = None,
        notes: str = "",
    ) -> Trade | None:
        """
        Registra un Trade a partir de un OrderResult del exchange.
        Retorna None si la orden no está filled o no tiene precio.
        """
        if order.status != "filled" or order.filled_price is None:
            return None
        instance = cls(session, is_paper=order.is_paper)
        return instance.log(
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            strategy=strategy,
            quantity=order.filled_qty,
            price=order.filled_price,
            fee=order.fee,
            fee_currency=order.fee_currency,
            order_id=order.order_id,
            pnl=pnl,
            notes=notes,
        )
