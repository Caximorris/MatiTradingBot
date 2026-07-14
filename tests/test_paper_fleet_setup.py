from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tools.paper_fleet_setup import desired_fleet, reconcile_fleet


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


def _add(db_session, name: str, active: bool, config: dict | None = None):
    from core.database import BotState

    db_session.add(BotState(
        strategy_name=name,
        symbol="BTC-USDT",
        is_active=active,
        config_json=json.dumps(config or {}),
        created_at=datetime.now(timezone.utc),
    ))
    db_session.flush()


def test_reconcile_sets_exact_active_fleet_and_preserves_internal_state(db_session):
    _add(db_session, "swing_allocator_btc_usdt", True)
    _add(db_session, "swing_allocator", False, {"initialized": True})
    _add(db_session, "swing_allocator_v5_btc_usdt", True)
    _add(db_session, "swing_allocator_v5", False, {"initialized": True})
    _add(db_session, "swing_allocator_v6", False, {"last_eval_block": "2026-07-14T2"})
    _add(db_session, "swing_allocator_demo", False, {"initialized": True})
    _add(db_session, "prop_swing", False, {"position": None})
    _add(db_session, "pro_trend_btc_usdt", True)

    result = reconcile_fleet(db_session, desired_fleet())

    from core.database import BotState

    rows = {row.strategy_name: row for row in db_session.query(BotState).all()}
    active = {name for name, row in rows.items() if row.is_active}
    assert active == {
        "swing_allocator_v6_btc_usdt",
        "swing_allocator_demo_btc_usdt",
    }
    assert "swing_allocator_btc_usdt" not in rows
    assert "swing_allocator" not in rows
    assert "swing_allocator_v5_btc_usdt" not in rows
    assert rows["swing_allocator_v5"].get_config()["initialized"] is True
    assert rows["pro_trend_btc_usdt"].is_active is False
    assert rows["swing_allocator_v6"].get_config()["last_eval_block"] == "2026-07-14T2"
    assert rows["swing_allocator_demo"].get_config()["initialized"] is True
    assert rows["prop_swing"].get_config()["position"] is None
    assert result["removed"] == [
        "swing_allocator",
        "swing_allocator_btc_usdt",
        "swing_allocator_v5_btc_usdt",
    ]


def test_reconcile_retires_prop_swing_without_deleting_its_history(db_session):
    """Prop Firm's CFT gate numbers were invalid (funding-accrual bug, EXP-013):
    45.4% pass vs the >=60% adoption gate. Retired from the active fleet 2026-07-14 —
    reconcile must deactivate the operable bot, not delete it (wallet/journal survive
    for audit, matching how v5 was retired earlier)."""
    _add(db_session, "prop_swing_btc_usdt", True, {"paper_portfolio_id": "prop_cft"})

    result = reconcile_fleet(db_session, desired_fleet())

    from core.database import BotState

    row = db_session.query(BotState).filter_by(strategy_name="prop_swing_btc_usdt").one()
    assert row.is_active is False
    assert row.get_config()["paper_portfolio_id"] == "prop_cft"
    assert "prop_swing_btc_usdt" in result["deactivated"]
    assert "prop_swing_btc_usdt" not in result["removed"]


def test_reconcile_is_idempotent_and_configs_are_v6_explicit(db_session):
    specs = desired_fleet()
    reconcile_fleet(db_session, specs)
    reconcile_fleet(db_session, specs)

    from core.database import BotState

    rows = db_session.query(BotState).all()
    assert len(rows) == 2
    by_name = {row.strategy_name: row for row in rows}
    assert by_name["swing_allocator_v6_btc_usdt"].get_config()["use_funding_overlay"] is True
    demo = by_name["swing_allocator_demo_btc_usdt"].get_config()
    assert demo["execution"] == "okx_demo"
    assert demo["use_phase_policy_router"] is True
