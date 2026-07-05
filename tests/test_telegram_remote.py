from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tools.telegram_remote import (
    format_report,
    format_status,
    handle_command,
    prop_bot_rows,
    set_prop_active,
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


def test_prop_pause_and_resume_only_touch_prop(db_session):
    _add_bot(db_session, "prop_swing_btc_usdt", active=True)
    _add_bot(db_session, "prop_swing", active=False)
    _add_bot(db_session, "swing_allocator_btc_usdt", active=True)

    @contextmanager
    def get_session():
        yield db_session

    assert set_prop_active(db_session, False) == ["prop_swing_btc_usdt"]
    assert prop_bot_rows(db_session)[0].is_active is False
    assert swing_bot_rows(db_session)[0].is_active is True
    assert "PROP REANUDADO" in handle_command("/prop_resume", get_session)
    assert prop_bot_rows(db_session)[0].is_active is True


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


def test_parse_daily_checks_and_streak():
    from tools.telegram_remote import format_parity, parse_daily_checks, parity_streak
    log = (
        "===== daily_checks 2026-07-05T12:10:00Z =====\n"
        "timestamp,2026-07-05T12:00:00+00:00\n"
        "live_target,0.2000\n"
        "live_signals,regime_bear;halving_bear_onset\n"
        "PARITY_OK\n"
        "no_data\n"
        "===== daily_checks 2026-07-06T12:10:00Z =====\n"
        "live_target,0.2000\n"
        "PARITY_FAIL\n"
        "===== daily_checks 2026-07-07T12:10:00Z =====\n"
        "live_target,0.2000\n"
        "PARITY_OK\n"
    )
    blocks = parse_daily_checks(log)
    assert [b["parity"] for b in blocks] == [True, False, True]
    assert blocks[0]["target"] == "0.2000"
    assert parity_streak(blocks) == 1          # el FAIL corta la racha
    out = format_parity(blocks)
    assert "1/30" in out and "OK" in out
    assert "PARIDAD" in format_parity([])


def test_build_equity_series_reconstructs_holdings():
    from tools.tg_charts import build_equity_series
    h = 3_600_000
    t0 = 1_751_600_000_000
    rebalances = [
        {"timestamp": "2026-07-04T08:00:00+00:00", "direction": "INIT",
         "btc_pct_after": 0.6, "price": 100.0, "portfolio_usdt": 1000.0},
        {"timestamp": "2026-07-04T10:00:00+00:00", "direction": "SELL",
         "btc_pct_after": 0.2, "price": 100.0, "portfolio_usdt": 1000.0},
    ]
    # timestamps de velas alineados con los de los rebalanceos
    import datetime as dt
    base = int(dt.datetime(2026, 7, 4, 8, tzinfo=dt.timezone.utc).timestamp() * 1000)
    candles = [(base + i * h, 100.0 + i * 10) for i in range(4)]  # 100,110,120,130

    s = build_equity_series(rebalances, candles)
    # INIT: 6 BTC + 400 USDT. Velas 0-1: 6*100+400=1000, 6*110+400=1060
    assert s["bot"][0] == 1000.0 and s["bot"][1] == 1060.0
    # SELL en vela 2 (10:00): 2 BTC + 800 USDT -> 2*120+800=1040, 2*130+800=1060
    assert s["bot"][2] == 1040.0 and s["bot"][3] == 1060.0
    # B&H: 10 BTC desde el INIT -> 1000,1100,1200,1300
    assert s["bnh"] == [1000.0, 1100.0, 1200.0, 1300.0]
    assert [e[2] for e in s["events"]] == ["INIT", "SELL"]
    assert build_equity_series([], candles)["ts"] == []


def test_format_heartbeat_summarizes():
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone
    from tools.telegram_remote import format_heartbeat
    now = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)
    rows = [_row(True, now - timedelta(minutes=1))]
    balances = {"BTC": Decimal("0.02"), "USDT": Decimal("8000")}
    rebalances = [{"timestamp": "2026-07-04T08:59:00+00:00", "portfolio_usdt": 10000.0,
                   "price": 62578.0}]
    hb = format_heartbeat(rows, balances, Decimal("62578"), rebalances, [], now)
    assert "vivo" in hb and "parity 0/30" in hb and "1 rebalanceos" in hb
    hb_paused = format_heartbeat([_row(False)], balances, None, [], [], now)
    assert "pausado" in hb_paused
