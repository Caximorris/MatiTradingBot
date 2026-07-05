from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from strategies.prop_swing import PropSwingBot, PropSwingConfig


class FakeClient:
    is_paper = True

    def current_time(self):
        return datetime(2026, 7, 5, tzinfo=timezone.utc)


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


def test_prop_live_state_survives_reinstantiation(db_session):
    bot1 = PropSwingBot(client=FakeClient(), config=PropSwingConfig(), session=db_session)
    bot1._pos = {
        "side": "short",
        "qty": Decimal("0.12345678"),
        "entry": 100.0,
        "stop": 110.0,
        "tp1": 90.0,
        "tp1_done": False,
        "water_mark": 100.0,
        "atr_entry": 5.0,
        "mark": 99.0,
        "fee_open_unit": 0.1,
        "entry_ms": 1,
        "funding_paid": 0.0,
    }
    bot1._day = "2026-07-05"
    bot1._day_start_equity = 10_000.0
    bot1._entries_today = 1
    bot1._settle_idx = 7
    bot1._save_live_state()

    bot2 = PropSwingBot(client=FakeClient(), config=PropSwingConfig(), session=db_session)
    assert bot2._pos["qty"] == Decimal("0.12345678")
    assert bot2._pos["side"] == "short"
    assert bot2._day == "2026-07-05"
    assert bot2._entries_today == 1
    assert bot2._settle_idx == 7


def test_prop_live_state_row_is_not_active_bot(db_session):
    from core.database import BotState

    bot = PropSwingBot(client=FakeClient(), config=PropSwingConfig(), session=db_session)
    bot._save_live_state()
    row = (db_session.query(BotState)
           .filter_by(strategy_name="prop_swing", symbol="BTC-USDT").one())
    assert row.is_active is False


def test_prop_live_event_is_persisted(tmp_path, monkeypatch, db_session):
    monkeypatch.chdir(tmp_path)
    bot = PropSwingBot(client=FakeClient(), config=PropSwingConfig(), session=db_session)
    ts = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)
    bot._persist_live_event("signal", ts, {"decision": "skip", "reason": "test"})

    path = tmp_path / "data" / "runtime" / "prop_live_journal.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["kind"] == "signal"
    assert payload["reason"] == "test"
