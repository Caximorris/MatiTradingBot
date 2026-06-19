"""
Clase abstracta base para todas las estrategias.
Las estrategias no comprueban el modo paper/live — eso es responsabilidad del OKXClient.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from core.exchange import OKXClient, OrderResult
from reporting.trade_logger import TradeLogger

if TYPE_CHECKING:
    from core.risk_manager import RiskManager


class BaseStrategy(ABC):
    def __init__(
        self,
        client: OKXClient,
        config: dict,
        session: Session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        self._client = client
        self._config = config
        self._session = session
        self._risk_manager = risk_manager
        self._trade_logger = TradeLogger(session, is_paper=client.is_paper)

    # -----------------------------------------------------------------------
    # Interfaz abstracta
    # -----------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador único de la estrategia. Usado en logs y en DB."""

    @abstractmethod
    def run(self) -> None:
        """
        Lógica principal del tick.
        Llamado periódicamente por el scheduler (APScheduler).
        Debe ser rápido y no bloquear el hilo del scheduler.
        """

    @abstractmethod
    def should_enter(self) -> bool:
        """True si las condiciones de entrada están dadas en este momento."""

    @abstractmethod
    def should_exit(self) -> bool:
        """True si las condiciones de salida están dadas en este momento."""

    # -----------------------------------------------------------------------
    # Helpers disponibles para las subclases
    # -----------------------------------------------------------------------

    def log_trade(self, order: OrderResult, pnl: Decimal | None = None, notes: str = "") -> None:
        """Registra una orden ejecutada en la DB vía TradeLogger."""
        TradeLogger.from_order_result(
            self._session, order, strategy=self.name, pnl=pnl, notes=notes
        )

    def check_risk(self, symbol: str, order_size_usdt: Decimal) -> tuple[bool, str]:
        """
        Consulta al RiskManager antes de operar.
        Sin RiskManager configurado, siempre permite (útil en tests).
        """
        if self._risk_manager is None:
            return True, ""
        return self._risk_manager.can_open_position(symbol, order_size_usdt)

    def _log_risk_block(self, symbol: str, reason: str) -> None:
        logger.warning("[{}] Operación bloqueada por RiskManager en {}: {}", self.name, symbol, reason)
