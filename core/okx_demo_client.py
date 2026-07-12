"""Cliente hibrido para el paper trading sobre la cuenta DEMO real de OKX.

Objetivo (pre-live septiembre 2026): ejercitar por primera vez el camino de ordenes
AUTENTICADO real de OKX (firma, params, errores) sin dinero real y SIN romper la paridad
F15 de los bots paper existentes.

Diseño hibrido — la parte critica:
  - MARKET DATA (ticker/velas): cuenta REAL, flag="0". Mismo feed que v5/v6/legacy.
    Medido 2026-07-11: el feed demo tiene high/low inflados $80-250 por vela 1H — usarlo
    para señales romperia la paridad con el backtest (CLAUDE.md / deploy-paper.md).
  - ORDENES/BALANCE/POSICIONES: TradeAPI/AccountAPI con header x-simulated-trading:1
    (flag="1") y credenciales DEMO. Las ordenes llegan a OKX de verdad y se ejecutan
    contra la cuenta de demo trading.

Credenciales: OKX_DEMO_API_KEY/SECRET/PASSPHRASE en .env. OJO: OKX exige una API key
creada DENTRO del modo demo trading (perfil -> demo trading -> API); una key de la cuenta
real devuelve error 50119 con flag="1".

Composicion, no herencia de OKXClient: cada metodo de este cliente es explicito para que
el camino "primera vez contra la API real" sea auditable linea a linea, sin ramas paper
heredadas que sorprendan. El market data se delega a un OKXClient interno en modo paper
(que solo construye MarketAPI, jamas envia ordenes).

is_paper=True a proposito: no es dinero real, y asi TradeLogger/reportes lo mantienen
fuera de los filtros "live". La distincion demo-vs-paper-local viaja en el strategy_name.

Espejo de balances: tras cada get_balance se escribe data/runtime/paper_state_<id>.json
(solo "balances", formato identico al paper local) para que la observabilidad existente
(Telegram /status, paper-status, anomaly-check) funcione sin cambios. Es un ESPEJO
read-only del estado en OKX, no la fuente de verdad — editarlo no cambia nada.

Nota de correctitud (hallazgo 2026-07-11, revisar OKXClient._live_place_order antes de
live): en OKX spot, una orden MARKET BUY interpreta `sz` como moneda QUOTE (USDT) por
defecto (tgtCcy=quote_ccy). Las estrategias pasan qty en BASE (BTC). Aqui se fija
tgtCcy="base_ccy" en toda orden market; sin eso, una compra de "0.05" seria 0.05 USDT,
no 0.05 BTC.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import Settings
from core.exchange import (
    ExchangeError,
    ExchangeUnavailable,
    OKXClient,
    OrderResult,
    _RateLimiter,
    _RATE_MAX_REQUESTS,
    _RATE_WINDOW_SECONDS,
    _with_retry,
)

# Espera unica antes de consultar el fill de una orden market (se ejecutan al instante en
# OKX; esto solo da margen a la consistencia del endpoint de consulta).
_FILL_QUERY_DELAY_S = 0.3


class OKXDemoClient:
    """Interfaz identica a OKXClient: data real (flag=0) + ejecucion demo (flag=1)."""

    def __init__(
        self,
        settings: Settings,
        mirror_name: str = "okx_demo",
        runtime_dir: Path | None = None,
        _trade_api: Any = None,
        _account_api: Any = None,
        _market_client: Any = None,
    ) -> None:
        if not settings.is_paper:
            raise EnvironmentError(
                "OKXDemoClient solo se instancia con TRADING_MODE=paper: en modo live "
                "un bot marcado execution=okx_demo seria ambiguo (¿demo o real?)."
            )
        missing = [
            name for name, val in [
                ("OKX_DEMO_API_KEY", settings.okx_demo_api_key),
                ("OKX_DEMO_SECRET_KEY", settings.okx_demo_secret_key),
                ("OKX_DEMO_PASSPHRASE", settings.okx_demo_passphrase),
            ] if not val
        ]
        if missing:
            raise EnvironmentError(
                f"Credenciales demo ausentes en .env: {', '.join(missing)}. "
                "Crear la API key DENTRO del modo demo trading de OKX."
            )

        self._settings = settings
        self._rate = _RateLimiter(_RATE_MAX_REQUESTS, _RATE_WINDOW_SECONDS)

        # Market data: OKXClient en modo paper = solo MarketAPI publica, flag segun
        # OKX_SANDBOX (false en la VM => datos reales). Nunca envia ordenes.
        self._md = _market_client if _market_client is not None else OKXClient(settings)

        if _trade_api is not None or _account_api is not None:
            self._trade_api = _trade_api
            self._account_api = _account_api
        else:
            from okx.Account import AccountAPI  # type: ignore[import]
            from okx.Trade import TradeAPI      # type: ignore[import]
            self._trade_api = TradeAPI(
                settings.okx_demo_api_key,
                settings.okx_demo_secret_key,
                settings.okx_demo_passphrase,
                False,
                "1",            # x-simulated-trading: 1 -> demo trading
                debug=False,
            )
            self._account_api = AccountAPI(
                settings.okx_demo_api_key,
                settings.okx_demo_secret_key,
                settings.okx_demo_passphrase,
                False,
                "1",
                debug=False,
            )

        safe = OKXClient._safe_state_name(mirror_name)
        base_dir = runtime_dir if runtime_dir is not None else Path("data") / "runtime"
        self._mirror_path = base_dir / f"paper_state_{safe}.json"

        logger.info("OKXDemoClient inicializado — data=real(flag=0) ordenes=demo(flag=1) "
                    "espejo={}", self._mirror_path)
        # Primer sync: valida credenciales al arrancar (fail-fast en el start, no en el
        # primer rebalanceo dias despues) y deja el espejo escrito para /status.
        bal = self.get_balance()
        if not bal:
            raise ExchangeUnavailable(
                "get_balance() demo devolvio vacio al arrancar: credenciales demo "
                "invalidas, sin permisos de trade, o cuenta demo sin fondos."
            )

    # ------------------------------------------------------------------
    # Plumbing compartido
    # ------------------------------------------------------------------

    def _call_api(self, method, *args, **kwargs) -> dict:
        @_with_retry
        def _inner():
            self._rate.acquire()
            try:
                resp = method(*args, **kwargs)
            except ExchangeError:
                raise
            except Exception as exc:
                raise ExchangeUnavailable(str(exc)) from exc
            if resp.get("code") != "0":
                raise ExchangeError(
                    f"OKX demo error code={resp.get('code')}: {resp.get('msg', 'desconocido')}"
                )
            return resp

        return _inner()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def current_time(self) -> datetime:
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Market data — delegado al feed REAL (paridad con v5/v6/legacy)
    # ------------------------------------------------------------------

    def get_ticker(self, symbol: str) -> Decimal:
        return self._md.get_ticker(symbol)

    def get_ohlcv(self, symbol: str, timeframe: str = "1H", limit: int = 100):
        return self._md.get_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def get_funding_rate(self, symbol: str) -> float:
        return self._md.get_funding_rate(symbol)

    # ------------------------------------------------------------------
    # Cuenta demo — API autenticada real
    # ------------------------------------------------------------------

    def get_balance(self) -> dict[str, Decimal]:
        try:
            resp = self._call_api(self._account_api.get_account_balance)
            result: dict[str, Decimal] = {}
            for detail in resp["data"][0].get("details", []):
                avail = detail.get("availEq") or detail.get("availBal", "0")
                result[detail["ccy"]] = Decimal(str(avail))
            self._write_mirror(result)
            return result
        except Exception as exc:
            logger.warning("[DEMO] get_balance() fallo: {}", exc)
            return {}

    def get_positions(self) -> list[dict]:
        try:
            resp = self._call_api(self._account_api.get_positions)
            return resp.get("data", [])
        except Exception as exc:
            logger.warning("[DEMO] get_positions() fallo: {}", exc)
            return []

    def get_open_orders(self, symbol: str) -> list[dict]:
        try:
            resp = self._call_api(self._trade_api.get_order_list, instId=symbol)
            return resp.get("data", [])
        except Exception as exc:
            logger.warning("[DEMO] get_open_orders({}) fallo: {}", symbol, exc)
            return []

    def get_order_history(self, symbol: str, limit: int = 100) -> list[dict]:
        try:
            resp = self._call_api(
                self._trade_api.get_orders_history,
                instType="SPOT", instId=symbol, limit=str(limit),
            )
            return resp.get("data", [])
        except Exception as exc:
            logger.warning("[DEMO] get_order_history({}) fallo: {}", symbol, exc)
            return []

    # ------------------------------------------------------------------
    # Ordenes — el camino que nunca se habia ejercitado
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: Decimal,
        price: Decimal | None = None,
        strategy: str = "",
    ) -> OrderResult:
        _, quote_ccy = symbol.split("-")

        def _rejected(msg: str) -> OrderResult:
            return OrderResult(
                order_id="", symbol=symbol, side=side, order_type=order_type,
                size=size, limit_price=price, filled_price=None,
                filled_qty=Decimal("0"), fee=Decimal("0"), fee_currency=quote_ccy,
                status="rejected", is_paper=True, strategy=strategy,
                timestamp=self._utcnow(), error=msg,
            )

        params: dict[str, Any] = {
            "instId": symbol,
            "tdMode": "cash",
            "side": side,
            "ordType": order_type,
            "sz": str(size),
        }
        if order_type == "market":
            # sz en moneda BASE siempre. Sin esto, un market BUY spot interpreta sz como
            # USDT (default de OKX: tgtCcy=quote_ccy) y compra ~64000x menos BTC.
            params["tgtCcy"] = "base_ccy"
        elif order_type == "limit" and price is not None:
            params["px"] = str(price)

        try:
            resp = self._call_api(self._trade_api.place_order, **params)
        except (ExchangeError, ExchangeUnavailable) as exc:
            logger.warning("[DEMO] place_order {} {} {} fallo: {}", side, size, symbol, exc)
            return _rejected(str(exc))

        data = resp["data"][0]
        # code=0 global no garantiza aceptacion por item: sCode va por orden.
        if str(data.get("sCode", "0")) != "0":
            msg = data.get("sMsg", "rechazada por OKX")
            logger.warning("[DEMO] Orden rechazada sCode={}: {}", data.get("sCode"), msg)
            return _rejected(msg)

        order_id = data["ordId"]
        filled_price: Decimal | None = price if order_type == "limit" else None
        filled_qty = size if order_type == "market" else Decimal("0")
        fee = Decimal("0")
        fee_ccy = quote_ccy
        status = "open" if order_type == "limit" else "filled"

        if order_type == "market":
            fill = self._query_fill(symbol, order_id)
            if fill is not None:
                filled_price, filled_qty, fee, fee_ccy = fill

        result = OrderResult(
            order_id=order_id, symbol=symbol, side=side, order_type=order_type,
            size=size, limit_price=price, filled_price=filled_price,
            filled_qty=filled_qty, fee=fee, fee_currency=fee_ccy,
            status=status, is_paper=True, strategy=strategy, timestamp=self._utcnow(),
        )
        logger.info("[DEMO] {} {} {} {} @ {} (id={}, fee={} {})",
                    status.upper(), side, size, symbol,
                    filled_price if filled_price is not None else "mkt",
                    order_id, fee, fee_ccy)
        # El balance en OKX ya cambio; refrescar el espejo para /status.
        self.get_balance()
        return result

    def _query_fill(self, symbol: str, order_id: str):
        """(fillPx, fillQty, fee, feeCcy) de una orden ya enviada. None si no se pudo."""
        try:
            time.sleep(_FILL_QUERY_DELAY_S)
            resp = self._call_api(self._trade_api.get_order, instId=symbol, ordId=order_id)
            d = resp["data"][0]
            px = d.get("avgPx") or d.get("fillPx")
            qty = d.get("accFillSz") or d.get("fillSz")
            if not px or not qty:
                return None
            fee = abs(Decimal(str(d.get("fee") or "0")))   # OKX reporta fee en negativo
            fee_ccy = d.get("feeCcy") or symbol.split("-")[1]
            return Decimal(str(px)), Decimal(str(qty)), fee, fee_ccy
        except Exception as exc:
            logger.warning("[DEMO] consulta de fill {} fallo (no critico): {}", order_id, exc)
            return None

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            self._call_api(self._trade_api.cancel_order, instId=symbol, ordId=order_id)
            return True
        except Exception as exc:
            logger.warning("[DEMO] cancel_order({}) fallo: {}", order_id, exc)
            return False

    # ------------------------------------------------------------------
    # Compatibilidad de interfaz con OKXClient (ramas paper: no aplican aqui)
    # ------------------------------------------------------------------

    def adjust_balance(self, currency: str, delta: Decimal) -> None:
        """No-op: el balance vive en OKX, no en un dict local."""

    def fill_paper_limit_orders(self, symbol: str, current_price: Decimal) -> list:
        """No-op: los fills de limit los hace el matching engine demo de OKX."""
        return []

    def get_paper_orders(self) -> dict:
        return {}

    # ------------------------------------------------------------------
    # Espejo de balances para la observabilidad existente
    # ------------------------------------------------------------------

    def _write_mirror(self, balances: dict[str, Decimal]) -> None:
        try:
            self._mirror_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "balances": {k: str(v) for k, v in balances.items()},
                "updated_at": self._utcnow().isoformat(),
                "mirror_of": "okx_demo_trading",   # espejo read-only, NO fuente de verdad
            }
            self._mirror_path.write_text(json.dumps(payload, ensure_ascii=True),
                                         encoding="utf-8")
        except Exception as exc:
            logger.warning("[DEMO] no se pudo escribir espejo {}: {}", self._mirror_path, exc)

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def is_paper(self) -> bool:
        # True a proposito: no es dinero real. Los trades quedan tagueados paper en DB
        # y fuera de los reportes live. Ver docstring del modulo.
        return True

    @property
    def is_available(self) -> bool:
        return self._md.is_available
