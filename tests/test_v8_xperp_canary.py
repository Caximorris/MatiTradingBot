from decimal import Decimal

import pytest

from execution.v8_xperp.adapter import SafetyError
from execution.v8_xperp.canary import CanaryConfig, KillAction, cap_target, kill_action


def config(**overrides) -> CanaryConfig:
    values = {
        "V8_XPERP_CONTINUOUS_DEMO_ENABLED": "true",
        "V8_XPERP_MAX_NOTIONAL_USD": "1000",
        "V8_XPERP_DAILY_LOSS_USD": "25",
        "V8_XPERP_TOTAL_LOSS_USD": "100",
        "V8_XPERP_MIN_LIQ_DISTANCE_PCT": "35",
        "V8_XPERP_MAX_SPREAD_BPS": "20",
        "V8_XPERP_MAX_SLIPPAGE_BPS": "15",
        "V8_XPERP_MAX_MARKET_AGE_SECONDS": "5",
        "V8_XPERP_MAX_STREAM_AGE_SECONDS": "15",
        "V8_XPERP_MAX_CLOCK_DRIFT_SECONDS": "2",
        "V8_XPERP_MAX_API_FAILURES": "3",
        "V8_XPERP_MAX_RECONCILIATION_SECONDS": "30",
        **overrides,
    }
    return CanaryConfig.from_env(values)


@pytest.mark.parametrize("field, value", [
    ("V8_XPERP_MAX_NOTIONAL_USD", "1000.0001"),
    ("V8_XPERP_DAILY_LOSS_USD", "25.01"),
    ("V8_XPERP_TOTAL_LOSS_USD", "100.01"),
    ("V8_XPERP_MIN_LIQ_DISTANCE_PCT", "34.999"),
    ("V8_XPERP_MAX_SPREAD_BPS", "20.001"),
    ("V8_XPERP_MAX_SLIPPAGE_BPS", "15.001"),
    ("V8_XPERP_MAX_MARKET_AGE_SECONDS", "5.001"),
    ("V8_XPERP_MAX_STREAM_AGE_SECONDS", "15.001"),
    ("V8_XPERP_MAX_API_FAILURES", "4"),
])
def test_configuration_above_hard_ceiling_is_rejected(field: str, value: str) -> None:
    with pytest.raises(SafetyError, match="hard safety"):
        config(**{field: value})


def test_long_two_x_is_reduced_to_at_most_1000() -> None:
    result = cap_target(
        target="long 2x",
        equity_usdc=Decimal("100000"),
        adverse_price=Decimal("65000"),
        contract_value=Decimal("1"),
        lot_size=Decimal("0.0001"),
        margin_safe_notional=Decimal("5000"),
        config=config(),
    )
    assert result.requested_notional == Decimal("200000")
    assert result.allowed_notional <= Decimal("1000")
    assert result.signed_contracts == Decimal("0.0153")
    assert result.cap_reduced


def test_short_sign_pending_exposure_and_existing_overage() -> None:
    result = cap_target(
        target="short 2x",
        equity_usdc=Decimal("1000"),
        adverse_price=Decimal("100"),
        contract_value=Decimal("1"),
        lot_size=Decimal("1"),
        margin_safe_notional=Decimal("1000"),
        pending_open_notional=Decimal("200"),
        config=config(),
    )
    assert result.signed_contracts == Decimal("-7")
    assert result.allowed_notional == Decimal("700")
    with pytest.raises(SafetyError, match="larger"):
        cap_target(
            target="long 1x", equity_usdc=Decimal("1000"), adverse_price=Decimal("100"),
            contract_value=Decimal("1"), lot_size=Decimal("1"),
            margin_safe_notional=Decimal("1000"), existing_notional=Decimal("1001"),
            config=config(),
        )


def test_flat_can_only_reduce_and_unknown_target_fails() -> None:
    flat = cap_target(
        target="flat", equity_usdc=Decimal("1000"), adverse_price=Decimal("100"),
        contract_value=Decimal("1"), lot_size=Decimal("1"),
        margin_safe_notional=Decimal("1000"), existing_notional=Decimal("500"),
        config=config(),
    )
    assert flat.signed_contracts == 0 and flat.cap_reduced
    with pytest.raises(SafetyError, match="unsupported"):
        cap_target(
            target="long 3x", equity_usdc=Decimal("1000"), adverse_price=Decimal("100"),
            contract_value=Decimal("1"), lot_size=Decimal("1"),
            margin_safe_notional=Decimal("1000"), config=config(),
        )


def test_kill_switches_never_mutate_unknown_state() -> None:
    assert kill_action("unknown_position") == KillAction.BLOCK_NO_MUTATION_MANUAL
    assert kill_action("unknown_order") == KillAction.BLOCK_NO_MUTATION_MANUAL
    assert kill_action("liquidation_distance") == KillAction.CANCEL_FLATTEN_STOP_MANUAL
    assert kill_action("stale_market") == KillAction.BLOCK_CANCEL_KNOWN
