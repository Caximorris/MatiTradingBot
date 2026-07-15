from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.backtest import BacktestClient, BacktestEngine
from data.market_data import OHLCVBar


def _bar(hour: int, price: str = "100", low: str | None = None) -> OHLCVBar:
    value = Decimal(price)
    return OHLCVBar(
        timestamp=int(datetime(2024, 1, 1, hour, tzinfo=timezone.utc).timestamp() * 1000),
        open=value,
        high=value,
        low=Decimal(low) if low is not None else value,
        close=value,
        volume=Decimal("1"),
    )


def test_buy_limit_reserves_principal_and_eight_decimal_fee() -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client.advance(0)

    order = client.place_order("BTC-USDT", "buy", "limit", Decimal("1"), Decimal("100"))

    assert order.status == "open"
    assert order.fee == Decimal("0.10000000")
    assert client.get_balance()["USDT"] == Decimal("899.90000000")
    assert client._get_total_balance()["USDT"] == Decimal("1000.00000000")


def test_buy_limit_rejection_preserves_limit_contract() -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("100"))
    client.advance(0)

    order = client.place_order("BTC-USDT", "buy", "limit", Decimal("1"), Decimal("100"))

    assert order.status == "rejected"
    assert order.order_type == "limit"
    assert order.limit_price == Decimal("100")
    assert client.get_balance()["USDT"] == Decimal("100")


def test_buy_limit_fill_never_drives_available_quote_negative() -> None:
    client = BacktestClient(
        "BTC-USDT", [_bar(0), _bar(1, low="99")], initial_balance=Decimal("100.1")
    )
    client.advance(0)
    order = client.place_order("BTC-USDT", "buy", "limit", Decimal("1"), Decimal("100"))

    fills = client.advance(1)

    assert order.status == "open"
    assert len(fills) == 1
    assert fills[0].fee == Decimal("0.10000000")
    assert client.get_balance()["USDT"] == Decimal("0E-8")
    assert client.get_balance()["BTC"] == Decimal("1")


def test_cancel_limit_restores_the_full_reservation() -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client.advance(0)
    order = client.place_order("BTC-USDT", "buy", "limit", Decimal("1"), Decimal("100"))

    assert client.cancel_order(order.order_id, "BTC-USDT") is True
    assert client.get_balance()["USDT"] == Decimal("1000.00000000")
    assert client.get_open_orders() == []


def test_backtest_funding_lookup_is_symbol_specific(monkeypatch) -> None:
    client = BacktestClient("ETH-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client.advance(0)
    captured = {}

    def lookup(dt, symbol):
        captured.update(dt=dt, symbol=symbol)
        return 0.001

    monkeypatch.setattr("strategies.funding_context.get_funding_rate_at", lookup)

    assert client.get_funding_rate("ETH-USDT") == 0.001
    assert captured == {
        "dt": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "symbol": "ETH-USDT",
    }


def test_engine_equity_includes_open_order_reservations() -> None:
    bars = [_bar(0), _bar(1), _bar(2)]
    client = BacktestClient("BTC-USDT", bars, initial_balance=Decimal("1000"))

    class PendingLimitStrategy:
        name = "pending-limit"

        def __init__(self) -> None:
            self.placed = False

        def run(self) -> None:
            if not self.placed:
                client.place_order(
                    "BTC-USDT", "buy", "limit", Decimal("1"), Decimal("50")
                )
                self.placed = True

    result = BacktestEngine(client, lambda _client, _session: PendingLimitStrategy(), warmup_bars=1).run()

    assert result.final_balance == Decimal("1000.00000000")
    assert client.get_balance()["USDT"] == Decimal("949.95000000")


def test_engine_aborts_on_first_strategy_exception() -> None:
    client = BacktestClient("BTC-USDT", [_bar(0), _bar(1)], initial_balance=Decimal("1000"))

    class FailingStrategy:
        name = "failing"

        def run(self) -> None:
            raise LookupError("strategy integrity failure")

    engine = BacktestEngine(client, lambda _client, _session: FailingStrategy(), warmup_bars=1)

    with pytest.raises(LookupError, match="strategy integrity failure"):
        engine.run()
