"""
Mean Reversion Bot para altcoins.

Señal de entrada:
  - Precio toca la banda inferior de Bollinger Bands (BB)
  - RSI por debajo del umbral de sobreventa
  - Volumen de la vela actual > media × volume_multiplier

Señal de salida:
  - Precio toca la banda superior de Bollinger Bands, O
  - RSI por encima del umbral de sobrecompra, O
  - Precio cae por debajo del stop loss calculado en la entrada

Indicadores: pandas-ta (instalación opcional; si no está disponible la estrategia
se desactiva con un warning claro).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy.orm import Session

from core.database import get_or_create_bot_state, set_bot_active, upsert_position, close_position
from core.exchange import OKXClient
from strategies.base_strategy import BaseStrategy

if TYPE_CHECKING:
    from core.risk_manager import RiskManager

try:
    import pandas_ta as ta  # type: ignore[import]
    _TA_AVAILABLE = True
except ImportError:
    _TA_AVAILABLE = False
    logger.warning("pandas-ta no instalado — MeanReversionBot no operará")


@dataclass
class MeanReversionConfig:
    symbol: str
    timeframe: str = "4H"
    bb_period: int = 20
    bb_std: Decimal = Decimal("2.0")
    rsi_period: int = 14
    rsi_oversold: Decimal = Decimal("35")
    rsi_overbought: Decimal = Decimal("65")
    volume_multiplier: Decimal = Decimal("1.0")
    stop_loss_pct: Decimal = Decimal("3.0")   # % por debajo del precio de entrada

    def __post_init__(self) -> None:
        if self.bb_period < 2:
            raise ValueError("bb_period debe ser >= 2")
        if not (0 < float(self.rsi_oversold) < float(self.rsi_overbought) < 100):
            raise ValueError("rsi_oversold y rsi_overbought deben ser 0 < os < ob < 100")

    @classmethod
    def from_dict(cls, d: dict) -> "MeanReversionConfig":
        return cls(
            symbol=d["symbol"],
            timeframe=d.get("timeframe", "4H"),
            bb_period=int(d.get("bb_period", 20)),
            bb_std=Decimal(str(d.get("bb_std", "2.0"))),
            rsi_period=int(d.get("rsi_period", 14)),
            rsi_oversold=Decimal(str(d.get("rsi_oversold", "35"))),
            rsi_overbought=Decimal(str(d.get("rsi_overbought", "65"))),
            volume_multiplier=Decimal(str(d.get("volume_multiplier", "1.0"))),
            stop_loss_pct=Decimal(str(d.get("stop_loss_pct", "3.0"))),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bb_period": self.bb_period,
            "bb_std": str(self.bb_std),
            "rsi_period": self.rsi_period,
            "rsi_oversold": str(self.rsi_oversold),
            "rsi_overbought": str(self.rsi_overbought),
            "volume_multiplier": str(self.volume_multiplier),
            "stop_loss_pct": str(self.stop_loss_pct),
        }


class MeanReversionBot(BaseStrategy):
    """
    Mean Reversion usando Bollinger Bands + RSI + filtro de volumen.

    Estado en BotState.config_json:
    {
        "is_in_position": false,
        "entry_price": "0",
        "stop_loss_price": "0",
        "position_qty": "0"
    }
    """

    def __init__(
        self,
        client: OKXClient,
        config: dict | MeanReversionConfig,
        session: Session,
        risk_manager: "RiskManager | None" = None,
    ) -> None:
        cfg = MeanReversionConfig.from_dict(config) if isinstance(config, dict) else config
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._mr_config = cfg
        self._state = self._load_state()
        self._last_indicators: dict[str, Any] = {}

    @property
    def name(self) -> str:
        sym = self._mr_config.symbol.lower().replace("-", "_")
        return f"mean_reversion_{sym}"

    # -----------------------------------------------------------------------
    # Persistencia
    # -----------------------------------------------------------------------

    def _load_state(self) -> dict:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="mean_reversion",
            symbol=self._mr_config.symbol,
            config=self._mr_config.to_dict(),
        )
        saved = bot_state.get_config()
        defaults = {
            "is_in_position": False,
            "entry_price": "0",
            "stop_loss_price": "0",
            "position_qty": "0",
        }
        return {**defaults, **saved}

    def _save_state(self) -> None:
        bot_state = get_or_create_bot_state(
            self._session,
            strategy_name="mean_reversion",
            symbol=self._mr_config.symbol,
        )
        bot_state.set_config(self._state)

    # -----------------------------------------------------------------------
    # Cálculo de indicadores
    # -----------------------------------------------------------------------

    def _fetch_indicators(self) -> bool:
        """
        Descarga OHLCV y calcula BB + RSI.
        Guarda los resultados en self._last_indicators.
        Retorna False si no hay datos suficientes o pandas-ta no está disponible.
        """
        if not _TA_AVAILABLE:
            return False

        cfg = self._mr_config
        min_candles = max(cfg.bb_period, cfg.rsi_period) + 5
        df = self._client.get_ohlcv(cfg.symbol, timeframe=cfg.timeframe, limit=min_candles + 10)

        if df is None or len(df) < min_candles:
            logger.warning("[{}] Datos insuficientes para calcular indicadores ({} velas)",
                           self.name, len(df) if df is not None else 0)
            return False

        try:
            bb = df.ta.bbands(length=cfg.bb_period, std=float(cfg.bb_std), append=False)
            rsi_series = df.ta.rsi(length=cfg.rsi_period, append=False)
        except Exception as exc:
            logger.warning("[{}] Error calculando indicadores: {}", self.name, exc)
            return False

        if bb is None or rsi_series is None:
            return False

        last = df.iloc[-1]
        bb_last = bb.iloc[-1]

        lower_col = f"BBL_{cfg.bb_period}_{float(cfg.bb_std)}"
        upper_col = f"BBU_{cfg.bb_period}_{float(cfg.bb_std)}"
        std_col   = f"BBB_{cfg.bb_period}_{float(cfg.bb_std)}"

        volume_mean = df["volume"].iloc[-(cfg.bb_period):].mean()

        self._last_indicators = {
            "close": Decimal(str(last["close"])),
            "volume": float(last["volume"]),
            "volume_mean": float(volume_mean),
            "bb_lower": Decimal(str(bb_last.get(lower_col, 0))),
            "bb_upper": Decimal(str(bb_last.get(upper_col, 0))),
            "bb_std_val": float(bb_last.get(std_col, 0)),
            "rsi": float(rsi_series.iloc[-1]),
        }
        return True

    # -----------------------------------------------------------------------
    # Señales
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        """
        True si:
        - Precio <= BB inferior
        - RSI < rsi_oversold
        - Volumen actual >= media × volume_multiplier
        """
        if self._state["is_in_position"]:
            return False
        ind = self._last_indicators
        if not ind:
            return False
        cfg = self._mr_config
        price_signal = ind["close"] <= ind["bb_lower"]
        rsi_signal   = ind["rsi"] < float(cfg.rsi_oversold)
        volume_signal = ind["volume"] >= ind["volume_mean"] * float(cfg.volume_multiplier)
        return price_signal and rsi_signal and volume_signal

    def should_exit(self) -> bool:
        """
        True si (en posición):
        - Precio >= BB superior, O
        - RSI > rsi_overbought, O
        - Precio cayó por debajo del stop loss
        """
        if not self._state["is_in_position"]:
            return False
        ind = self._last_indicators
        if not ind:
            return False
        cfg = self._mr_config
        stop_loss = Decimal(self._state["stop_loss_price"])
        bb_exit  = ind["close"] >= ind["bb_upper"]
        rsi_exit = ind["rsi"] > float(cfg.rsi_overbought)
        sl_hit   = stop_loss > Decimal("0") and ind["close"] <= stop_loss
        return bb_exit or rsi_exit or sl_hit

    # -----------------------------------------------------------------------
    # Tick principal
    # -----------------------------------------------------------------------

    def run(self) -> None:
        if not _TA_AVAILABLE:
            return

        if not self._fetch_indicators():
            return

        current_price = self._last_indicators.get("close", Decimal("0"))
        if current_price == Decimal("0"):
            return

        if not self._state["is_in_position"] and self.should_enter():
            self._open_position(current_price)
        elif self._state["is_in_position"] and self.should_exit():
            self._close_position(current_price)

    # -----------------------------------------------------------------------
    # Acciones
    # -----------------------------------------------------------------------

    def _open_position(self, current_price: Decimal) -> None:
        cfg = self._mr_config
        stop_loss_price = current_price * (1 - cfg.stop_loss_pct / 100)

        # Tamaño: si hay risk_manager lo calcula; si no, usa base_order_size fijo de 100 USDT
        if self._risk_manager is not None:
            size_usdt = self._risk_manager.calculate_position_size(
                cfg.symbol,
                risk_pct=Decimal("1"),
                entry=current_price,
                stop_loss=stop_loss_price,
            ) * current_price
        else:
            size_usdt = Decimal("100")

        ok, reason = self.check_risk(cfg.symbol, size_usdt)
        if not ok:
            self._log_risk_block(cfg.symbol, reason)
            return

        qty = (size_usdt / current_price).quantize(Decimal("0.00000001"))
        result = self._client.place_order(cfg.symbol, "buy", "market", qty, strategy=self.name)

        if result.status == "filled" and result.filled_price:
            self.log_trade(result)
            self._state["is_in_position"] = True
            self._state["entry_price"] = str(result.filled_price)
            self._state["stop_loss_price"] = str(stop_loss_price)
            self._state["position_qty"] = str(result.filled_qty)
            self._save_state()

            upsert_position(
                self._session,
                symbol=cfg.symbol,
                strategy=self.name,
                side="long",
                entry_price=result.filled_price,
                quantity=result.filled_qty,
                current_price=result.filled_price,
                unrealized_pnl=Decimal("0"),
            )
            logger.info("[{}] Posición abierta @ {} | SL @ {}", self.name, result.filled_price, stop_loss_price)

    def _close_position(self, current_price: Decimal) -> None:
        qty = Decimal(self._state["position_qty"])
        entry = Decimal(self._state["entry_price"])
        if qty <= Decimal("0"):
            self._reset_state()
            return

        result = self._client.place_order(
            self._mr_config.symbol, "sell", "market", qty, strategy=self.name
        )
        if result.status == "filled" and result.filled_price:
            pnl = (result.filled_price - entry) * result.filled_qty - result.fee
            reason = self._exit_reason(result.filled_price, entry)
            self.log_trade(result, pnl=pnl, notes=reason)
            logger.info("[{}] Posición cerrada @ {} | PnL = {:.4f} USDT | Razón: {}",
                        self.name, result.filled_price, pnl, reason)
            close_position(self._session, self._mr_config.symbol, self.name)
            self._reset_state()

    def _exit_reason(self, current_price: Decimal, entry: Decimal) -> str:
        ind = self._last_indicators
        if current_price <= Decimal(self._state["stop_loss_price"]):
            return "stop_loss"
        if ind.get("rsi", 0) > float(self._mr_config.rsi_overbought):
            return "rsi_overbought"
        return "bb_upper_touch"

    def _reset_state(self) -> None:
        self._state.update({
            "is_in_position": False,
            "entry_price": "0",
            "stop_loss_price": "0",
            "position_qty": "0",
        })
        self._save_state()
