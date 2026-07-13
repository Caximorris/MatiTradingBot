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
        exec_quote: str | None = None,
        bridge_quote: str | None = None,
        _trade_api: Any = None,
        _account_api: Any = None,
        _market_client: Any = None,
    ) -> None:
        # Mapeo señal->ejecucion (cuentas EEA/MiCA, 2026-07-13): la estrategia opera
        # BTC-USDT (feed real, paridad con backtest) pero la cuenta europea NO puede
        # tradear USDT (sCode 51155). Con exec_quote="USDC" toda orden/consulta *-USDT
        # se traduce a *-USDC y el balance USDC se presenta como USDT a la estrategia.
        # USDC≈USDT≈USD: misma unidad de cuenta que el backtest. None = sin traduccion.
        self._exec_quote = exec_quote.upper() if exec_quote else None
        self._strategy_quote = "USDT"
        # Fallback 2-patas (2026-07-13): el book demo de BTC-USDC tiene los bids muertos
        # (por debajo de la banda de precio 51138) y el motor cancela los market SELL.
        # Con bridge_quote="EUR", una market cancelada por el motor se reintenta via
        # BTC<->EUR<->USDC (books demo EUR vivos). Solo afecta al entorno demo: en el
        # exchange real BTC-USDC es profundo y este codigo no se activa.
        self._bridge_quote = bridge_quote.upper() if bridge_quote else None
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
            # Cuentas de la entidad europea (MiCA) viven en https://my.okx.com: sus keys
            # devuelven 60032 contra www.okx.com. OKX_DEMO_DOMAIN selecciona la entidad.
            self._trade_api = TradeAPI(
                settings.okx_demo_api_key,
                settings.okx_demo_secret_key,
                settings.okx_demo_passphrase,
                False,
                "1",            # x-simulated-trading: 1 -> demo trading
                domain=settings.okx_demo_domain,
                debug=False,
            )
            self._account_api = AccountAPI(
                settings.okx_demo_api_key,
                settings.okx_demo_secret_key,
                settings.okx_demo_passphrase,
                False,
                "1",
                domain=settings.okx_demo_domain,
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

    def _exec_symbol(self, symbol: str) -> str:
        """Traduce el simbolo de la estrategia al de ejecucion (BTC-USDT -> BTC-USDC)."""
        if self._exec_quote:
            base, _, quote = symbol.rpartition("-")
            if quote == self._strategy_quote:
                return f"{base}-{self._exec_quote}"
        return symbol

    def _alias_ccy(self, ccy: str) -> str:
        """Presenta la quote de ejecucion con el nombre que espera la estrategia."""
        if self._exec_quote and ccy == self._exec_quote:
            return self._strategy_quote
        return ccy

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
                # El msg global ("All operations failed") no dice nada: el motivo real
                # viaja en data[i].sMsg (p.ej. "Insufficient balance").
                detail = "; ".join(
                    f"sCode={d.get('sCode')} {d.get('sMsg')}"
                    for d in resp.get("data", []) if d.get("sMsg")
                )
                raise ExchangeError(
                    f"OKX demo error code={resp.get('code')}: "
                    f"{detail or resp.get('msg', 'desconocido')}"
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
                # La quote de ejecucion (USDC) se presenta como USDT: la estrategia y la
                # observabilidad (/status) trabajan en el espacio de simbolos del backtest.
                result[self._alias_ccy(detail["ccy"])] = Decimal(str(avail))
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
            resp = self._call_api(self._trade_api.get_order_list,
                                  instId=self._exec_symbol(symbol))
            return resp.get("data", [])
        except Exception as exc:
            logger.warning("[DEMO] get_open_orders({}) fallo: {}", symbol, exc)
            return []

    def get_order_history(self, symbol: str, limit: int = 100) -> list[dict]:
        try:
            resp = self._call_api(
                self._trade_api.get_orders_history,
                instType="SPOT", instId=self._exec_symbol(symbol), limit=str(limit),
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
        # La orden viaja a OKX en el simbolo de EJECUCION (BTC-USDC en cuentas EEA);
        # el OrderResult vuelve en el simbolo de la ESTRATEGIA (BTC-USDT).
        exec_symbol = self._exec_symbol(symbol)
        if exec_symbol != symbol:
            logger.debug("[DEMO] orden {} enrutada como {}", symbol, exec_symbol)

        def _rejected(msg: str) -> OrderResult:
            return OrderResult(
                order_id="", symbol=symbol, side=side, order_type=order_type,
                size=size, limit_price=price, filled_price=None,
                filled_qty=Decimal("0"), fee=Decimal("0"), fee_currency=quote_ccy,
                status="rejected", is_paper=True, strategy=strategy,
                timestamp=self._utcnow(), error=msg,
            )

        params: dict[str, Any] = {
            "instId": exec_symbol,
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
            info = self._query_order(exec_symbol, order_id)
            if info is not None:
                state, px, qty, q_fee, q_fee_ccy = info
                if state in ("canceled", "mmp_canceled") and qty <= 0:
                    # El motor puede aceptar la orden (sCode=0) y cancelarla despues sin
                    # fill (visto en demo EEA 2026-07-13: book demo sin liquidez). Sin
                    # este check se reportaria un fill fantasma con la qty pedida.
                    logger.warning("[DEMO] market {} {} aceptada pero cancelada sin fill "
                                   "(state={})", side, symbol, state)
                    if self._bridge_quote:
                        bridged = self._bridge_market(symbol, side, size, strategy)
                        if bridged is not None:
                            return bridged
                    return _rejected(f"market order cancelada por el motor (state={state})")
                if qty > 0:
                    filled_qty, fee, fee_ccy = qty, q_fee, self._alias_ccy(q_fee_ccy)
                    if px is not None:
                        filled_price = px

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

    def _query_order(self, symbol: str, order_id: str):
        """(state, avgPx|None, accFillSz, fee, feeCcy) de una orden enviada.

        None si la consulta fallo (el caller conserva el default optimista: mejor un
        fill asumido que romper el bot por un endpoint lento).
        """
        try:
            time.sleep(_FILL_QUERY_DELAY_S)
            resp = self._call_api(self._trade_api.get_order, instId=symbol, ordId=order_id)
            d = resp["data"][0]
            state = d.get("state", "")
            px = d.get("avgPx") or d.get("fillPx")
            qty = d.get("accFillSz") or d.get("fillSz") or "0"
            fee = abs(Decimal(str(d.get("fee") or "0")))   # OKX reporta fee en negativo
            fee_ccy = d.get("feeCcy") or symbol.split("-")[1]
            return state, (Decimal(str(px)) if px else None), Decimal(str(qty)), fee, fee_ccy
        except Exception as exc:
            logger.warning("[DEMO] consulta de orden {} fallo (no critico): {}", order_id, exc)
            return None

    # ------------------------------------------------------------------
    # Fallback 2-patas via bridge (EUR) — solo entorno demo, ver __init__
    # ------------------------------------------------------------------

    def _bridge_leg(self, inst: str, side: str, sz: Decimal, tgt: str):
        """Una pata market del bridge. (avgPx, qty, fee, feeCcy) o None si no ejecuto."""
        try:
            resp = self._call_api(
                self._trade_api.place_order, instId=inst, tdMode="cash",
                side=side, ordType="market", sz=str(sz), tgtCcy=tgt,
            )
            d = resp["data"][0]
            if str(d.get("sCode", "0")) != "0":
                logger.warning("[DEMO-BRIDGE] pata {} {} sz={} rechazada: {}",
                               side, inst, sz, d.get("sMsg"))
                return None
            info = self._query_order(inst, d["ordId"])
            if info is None:
                return None
            state, px, qty, fee, fee_ccy = info
            if qty <= 0 or px is None:
                logger.warning("[DEMO-BRIDGE] pata {} {} sz={} sin fill (state={})",
                               side, inst, sz, state)
                return None
            logger.info("[DEMO-BRIDGE] pata {} {} qty={} @ {} fee={} {}",
                        side, inst, qty, px, fee, fee_ccy)
            return px, qty, fee, fee_ccy
        except Exception as exc:
            logger.warning("[DEMO-BRIDGE] pata {} {} fallo: {}", side, inst, exc)
            return None

    def _bridge_market(self, symbol: str, side: str, size: Decimal,
                       strategy: str) -> OrderResult | None:
        """Reintenta una market cancelada por el motor demo en 2 patas via bridge.

        SELL base: base->EUR (pata 1) y EUR->quote de ejecucion (pata 2).
        BUY  base: quote->EUR (pata 1), EUR->base (pata 2) y barrido del EUR sobrante
        de vuelta a la quote (pata 3, best-effort).

        Devuelve un OrderResult en el espacio de la estrategia con precio EFECTIVO
        (quote neta movida / base movida; fee=0 porque ya va neteada en el precio), o
        None si la pata 1 no ejecuto (sin cambios de estado, el caller reporta rejected).
        Si una pata intermedia falla, el sobrante queda en EUR y se avisa con ERROR:
        se corrige a mano o en el siguiente rebalanceo. Es entorno demo: prioridad a
        ejercitar el camino real de ordenes, no a la contabilidad perfecta.
        """
        base, _ = symbol.split("-")
        bq = self._bridge_quote
        exec_q = self._exec_quote or self._strategy_quote
        base_eur = f"{base}-{bq}"      # BTC-EUR
        quote_eur = f"{exec_q}-{bq}"   # USDC-EUR
        two_dp = Decimal("0.01")

        if side == "sell":
            leg1 = self._bridge_leg(base_eur, "sell", size, "base_ccy")
            if leg1 is None:
                return None
            px1, qty1, fee1, _ = leg1                       # fee1 en EUR
            eur_got = (px1 * qty1 - fee1).quantize(two_dp, rounding="ROUND_DOWN")
            leg2 = self._bridge_leg(quote_eur, "buy", eur_got, "quote_ccy")
            if leg2 is None:
                logger.error("[DEMO-BRIDGE] {} {} vendidos pero {} EUR varados (pata 2 "
                             "fallo). Convertir a mano o esperar siguiente rebalanceo.",
                             qty1, base, eur_got)
                quote_moved = eur_got / self._bridge_rate()  # estimacion para el journal
            else:
                px2, qty2, fee2, _ = leg2                    # qty2 = quote comprada, fee2 en quote
                quote_moved = qty2 - fee2
            eff_px = (quote_moved / qty1).quantize(two_dp)
            base_moved = qty1
        else:
            # Estimar el EUR necesario con el feed real (el demo cotiza distinto pero
            # el buffer del 3% + barrido final absorben la diferencia).
            px_ref = self._md.get_ticker(base_eur)
            if px_ref <= 0:
                return None
            eur_needed = (size * px_ref * Decimal("1.03")).quantize(two_dp)
            quote_to_sell = (eur_needed / self._bridge_rate() * Decimal("1.01")
                             ).quantize(two_dp)
            leg1 = self._bridge_leg(quote_eur, "sell", quote_to_sell, "base_ccy")
            if leg1 is None:
                return None
            px1, qty1, fee1, _ = leg1                       # qty1 = quote vendida, fee1 EUR
            eur_avail = (px1 * qty1 - fee1).quantize(two_dp, rounding="ROUND_DOWN")
            leg2 = self._bridge_leg(base_eur, "buy", size, "base_ccy")
            if leg2 is None:
                logger.error("[DEMO-BRIDGE] {} {} vendidos pero {} EUR varados (pata 2 "
                             "fallo). Convertir a mano o esperar siguiente rebalanceo.",
                             qty1, exec_q, eur_avail)
                return None
            px2, qty2, fee2, _ = leg2                       # qty2 = base comprada, fee2 en base
            eur_left = (eur_avail - px2 * qty2).quantize(two_dp, rounding="ROUND_DOWN")
            quote_back = Decimal("0")
            if eur_left > Decimal("1"):
                leg3 = self._bridge_leg(quote_eur, "buy", eur_left, "quote_ccy")
                if leg3 is not None:
                    _, qty3, fee3, _ = leg3
                    quote_back = qty3 - fee3
                else:
                    logger.warning("[DEMO-BRIDGE] barrido: {} EUR quedan sin volver a {}",
                                   eur_left, exec_q)
            quote_moved = qty1 - quote_back
            base_moved = qty2 - fee2
            eff_px = (quote_moved / base_moved).quantize(two_dp)

        logger.info("[DEMO-BRIDGE] {} {} {} via {} completado: {} {} <-> {} {} (px efectivo {})",
                    side, size, symbol, bq, base_moved, base, quote_moved, exec_q, eff_px)
        result = OrderResult(
            order_id=f"BRIDGE-{self._utcnow().strftime('%H%M%S')}", symbol=symbol,
            side=side, order_type="market", size=size, limit_price=None,
            filled_price=eff_px, filled_qty=base_moved, fee=Decimal("0"),
            fee_currency=self._strategy_quote, status="filled", is_paper=True,
            strategy=strategy, timestamp=self._utcnow(),
        )
        self.get_balance()   # refresca el espejo tras mover 2-3 patas
        return result

    def _bridge_rate(self) -> Decimal:
        """EUR por unidad de quote (USDC), estimado con el feed real. Fallback 0.9."""
        try:
            rate = self._md.get_ticker(f"{self._exec_quote or self._strategy_quote}"
                                       f"-{self._bridge_quote}")
            if rate > 0:
                return rate
        except Exception:
            pass
        return Decimal("0.9")

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            self._call_api(self._trade_api.cancel_order,
                           instId=self._exec_symbol(symbol), ordId=order_id)
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
