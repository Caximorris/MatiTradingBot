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


@pytest.mark.parametrize("size", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_invalid_size_is_rejected_without_mutating_balances(size: Decimal) -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client.advance(0)

    order = client.place_order("BTC-USDT", "buy", "market", size)

    assert order.status == "rejected"
    assert "Tamaño de orden" in order.error
    assert client.get_balance() == {"USDT": Decimal("1000")}
    assert client.get_open_orders() == []


@pytest.mark.parametrize(
    ("side", "order_type", "error"),
    [
        ("hold", "market", "Lado de orden"),
        ("buy", "stop", "Tipo de orden"),
    ],
)
def test_invalid_side_or_type_is_rejected_without_creating_an_order(
    side: str, order_type: str, error: str
) -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client.advance(0)

    order = client.place_order("BTC-USDT", side, order_type, Decimal("1"))

    assert order.status == "rejected"
    assert error in order.error
    assert client.get_balance() == {"USDT": Decimal("1000")}
    assert client.get_open_orders() == []


@pytest.mark.parametrize("price", [Decimal("0"), Decimal("-100"), Decimal("NaN")])
def test_invalid_limit_price_is_rejected_without_reserving_funds(price: Decimal) -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client.advance(0)

    order = client.place_order("BTC-USDT", "buy", "limit", Decimal("1"), price)

    assert order.status == "rejected"
    if price.is_nan():
        assert order.limit_price is not None and order.limit_price.is_nan()
    else:
        assert order.limit_price == price
    assert "Precio límite" in order.error
    assert client.get_balance() == {"USDT": Decimal("1000")}
    assert client.get_open_orders() == []


def test_limit_order_without_price_keeps_current_close_compatibility() -> None:
    client = BacktestClient("BTC-USDT", [_bar(0, price="100")], initial_balance=Decimal("1000"))
    client.advance(0)

    order = client.place_order("BTC-USDT", "buy", "limit", Decimal("1"))

    assert order.status == "open"
    assert order.limit_price == Decimal("100")


def test_symbol_mismatch_and_unsupported_quote_are_rejected() -> None:
    btc_client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    btc_client.advance(0)
    mismatch = btc_client.place_order("ETH-USDT", "buy", "market", Decimal("1"))

    usdc_client = BacktestClient("BTC-USDC", [_bar(0)], initial_balance=Decimal("1000"))
    usdc_client.advance(0)
    unsupported_quote = usdc_client.place_order("BTC-USDC", "buy", "market", Decimal("1"))

    assert mismatch.status == unsupported_quote.status == "rejected"
    assert "Símbolo no coincide" in mismatch.error
    assert "Moneda cotizada no soportada" in unsupported_quote.error
    assert btc_client.get_balance() == usdc_client.get_balance() == {"USDT": Decimal("1000")}


def test_cancel_rejects_symbol_mismatch_and_missing_reservation_state() -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client.advance(0)
    order = client.place_order("BTC-USDT", "buy", "limit", Decimal("1"), Decimal("100"))

    assert client.cancel_order(order.order_id, "ETH-USDT") is False
    assert client.get_open_orders() != []

    client._reserved_usdt.clear()
    with pytest.raises(RuntimeError, match="reservation missing quote funds"):
        client.cancel_order(order.order_id, "BTC-USDT")
    assert client.get_open_orders() != []


def test_limit_fill_raises_when_reservation_state_is_missing() -> None:
    client = BacktestClient(
        "BTC-USDT", [_bar(0), _bar(1, low="99")], initial_balance=Decimal("1000")
    )
    client.advance(0)
    client.place_order("BTC-USDT", "buy", "limit", Decimal("1"), Decimal("100"))
    client._reserved_usdt.clear()

    with pytest.raises(RuntimeError, match="reservation missing quote funds"):
        client.advance(1)


def test_sell_limit_fill_raises_when_base_reservation_is_missing() -> None:
    client = BacktestClient(
        "BTC-USDT", [_bar(0), _bar(1, price="101")], initial_balance=Decimal("1000")
    )
    client.adjust_balance("BTC", Decimal("1"))
    client.advance(0)
    client.place_order("BTC-USDT", "sell", "limit", Decimal("1"), Decimal("100"))
    client._reserved_base.clear()

    with pytest.raises(RuntimeError, match="reservation missing base funds"):
        client.advance(1)


def test_total_balance_raises_for_orphaned_base_reservation() -> None:
    client = BacktestClient("BTC-USDT", [_bar(0)], initial_balance=Decimal("1000"))
    client._reserved_base["missing-order"] = Decimal("1")

    with pytest.raises(RuntimeError, match="reservation missing order state"):
        client._get_total_balance()


def test_next_open_market_fill_occurs_before_the_next_strategy_tick() -> None:
    client = BacktestClient(
        "BTC-USDT", [_bar(0, price="110"), _bar(1, price="120")],
        initial_balance=Decimal("1000"), fill_next_open=True,
    )
    observed: list[tuple[datetime, Decimal, Decimal]] = []

    class NextOpenStrategy:
        name = "next-open"

        def run(self) -> None:
            balance = client.get_balance()
            observed.append((
                client.current_time(), balance.get("USDT", Decimal("0")),
                balance.get("BTC", Decimal("0")),
            ))
            if len(observed) == 1:
                client.place_order("BTC-USDT", "buy", "market", Decimal("1"))

    BacktestEngine(
        client, lambda _client, _session: NextOpenStrategy(), warmup_bars=0
    ).run()

    assert observed == [
        (datetime(2024, 1, 1, 0, tzinfo=timezone.utc), Decimal("1000"), Decimal("0")),
        (datetime(2024, 1, 1, 1, tzinfo=timezone.utc), Decimal("879.88000000"), Decimal("1")),
    ]
    assert client._executed[0].price == Decimal("120")
    assert client._executed[0].timestamp == datetime(2024, 1, 1, 1, tzinfo=timezone.utc)


def test_default_market_fill_remains_immediate_at_the_decision_close() -> None:
    client = BacktestClient(
        "BTC-USDT", [_bar(0, price="110"), _bar(1, price="120")],
        initial_balance=Decimal("1000"),
    )
    client.advance(0)

    order = client.place_order("BTC-USDT", "buy", "market", Decimal("1"))

    assert order.status == "filled"
    assert order.filled_price == Decimal("110")
    assert order.timestamp == datetime(2024, 1, 1, 0, tzinfo=timezone.utc)
    assert client.advance(1) == []


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
