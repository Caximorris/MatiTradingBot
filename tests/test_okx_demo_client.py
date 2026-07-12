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


def _client(tmp_path, trade=None, account=None, settings=None) -> OKXDemoClient:
    md = MagicMock()
    md.is_available = True
    return OKXDemoClient(
        settings or _settings(),
        runtime_dir=tmp_path,
        _trade_api=trade or _fake_trade(),
        _account_api=account or _fake_account(),
        _market_client=md,
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
