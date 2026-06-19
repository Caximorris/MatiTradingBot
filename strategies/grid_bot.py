"""
Grid Trading Bot.

Divide el rango [lower_price, upper_price] en num_grids intervalos.
En cada intervalo coloca una orden limit de compra en el límite inferior.
Cuando una compra se ejecuta en nivel N → coloca venta en nivel N+1.
Cuando una venta se ejecuta en nivel N → coloca compra en nivel N-1.
El estado del grid sobrevive reinicios gracias a BotState en SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from core.database import get_or_create_bot_state, set_bot_active
from core.exchange import OKXClient, OrderResult
from strategies.base_strategy import BaseStrategy

if TYPE_CHECKING:
    from core.risk_manager import RiskManager


@dataclass
class GridConfig:
    symbol: str
    upper_price: Decimal
    lower_price: Decimal
    num_grids: int
    total_investment: Decimal
    auto_adjust: bool = True

    def __post_init__(self) -> None:
        if self.upper_price <= self.lower_price:
            raise ValueError("upper_price debe ser mayor que lower_price")
        if self.num_grids < 2:
            raise ValueError("num_grids debe ser al menos 2")
        if self.total_investment <= Decimal("0"):
            raise ValueError("total_investment debe ser positivo")

    @classmethod
    def from_dict(cls, d: dict) -> "GridConfig":
        return cls(
            symbol=d["symbol"],
            upper_price=Decimal(str(d["upper_price"])),
            lower_price=Decimal(str(d["lower_price"])),
            num_grids=int(d["num_grids"]),
            total_investment=Decimal(str(d["total_investment"])),
            auto_adjust=bool(d.get("auto_adjust", True)),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "upper_price": str(self.upper_price),
            "lower_price": str(self.lower_price),
            "num_grids": self.num_grids,
            "total_investment": str(self.total_investment),
            "auto_adjust": self.auto_adjust,
        }


class GridBot(BaseStrategy):
    """
    Grid Trading Bot clásico.

    Estado persistido en BotState.config_json:
    {
        "levels": ["60000", "62000", ...],   # N+1 niveles de precio
        "order_size_base": "0.0161",          # unidades de base currency por orden
        "active_orders": {                    # precio_str → datos de la orden
            "60000": {"order_id": "...", "side": "buy", "level_idx": 0},
            ...
        },
        ... (+ campos de GridConfig)
    }
    """

    def __init__(
        self,
        client: OKXClient,
        config: dict | GridConfig,
        session: Session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        cfg = GridConfig.from_dict(config) if isinstance(config, dict) else config
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._grid_config = cfg
        self._state = self._load_state()

    @property
    def name(self) -> str:
        sym = self._grid_config.symbol.lower().replace("-", "_")
        return f"grid_{sym}"

    # -----------------------------------------------------------------------
    # Persistencia de estado
    # -----------------------------------------------------------------------

    def _load_state(self) -> dict:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="grid",
            symbol=self._grid_config.symbol,
            config=self._grid_config.to_dict(),
        )
        saved = bot_state.get_config()
        if "levels" in saved and saved["levels"]:
            return saved
        return {
            **self._grid_config.to_dict(),
            "levels": [],
            "order_size_base": "0",
            "active_orders": {},
        }

    def _save_state(self) -> None:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="grid",
            symbol=self._grid_config.symbol,
        )
        bot_state.set_config(self._state)

    # -----------------------------------------------------------------------
    # Cálculos del grid
    # -----------------------------------------------------------------------

    def _calculate_levels(self) -> list[Decimal]:
        cfg = self._grid_config
        step = (cfg.upper_price - cfg.lower_price) / cfg.num_grids
        return [cfg.lower_price + step * i for i in range(cfg.num_grids + 1)]

    def _calculate_order_size(self, levels: list[Decimal]) -> Decimal:
        """Tamaño en base currency para cada nivel (inversión uniforme por grid)."""
        cfg = self._grid_config
        usdt_per_grid = cfg.total_investment / cfg.num_grids
        avg_price = sum(levels) / len(levels)
        size = usdt_per_grid / avg_price
        return size.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    # -----------------------------------------------------------------------
    # Setup inicial
    # -----------------------------------------------------------------------

    def setup_grid(self) -> None:
        """
        Calcula niveles y coloca órdenes limit iniciales.
        - Niveles por debajo del precio actual → órdenes de compra
        - Niveles por encima del precio actual → órdenes de venta
          (requiere tener inventario; en paper mode se asume disponible)

        Es seguro llamarlo múltiples veces: si ya hay órdenes activas no hace nada.
        """
        if self._state.get("active_orders"):
            logger.info("[{}] Grid ya activo con {} órdenes", self.name,
                        len(self._state["active_orders"]))
            return

        current_price = self._client.get_ticker(self._grid_config.symbol)
        if current_price == Decimal("0"):
            logger.warning("[{}] setup_grid abortado: no se pudo obtener precio", self.name)
            return

        levels = self._calculate_levels()
        order_size = self._calculate_order_size(levels)

        self._state["levels"] = [str(lv) for lv in levels]
        self._state["order_size_base"] = str(order_size)
        self._state["active_orders"] = {}

        logger.info("[{}] Configurando grid: {} niveles de {} a {}, {} {} por orden",
                    self.name, len(levels), levels[0], levels[-1],
                    order_size, self._grid_config.symbol.split("-")[0])

        for idx, level in enumerate(levels[:-1]):
            side = "buy" if level < current_price else "sell"
            ok, reason = self.check_risk(self._grid_config.symbol, order_size * level)
            if not ok:
                self._log_risk_block(self._grid_config.symbol, reason)
                continue

            result = self._client.place_order(
                symbol=self._grid_config.symbol,
                side=side,
                order_type="limit",
                size=order_size,
                price=level,
                strategy=self.name,
            )
            if result.status in ("open", "filled"):
                self._state["active_orders"][str(level)] = {
                    "order_id": result.order_id,
                    "side": side,
                    "level_idx": idx,
                }
                if result.status == "filled":
                    self.log_trade(result)

        self._save_state()
        set_bot_active(self._session, "grid", self._grid_config.symbol, active=True)
        logger.info("[{}] Grid inicializado — {} órdenes colocadas",
                    self.name, len(self._state["active_orders"]))

    # -----------------------------------------------------------------------
    # Tick principal
    # -----------------------------------------------------------------------

    def run(self) -> None:
        """
        Tick del grid:
        1. Verifica si el precio salió del rango (auto_adjust o warning)
        2. En paper mode activa los fills pendientes
        3. Por cada fill coloca la orden contraria
        """
        cfg = self._grid_config
        current_price = self._client.get_ticker(cfg.symbol)
        if current_price == Decimal("0"):
            logger.warning("[{}] run() abortado: exchange no disponible", self.name)
            return

        # Precio fuera de rango
        out_of_range = current_price < cfg.lower_price or current_price > cfg.upper_price
        if out_of_range:
            if cfg.auto_adjust:
                logger.info("[{}] Precio {} fuera de rango — reiniciando grid", self.name, current_price)
                self._cancel_all_orders()
                self.setup_grid()
            else:
                logger.warning("[{}] Precio {} fuera de rango [{}, {}]",
                               self.name, current_price, cfg.lower_price, cfg.upper_price)
            return

        # Verificar fills en paper mode
        if self._client.is_paper:
            filled = self._client.fill_paper_limit_orders(cfg.symbol, current_price)
            for order in filled:
                self._on_order_filled(order)

    def _on_order_filled(self, filled: OrderResult) -> None:
        """Procesa un fill: registra el trade y coloca la orden contraria."""
        self.log_trade(filled)
        levels = [Decimal(lv) for lv in self._state.get("levels", [])]
        if not levels or filled.limit_price is None:
            return

        filled_level = min(levels, key=lambda lv: abs(lv - filled.limit_price))
        idx = levels.index(filled_level)
        order_size = Decimal(self._state.get("order_size_base", "0"))

        if filled.side == "buy" and idx + 1 < len(levels):
            next_level = levels[idx + 1]
            self._place_counter_order("sell", next_level, order_size, idx + 1)
        elif filled.side == "sell" and idx - 1 >= 0:
            prev_level = levels[idx - 1]
            self._place_counter_order("buy", prev_level, order_size, idx - 1)

        self._state["active_orders"].pop(str(filled_level), None)
        self._save_state()

    def _place_counter_order(
        self, side: str, price: Decimal, size: Decimal, level_idx: int
    ) -> None:
        result = self._client.place_order(
            symbol=self._grid_config.symbol,
            side=side,
            order_type="limit",
            size=size,
            price=price,
            strategy=self.name,
        )
        if result.status in ("open", "filled"):
            self._state["active_orders"][str(price)] = {
                "order_id": result.order_id,
                "side": side,
                "level_idx": level_idx,
            }
            logger.info("[{}] Counter-order {} @ {} colocada", self.name, side, price)
            if result.status == "filled":
                self.log_trade(result)

    def _cancel_all_orders(self) -> None:
        for level_key, info in list(self._state["active_orders"].items()):
            oid = info.get("order_id", "")
            if oid:
                self._client.cancel_order(oid, self._grid_config.symbol)
        self._state["active_orders"] = {}

    # -----------------------------------------------------------------------
    # Señales abstractas
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        """True si el precio está dentro del rango del grid."""
        price = self._client.get_ticker(self._grid_config.symbol)
        return self._grid_config.lower_price <= price <= self._grid_config.upper_price

    def should_exit(self) -> bool:
        """True si el precio salió del rango y auto_adjust está desactivado."""
        price = self._client.get_ticker(self._grid_config.symbol)
        out = price < self._grid_config.lower_price or price > self._grid_config.upper_price
        return out and not self._grid_config.auto_adjust
