"""
Dollar Cost Averaging (DCA) Bot.

Compra a intervalos regulares y activa "safety orders" si el precio cae.
Cierra la posición cuando el precio sube X% desde el precio medio de entrada.
Implementa Martingale opcional en las safety orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from core.database import get_or_create_bot_state, set_bot_active
from core.exchange import OKXClient
from strategies.base_strategy import BaseStrategy

if TYPE_CHECKING:
    from core.risk_manager import RiskManager


@dataclass
class DCAConfig:
    symbol: str
    base_order_size: Decimal         # USDT por orden base
    safety_order_size: Decimal       # USDT por primera safety order
    price_deviation_pct: Decimal     # caída % desde precio medio que activa safety order
    take_profit_pct: Decimal         # subida % desde precio medio para cerrar
    max_safety_orders: int
    safety_order_volume_scale: Decimal  # multiplicador Martingale (1.0 = sin Martingale)
    interval_hours: Decimal          # horas entre órdenes base

    def __post_init__(self) -> None:
        if self.base_order_size <= Decimal("0"):
            raise ValueError("base_order_size debe ser positivo")
        if self.take_profit_pct <= Decimal("0"):
            raise ValueError("take_profit_pct debe ser positivo")
        if self.max_safety_orders < 0:
            raise ValueError("max_safety_orders no puede ser negativo")
        if self.safety_order_volume_scale < Decimal("1"):
            raise ValueError("safety_order_volume_scale debe ser >= 1")

    @classmethod
    def from_dict(cls, d: dict) -> "DCAConfig":
        return cls(
            symbol=d["symbol"],
            base_order_size=Decimal(str(d["base_order_size"])),
            safety_order_size=Decimal(str(d["safety_order_size"])),
            price_deviation_pct=Decimal(str(d["price_deviation_pct"])),
            take_profit_pct=Decimal(str(d["take_profit_pct"])),
            max_safety_orders=int(d["max_safety_orders"]),
            safety_order_volume_scale=Decimal(str(d.get("safety_order_volume_scale", "1.0"))),
            interval_hours=Decimal(str(d.get("interval_hours", "24"))),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "base_order_size": str(self.base_order_size),
            "safety_order_size": str(self.safety_order_size),
            "price_deviation_pct": str(self.price_deviation_pct),
            "take_profit_pct": str(self.take_profit_pct),
            "max_safety_orders": self.max_safety_orders,
            "safety_order_volume_scale": str(self.safety_order_volume_scale),
            "interval_hours": str(self.interval_hours),
        }


class DCABot(BaseStrategy):
    """
    DCA Bot.

    Estado persistido en BotState.config_json:
    {
        "is_in_position": false,
        "avg_entry_price": "0",
        "total_quantity": "0",      # base currency acumulada
        "total_invested": "0",      # USDT invertido (sin fees)
        "safety_orders_count": 0,
        "last_base_order_at": null  # ISO 8601 UTC
    }
    """

    def __init__(
        self,
        client: OKXClient,
        config: dict | DCAConfig,
        session: Session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        cfg = DCAConfig.from_dict(config) if isinstance(config, dict) else config
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._dca_config = cfg
        self._state = self._load_state()

    @property
    def name(self) -> str:
        sym = self._dca_config.symbol.lower().replace("-", "_")
        return f"dca_{sym}"

    # -----------------------------------------------------------------------
    # Persistencia
    # -----------------------------------------------------------------------

    def _load_state(self) -> dict:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="dca",
            symbol=self._dca_config.symbol,
            config=self._dca_config.to_dict(),
        )
        saved = bot_state.get_config()
        defaults = {
            "is_in_position": False,
            "avg_entry_price": "0",
            "total_quantity": "0",
            "total_invested": "0",
            "safety_orders_count": 0,
            "last_base_order_at": None,
        }
        return {**defaults, **saved}

    def _save_state(self) -> None:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="dca",
            symbol=self._dca_config.symbol,
        )
        bot_state.set_config(self._state)

    # -----------------------------------------------------------------------
    # Señales
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        """True si el intervalo ha pasado y no hay posición abierta."""
        if self._state["is_in_position"]:
            return False
        last_str = self._state.get("last_base_order_at")
        if not last_str:
            return True
        last_order = datetime.fromisoformat(last_str)
        interval = timedelta(hours=float(self._dca_config.interval_hours))
        return self._client.current_time() - last_order >= interval

    def should_exit(self) -> bool:
        """True si el precio alcanzó el take profit desde el precio medio."""
        if not self._state["is_in_position"]:
            return False
        avg_price = Decimal(self._state["avg_entry_price"])
        if avg_price == Decimal("0"):
            return False
        current_price = self._client.get_ticker(self._dca_config.symbol)
        take_profit_price = avg_price * (1 + self._dca_config.take_profit_pct / 100)
        return current_price >= take_profit_price

    def _should_place_safety_order(self, current_price: Decimal) -> bool:
        """True si el precio cayó price_deviation_pct% desde el precio medio de entrada."""
        if self._state["safety_orders_count"] >= self._dca_config.max_safety_orders:
            return False
        avg_price = Decimal(self._state["avg_entry_price"])
        if avg_price == Decimal("0"):
            return False
        deviation = (avg_price - current_price) / avg_price * 100
        return deviation >= self._dca_config.price_deviation_pct

    # -----------------------------------------------------------------------
    # Tick principal
    # -----------------------------------------------------------------------

    def run(self) -> None:
        current_price = self._client.get_ticker(self._dca_config.symbol)
        if current_price == Decimal("0"):
            logger.warning("[{}] run() abortado: exchange no disponible", self.name)
            return

        if not self._state["is_in_position"]:
            if self.should_enter():
                self._place_base_order(current_price)
        else:
            if self.should_exit():
                self._close_position(current_price)
            elif self._should_place_safety_order(current_price):
                self._place_safety_order(current_price)

    # -----------------------------------------------------------------------
    # Acciones de trading
    # -----------------------------------------------------------------------

    def _place_base_order(self, current_price: Decimal) -> None:
        cfg = self._dca_config
        size = (cfg.base_order_size / current_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        ok, reason = self.check_risk(cfg.symbol, cfg.base_order_size)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        result = self._client.place_order(cfg.symbol, "buy", "market", size, strategy=self.name)
        if result.status == "filled" and result.filled_price:
            self.log_trade(result)
            self._update_avg_entry(result.filled_qty, result.filled_price)
            self._state["is_in_position"] = True
            self._state["last_base_order_at"] = self._client.current_time().isoformat()
            self._save_state()
            logger.info("[{}] Orden base ejecutada: {} @ {}", self.name, size, result.filled_price)

    def _place_safety_order(self, current_price: Decimal) -> None:
        cfg = self._dca_config
        n = self._state["safety_orders_count"]
        order_usdt = cfg.safety_order_size * (cfg.safety_order_volume_scale ** n)
        size = (order_usdt / current_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        ok, reason = self.check_risk(cfg.symbol, order_usdt)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        result = self._client.place_order(cfg.symbol, "buy", "market", size, strategy=self.name)
        if result.status == "filled" and result.filled_price:
            self.log_trade(result)
            self._update_avg_entry(result.filled_qty, result.filled_price)
            self._state["safety_orders_count"] = n + 1
            self._save_state()
            logger.info("[{}] Safety order #{} ejecutada: {} @ {}", self.name, n + 1, size, result.filled_price)

    def _close_position(self, current_price: Decimal) -> None:
        total_qty = Decimal(self._state["total_quantity"])
        avg_price = Decimal(self._state["avg_entry_price"])

        if total_qty <= Decimal("0"):
            self._reset_state()
            return

        result = self._client.place_order(
            self._dca_config.symbol, "sell", "market", total_qty, strategy=self.name
        )
        if result.status == "filled" and result.filled_price:
            pnl = (result.filled_price - avg_price) * result.filled_qty - result.fee
            self.log_trade(result, pnl=pnl)
            logger.info(
                "[{}] Posición cerrada: {} {} vendidos @ {} | PnL = {:.4f} USDT",
                self.name, total_qty, self._dca_config.symbol.split("-")[0],
                result.filled_price, pnl,
            )
            self._reset_state()

    # -----------------------------------------------------------------------
    # Helpers de estado
    # -----------------------------------------------------------------------

    def _update_avg_entry(self, qty: Decimal, price: Decimal) -> None:
        """Actualiza precio medio, cantidad total e inversión total."""
        prev_qty = Decimal(self._state["total_quantity"])
        prev_invested = Decimal(self._state["total_invested"])
        new_invested = prev_invested + qty * price
        new_qty = prev_qty + qty
        self._state["total_quantity"] = str(new_qty)
        self._state["total_invested"] = str(new_invested)
        self._state["avg_entry_price"] = str(new_invested / new_qty) if new_qty > 0 else "0"

    def _reset_state(self) -> None:
        self._state.update({
            "is_in_position": False,
            "avg_entry_price": "0",
            "total_quantity": "0",
            "total_invested": "0",
            "safety_orders_count": 0,
        })
        self._save_state()

    # -----------------------------------------------------------------------
    # Propiedades útiles para el dashboard
    # -----------------------------------------------------------------------

    @property
    def avg_entry_price(self) -> Decimal:
        return Decimal(self._state.get("avg_entry_price", "0"))

    @property
    def total_quantity(self) -> Decimal:
        return Decimal(self._state.get("total_quantity", "0"))

    @property
    def safety_orders_count(self) -> int:
        return int(self._state.get("safety_orders_count", 0))

    @property
    def is_in_position(self) -> bool:
        return bool(self._state.get("is_in_position", False))
