"""Tests de core/okx_demo_client.py — APIs falsas inyectadas, cero red.

Cubren el camino de ordenes autenticado (el que nunca se habia ejercitado) y los guardas
de configuracion. El detalle mas critico: tgtCcy=base_ccy en ordenes market (sin el, un
market BUY spot en OKX interpreta sz como USDT y compra ~64000x menos BTC).
"""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from core.okx_demo_client import OKXDemoClient


def _settings(**overrides) -> Settings:
    defaults = dict(
        okx_api_key="", okx_secret_key="", okx_passphrase="",
        trading_mode="paper", okx_sandbox=False,
        trading_pairs=["BTC-USDT"],
        max_portfolio_risk_pct=Decimal("2.0"),
        max_open_positions=10,
        daily_loss_limit_pct=Decimal("5.0"),
        fiscal_year=2026,
        cost_basis_method="FIFO",
        okx_demo_api_key="demo-key",
        okx_demo_secret_key="demo-secret",
        okx_demo_passphrase="demo-pass",
    )
    return Settings(**{**defaults, **overrides})


def _balance_resp(details):
    return {"code": "0", "data": [{"details": details}]}


def _fake_account(usdt="10000", btc=None):
    acc = MagicMock()
    details = [{"ccy": "USDT", "availEq": usdt}]
    if btc is not None:
        details.append({"ccy": "BTC", "availBal": btc})
    acc.get_account_balance.return_value = _balance_resp(details)
    return acc


def _fake_trade(s_code="0", ord_id="oid-1", fill=None):
    tr = MagicMock()
    tr.place_order.return_value = {
        "code": "0",
        "data": [{"ordId": ord_id, "sCode": s_code, "sMsg": "rechazo simulado"}],
    }
    tr.get_order.return_value = {
        "code": "0",
        "data": [fill or {"avgPx": "64000", "accFillSz": "0.05",
                          "fee": "-3.2", "feeCcy": "USDT"}],
    }
    tr.cancel_order.return_value = {"code": "0", "data": [{}]}
    return tr


def _client(tmp_path, trade=None, account=None, settings=None, **kw) -> OKXDemoClient:
    md = MagicMock()
    md.is_available = True
    return OKXDemoClient(
        settings or _settings(),
        runtime_dir=tmp_path,
        _trade_api=trade or _fake_trade(),
        _account_api=account or _fake_account(),
        _market_client=md,
        **kw,
    )


# ---------------------------------------------------------------------------
# Guardas de configuracion
# ---------------------------------------------------------------------------

def test_requires_demo_credentials(tmp_path):
    with pytest.raises(EnvironmentError, match="OKX_DEMO_API_KEY"):
        _client(tmp_path, settings=_settings(okx_demo_api_key=""))


def test_refuses_live_mode(tmp_path):
    with pytest.raises(EnvironmentError, match="TRADING_MODE=paper"):
        _client(tmp_path, settings=_settings(
            trading_mode="live", okx_api_key="k", okx_secret_key="s", okx_passphrase="p"))


def test_init_fails_fast_on_empty_balance(tmp_path):
    acc = MagicMock()
    acc.get_account_balance.side_effect = RuntimeError("auth fail")
    with pytest.raises(Exception, match="vacio al arrancar"):
        _client(tmp_path, account=acc)


# ---------------------------------------------------------------------------
# Ordenes — el camino critico
# ---------------------------------------------------------------------------

def test_market_buy_sets_tgtccy_base(tmp_path):
    trade = _fake_trade()
    c = _client(tmp_path, trade=trade)
    result = c.place_order("BTC-USDT", "buy", "market", Decimal("0.05"), strategy="t")
    params = trade.place_order.call_args.kwargs
    assert params["tgtCcy"] == "base_ccy"
    assert params["sz"] == "0.05"
    assert params["tdMode"] == "cash"
    assert result.status == "filled"
    assert result.order_id == "oid-1"


# ---------------------------------------------------------------------------
# Bridge EUR: market cancelada por el motor -> 2 patas via EUR (solo demo)
# ---------------------------------------------------------------------------

def _fake_trade_bridge():
    """SELL en BTC-USDC lo cancela el motor; las patas EUR ejecutan bien."""
    tr = MagicMock()
    orders = {}   # ordId -> respuesta de get_order

    def place_order(**kw):
        oid = f"oid-{len(orders)}"
        inst, side = kw["instId"], kw["side"]
        if inst == "BTC-USDC" and side == "sell":
            orders[oid] = {"state": "canceled", "avgPx": "", "accFillSz": "0",
                           "fee": "0", "feeCcy": ""}
        elif inst == "BTC-EUR" and side == "sell":
            orders[oid] = {"state": "filled", "avgPx": "54600", "accFillSz": kw["sz"],
                           "fee": "-3.41", "feeCcy": "EUR"}
        elif inst == "USDC-EUR" and side == "buy":
            # compra por importe EUR (tgtCcy=quote_ccy): qty base = sz/0.78
            qty = str(round(float(kw["sz"]) / 0.78, 4))
            orders[oid] = {"state": "filled", "avgPx": "0.78", "accFillSz": qty,
                           "fee": "-0.5", "feeCcy": "USDC"}
        else:
            orders[oid] = {"state": "canceled", "avgPx": "", "accFillSz": "0",
                           "fee": "0", "feeCcy": ""}
        return {"code": "0", "data": [{"ordId": oid, "sCode": "0"}]}

    tr.place_order.side_effect = place_order
    tr.get_order.side_effect = lambda **kw: {"code": "0", "data": [orders[kw["ordId"]]]}
    return tr


