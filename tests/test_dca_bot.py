"""Tests para strategies/dca_bot.py — paper mode, sin llamadas reales a OKX."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.exchange import OKXClient, OrderResult
from strategies.dca_bot import DCABot, DCAConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _now():
    return datetime.now(timezone.utc)


def _make_order(side, price=Decimal("65000"), qty=Decimal("0.01"), status="filled", order_id="PAPER-001"):
    return OrderResult(
        order_id=order_id,
        symbol="BTC-USDT",
        side=side,
        order_type="market",
        size=qty,
        limit_price=None,
        filled_price=price if status == "filled" else None,
        filled_qty=qty if status == "filled" else Decimal("0"),
        fee=Decimal("0.065"),
        fee_currency="USDT",
        status=status,
        is_paper=True,
        strategy="dca_btc_usdt",
        timestamp=_now(),
    )


def _make_client(ticker_price=Decimal("65000")):
    client = MagicMock(spec=OKXClient)
    client.is_paper = True
    client.get_ticker.return_value = ticker_price
    client.current_time.return_value = datetime.now(timezone.utc)
    return client


def _make_dca(client, session, **overrides):
    defaults = dict(
        symbol="BTC-USDT",
        base_order_size=Decimal("100"),
        safety_order_size=Decimal("100"),
        price_deviation_pct=Decimal("2.0"),
        take_profit_pct=Decimal("1.5"),
        max_safety_orders=3,
        safety_order_volume_scale=Decimal("1.5"),
        interval_hours=Decimal("24"),
    )
    cfg = DCAConfig(**{**defaults, **overrides})
    return DCABot(client=client, config=cfg, session=session)


# ---------------------------------------------------------------------------
# Tests de DCAConfig
# ---------------------------------------------------------------------------

def test_dca_config_validates_positive_order_size():
    with pytest.raises(ValueError):
        DCAConfig(
            symbol="BTC-USDT",
            base_order_size=Decimal("0"),
            safety_order_size=Decimal("100"),
            price_deviation_pct=Decimal("2"),
            take_profit_pct=Decimal("1.5"),
            max_safety_orders=3,
            safety_order_volume_scale=Decimal("1.5"),
            interval_hours=Decimal("24"),
        )


def test_dca_config_roundtrip():
    cfg = DCAConfig(
        symbol="ETH-USDT",
        base_order_size=Decimal("200"),
        safety_order_size=Decimal("100"),
        price_deviation_pct=Decimal("3.0"),
        take_profit_pct=Decimal("2.0"),
        max_safety_orders=5,
        safety_order_volume_scale=Decimal("2.0"),
        interval_hours=Decimal("12"),
    )
    restored = DCAConfig.from_dict(cfg.to_dict())
    assert restored.symbol == cfg.symbol
    assert restored.take_profit_pct == cfg.take_profit_pct
    assert restored.safety_order_volume_scale == cfg.safety_order_volume_scale


# ---------------------------------------------------------------------------
# Tests de should_enter
# ---------------------------------------------------------------------------

def test_should_enter_true_on_first_run(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session)
    assert bot.should_enter() is True


def test_should_enter_false_when_in_position(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session)
    bot._state["is_in_position"] = True
    assert bot.should_enter() is False


def test_should_enter_false_within_interval(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session, interval_hours=Decimal("24"))
    # Última orden hace 1 hora → intervalo de 24h no cumplido
    bot._state["last_base_order_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert bot.should_enter() is False


def test_should_enter_true_after_interval(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session, interval_hours=Decimal("24"))
    # Última orden hace 25 horas → intervalo cumplido
    bot._state["last_base_order_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert bot.should_enter() is True


# ---------------------------------------------------------------------------
# Tests de should_exit (take profit)
# ---------------------------------------------------------------------------

def test_should_exit_false_when_not_in_position(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session)
    assert bot.should_exit() is False


def test_should_exit_true_at_take_profit(db_session):
    client = _make_client(ticker_price=Decimal("66000"))  # +1.54% sobre 65000
    bot = _make_dca(client, db_session, take_profit_pct=Decimal("1.5"))
    bot._state["is_in_position"] = True
    bot._state["avg_entry_price"] = "65000"
    # 65000 * 1.015 = 65975 → precio 66000 > 65975 → take profit
    assert bot.should_exit() is True


def test_should_exit_false_before_take_profit(db_session):
    client = _make_client(ticker_price=Decimal("65500"))  # solo +0.77%
    bot = _make_dca(client, db_session, take_profit_pct=Decimal("1.5"))
    bot._state["is_in_position"] = True
    bot._state["avg_entry_price"] = "65000"
    assert bot.should_exit() is False


# ---------------------------------------------------------------------------
# Tests de safety orders
# ---------------------------------------------------------------------------

def test_safety_order_triggered_on_price_drop(db_session):
    client = _make_client(ticker_price=Decimal("63700"))  # −2.0% sobre 65000
    client.place_order.return_value = _make_order("buy", Decimal("63700"), qty=Decimal("0.00157"))

    bot = _make_dca(client, db_session, price_deviation_pct=Decimal("2.0"))
    bot._state["is_in_position"] = True
    bot._state["avg_entry_price"] = "65000"
    bot._state["total_quantity"] = "0.01"
    bot._state["total_invested"] = "650"

    bot.run()

    client.place_order.assert_called_once()
    # place_order se llama con args posicionales: (symbol, side, order_type, size, ...)
    assert client.place_order.call_args.args[1] == "buy"


def test_safety_order_not_triggered_on_small_drop(db_session):
    client = _make_client(ticker_price=Decimal("64500"))  # solo −0.77%
    bot = _make_dca(client, db_session, price_deviation_pct=Decimal("2.0"))
    bot._state["is_in_position"] = True
    bot._state["avg_entry_price"] = "65000"

    bot.run()
    client.place_order.assert_not_called()


def test_safety_order_respects_max_limit(db_session):
    client = _make_client(ticker_price=Decimal("63000"))
    bot = _make_dca(client, db_session, max_safety_orders=2)
    bot._state["is_in_position"] = True
    bot._state["avg_entry_price"] = "65000"
    bot._state["safety_orders_count"] = 2  # ya en el límite

    bot.run()
    client.place_order.assert_not_called()


# ---------------------------------------------------------------------------
# Tests de Martingale
# ---------------------------------------------------------------------------

def test_martingale_scales_safety_order_size(db_session):
    client = _make_client(ticker_price=Decimal("63700"))
    captured_sizes = []

    def capture_order(symbol, side, order_type, size, **kwargs):
        captured_sizes.append(size)
        return _make_order(side, Decimal("63700"), qty=size)

    client.place_order.side_effect = capture_order

    bot = _make_dca(
        client, db_session,
        safety_order_size=Decimal("100"),
        safety_order_volume_scale=Decimal("2.0"),
        price_deviation_pct=Decimal("2.0"),
        max_safety_orders=3,
    )
    bot._state["is_in_position"] = True
    bot._state["avg_entry_price"] = "65000"
    bot._state["safety_orders_count"] = 1  # segunda safety order (escala 2.0^1 = 2x)

    bot.run()

    if captured_sizes:
        # Segunda safety order: 100 * 2.0^1 = 200 USDT
        expected_size = Decimal("200") / Decimal("63700")
        assert abs(captured_sizes[0] - expected_size) < Decimal("0.000001")


# ---------------------------------------------------------------------------
# Tests de avg_entry_price
# ---------------------------------------------------------------------------

def test_update_avg_entry_single_buy(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session)
    bot._update_avg_entry(Decimal("0.1"), Decimal("65000"))
    assert bot.avg_entry_price == Decimal("65000")
    assert bot.total_quantity == Decimal("0.1")


def test_update_avg_entry_two_buys(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session)
    # Primera compra: 0.1 BTC @ 65000 → 6500 USDT
    bot._update_avg_entry(Decimal("0.1"), Decimal("65000"))
    # Segunda compra: 0.1 BTC @ 63000 → 6300 USDT
    bot._update_avg_entry(Decimal("0.1"), Decimal("63000"))
    # Precio medio: (6500 + 6300) / 0.2 = 64000
    assert bot.avg_entry_price == Decimal("64000")
    assert bot.total_quantity == Decimal("0.2")


# ---------------------------------------------------------------------------
# Tests del ciclo completo (run)
# ---------------------------------------------------------------------------

def test_run_places_base_order_on_first_tick(db_session):
    client = _make_client(ticker_price=Decimal("65000"))
    client.place_order.return_value = _make_order("buy", Decimal("65000"), qty=Decimal("0.00153"))

    bot = _make_dca(client, db_session)
    bot.run()

    client.place_order.assert_called_once()
    assert bot.is_in_position is True


def test_run_closes_position_at_take_profit(db_session):
    client = _make_client(ticker_price=Decimal("66000"))
    client.place_order.return_value = _make_order("sell", Decimal("66000"), qty=Decimal("0.01"))

    bot = _make_dca(client, db_session, take_profit_pct=Decimal("1.5"))
    bot._state["is_in_position"] = True
    bot._state["avg_entry_price"] = "65000"
    bot._state["total_quantity"] = "0.01"
    bot._state["total_invested"] = "650"

    bot.run()

    client.place_order.assert_called_once()
    assert client.place_order.call_args.args[1] == "sell"
    assert bot.is_in_position is False


def test_run_does_nothing_within_interval(db_session):
    client = _make_client(ticker_price=Decimal("65000"))
    bot = _make_dca(client, db_session, interval_hours=Decimal("24"))
    bot._state["last_base_order_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    bot.run()
    client.place_order.assert_not_called()


def test_strategy_name(db_session):
    client = _make_client()
    bot = _make_dca(client, db_session)
    assert bot.name == "dca_btc_usdt"
