from datetime import UTC, datetime, timedelta

import pytest

from execution.v8_xperp.adapter import SafetyError
from execution.v8_xperp.schedule import (
    REAL_CYCLE,
    SYNTHETIC_DEMO_CYCLE,
    ScheduleConfig,
    ScheduleModeStore,
    synthetic_events_between,
    synthetic_preview,
)
from execution.v8_xperp.target_transport import (
    OperationalTarget,
    decide_transport,
    scheduled_target,
)


ANCHOR = datetime(2026, 8, 1, tzinfo=UTC)


def config(**changes) -> ScheduleConfig:
    values = {
        "mode": SYNTHETIC_DEMO_CYCLE,
        "synthetic_enabled": True,
        "synthetic_anchor_utc": ANCHOR.isoformat(),
        "environment": "okx_demo",
        "live_execution_enabled": False,
    }
    values.update(changes)
    return ScheduleConfig(**values)


@pytest.mark.parametrize(
    ("offset", "phase", "target"),
    [
        (timedelta(0), "long_phase", "long 2x"),
        (timedelta(days=2), "short_phase", "short 2x"),
        (timedelta(days=3), "long_phase", "long 2x"),
        (timedelta(days=4), "long_phase", "long 2x"),
    ],
)
def test_exact_synthetic_phase_boundaries(offset, phase, target) -> None:
    preview = synthetic_preview(config(), now=ANCHOR + offset)
    assert preview.current_phase == phase
    assert preview.current_target == target


def test_multiple_cycles_have_deterministic_noncolliding_events() -> None:
    events = synthetic_events_between(
        config(),
        previous_observed_at=None,
        now=ANCHOR + timedelta(days=13),
    )
    assert len(events) == 10
    assert len({event.transition_id for event in events}) == len(events)
    assert events[-1].cycle_number == 3
    assert events[-1].event_type == "synthetic_halving"


def test_catch_up_executes_only_latest_required_target() -> None:
    due = scheduled_target(
        at=ANCHOR + timedelta(days=3, hours=1),
        previous_observed_at=ANCHOR + timedelta(days=1),
        schedule_config=config(),
    )
    assert due is not None
    assert due.kind == "accumulation_transition"
    assert due.direction == "long"


def test_restart_before_and_after_transition_is_idempotent() -> None:
    assert scheduled_target(
        at=ANCHOR + timedelta(days=1),
        previous_observed_at=ANCHOR + timedelta(hours=1),
        schedule_config=config(),
    ) is None
    first = scheduled_target(
        at=ANCHOR + timedelta(days=2, seconds=1),
        previous_observed_at=ANCHOR + timedelta(days=1),
        schedule_config=config(),
    )
    restarted = scheduled_target(
        at=ANCHOR + timedelta(days=2, minutes=1),
        previous_observed_at=ANCHOR + timedelta(days=2, seconds=1),
        schedule_config=config(),
    )
    assert first is not None and restarted is None


def test_synthetic_server_time_must_be_monotonic() -> None:
    with pytest.raises(SafetyError, match="backwards"):
        synthetic_events_between(
            config(),
            previous_observed_at=ANCHOR + timedelta(hours=2),
            now=ANCHOR + timedelta(hours=1),
        )


def test_preview_before_anchor_is_valid_without_prior_observation() -> None:
    preview = synthetic_preview(
        config(), now=ANCHOR - timedelta(minutes=1), previous_observed_at=None
    )
    assert preview.current_phase == "pending"
    assert preview.current_target == "flat"
    assert preview.transition_due is False


def test_day_four_persists_without_order_when_long_target_unchanged() -> None:
    active = OperationalTarget(
        "day3", "accumulation_transition", "long", "2", "0.01",
        "650", "0.0065", (ANCHOR + timedelta(days=3)).isoformat(), "cycle-0",
        state="EXECUTED",
    )
    result = decide_transport(
        now=ANCHOR + timedelta(days=4, seconds=1),
        previous_observed_at=ANCHOR + timedelta(days=3, hours=1),
        current_position=active.signed_contracts,
        active_target=active,
        bootstrap_target=None,
        schedule_config=config(),
    )
    assert result.action == "NOOP"
    assert result.target is not None
    assert result.target.kind == "synthetic_halving"


def test_real_and_synthetic_transition_ids_cannot_collide() -> None:
    real = scheduled_target(
        at=datetime(2025, 10, 12, 0, 9, 28, tzinfo=UTC),
        previous_observed_at=datetime(2025, 10, 12, 0, 9, 26, tzinfo=UTC),
        schedule_config=ScheduleConfig(mode=REAL_CYCLE),
    )
    synthetic = scheduled_target(
        at=ANCHOR,
        previous_observed_at=None,
        schedule_config=config(),
    )
    assert real is not None and synthetic is not None
    assert real.transition_id != synthetic.transition_id


@pytest.mark.parametrize(
    "bad",
    [
        config(environment="okx_live"),
        config(live_execution_enabled=True),
        config(synthetic_enabled=False),
        config(synthetic_anchor_utc=None),
    ],
)
def test_synthetic_mode_rejected_outside_strict_demo_envelope(bad) -> None:
    with pytest.raises(SafetyError):
        bad.validate()


def test_mode_switch_with_open_position_fails_closed(tmp_path) -> None:
    with pytest.raises(SafetyError, match="flat position"):
        ScheduleModeStore(tmp_path).switch(
            new_mode=SYNTHETIC_DEMO_CYCLE,
            service_stopped=True,
            reconciled=True,
            position_contracts="0.01",
            open_orders=0,
            non_terminal_intents=0,
            acknowledgement="switch to isolated synthetic schedule",
            config=config(),
            now=ANCHOR - timedelta(days=1),
        )


def test_mode_switch_archives_and_persists_new_mode(tmp_path) -> None:
    store = ScheduleModeStore(tmp_path)
    switched = store.switch(
        new_mode=SYNTHETIC_DEMO_CYCLE,
        service_stopped=True,
        reconciled=True,
        position_contracts="0",
        open_orders=0,
        non_terminal_intents=0,
        acknowledgement="switch to isolated synthetic schedule",
        config=config(),
        now=ANCHOR - timedelta(days=1),
    )
    assert store.load() == switched
    assert switched.mode == SYNTHETIC_DEMO_CYCLE
    assert len(list((tmp_path / "schedule_mode_archive").glob("*.json"))) == 1
