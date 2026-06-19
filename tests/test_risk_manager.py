"""
Tests para core/risk_manager.py.

RiskManager usa get_session() internamente (no recibe sesión en el constructor),
así que lo parcheamos con un context manager que devuelve la sesión de test.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, BotState, Position, Trade
from core.exchange import OKXClient
from core.risk_manager import RiskManager


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


@pytest.fixture
def patched_session(db_session):
    """Reemplaza get_session() en risk_manager con la sesión de test."""
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=db_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("core.risk_manager.get_session", return_value=mock_ctx):
        yield db_session


def _make_settings(**overrides):
    s = MagicMock()
    s.max_portfolio_risk_pct = Decimal("2.0")
    s.max_open_positions = 5
    s.daily_loss_limit_pct = Decimal("5.0")
    s.trading_pairs = ["BTC-USDT"]
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_client(balance_usdt: Decimal = Decimal("10000")):
    client = MagicMock(spec=OKXClient)
    client.get_balance.return_value = {"USDT": balance_usdt}
    client.get_open_orders.return_value = []
    client.cancel_order.return_value = True
    return client


def _make_rm(client=None, **settings_overrides):
    return RiskManager(
        client=client or _make_client(),
        app_settings=_make_settings(**settings_overrides),
    )


def _insert_trade(session, pnl: Decimal, is_paper: bool = False):
    trade = Trade(
        order_id=f"T-{datetime.now().timestamp()}",
        symbol="BTC-USDT",
        side="sell",
        order_type="market",
        quantity=Decimal("0.01"),
        price=Decimal("65000"),
        fee=Decimal("0"),
        fee_currency="USDT",
        pnl=pnl,
        strategy="test",
        is_paper=is_paper,
        timestamp=datetime.now(timezone.utc),
    )
    session.add(trade)
    session.commit()


def _insert_position(session, symbol="BTC-USDT"):
    pos = Position(
        symbol=symbol,
        side="long",
        quantity=Decimal("0.01"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        strategy="test",
        opened_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(pos)
    session.commit()


def _insert_bot_state(session, name: str, is_active: bool = True):
    bot = BotState(
        strategy_name=name,
        symbol="BTC-USDT",
        is_active=is_active,
        config_json="{}",
        created_at=datetime.now(timezone.utc),
    )
    session.add(bot)
    session.commit()


# ---------------------------------------------------------------------------
# Tests can_open_position
# ---------------------------------------------------------------------------

def test_can_open_position_allows_valid_trade(patched_session):
    rm = _make_rm()
    ok, reason = rm.can_open_position("BTC-USDT", Decimal("100"))
    assert ok is True
    assert reason == ""


def test_can_open_position_blocks_when_daily_loss_exceeded(patched_session):
    # balance 10000 USDT, límite 5% = 500 → pérdida de 600 supera el límite
    _insert_trade(patched_session, pnl=Decimal("-600"))
    rm = _make_rm(daily_loss_limit_pct=Decimal("5.0"))
    ok, reason = rm.can_open_position("BTC-USDT", Decimal("100"))
    assert ok is False
    assert reason != ""


def test_can_open_position_blocks_when_max_positions_reached(patched_session):
    _insert_position(patched_session)
    rm = _make_rm(max_open_positions=1)
    # Ya hay 1 posición abierta → límite exacto (>= no permite más)
    ok, reason = rm.can_open_position("BTC-USDT", Decimal("100"))
    assert ok is False
    assert reason != ""


def test_can_open_position_blocks_portfolio_risk_exceeded(patched_session):
    # balance 10000, max_risk 2% = 200 USDT → 9999 > 200
    rm = _make_rm()
    ok, reason = rm.can_open_position("BTC-USDT", Decimal("9999"))
    assert ok is False
    assert reason != ""


def test_can_open_position_blocks_blacklisted_symbol(patched_session):
    rm = _make_rm()
    rm.add_to_blacklist("DOGE-USDT")
    ok, reason = rm.can_open_position("DOGE-USDT", Decimal("100"))
    assert ok is False
    assert "lista negra" in reason.lower() or "blacklist" in reason.lower()


def test_can_open_position_blocks_insufficient_balance(patched_session):
    client = _make_client(balance_usdt=Decimal("50"))
    rm = RiskManager(client=client, app_settings=_make_settings())
    ok, reason = rm.can_open_position("BTC-USDT", Decimal("100"))
    assert ok is False
    assert reason != ""


# ---------------------------------------------------------------------------
# Tests calculate_position_size
# ---------------------------------------------------------------------------

def test_calculate_position_size_returns_positive():
    rm = _make_rm()
    size = rm.calculate_position_size(
        symbol="BTC-USDT",
        risk_pct=Decimal("1.0"),
        entry=Decimal("65000"),
        stop_loss=Decimal("63000"),
    )
    assert size > Decimal("0")


def test_calculate_position_size_is_decimal():
    rm = _make_rm()
    size = rm.calculate_position_size(
        symbol="BTC-USDT",
        risk_pct=Decimal("1.0"),
        entry=Decimal("65000"),
        stop_loss=Decimal("63000"),
    )
    assert isinstance(size, Decimal)


def test_calculate_position_size_scales_with_risk_pct():
    """Mayor % de riesgo → posición más grande."""
    rm = _make_rm()
    size_1 = rm.calculate_position_size("BTC-USDT", Decimal("1.0"), Decimal("65000"), Decimal("63000"))
    size_2 = rm.calculate_position_size("BTC-USDT", Decimal("2.0"), Decimal("65000"), Decimal("63000"))
    assert size_2 > size_1


def test_calculate_position_size_wider_stop_reduces_units():
    """
    Stop más amplio → mayor riesgo por unidad → menos unidades para
    el mismo importe arriesgado.
    """
    rm = _make_rm()
    size_tight = rm.calculate_position_size("BTC-USDT", Decimal("1.0"), Decimal("65000"), Decimal("64500"))
    size_wide = rm.calculate_position_size("BTC-USDT", Decimal("1.0"), Decimal("65000"), Decimal("60000"))
    assert size_tight > size_wide


def test_calculate_position_size_returns_zero_on_invalid_stop():
    """entry <= stop_loss → retorna 0."""
    rm = _make_rm()
    size = rm.calculate_position_size("BTC-USDT", Decimal("1.0"), Decimal("60000"), Decimal("65000"))
    assert size == Decimal("0")


# ---------------------------------------------------------------------------
# Tests check_daily_loss
# ---------------------------------------------------------------------------

def test_check_daily_loss_no_trades(patched_session):
    rm = _make_rm()
    limit_reached, pnl = rm.check_daily_loss()
    assert limit_reached is False
    assert pnl == 0.0


def test_check_daily_loss_below_limit(patched_session):
    _insert_trade(patched_session, pnl=Decimal("-100"))  # 1% de 10000
    rm = _make_rm(daily_loss_limit_pct=Decimal("5.0"))
    limit_reached, pnl = rm.check_daily_loss()
    assert limit_reached is False
    assert pnl < 0


def test_check_daily_loss_at_limit(patched_session):
    _insert_trade(patched_session, pnl=Decimal("-500"))  # exactamente 5% de 10000
    rm = _make_rm(daily_loss_limit_pct=Decimal("5.0"))
    limit_reached, _ = rm.check_daily_loss()
    assert limit_reached is True


def test_check_daily_loss_gains_dont_trigger_limit(patched_session):
    _insert_trade(patched_session, pnl=Decimal("1000"))
    rm = _make_rm(daily_loss_limit_pct=Decimal("5.0"))
    limit_reached, _ = rm.check_daily_loss()
    assert limit_reached is False


# ---------------------------------------------------------------------------
# Tests blacklist
# ---------------------------------------------------------------------------

def test_add_to_blacklist():
    rm = _make_rm()
    rm.add_to_blacklist("SHIB-USDT")
    assert "SHIB-USDT" in rm.blacklist


def test_remove_from_blacklist():
    rm = _make_rm()
    rm.add_to_blacklist("SHIB-USDT")
    rm.remove_from_blacklist("SHIB-USDT")
    assert "SHIB-USDT" not in rm.blacklist


def test_blacklist_is_case_insensitive():
    rm = _make_rm()
    rm.add_to_blacklist("shib-usdt")
    assert "SHIB-USDT" in rm.blacklist


# ---------------------------------------------------------------------------
# Tests emergency_stop
# ---------------------------------------------------------------------------

def test_emergency_stop_cancels_open_orders(patched_session):
    open_order = {"order_id": "PAPER-001"}
    client = _make_client()
    client.get_open_orders.return_value = [open_order]

    rm = RiskManager(client=client, app_settings=_make_settings(trading_pairs=["BTC-USDT"]))
    rm.emergency_stop()

    client.cancel_order.assert_called_once_with("PAPER-001", "BTC-USDT")


def test_emergency_stop_deactivates_all_bots(patched_session):
    _insert_bot_state(patched_session, "grid_btc", is_active=True)
    _insert_bot_state(patched_session, "dca_eth", is_active=True)

    rm = _make_rm()
    rm.emergency_stop()

    bots = patched_session.query(BotState).all()
    assert all(not b.is_active for b in bots)


def test_emergency_stop_handles_exchange_error_gracefully(patched_session):
    client = _make_client()
    client.get_open_orders.side_effect = Exception("OKX caído")

    rm = RiskManager(client=client, app_settings=_make_settings())
    try:
        rm.emergency_stop()
    except Exception:
        pytest.fail("emergency_stop propagó excepción cuando el exchange falló")
