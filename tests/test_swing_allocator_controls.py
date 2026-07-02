from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig


class FakeClient:
    def __init__(self, price: Decimal = Decimal("100")):
        self.price = price
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def current_time(self):
        return self.now

    def get_ticker(self, symbol: str):
        return self.price

    def get_ohlcv(self, symbol: str, limit: int = 2):
        return pd.DataFrame(
            {
                "timestamp": [1, 2],
                "open": [100.0, 100.0],
                "high": [101.0, 101.0],
                "low": [99.0, 99.0],
                "close": [100.0, 100.0],
                "volume": [1.0, 1.0],
            }
        )


class BacktestClient(FakeClient):
    """El nombre de clase exacto activa la rama backtest en _is_backtest_client()."""


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


class BlockingRisk:
    def check_daily_loss(self):
        return True, -123.45


def test_market_data_rejects_anomalous_price_jump():
    bot = SwingAllocatorBot(
        client=FakeClient(price=Decimal("140")),
        config=SwingAllocatorConfig(max_price_jump_pct=0.25),
    )
    assert bot._market_data_ok() is False


def test_risk_manager_blocks_swing_buys_on_daily_loss():
    bot = SwingAllocatorBot(
        client=FakeClient(),
        config=SwingAllocatorConfig(),
        risk_manager=BlockingRisk(),
    )
    assert bot._risk_allows_buy(Decimal("100")) is False


def test_live_rebalance_is_persisted_as_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bot = SwingAllocatorBot(
        client=FakeClient(),
        config=SwingAllocatorConfig(persist_live_rebalance_log=True),
    )

    bot._log_rebalance(
        pct_before=0.6,
        pct_target=0.8,
        pct_after=0.8,
        direction="BUY",
        price=100.0,
        qty=1.0,
        portfolio_usdt=1000.0,
        signals=["test"],
    )

    path = tmp_path / "data" / "runtime" / "swing_rebalances.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["strategy"] == "swing_allocator_btc_usdt"
    assert payload["direction"] == "BUY"


def test_price_jump_filter_is_noop_in_backtest():
    # M2 auditoria v5: el control de tick anomalo es SOLO live/paper.
    bot = SwingAllocatorBot(
        client=BacktestClient(price=Decimal("140")),
        config=SwingAllocatorConfig(max_price_jump_pct=0.25),
    )
    assert bot._live_mode is False
    assert bot._market_data_ok() is True


def test_live_state_survives_reinstantiation(db_session):
    # El scheduler de `start` crea una instancia nueva por tick: initialized y
    # last_rebalance deben sobrevivir en BotState.
    reb_time = datetime(2026, 6, 30, 8, 0, tzinfo=timezone.utc)

    bot1 = SwingAllocatorBot(client=FakeClient(), config=SwingAllocatorConfig(), session=db_session)
    assert bot1._initialized is False
    bot1._last_rebalance = reb_time
    bot1._mark_initialized()

    bot2 = SwingAllocatorBot(client=FakeClient(), config=SwingAllocatorConfig(), session=db_session)
    assert bot2._initialized is True
    assert bot2._last_rebalance == reb_time


def test_live_state_row_is_not_an_active_bot(db_session):
    from core.database import BotState

    bot = SwingAllocatorBot(client=FakeClient(), config=SwingAllocatorConfig(), session=db_session)
    bot._mark_initialized()
    row = (db_session.query(BotState)
           .filter_by(strategy_name="swing_allocator", symbol="BTC-USDT").one())
    assert row.is_active is False


def test_live_cadence_evaluates_once_per_4h_block(db_session):
    client = FakeClient()
    bot = SwingAllocatorBot(client=client, config=SwingAllocatorConfig(), session=db_session)
    bot._initialized = True
    bot._cooldown_ok = lambda: True
    bot._market_data_ok = lambda: True
    bot._current_btc_pct = lambda: 0.6

    calls = []

    def fake_target(current):
        calls.append(client.now)
        return 0.6, []   # diff 0 -> no rebalancea

    bot._compute_target = fake_target

    client.now = datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc)
    bot.run()
    assert len(calls) == 1

    client.now += timedelta(minutes=30)   # mismo bloque 12:00-15:59
    bot.run()
    assert len(calls) == 1

    client.now = datetime(2026, 7, 1, 16, 1, tzinfo=timezone.utc)   # bloque siguiente
    bot.run()
    assert len(calls) == 2

    # El bloque consumido sobrevive a una re-instanciacion (mismo tick repetido tras restart)
    bot2 = SwingAllocatorBot(client=client, config=SwingAllocatorConfig(), session=db_session)
    assert bot2._live_state["last_eval_block"] == "2026-07-01T4"


def test_live_market_data_failure_does_not_consume_block(db_session):
    client = FakeClient()
    bot = SwingAllocatorBot(client=client, config=SwingAllocatorConfig(), session=db_session)
    bot._initialized = True
    bot._cooldown_ok = lambda: True
    bot._market_data_ok = lambda: False   # API caida en este tick

    client.now = datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc)
    bot.run()
    assert bot._live_state["last_eval_block"] is None   # se reintenta en el proximo tick
