from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tools.telegram_remote import (
    format_report,
    format_status,
    handle_command,
    set_swing_active,
    swing_bot_rows,
)


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.database import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_bot(session, name, symbol="BTC-USDT", active=True):
    from core.database import BotState
    session.add(BotState(
        strategy_name=name, symbol=symbol, is_active=active,
        config_json="{}", created_at=datetime.now(timezone.utc),
    ))
    session.flush()


def test_set_swing_active_ignores_internal_state_row(db_session):
    _add_bot(db_session, "swing_allocator_btc_usdt", active=True)
    _add_bot(db_session, "swing_allocator", active=False)   # fila de estado interno
    _add_bot(db_session, "pro_trend_btc_usdt", active=True)  # otra estrategia: no tocar

    names = set_swing_active(db_session, False)

    assert names == ["swing_allocator_btc_usdt"]
    rows = {r.strategy_name: r.is_active for r in swing_bot_rows(db_session)}
    assert rows["swing_allocator_btc_usdt"] is False


def test_pause_and_resume_commands_flip_is_active(db_session):
    _add_bot(db_session, "swing_allocator_btc_usdt", active=True)

    @contextmanager
    def get_session():
        yield db_session

    assert "PAUSADO" in handle_command("/pause", get_session)
    assert swing_bot_rows(db_session)[0].is_active is False
    assert "REANUDADO" in handle_command("/resume", get_session)
    assert swing_bot_rows(db_session)[0].is_active is True


def test_unknown_command_returns_help(db_session):
    @contextmanager
    def get_session():
        yield db_session

    assert "/status" in handle_command("/loquesea", get_session)


def _row(active=True, last_run=None):
    return SimpleNamespace(
        strategy_name="swing_allocator_btc_usdt", symbol="BTC-USDT",
        is_active=active, last_run=last_run,
    )


def test_format_status_reports_alive_paused_and_stale():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    from decimal import Decimal
    balances = {"BTC": Decimal("0.5"), "USDT": Decimal("1000")}

    alive = format_status([_row(True, now - timedelta(minutes=2))], balances, Decimal("100000"), [], now)
    assert "VIVO" in alive
    assert "Portfolio: $51,000.00" in alive   # total = 0.5*100k+1000, no la pata BTC ($50k)

    paused = format_status([_row(False)], balances, None, [], now)
    assert "PAUSADO" in paused

    stale = format_status([_row(True, now - timedelta(hours=3))], balances, None, [], now)
    assert "SIN TICK" in stale


def test_format_report_truncates_and_counts():
    rebalances = [
        {"timestamp": f"2026-07-{d:02d}T12:00:00+00:00", "direction": "BUY",
         "btc_pct_before": 0.6, "btc_pct_after": 0.8, "price": 100000.0,
         "portfolio_usdt": 12000.0, "signals": ["regime_bull"]}
        for d in range(1, 16)
    ]
    out = format_report(rebalances, n=10)
    assert "15 rebalanceo(s)" in out
    assert "5 anteriores omitidos" in out
    assert out.count("regime_bull") == 10
