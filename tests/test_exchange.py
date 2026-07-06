"""
Tests de core/exchange.py — exclusivamente paper mode y degradación graceful.
Nunca llaman a la API real de OKX.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from core.exchange import ExchangeUnavailable, OKXClient, OrderResult, _RateLimiter
from config.settings import Settings


# ---------------------------------------------------------------------------
# Fixture: Settings en modo paper
# ---------------------------------------------------------------------------

def _paper_settings(**overrides) -> Settings:
    defaults = dict(
        okx_api_key="", okx_secret_key="", okx_passphrase="",
        trading_mode="paper", okx_sandbox=True,
        trading_pairs=["BTC-USDT", "ETH-USDT"],
        max_portfolio_risk_pct=Decimal("2.0"),
        max_open_positions=10,
        daily_loss_limit_pct=Decimal("5.0"),
        fiscal_year=2025,
        cost_basis_method="FIFO",
    )
    return Settings(**{**defaults, **overrides})


@pytest.fixture
def client() -> OKXClient:
    """OKXClient en paper mode, sin llamadas a OKX."""
    settings = _paper_settings()
    # Evitar que _init_apis intente importar okx (puede no estar instalado en CI)
    with patch("core.exchange.OKXClient._init_apis"):
        c = OKXClient(settings)
        c._available = False  # Simular exchange no disponible
    return c


@pytest.fixture
def client_with_ticker(client: OKXClient) -> OKXClient:
    """Cliente paper con get_ticker mockeado para devolver 65000."""
    client.get_ticker = MagicMock(return_value=Decimal("65000"))
    return client


# ---------------------------------------------------------------------------
# Tests de balance
# ---------------------------------------------------------------------------

def test_initial_paper_balance_is_10000_usdt(client):
    balance = client.get_balance()
    assert balance["USDT"] == Decimal("10000")


def test_set_paper_balance(client):
    client.set_paper_balance("BTC", Decimal("0.5"))
    balance = client.get_balance()
    assert balance["BTC"] == Decimal("0.5")
    assert balance["USDT"] == Decimal("10000")  # no afecta otras monedas


def test_paper_state_name_isolates_persisted_balances(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = _paper_settings()
    with patch("core.exchange.OKXClient._init_apis"):
        v5 = OKXClient(settings, persist_paper_state=True, paper_state_name="swing_v5")
        v6 = OKXClient(settings, persist_paper_state=True, paper_state_name="swing_v6")
        v5.set_paper_balance("USDT", Decimal("111"))
        v6.set_paper_balance("USDT", Decimal("222"))

        v5_reload = OKXClient(settings, persist_paper_state=True, paper_state_name="swing_v5")
        v6_reload = OKXClient(settings, persist_paper_state=True, paper_state_name="swing_v6")

    assert v5_reload.get_balance()["USDT"] == Decimal("111")
    assert v6_reload.get_balance()["USDT"] == Decimal("222")
    assert (tmp_path / "data" / "runtime" / "paper_state_swing_v5.json").exists()
    assert (tmp_path / "data" / "runtime" / "paper_state_swing_v6.json").exists()


# ---------------------------------------------------------------------------
# Tests de market orders (compra)
# ---------------------------------------------------------------------------

def test_market_buy_deducts_usdt_and_credits_btc(client_with_ticker):
    c = client_with_ticker
    result = c.place_order("BTC-USDT", "buy", "market", Decimal("0.1"))

    assert result.status == "filled"
    assert result.filled_price == Decimal("65000")
    assert result.filled_qty == Decimal("0.1")
    assert result.is_paper is True

    balance = c.get_balance()
    expected_cost = Decimal("0.1") * Decimal("65000")
    fee = expected_cost * Decimal("0.001")
    assert balance["USDT"] == Decimal("10000") - expected_cost - fee
    assert balance["BTC"] == Decimal("0.1")


def test_market_sell_deducts_btc_and_credits_usdt(client_with_ticker):
    c = client_with_ticker
    c.set_paper_balance("BTC", Decimal("1.0"))
    initial_usdt = c.get_balance()["USDT"]

    result = c.place_order("BTC-USDT", "sell", "market", Decimal("0.5"))

    assert result.status == "filled"
    balance = c.get_balance()
    assert balance["BTC"] == Decimal("0.5")
    proceeds = Decimal("0.5") * Decimal("65000")
    fee = proceeds * Decimal("0.001")
    assert balance["USDT"] == initial_usdt + proceeds - fee


def test_market_buy_rejected_on_insufficient_balance(client_with_ticker):
    c = client_with_ticker
    c.set_paper_balance("USDT", Decimal("100"))

    result = c.place_order("BTC-USDT", "buy", "market", Decimal("1.0"))

    assert result.status == "rejected"
    assert result.order_id == ""
    assert "insuficiente" in result.error.lower()
    # Balance no debe cambiar
    assert c.get_balance()["USDT"] == Decimal("100")


def test_market_sell_rejected_on_insufficient_btc(client_with_ticker):
    c = client_with_ticker
    result = c.place_order("BTC-USDT", "sell", "market", Decimal("0.5"))

    assert result.status == "rejected"
    assert "insuficiente" in result.error.lower()


# ---------------------------------------------------------------------------
# Tests de limit orders
# ---------------------------------------------------------------------------

def test_limit_buy_creates_pending_order(client_with_ticker):
    c = client_with_ticker
    result = c.place_order("BTC-USDT", "buy", "limit", Decimal("0.1"), price=Decimal("60000"))

    assert result.status == "open"
    assert result.order_id.startswith("PAPER-")
    assert result.filled_price is None
    assert len(c.get_paper_orders()) == 1


def test_limit_buy_reserves_balance(client_with_ticker):
    c = client_with_ticker
    initial = c.get_balance()["USDT"]

    c.place_order("BTC-USDT", "buy", "limit", Decimal("0.1"), price=Decimal("60000"))

    balance = c.get_balance()
    reserved = Decimal("0.1") * Decimal("60000") * Decimal("1.001")  # incluye fee estimada
    assert balance["USDT"] == initial - reserved


def test_cancel_order_restores_reserved_balance(client_with_ticker):
    c = client_with_ticker
    initial_usdt = c.get_balance()["USDT"]

    result = c.place_order("BTC-USDT", "buy", "limit", Decimal("0.1"), price=Decimal("60000"))
    ok = c.cancel_order(result.order_id, "BTC-USDT")

    assert ok is True
    assert len(c.get_paper_orders()) == 0
    assert c.get_balance()["USDT"] == initial_usdt  # balance devuelto


def test_cancel_nonexistent_order_returns_false(client):
    assert client.cancel_order("PAPER-999999-XXXXXX", "BTC-USDT") is False


# ---------------------------------------------------------------------------
# Tests de fill de limit orders
# ---------------------------------------------------------------------------

def test_fill_limit_buy_when_price_drops(client_with_ticker):
    c = client_with_ticker
    c.place_order("BTC-USDT", "buy", "limit", Decimal("0.1"), price=Decimal("60000"))

    # Precio cae a 59500 → debe ejecutarse
    filled = c.fill_paper_limit_orders("BTC-USDT", Decimal("59500"))

    assert len(filled) == 1
    assert filled[0].status == "filled"
    assert filled[0].filled_price == Decimal("59500")
    assert len(c.get_paper_orders()) == 0


def test_fill_limit_sell_when_price_rises(client_with_ticker):
    c = client_with_ticker
    c.set_paper_balance("BTC", Decimal("1.0"))
    c.place_order("BTC-USDT", "sell", "limit", Decimal("1.0"), price=Decimal("70000"))

    # Precio sube a 71000 → debe ejecutarse
    filled = c.fill_paper_limit_orders("BTC-USDT", Decimal("71000"))

    assert len(filled) == 1
    assert filled[0].filled_price == Decimal("71000")


def test_limit_order_not_filled_before_price_crosses(client_with_ticker):
    c = client_with_ticker
    c.place_order("BTC-USDT", "buy", "limit", Decimal("0.1"), price=Decimal("60000"))

    # Precio sigue alto → no debe ejecutarse
    filled = c.fill_paper_limit_orders("BTC-USDT", Decimal("62000"))
    assert len(filled) == 0
    assert len(c.get_paper_orders()) == 1


def test_fill_only_matching_symbol(client_with_ticker):
    c = client_with_ticker
    c.set_paper_balance("ETH", Decimal("10"))
    c.place_order("BTC-USDT", "buy", "limit", Decimal("0.1"), price=Decimal("60000"))
    c.place_order("ETH-USDT", "sell", "limit", Decimal("1.0"), price=Decimal("3000"))

    # Solo ejecutar los de ETH-USDT
    filled = c.fill_paper_limit_orders("ETH-USDT", Decimal("3100"))
    assert len(filled) == 1
    assert filled[0].symbol == "ETH-USDT"
    assert len(c.get_paper_orders()) == 1  # el BTC sigue pendiente


# ---------------------------------------------------------------------------
# Tests de degradación graceful (exchange no disponible)
# ---------------------------------------------------------------------------

def test_get_ticker_returns_zero_when_unavailable(client):
    assert client.get_ticker("BTC-USDT") == Decimal("0")


def test_get_balance_paper_works_without_exchange(client):
    balance = client.get_balance()
    assert "USDT" in balance  # paper balance siempre disponible


def test_get_open_orders_returns_empty_when_unavailable(client):
    assert client.get_open_orders("BTC-USDT") == []


def test_get_positions_returns_empty_in_paper_mode(client):
    assert client.get_positions() == []


def test_get_ohlcv_paginates_and_returns_ms_timestamps(client):
    class MarketApi:
        def __init__(self):
            self.calls = []

        def get_candlesticks(self, **params):
            self.calls.append(("recent", params))
            return {
                "data": [
                    ["3000", "3", "4", "2", "3.5", "30", "0", "0", "1"],
                    ["2000", "2", "3", "1", "2.5", "20", "0", "0", "1"],
                ]
            }

        def get_history_candlesticks(self, **params):
            self.calls.append(("history", params))
            return {
                "data": [
                    ["1000", "1", "2", "0.5", "1.5", "10", "0", "0", "1"],
                ]
            }

    market = MarketApi()
    client._available = True
    client._market_api = market
    client._call_api = lambda fn, **params: fn(**params)

    df = client.get_ohlcv("BTC-USDT", "1H", limit=3)

    assert list(df["timestamp"]) == [1000, 2000, 3000]
    assert str(df["timestamp"].dtype).startswith("int")
    assert market.calls[0][0] == "recent"
    assert "after" not in market.calls[0][1]
    assert market.calls[1][0] == "history"
    assert market.calls[1][1]["after"] == "2000"


# ---------------------------------------------------------------------------
# Tests del rate limiter
# ---------------------------------------------------------------------------

def test_rate_limiter_allows_requests_within_limit():
    limiter = _RateLimiter(max_requests=5, window=2.0)
    start = __import__("time").monotonic()
    for _ in range(5):
        limiter.acquire()
    elapsed = __import__("time").monotonic() - start
    assert elapsed < 1.0  # 5 requests sin throttle deben ser rápidas


def test_paper_order_ids_are_unique(client_with_ticker):
    results = [
        client_with_ticker.place_order("BTC-USDT", "buy", "limit", Decimal("0.01"), price=Decimal("60000"))
        for _ in range(5)
    ]
    ids = [r.order_id for r in results if r.status == "open"]
    assert len(ids) == len(set(ids))  # todos distintos


# ---------------------------------------------------------------------------
# Tests de persistencia del estado paper (fix post-freeze 2026-07-02)
# ---------------------------------------------------------------------------

def _persistent_client() -> OKXClient:
    settings = _paper_settings()
    with patch("core.exchange.OKXClient._init_apis"):
        c = OKXClient(settings, persist_paper_state=True)
        c._available = False
    return c


def test_paper_state_roundtrip_survives_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    c1 = _persistent_client()
    c1.set_paper_balance("USDT", Decimal("4000"))
    c1.set_paper_balance("BTC", Decimal("0.123456"))

    # "Reinicio del proceso": instancia nueva debe recuperar el portfolio
    c2 = _persistent_client()
    balance = c2.get_balance()
    assert balance["USDT"] == Decimal("4000")
    assert balance["BTC"] == Decimal("0.123456")


def test_paper_state_not_persisted_by_default(tmp_path, monkeypatch, client):
    monkeypatch.chdir(tmp_path)
    client.set_paper_balance("USDT", Decimal("1234"))
    assert not (tmp_path / "data" / "runtime" / "paper_state.json").exists()


def test_paper_state_corrupt_file_falls_back_to_fresh(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_path = tmp_path / "data" / "runtime" / "paper_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{esto no es json", encoding="utf-8")

    c = _persistent_client()
    assert c.get_balance()["USDT"] == Decimal("10000")