def test_bridge_sell_via_eur_when_engine_cancels(tmp_path, monkeypatch):
    monkeypatch.setattr("core.okx_demo_client._FILL_QUERY_DELAY_S", 0)
    trade = _fake_trade_bridge()
    c = _client(tmp_path, trade=trade, exec_quote="USDC", bridge_quote="EUR")
    result = c.place_order("BTC-USDT", "sell", "market", Decimal("0.0627"), strategy="t")
    assert result.status == "filled"
    assert result.filled_qty == Decimal("0.0627")
    # 0.0627*54600-3.41 = 3419.01 EUR -> /0.78 ~ 4383.34 USDC -0.5 fee -> px ~ 69902
    assert Decimal("69000") < result.filled_price < Decimal("70500")
    insts = [k.kwargs["instId"] for k in trade.place_order.call_args_list]
    assert insts == ["BTC-USDC", "BTC-EUR", "USDC-EUR"]
    assert result.order_id.startswith("BRIDGE-")


def test_bridge_not_used_without_config(tmp_path, monkeypatch):
    monkeypatch.setattr("core.okx_demo_client._FILL_QUERY_DELAY_S", 0)
    trade = _fake_trade_bridge()
    c = _client(tmp_path, trade=trade, exec_quote="USDC")   # sin bridge_quote
    result = c.place_order("BTC-USDT", "sell", "market", Decimal("0.0627"), strategy="t")
    assert result.status == "rejected"
    insts = [k.kwargs["instId"] for k in trade.place_order.call_args_list]
    assert insts == ["BTC-USDC"]   # ni una pata EUR


def test_bridge_gives_up_if_first_leg_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("core.okx_demo_client._FILL_QUERY_DELAY_S", 0)
    trade = MagicMock()
    trade.place_order.return_value = {"code": "0", "data": [{"ordId": "o", "sCode": "0"}]}
    trade.get_order.return_value = {"code": "0", "data": [
        {"state": "canceled", "avgPx": "", "accFillSz": "0", "fee": "0", "feeCcy": ""}]}
    c = _client(tmp_path, trade=trade, exec_quote="USDC", bridge_quote="EUR")
    result = c.place_order("BTC-USDT", "sell", "market", Decimal("0.05"), strategy="t")
    # pata 1 (BTC-EUR) tambien cancelada -> rejected honesto, sin patas extra
    assert result.status == "rejected"
    assert "cancelada por el motor" in result.error


# ---------------------------------------------------------------------------
# Mapeo señal->ejecucion (cuentas EEA/MiCA: USDT bloqueado, se ejecuta en USDC)
# ---------------------------------------------------------------------------

def test_exec_quote_routes_usdt_orders_to_usdc(tmp_path):
    trade = _fake_trade()
    c = _client(tmp_path, trade=trade, exec_quote="USDC")
    result = c.place_order("BTC-USDT", "buy", "market", Decimal("0.05"), strategy="t")
    assert trade.place_order.call_args.kwargs["instId"] == "BTC-USDC"
    # La estrategia sigue viendo su propio simbolo, no el de ejecucion.
    assert result.symbol == "BTC-USDT"
    assert result.status == "filled"


def test_exec_quote_aliases_usdc_balance_as_usdt(tmp_path):
    acc = MagicMock()
    acc.get_account_balance.return_value = _balance_resp(
        [{"ccy": "USDC", "availBal": "14000"}, {"ccy": "EUR", "availBal": "4600"}]
    )
    c = _client(tmp_path, account=acc, exec_quote="USDC")
    bal = c.get_balance()
    assert bal["USDT"] == Decimal("14000")
    assert "USDC" not in bal
    assert bal["EUR"] == Decimal("4600")   # el resto de monedas no se toca


def test_exec_quote_leaves_non_usdt_symbols_untouched(tmp_path):
    trade = _fake_trade()
    c = _client(tmp_path, trade=trade, exec_quote="USDC")
    c.place_order("XRP-USDC", "sell", "market", Decimal("10"), strategy="t")
    assert trade.place_order.call_args.kwargs["instId"] == "XRP-USDC"


def test_without_exec_quote_no_translation(tmp_path):
    trade = _fake_trade()
    c = _client(tmp_path, trade=trade)
    c.place_order("BTC-USDT", "buy", "market", Decimal("0.05"), strategy="t")
    assert trade.place_order.call_args.kwargs["instId"] == "BTC-USDT"


