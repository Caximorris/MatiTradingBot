"""Tests para core/database.py — usa SQLite en memoria."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import (
    Base,
    BotState,
    Position,
    Trade,
    close_position,
    create_trade,
    get_or_create_bot_state,
    get_trades,
    set_bot_active,
    upsert_position,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Trade CRUD
# ---------------------------------------------------------------------------

def test_create_trade_sets_timestamp_automatically(session):
    trade = create_trade(
        session,
        symbol="BTC-USDT",
        side="buy",
        order_type="market",
        strategy="dca",
        quantity=Decimal("0.001"),
        price=Decimal("65000"),
        fee=Decimal("0.065"),
        fee_currency="USDT",
        order_id="okx-001",
        is_paper=True,
    )
    assert trade.id is not None
    assert trade.timestamp is not None


def test_get_trades_filters_by_symbol(session):
    create_trade(session, symbol="BTC-USDT", side="buy", order_type="market",
                 strategy="dca", quantity=Decimal("0.001"), price=Decimal("65000"),
                 fee=Decimal("0"), fee_currency="USDT", order_id="1", is_paper=True)
    create_trade(session, symbol="ETH-USDT", side="buy", order_type="market",
                 strategy="dca", quantity=Decimal("0.1"), price=Decimal("3000"),
                 fee=Decimal("0"), fee_currency="USDT", order_id="2", is_paper=True)

    btc_trades = get_trades(session, symbol="BTC-USDT")
    assert len(btc_trades) == 1
    assert btc_trades[0].symbol == "BTC-USDT"


def test_get_trades_filters_by_paper(session):
    create_trade(session, symbol="BTC-USDT", side="buy", order_type="market",
                 strategy="dca", quantity=Decimal("0.001"), price=Decimal("65000"),
                 fee=Decimal("0"), fee_currency="USDT", order_id="p1", is_paper=True)
    create_trade(session, symbol="BTC-USDT", side="buy", order_type="market",
                 strategy="dca", quantity=Decimal("0.001"), price=Decimal("65000"),
                 fee=Decimal("0"), fee_currency="USDT", order_id="l1", is_paper=False)

    paper = get_trades(session, is_paper=True)
    live = get_trades(session, is_paper=False)
    assert len(paper) == 1
    assert len(live) == 1


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

def test_upsert_position_creates_and_updates(session):
    pos = upsert_position(
        session, "ETH-USDT", "grid",
        side="long",
        entry_price=Decimal("3000"),
        quantity=Decimal("0.5"),
        current_price=Decimal("3000"),
        unrealized_pnl=Decimal("0"),
    )
    assert pos.id is not None

    # Actualiza el precio
    updated = upsert_position(
        session, "ETH-USDT", "grid",
        side="long",
        entry_price=Decimal("3000"),
        quantity=Decimal("0.5"),
        current_price=Decimal("3200"),
        unrealized_pnl=Decimal("100"),
    )
    assert updated.id == pos.id
    assert updated.current_price == Decimal("3200")


def test_close_position_removes_record(session):
    upsert_position(
        session, "SOL-USDT", "pro_trend",
        side="long",
        entry_price=Decimal("150"),
        quantity=Decimal("10"),
        current_price=Decimal("155"),
        unrealized_pnl=Decimal("50"),
    )
    close_position(session, "SOL-USDT", "pro_trend")
    remaining = session.query(Position).filter_by(symbol="SOL-USDT").count()
    assert remaining == 0


# ---------------------------------------------------------------------------
# BotState
# ---------------------------------------------------------------------------

def test_get_or_create_bot_state_idempotent(session):
    state1 = get_or_create_bot_state(session, "grid", "BTC-USDT", config={"grids": 10})
    state2 = get_or_create_bot_state(session, "grid", "BTC-USDT")
    assert state1.id == state2.id


def test_set_bot_active_toggles_flag(session):
    get_or_create_bot_state(session, "dca", "ETH-USDT")
    active = set_bot_active(session, "dca", "ETH-USDT", active=True)
    assert active.is_active is True

    inactive = set_bot_active(session, "dca", "ETH-USDT", active=False)
    assert inactive.is_active is False


def test_bot_state_config_json_roundtrip(session):
    config = {"grids": 10, "upper": 70000.0, "lower": 60000.0}
    state = get_or_create_bot_state(session, "grid", "SOL-USDT", config=config)
    assert state.get_config() == config
