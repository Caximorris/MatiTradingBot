"""
Signal Follower — copytrading vía señales externas.

Fuente 1: TradingView Webhook (servidor HTTP aiohttp en WEBHOOK_PORT)
  Payload esperado:
  {
    "symbol": "BTC-USDT",
    "action": "buy" | "sell",
    "price": 65000,
    "strategy": "mi_estrategia_tv",
    "risk_pct": 1.0
  }

Fuente 2: Canal de Telegram
  Formato de mensaje esperado:
  🟢 BUY BTC-USDT
  Entry: 65000
  TP: 67000
  SL: 63500

Las señales entrantes se ponen en una cola thread-safe.
El método run() drena la cola y ejecuta las órdenes.
"""
from __future__ import annotations

import asyncio
import queue
import re
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy.orm import Session

from config.settings import Settings, settings as _global_settings
from core.exchange import OKXClient
from strategies.base_strategy import BaseStrategy

if TYPE_CHECKING:
    from core.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SignalConfig:
    source: str = "none"       # "none" | "tradingview_webhook" | "telegram"
    webhook_port: int = 8080
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    default_risk_pct: Decimal = Decimal("1.0")
    allowed_symbols: list[str] | None = None  # None = todos los pares configurados

    @classmethod
    def from_settings(cls, s: Settings) -> "SignalConfig":
        return cls(
            source=s.signal_source,
            webhook_port=s.webhook_port,
            telegram_bot_token=s.telegram_bot_token,
            telegram_channel_id=s.telegram_channel_id,
        )

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "webhook_port": self.webhook_port,
            "default_risk_pct": str(self.default_risk_pct),
        }


@dataclass
class Signal:
    symbol: str
    action: str          # "buy" | "sell"
    price: Decimal | None
    take_profit: Decimal | None
    stop_loss: Decimal | None
    risk_pct: Decimal
    source: str


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_webhook_payload(data: dict) -> Signal | None:
    """Valida y convierte el payload JSON de TradingView en un Signal."""
    try:
        action = data.get("action", "").lower()
        if action not in ("buy", "sell"):
            logger.warning("Webhook: campo 'action' inválido: {}", data.get("action"))
            return None
        symbol = str(data.get("symbol", "")).upper()
        if not symbol or "-" not in symbol:
            logger.warning("Webhook: símbolo inválido: {}", symbol)
            return None
        price_raw = data.get("price")
        price = Decimal(str(price_raw)) if price_raw is not None else None
        risk_pct = Decimal(str(data.get("risk_pct", "1.0")))
        return Signal(
            symbol=symbol,
            action=action,
            price=price,
            take_profit=None,
            stop_loss=None,
            risk_pct=risk_pct,
            source="tradingview_webhook",
        )
    except (InvalidOperation, KeyError, ValueError) as exc:
        logger.warning("Webhook: error parseando payload {}: {}", data, exc)
        return None


# Patrón para mensajes de Telegram tipo:
# 🟢 BUY BTC-USDT
# Entry: 65000
# TP: 67000
# SL: 63500
_TG_PATTERN = re.compile(
    r"(?:🟢|🔴|BUY|SELL)?\s*(?P<action>BUY|SELL)\s+(?P<symbol>[A-Z]+-[A-Z]+)"
    r".*?Entry:\s*(?P<entry>[\d.]+)"
    r"(?:.*?TP:\s*(?P<tp>[\d.]+))?"
    r"(?:.*?SL:\s*(?P<sl>[\d.]+))?",
    re.IGNORECASE | re.DOTALL,
)


def _parse_telegram_message(text: str, default_risk_pct: Decimal) -> Signal | None:
    """Extrae una señal de un mensaje de Telegram con formato estándar."""
    match = _TG_PATTERN.search(text)
    if not match:
        return None
    try:
        action = match.group("action").lower()
        symbol = match.group("symbol").upper()
        entry_raw = match.group("entry")
        tp_raw = match.group("tp")
        sl_raw = match.group("sl")

        price = Decimal(entry_raw) if entry_raw else None
        tp = Decimal(tp_raw) if tp_raw else None
        sl = Decimal(sl_raw) if sl_raw else None
        return Signal(
            symbol=symbol,
            action=action,
            price=price,
            take_profit=tp,
            stop_loss=sl,
            risk_pct=default_risk_pct,
            source="telegram",
        )
    except (InvalidOperation, AttributeError) as exc:
        logger.warning("Telegram: error parseando mensaje: {}", exc)
        return None


