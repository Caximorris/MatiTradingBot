"""
Gestor de riesgo global.
Se consulta antes de cada operación para decidir si está permitida.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import func

from config.settings import Settings, settings as _global_settings
from core.database import BotState, Position, Trade, get_session
from core.exchange import OKXClient


class RiskManager:
    def __init__(
        self,
        client: OKXClient,
        app_settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = app_settings or _global_settings
        self._blacklist: set[str] = set()

    # -----------------------------------------------------------------------
    # Comprobación principal
    # -----------------------------------------------------------------------

    def can_open_position(self, symbol: str, size_usdt: Decimal) -> tuple[bool, str]:
        """
        Retorna (True, "") si la operación está permitida.
        Retorna (False, "razón") si debe bloquearse.

        Orden de comprobaciones (fail-fast):
        1. Límite de pérdida diaria
        2. Número máximo de posiciones abiertas
        3. Porcentaje de riesgo máximo por operación
        4. Lista negra del usuario
        5. Balance disponible suficiente
        """
        # 1 — Pérdida diaria
        limit_hit, daily_pnl = self.check_daily_loss()
        if limit_hit:
            return False, f"Límite de pérdida diaria alcanzado: {daily_pnl:.2f} USDT"

        # 2 — Posiciones abiertas
        with get_session() as session:
            open_count = session.query(Position).count()
        if open_count >= self._settings.max_open_positions:
            return False, (
                f"Máximo de posiciones simultáneas alcanzado "
                f"({self._settings.max_open_positions})"
            )

        # 3 — Riesgo por operación
        balance = self._client.get_balance()
        total_usdt = balance.get("USDT", Decimal("0"))

        if total_usdt <= Decimal("0"):
            return False, "Balance USDT es cero o no disponible"

        max_risk_usdt = total_usdt * self._settings.max_portfolio_risk_pct / Decimal("100")
        if size_usdt > max_risk_usdt:
            return False, (
                f"Tamaño {size_usdt:.2f} USDT supera el riesgo máximo "
                f"{max_risk_usdt:.2f} USDT "
                f"({self._settings.max_portfolio_risk_pct}% del portfolio)"
            )

        # 4 — Lista negra
        if symbol.upper() in self._blacklist:
            return False, f"{symbol} está en lista negra"

        # 5 — Balance suficiente
        if total_usdt < size_usdt:
            return False, (
                f"Balance insuficiente: {total_usdt:.2f} USDT disponibles, "
                f"se necesitan {size_usdt:.2f} USDT"
            )

        return True, ""

    # -----------------------------------------------------------------------
    # Cálculo de tamaño de posición
    # -----------------------------------------------------------------------

    def calculate_position_size(
        self,
        symbol: str,
        risk_pct: Decimal,
        entry: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """
        Kelly Criterion simplificado.

        Fórmula:
            risk_amount  = account_value × risk_pct / 100
            price_risk   = entry − stop_loss   (riesgo por unidad)
            units        = risk_amount / price_risk

        Retorna 0 si los parámetros son inválidos.
        """
        if entry <= stop_loss or stop_loss <= Decimal("0"):
            logger.warning(
                "calculate_position_size: parámetros inválidos entry={} stop_loss={}",
                entry, stop_loss,
            )
            return Decimal("0")

        balance = self._client.get_balance()
        account_value = balance.get("USDT", Decimal("0"))
        if account_value <= Decimal("0"):
            return Decimal("0")

        risk_amount = account_value * risk_pct / Decimal("100")
        price_risk_per_unit = entry - stop_loss
        units = risk_amount / price_risk_per_unit
        return units.quantize(Decimal("0.00000001"))

    # -----------------------------------------------------------------------
    # Pérdida diaria
    # -----------------------------------------------------------------------

    def check_daily_loss(self) -> tuple[bool, float]:
        """
        Suma el PnL realizado de hoy desde la DB.
        Retorna (limite_alcanzado: bool, pnl_dia: float).
        """
        today_start = datetime.combine(
            date.today(), datetime.min.time()
        ).replace(tzinfo=timezone.utc)

        with get_session() as session:
            result = (
                session.query(func.sum(Trade.pnl))
                .filter(Trade.timestamp >= today_start, Trade.pnl.isnot(None))
                .scalar()
            )

        daily_pnl = float(result or 0)

        balance = self._client.get_balance()
        account_value = float(balance.get("USDT", Decimal("0")))

        if account_value <= 0:
            return False, daily_pnl

        loss_pct = abs(min(daily_pnl, 0)) / account_value * 100
        limit_hit = loss_pct >= float(self._settings.daily_loss_limit_pct)

        if limit_hit:
            logger.warning(
                "Límite de pérdida diaria alcanzado: {:.2f} USDT ({:.1f}%)",
                daily_pnl,
                loss_pct,
            )

        return limit_hit, daily_pnl

    # -----------------------------------------------------------------------
    # Parada de emergencia
    # -----------------------------------------------------------------------

    def emergency_stop(self) -> None:
        """
        Cancela TODAS las órdenes abiertas y desactiva todos los bots en DB.
        """
        logger.critical(
            "[EMERGENCY STOP] Activado a las {} UTC", datetime.now(timezone.utc).isoformat()
        )

        for symbol in self._settings.trading_pairs:
            try:
                open_orders = self._client.get_open_orders(symbol)
                for order in open_orders:
                    order_id = (
                        order.get("order_id")
                        or order.get("ordId")
                        or getattr(order, "order_id", "")
                    )
                    if order_id:
                        self._client.cancel_order(order_id, symbol)
                        logger.info(
                            "[EMERGENCY STOP] Cancelada orden {} en {}", order_id, symbol
                        )
            except Exception as exc:
                logger.error(
                    "[EMERGENCY STOP] Error cancelando órdenes de {}: {}", symbol, exc
                )

        with get_session() as session:
            session.query(BotState).update({"is_active": False})

        logger.critical("[EMERGENCY STOP] Completado — todos los bots desactivados")

    # -----------------------------------------------------------------------
    # Lista negra
    # -----------------------------------------------------------------------

    def add_to_blacklist(self, symbol: str) -> None:
        self._blacklist.add(symbol.upper())
        logger.info("RiskManager: {} añadido a lista negra", symbol.upper())

    def remove_from_blacklist(self, symbol: str) -> None:
        self._blacklist.discard(symbol.upper())
        logger.info("RiskManager: {} eliminado de lista negra", symbol.upper())

    @property
    def blacklist(self) -> frozenset[str]:
        return frozenset(self._blacklist)
