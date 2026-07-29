from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from execution.v8_xperp.adapter import SafetyError
from execution.v8_xperp.bootstrap import BootstrapDecision
from execution.v8_xperp.target_transport import (
    OperationalTarget,
    OperationalTargetLedger,
    decide_transport,
    target_from_bootstrap,
)
from strategies.cycle_phase_clock import CyclePhaseClock


HALVING = datetime(2024, 4, 20, 0, 9, 27, tzinfo=UTC)
CLOCK = CyclePhaseClock(halving_timestamps=(HALVING,))
BEAR = HALVING + timedelta(days=540)


def target(direction="short", contracts="0.015"):
    return OperationalTarget(
        "target-1", "operational_bootstrap", direction, "0.3", contracts,
        "975", "0.01", (BEAR + timedelta(days=1)).isoformat(), "source",
        state="EXECUTED",
    )


def bootstrap() -> BootstrapDecision:
    return BootstrapDecision(
        "bootstrap-1", "okx_demo", "account", "inst", "short_phase", "short",
        "day_540", BEAR.isoformat(), (BEAR + timedelta(hours=1)).isoformat(),
        "100", (BEAR + timedelta(days=1)).isoformat(), "60",
        "okx_eea_btc_usd_index", "a" * 64, "b" * 64, "0.666", "0.20",
        "100000", "0.3", "2", "2", "2", "0.3", "0.25", True,
        "dynamic bootstrap allowed", "0.015", "975", "0.00975",
    )


def test_restart_adopts_without_recalculating_bootstrap() -> None:
    active = target()
    result = decide_transport(
        now=BEAR + timedelta(days=10),
        previous_observed_at=BEAR + timedelta(days=9),
        current_position=Decimal("-0.015"),
        active_target=active,
        bootstrap_target=target_from_bootstrap(
            replace(bootstrap(), current_price="30", calculated_leverage="0.1")
        ),
        clock=CLOCK,
    )
    assert result.action == "ADOPT"
    assert result.target.transition_id == active.transition_id
    assert result.target.strategy_leverage == "0.3"


def test_unchanged_target_does_not_resubmit() -> None:
    active = target()
    result = decide_transport(
        now=BEAR + timedelta(days=3),
        previous_observed_at=BEAR + timedelta(days=2),
        current_position=active.signed_contracts,
        active_target=active,
        bootstrap_target=None,
        clock=CLOCK,
    )
    assert result.action == "ADOPT"


def test_scheduled_transition_replaces_bootstrap_with_two_x() -> None:
    long_at = HALVING + timedelta(days=900)
    active = target()
    result = decide_transport(
        now=long_at + timedelta(seconds=1),
        previous_observed_at=long_at - timedelta(seconds=1),
        current_position=active.signed_contracts,
        active_target=active,
        bootstrap_target=None,
        clock=CLOCK,
    )
    assert result.action == "EXECUTE"
    assert result.target.kind == "scheduled_540_900"
    assert result.target.direction == "long"
    assert result.target.strategy_leverage == "2"


def test_flat_mid_phase_emits_bootstrap_once() -> None:
    boot = target_from_bootstrap(bootstrap())
    result = decide_transport(
        now=BEAR + timedelta(days=2),
        previous_observed_at=None,
        current_position=Decimal("0"),
        active_target=None,
        bootstrap_target=boot,
        clock=CLOCK,
    )
    assert result == type(result)("EXECUTE", boot, "new flat mid-phase bootstrap")


def test_unknown_position_without_target_fails_closed() -> None:
    with pytest.raises(SafetyError, match="lacks"):
        decide_transport(
            now=BEAR + timedelta(days=2), previous_observed_at=None,
            current_position=Decimal("1"), active_target=None,
            bootstrap_target=None, clock=CLOCK,
        )


def test_target_ledger_supersedes_and_is_restart_deterministic(tmp_path) -> None:
    ledger = OperationalTargetLedger(tmp_path / "targets.json")
    first = target()
    assert ledger.create(first) == first
    assert ledger.active() == first
    second = replace(first, transition_id="scheduled", kind="scheduled_540_900")
    ledger.create(second)
    assert OperationalTargetLedger(ledger.path).active() == second
    assert ledger.load()[0].state == "SUPERSEDED"