# ---------------------------------------------------------------------------
# SignalFollower Strategy
# ---------------------------------------------------------------------------

class SignalFollower(BaseStrategy):
    """
    Copytrading vía señales externas (TradingView webhook o canal de Telegram).

    Las señales se reciben en hilos de fondo y se encolan.
    El método run() las procesa y ejecuta las órdenes.
    """

    def __init__(
        self,
        client: OKXClient,
        config: dict | SignalConfig,
        session: Session,
        risk_manager: "RiskManager | None" = None,
        app_settings: Settings | None = None,
    ) -> None:
        cfg = SignalConfig.from_settings(app_settings or _global_settings) if isinstance(config, dict) and not config else (
            config if isinstance(config, SignalConfig) else SignalConfig(**config)
        )
        super().__init__(client, cfg.to_dict(), session, risk_manager)
        self._sig_config = cfg
        self._signal_queue: queue.Queue[Signal] = queue.Queue()
        self._bg_threads: list[threading.Thread] = []
        self._running = False
        self._pending_signal: Signal | None = None

    @property
    def name(self) -> str:
        return "signal_follower"

    # -----------------------------------------------------------------------
    # Inicio y parada de hilos de fondo
    # -----------------------------------------------------------------------

    def start_listeners(self) -> None:
        """Arranca los hilos de escucha según la fuente configurada."""
        if self._running:
            return
        self._running = True
        source = self._sig_config.source

        if source == "tradingview_webhook":
            t = threading.Thread(target=self._run_webhook_server, daemon=True, name="tv-webhook")
            t.start()
            self._bg_threads.append(t)
            logger.info("[{}] Servidor webhook arrancado en puerto {}", self.name, self._sig_config.webhook_port)

        elif source == "telegram":
            t = threading.Thread(target=self._run_telegram_listener, daemon=True, name="tg-listener")
            t.start()
            self._bg_threads.append(t)
            logger.info("[{}] Listener de Telegram arrancado", self.name)

        elif source == "none":
            logger.info("[{}] SIGNAL_SOURCE=none — sin listeners externos", self.name)

    def stop_listeners(self) -> None:
        self._running = False

    # -----------------------------------------------------------------------
    # TradingView Webhook (aiohttp)
    # -----------------------------------------------------------------------

    def _run_webhook_server(self) -> None:
        """Ejecuta el servidor aiohttp en un event loop propio."""
        try:
            import aiohttp
            from aiohttp import web
        except ImportError:
            logger.error("[{}] aiohttp no instalado — webhook no disponible", self.name)
            return

        async def handle_signal(request: web.Request) -> web.Response:
            try:
                data = await request.json()
            except Exception:
                return web.Response(status=400, text="JSON inválido")
            signal = _parse_webhook_payload(data)
            if signal is None:
                return web.Response(status=422, text="Payload inválido")
            self._signal_queue.put(signal)
            logger.info("[{}] Señal webhook recibida: {} {}", self.name, signal.action, signal.symbol)
            return web.Response(status=200, text="OK")

        async def run():
            app = web.Application()
            app.router.add_post("/signal", handle_signal)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", self._sig_config.webhook_port)
            await site.start()
            while self._running:
                await asyncio.sleep(1)
            await runner.cleanup()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
        except Exception as exc:
            logger.error("[{}] Error en servidor webhook: {}", self.name, exc)
        finally:
            loop.close()

    # -----------------------------------------------------------------------
    # Telegram listener (python-telegram-bot)
    # -----------------------------------------------------------------------

    def _run_telegram_listener(self) -> None:
        try:
            from telegram import Update
            from telegram.ext import Application, MessageHandler, filters
        except ImportError:
            logger.error("[{}] python-telegram-bot no instalado", self.name)
            return

        cfg = self._sig_config
        if not cfg.telegram_bot_token:
            logger.error("[{}] TELEGRAM_BOT_TOKEN no configurado", self.name)
            return

        async def message_handler(update: Update, context: Any) -> None:
            if update.message is None:
                return
            chat_id = str(update.message.chat_id)
            if cfg.telegram_channel_id and chat_id != cfg.telegram_channel_id:
                return
            text = update.message.text or ""
            signal = _parse_telegram_message(text, cfg.default_risk_pct)
            if signal:
                self._signal_queue.put(signal)
                logger.info("[{}] Señal Telegram recibida: {} {}", self.name, signal.action, signal.symbol)

        async def run_bot():
            app = Application.builder().token(cfg.telegram_bot_token).build()
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            while self._running:
                await asyncio.sleep(1)
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_bot())
        except Exception as exc:
            logger.error("[{}] Error en listener Telegram: {}", self.name, exc)
        finally:
            loop.close()

    # -----------------------------------------------------------------------
    # Tick principal — drena la cola y ejecuta señales
    # -----------------------------------------------------------------------

    def run(self) -> None:
        processed = 0
        while not self._signal_queue.empty():
            try:
                signal = self._signal_queue.get_nowait()
            except queue.Empty:
                break
            self._execute_signal(signal)
            processed += 1
        if processed:
            logger.info("[{}] {} señal(es) procesada(s) en este tick", self.name, processed)

    def _execute_signal(self, signal: Signal) -> None:
        """Valida la señal contra el risk manager y ejecuta la orden."""
        # Filtrar por símbolos permitidos
        allowed = self._sig_config.allowed_symbols
        if allowed is not None and signal.symbol not in allowed:
            logger.warning("[{}] Símbolo {} no permitido — señal ignorada", self.name, signal.symbol)
            return

        # Estimar tamaño de la orden
        current_price = signal.price or self._client.get_ticker(signal.symbol)
        if current_price == Decimal("0"):
            logger.warning("[{}] No se pudo obtener precio para {} — señal ignorada", self.name, signal.symbol)
            return

        if self._risk_manager is not None and signal.stop_loss:
            qty = self._risk_manager.calculate_position_size(
                symbol=signal.symbol,
                risk_pct=signal.risk_pct,
                entry=current_price,
                stop_loss=signal.stop_loss,
            )
            size_usdt = qty * current_price
        else:
            size_usdt = Decimal("100")  # fallback conservador
            qty = (size_usdt / current_price).quantize(Decimal("0.00000001"))

        if qty <= Decimal("0"):
            logger.warning("[{}] Cantidad calculada inválida para {}", self.name, signal.symbol)
            return

        ok, reason = self.check_risk(signal.symbol, size_usdt)
        if not ok:
            self._log_risk_block(signal.symbol, reason)
            return

        result = self._client.place_order(
            symbol=signal.symbol,
            side=signal.action,
            order_type="market",
            size=qty,
            strategy=f"signal_{signal.source}",
        )
        if result.status == "filled":
            self.log_trade(result, notes=f"source={signal.source}")
            logger.info(
                "[{}] {} {} {} @ {} (fuente={})",
                self.name, signal.action.upper(), qty, signal.symbol,
                result.filled_price, signal.source,
            )

    # -----------------------------------------------------------------------
    # Señales abstractas
    # -----------------------------------------------------------------------

    def should_enter(self) -> bool:
        """True si hay señales de compra pendientes en la cola."""
        return any(s.action == "buy" for s in list(self._signal_queue.queue))

    def should_exit(self) -> bool:
        """True si hay señales de venta pendientes en la cola."""
        return any(s.action == "sell" for s in list(self._signal_queue.queue))

    def inject_signal(self, signal: Signal) -> None:
        """Inserta una señal manualmente. Útil para tests y backtest."""
        self._signal_queue.put(signal)
