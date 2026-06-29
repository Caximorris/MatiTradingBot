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

        # Journal de trades — poblado durante el backtest, escrito al finalizar
        self._journal: list[dict] = []
        self._pending_journal_entry: dict | None = None
        # Valores temporales escritos por _open_* y _close_* para el journal
        self._last_open_invest:  float = 0.0
        self._last_close_pnl:    float = 0.0
        self._last_close_reason: str   = ""

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

    # -----------------------------------------------------------------------
    # Journal helpers — llamados desde run() en las subclases
    # -----------------------------------------------------------------------

    def _journal_open(
        self,
        side: str,
        ts: str,
        price: float,
        invest: float,
        stop: float,
        qty: float,
        balance_before: float,
        ls: int,
        ss: int,
        indicators: dict,
        tp: float = 0.0,
    ) -> None:
        """Registra la apertura de un trade en el journal pendiente."""
        self._pending_journal_entry = {
            "trade_num": len(self._journal) + 1,
            "side":      side,
            "symbol":    getattr(getattr(self, "_cfg", None), "symbol", "?"),
            "open": {
                "timestamp":           ts,
                "price":               round(price, 2),
                "qty":                 qty,
                "invest_usdt":         round(invest, 2),
                "stop_loss":           round(stop, 2),
                "take_profit":         round(tp, 2),
                "balance_usdt_before": round(balance_before, 2),
                "score_long":          ls,
                "score_short":         ss,
                "indicators":          indicators,
            },
        }

    def _journal_close(
        self,
        ts: str,
        price: float,
        pnl: float,
        reason: str,
        holding_hours: float,
        balance_after: float,
        ls: int,
        ss: int,
        indicators: dict,
        mae_pct: float = 0.0,
        mfe_pct: float = 0.0,
        r_multiple: float = 0.0,
    ) -> None:
        """Finaliza el trade pendiente y lo añade al journal."""
        if not self._pending_journal_entry:
            return
        invest = self._pending_journal_entry["open"].get("invest_usdt", 1.0)
        pnl_pct = round(pnl / invest * 100, 2) if invest else 0.0
        self._pending_journal_entry["close"] = {
            "timestamp":          ts,
            "price":              round(price, 2),
            "pnl_usdt":           round(pnl, 2),
            "pnl_pct":            pnl_pct,
            "reason":             reason,
            "holding_hours":      round(holding_hours, 1),
            "balance_usdt_after": round(balance_after, 2),
            "score_long":         ls,
            "score_short":        ss,
            "mae_pct":            mae_pct,
            "mfe_pct":            mfe_pct,
            "r_multiple":         r_multiple,
            "indicators":         indicators,
        }
        self._journal.append(self._pending_journal_entry)
        self._pending_journal_entry = None
        self._last_close_pnl    = 0.0
        self._last_close_reason = ""
