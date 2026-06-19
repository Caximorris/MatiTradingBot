"""Sincronización del estado de posiciones abiertas con la DB."""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from core.database import Position, get_session, upsert_position, close_position

if TYPE_CHECKING:
    from core.exchange import OKXClient


class PositionTracker:
    """
    Sincroniza posiciones abiertas entre la DB y el exchange.
    En modo paper lee de _paper_balance; en live consulta la API de OKX.
    """

    def __init__(self, client: "OKXClient", session: Session) -> None:
        self._client = client
        self._session = session

    def sync(self, symbols: list[str]) -> None:
        """Actualiza current_price y unrealized_pnl de todas las posiciones abiertas."""
        positions: list[Position] = (
            self._session.query(Position)
            .filter(Position.symbol.in_(symbols), Position.is_open == True)
            .all()
        )
        for pos in positions:
            try:
                current_price = self._client.get_ticker(pos.symbol)
                if current_price <= Decimal("0"):
                    continue
                pnl = self._calc_unrealized_pnl(pos, current_price)
                pos.current_price = current_price
                pos.unrealized_pnl = pnl
            except Exception as exc:
                logger.warning("PositionTracker: error actualizando {}: {}", pos.symbol, exc)
        try:
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            logger.error("PositionTracker: error en commit: {}", exc)

    def _calc_unrealized_pnl(self, pos: Position, current_price: Decimal) -> Decimal:
        if pos.side == "long":
            return (current_price - pos.entry_price) * pos.quantity
        # short
        return (pos.entry_price - current_price) * pos.quantity

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        q = self._session.query(Position).filter(Position.is_open == True)
        if symbol:
            q = q.filter(Position.symbol == symbol)
        return q.all()

    def open_count(self) -> int:
        return self._session.query(Position).filter(Position.is_open == True).count()