def test_market_order_canceled_by_engine_maps_to_rejected(tmp_path):
    # Visto en demo EEA 2026-07-13: OKX acepta la market (sCode=0) y el motor la
    # cancela sin fill (book demo sin liquidez). No debe reportarse fill fantasma.
    canceled = {"state": "canceled", "avgPx": "", "accFillSz": "0", "fee": "0", "feeCcy": ""}
    c = _client(tmp_path, trade=_fake_trade(fill=canceled))
    result = c.place_order("BTC-USDC", "sell", "market", Decimal("0.001"), strategy="t")
    assert result.status == "rejected"
    assert result.filled_qty == Decimal("0")
    assert "cancelada por el motor" in result.error
    assert result.size == Decimal("0.001")


def test_market_order_partial_fill_then_cancel_keeps_real_qty(tmp_path):
    partial = {"state": "canceled", "avgPx": "60544", "accFillSz": "0.15",
               "fee": "-18.5", "feeCcy": "USDC"}
    c = _client(tmp_path, trade=_fake_trade(fill=partial))
    result = c.place_order("BTC-USDC", "sell", "market", Decimal("1"), strategy="t")
    assert result.status == "filled"
    assert result.filled_qty == Decimal("0.15")   # la qty REAL, no la pedida
    assert result.filled_price == Decimal("60544")


def test_market_order_enriched_with_fill_details(tmp_path):
    c = _client(tmp_path)
    result = c.place_order("BTC-USDT", "buy", "market", Decimal("0.05"), strategy="t")
    assert result.filled_price == Decimal("64000")
    assert result.filled_qty == Decimal("0.05")
    assert result.fee == Decimal("3.2")   # OKX reporta -3.2; se guarda en positivo
    assert result.fee_currency == "USDT"


def test_limit_order_no_tgtccy_and_stays_open(tmp_path):
    trade = _fake_trade()
    c = _client(tmp_path, trade=trade)
    result = c.place_order("BTC-USDT", "sell", "limit", Decimal("0.05"),
                           price=Decimal("70000"), strategy="t")
    params = trade.place_order.call_args.kwargs
    assert "tgtCcy" not in params
    assert params["px"] == "70000"
    assert result.status == "open"
    assert result.limit_price == Decimal("70000")
    assert result.size == Decimal("0.05")


def test_scode_rejection_maps_to_rejected(tmp_path):
    c = _client(tmp_path, trade=_fake_trade(s_code="51008"))
    result = c.place_order("BTC-USDT", "buy", "market", Decimal("0.05"), strategy="t")
    assert result.status == "rejected"
    assert "rechazo simulado" in result.error
    assert result.size == Decimal("0.05")   # OrderResult siempre con size (CLAUDE.md)


def test_api_exception_maps_to_rejected_not_raise(tmp_path):
    trade = _fake_trade()
    c = _client(tmp_path, trade=trade)
    trade.place_order.side_effect = RuntimeError("timeout")
    result = c.place_order("BTC-USDT", "buy", "market", Decimal("0.05"), strategy="t")
    assert result.status == "rejected"


def test_cancel_order(tmp_path):
    trade = _fake_trade()
    c = _client(tmp_path, trade=trade)
    assert c.cancel_order("oid-1", "BTC-USDT") is True
    trade.cancel_order.assert_called_once_with(instId="BTC-USDT", ordId="oid-1")


# ---------------------------------------------------------------------------
# Balance + espejo
# ---------------------------------------------------------------------------

def test_balance_parses_decimals_and_writes_mirror(tmp_path):
    c = _client(tmp_path, account=_fake_account(usdt="9876.5", btc="0.031"))
    bal = c.get_balance()
    assert bal == {"USDT": Decimal("9876.5"), "BTC": Decimal("0.031")}
    mirror = json.loads((tmp_path / "paper_state_okx_demo.json").read_text())
    assert mirror["balances"]["USDT"] == "9876.5"
    assert mirror["mirror_of"] == "okx_demo_trading"


def test_market_data_delegates_to_real_feed(tmp_path):
    c = _client(tmp_path)
    c._md.get_ticker.return_value = Decimal("64000")
    assert c.get_ticker("BTC-USDT") == Decimal("64000")
    c.get_ohlcv("BTC-USDT", timeframe="1H", limit=2000)
    c._md.get_ohlcv.assert_called_once_with("BTC-USDT", timeframe="1H", limit=2000)


def test_interface_compat_paper_noops(tmp_path):
    c = _client(tmp_path)
    assert c.is_paper is True     # tagueo DB: no es dinero real
    assert c.fill_paper_limit_orders("BTC-USDT", Decimal("64000")) == []
    assert c.get_paper_orders() == {}
    c.adjust_balance("USDT", Decimal("5"))   # no-op, no debe lanzar
