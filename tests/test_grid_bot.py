"""Tests para strategies/grid_bot.py — paper mode, sin llamadas reales a OKX."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.exchange import OKXClient, OrderResult
from strategies.grid_bot import GridBot, GridConfig
from datetime import datetime, timezone


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


def _make_order(side, price, status="open", order_id="PAPER-001"):
    return OrderResult(
        order_id=order_id,
        symbol="BTC-USDT",
        side=side,
        order_type="limit",
        size=Decimal("0.016"),
        limit_price=price,
        filled_price=price if status == "filled" else None,
        filled_qty=Decimal("0.016") if status == "filled" else Decimal("0"),
        fee=Decimal("0.001"),
        fee_currency="USDT",
        status=status,
        is_paper=True,
        strategy="grid_btc_usdt",
        timestamp=_now(),
    )


def _make_client(ticker_price=Decimal("65000")):
    client = MagicMock(spec=OKXClient)
    client.is_paper = True
    client.get_ticker.return_value = ticker_price
    client.fill_paper_limit_orders.return_value = []
    return client


def _make_grid(client, session, **cfg_overrides):
    defaults = dict(
        symbol="BTC-USDT",
        upper_price=Decimal("70000"),
        lower_price=Decimal("60000"),
        num_grids=5,
        total_investment=Decimal("10000"),
        auto_adjust=True,
    )
    cfg = GridConfig(**{**defaults, **cfg_overrides})
    return GridBot(client=client, config=cfg, session=session)


# ---------------------------------------------------------------------------
# Tests de GridConfig
# ---------------------------------------------------------------------------

def test_grid_config_validates_range():
    with pytest.raises(ValueError, match="upper_price"):
        GridConfig(
            symbol="BTC-USDT",
            upper_price=Decimal("50000"),
            lower_price=Decimal("60000"),
            num_grids=5,
            total_investment=Decimal("1000"),
        )


def test_grid_config_validates_min_grids():
    with pytest.raises(ValueError, match="num_grids"):
        GridConfig(
            symbol="BTC-USDT",
            upper_price=Decimal("70000"),
            lower_price=Decimal("60000"),
            num_grids=1,
            total_investment=Decimal("1000"),
        )


def test_grid_config_roundtrip():
    cfg = GridConfig(
        symbol="ETH-USDT",
        upper_price=Decimal("4000"),
        lower_price=Decimal("3000"),
        num_grids=10,
        total_investment=Decimal("5000"),
        auto_adjust=False,
    )
    restored = GridConfig.from_dict(cfg.to_dict())
    assert restored.symbol == cfg.symbol
    assert restored.upper_price == cfg.upper_price
    assert restored.num_grids == cfg.num_grids


# ---------------------------------------------------------------------------
# Tests de cálculo de niveles
# ---------------------------------------------------------------------------

def test_calculate_levels_count(db_session):
    client = _make_client()
    bot = _make_grid(client, db_session)
    levels = bot._calculate_levels()
    assert len(levels) == 6  # num_grids + 1


def test_calculate_levels_boundaries(db_session):
    client = _make_client()
    bot = _make_grid(client, db_session)
    levels = bot._calculate_levels()
    assert levels[0] == Decimal("60000")
    assert levels[-1] == Decimal("70000")


def test_calculate_levels_are_uniform(db_session):
    client = _make_client()
    bot = _make_grid(client, db_session)
    levels = bot._calculate_levels()
    steps = [levels[i + 1] - levels[i] for i in range(len(levels) - 1)]
    # Todos los pasos deben ser iguales
    assert all(abs(s - steps[0]) < Decimal("0.01") for s in steps)


def test_order_size_is_positive(db_session):
    client = _make_client()
    bot = _make_grid(client, db_session)
    levels = bot._calculate_levels()
    size = bot._calculate_order_size(levels)
    assert size > Decimal("0")


# ---------------------------------------------------------------------------
# Tests de setup_grid
# ---------------------------------------------------------------------------

def test_setup_grid_places_buy_orders_below_price(db_session):
    client = _make_client(ticker_price=Decimal("65000"))  # precio en el medio del rango

    def side_effect(symbol, side, order_type, size, price, strategy):
        return _make_order(side, price, status="open", order_id=f"PAPER-{price}")

    client.place_order.side_effect = side_effect

    bot = _make_grid(client, db_session)
    bot.setup_grid()

    calls = client.place_order.call_args_list
    buy_calls = [c for c in calls if c.kwargs.get("side") == "buy" or (c.args and c.args[1] == "buy")]
    assert len(buy_calls) > 0


def test_setup_grid_idempotent(db_session):
    client = _make_client()
    client.place_order.return_value = _make_order("buy", Decimal("60000"), status="open")
    bot = _make_grid(client, db_session)
    bot.setup_grid()
    first_call_count = client.place_order.call_count

    # Segunda llamada no debe colocar más órdenes
    bot.setup_grid()
    assert client.place_order.call_count == first_call_count


def test_setup_grid_aborts_when_no_ticker(db_session):
    client = _make_client(ticker_price=Decimal("0"))
    bot = _make_grid(client, db_session)
    bot.setup_grid()
    client.place_order.assert_not_called()


# ---------------------------------------------------------------------------
# Tests de run() y fill handling
# ---------------------------------------------------------------------------

def test_run_processes_filled_buy_and_places_sell(db_session):
    client = _make_client(ticker_price=Decimal("65000"))

    # Simular que una orden de compra se llenó
    filled_buy = _make_order("buy", Decimal("62000"), status="filled", order_id="PAPER-BUY-1")
    client.fill_paper_limit_orders.return_value = [filled_buy]
    client.place_order.return_value = _make_order("sell", Decimal("64000"), status="open", order_id="PAPER-SELL-1")

    bot = _make_grid(client, db_session)
    # Inicializar niveles manualmente
    bot._state["levels"] = ["60000", "62000", "64000", "66000", "68000", "70000"]
    bot._state["order_size_base"] = "0.016"
    bot._state["active_orders"] = {"62000": {"order_id": "PAPER-BUY-1", "side": "buy", "level_idx": 1}}

    bot.run()

    # Debe haber colocado una orden de venta en el nivel superior
    sell_calls = [
        c for c in client.place_order.call_args_list
        if (c.kwargs.get("side") or (c.args[1] if len(c.args) > 1 else "")) == "sell"
    ]
    assert len(sell_calls) == 1


def test_run_processes_filled_sell_and_places_buy(db_session):
    client = _make_client(ticker_price=Decimal("65000"))

    filled_sell = _make_order("sell", Decimal("64000"), status="filled", order_id="PAPER-SELL-1")
    client.fill_paper_limit_orders.return_value = [filled_sell]
    client.place_order.return_value = _make_order("buy", Decimal("62000"), status="open", order_id="PAPER-BUY-2")

    bot = _make_grid(client, db_session)
    bot._state["levels"] = ["60000", "62000", "64000", "66000", "68000", "70000"]
    bot._state["order_size_base"] = "0.016"
    bot._state["active_orders"] = {"64000": {"order_id": "PAPER-SELL-1", "side": "sell", "level_idx": 2}}

    bot.run()

    buy_calls = [
        c for c in client.place_order.call_args_list
        if (c.kwargs.get("side") or (c.args[1] if len(c.args) > 1 else "")) == "buy"
    ]
    assert len(buy_calls) == 1


# ---------------------------------------------------------------------------
# Tests de auto_adjust
# ---------------------------------------------------------------------------

def test_run_reinitializes_when_price_out_of_range(db_session):
    client = _make_client(ticker_price=Decimal("55000"))  # fuera del rango [60000, 70000]
    client.place_order.return_value = _make_order("buy", Decimal("55000"), status="open")

    bot = _make_grid(client, db_session)
    bot._state["active_orders"] = {"60000": {"order_id": "PAPER-001", "side": "buy", "level_idx": 0}}

    bot.run()

    # Con auto_adjust=True, debe cancelar y reiniciar → se llama cancel_order
    client.cancel_order.assert_called()


def test_run_warns_out_of_range_no_auto_adjust(db_session):
    client = _make_client(ticker_price=Decimal("55000"))
    bot = _make_grid(client, db_session, auto_adjust=False)
    bot._state["active_orders"] = {}

    bot.run()

    # Con auto_adjust=False y sin órdenes activas, no debe colocar ni cancelar nada
    client.place_order.assert_not_called()
    client.cancel_order.assert_not_called()


# ---------------------------------------------------------------------------
# Tests de should_enter / should_exit
# ---------------------------------------------------------------------------

def test_should_enter_when_price_in_range(db_session):
    client = _make_client(ticker_price=Decimal("65000"))
    bot = _make_grid(client, db_session)
    assert bot.should_enter() is True


def test_should_not_enter_when_price_out_of_range(db_session):
    client = _make_client(ticker_price=Decimal("75000"))
    bot = _make_grid(client, db_session)
    assert bot.should_enter() is False


def test_should_exit_when_price_out_of_range_and_no_auto_adjust(db_session):
    client = _make_client(ticker_price=Decimal("55000"))
    bot = _make_grid(client, db_session, auto_adjust=False)
    assert bot.should_exit() is True


def test_should_not_exit_with_auto_adjust_enabled(db_session):
    client = _make_client(ticker_price=Decimal("55000"))
    bot = _make_grid(client, db_session, auto_adjust=True)
    assert bot.should_exit() is False


# ---------------------------------------------------------------------------
# Test de nombre de estrategia
# ---------------------------------------------------------------------------

def test_strategy_name(db_session):
    client = _make_client()
    bot = _make_grid(client, db_session)
    assert bot.name == "grid_btc_usdt"
