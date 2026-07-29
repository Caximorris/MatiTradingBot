from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from execution.v8_xperp.adapter import SafetyError
from execution.v8_xperp.bootstrap import (
    BootstrapConfig,
    BootstrapDecisionLedger,
    IndexPriceSample,
    OperationalPhase,
    calculate_bootstrap,
    finalize_bootstrap,
)


TRANSITION = datetime(2025, 10, 12, 0, 9, 27, tzinfo=UTC)


def sample(price: str, *, at: datetime, source: str = "okx_eea_btc_usd_index"):
    return IndexPriceSample(
        source, "BTC-USD", at, Decimal(price), at + timedelta(seconds=1), "a" * 64
    )


def phase(direction: str) -> OperationalPhase:
    return OperationalPhase(
        f"{direction}_phase", direction,
        "day_900" if direction == "long" else "day_540",
        TRANSITION, None, datetime(2024, 4, 20, 0, 9, 27, tzinfo=UTC),
    )


def decision(
    *,
    direction: str,
    reference: str,
    current: str,
    margin: str = "2",
    liquidation: str = "2",
    account: str = "2",
    minimum: str = "0.25",
):
    config = BootstrapConfig(minimum_entry_leverage=Decimal(minimum))
    return calculate_bootstrap(
        environment="okx_demo",
        account_hash="account",
        instrument_id="BTC-XPERP",
        phase=phase(direction),
        reference=sample(reference, at=TRANSITION + timedelta(minutes=51)),
        current=sample(current, at=TRANSITION + timedelta(days=1)),
        eligible_equity=Decimal("10000"),
        margin_safe_leverage=Decimal(margin),
        liquidation_safe_leverage=Decimal(liquidation),
        account_safe_leverage=Decimal(account),
        config=config,
    )


def test_long_below_reference_allows_two_x() -> None:
    result = decision(direction="long", reference="100", current="90")
    assert result.adverse_move_to_reference == "0"
    assert result.calculated_leverage == "2"


def test_long_above_reference_reduces_leverage() -> None:
    result = decision(direction="long", reference="100", current="200")
    assert result.adverse_move_to_reference == "0.5"
    assert result.calculated_leverage == "0.4"


def test_short_above_reference_allows_two_x() -> None:
    result = decision(direction="short", reference="100", current="110")
    assert result.adverse_move_to_reference == "0"
    assert result.calculated_leverage == "2"


def test_short_below_reference_reduces_leverage() -> None:
    result = decision(direction="short", reference="100", current="60")
    assert result.adverse_move_to_reference == str(Decimal("40") / Decimal("60"))
    assert result.calculated_leverage == str(Decimal("0.20") / (Decimal("40") / Decimal("60")))
    assert result.enter


def test_below_minimum_remains_flat() -> None:
    result = decision(direction="long", reference="100", current="1000")
    assert Decimal(result.leverage_from_reference) < Decimal("0.25")
    assert result.calculated_leverage == "0"
    assert not result.enter


def test_margin_and_liquidation_limits_reduce_dynamic_leverage() -> None:
    assert decision(
        direction="long", reference="100", current="100", margin="0.7"
    ).calculated_leverage == "0.7"
    assert decision(
        direction="long", reference="100", current="100", liquidation="0.6"
    ).calculated_leverage == "0.6"


def test_canary_cap_and_contract_quantization_never_increase_leverage() -> None:
    result = decision(direction="long", reference="100", current="100")
    final = finalize_bootstrap(
        result,
        adverse_price=Decimal("65000"),
        contract_value=Decimal("1"),
        lot_size=Decimal("0.0001"),
        maximum_notional=Decimal("1000"),
        margin_safe_notional=Decimal("5000"),
    )
    assert Decimal(final.final_notional) <= 1000
    assert Decimal(final.actual_leverage) <= Decimal(result.calculated_leverage)
    assert final.final_contracts == "0.0153"


def test_missing_or_inconsistent_reference_fails_closed() -> None:
    with pytest.raises(SafetyError, match="invalid BTC-USD index"):
        calculate_bootstrap(
            environment="okx_demo", account_hash="account", instrument_id="inst",
            phase=phase("long"),
            reference=sample("100", at=TRANSITION + timedelta(hours=1), source="other"),
            current=sample("100", at=TRANSITION + timedelta(hours=2)),
            eligible_equity=Decimal("100"), margin_safe_leverage=Decimal("2"),
            liquidation_safe_leverage=Decimal("2"), account_safe_leverage=Decimal("2"),
            config=BootstrapConfig(),
        )
    with pytest.raises(SafetyError, match="strictly after"):
        calculate_bootstrap(
            environment="okx_demo", account_hash="account", instrument_id="inst",
            phase=phase("long"), reference=sample("100", at=TRANSITION),
            current=sample("100", at=TRANSITION + timedelta(hours=2)),
            eligible_equity=Decimal("100"), margin_safe_leverage=Decimal("2"),
            liquidation_safe_leverage=Decimal("2"), account_safe_leverage=Decimal("2"),
            config=BootstrapConfig(),
        )


def test_decision_ledger_is_idempotent_and_survives_restart(tmp_path) -> None:
    result = finalize_bootstrap(
        decision(direction="long", reference="100", current="120"),
        adverse_price=Decimal("100"), contract_value=Decimal("1"),
        lot_size=Decimal("1"), maximum_notional=Decimal("1000"),
        margin_safe_notional=Decimal("1000"),
    )
    ledger = BootstrapDecisionLedger(tmp_path / "bootstrap.json")
    assert ledger.create(result) == result
    assert ledger.create(result) == result
    executed = ledger.update_state(result.transition_id, "EXECUTED")
    assert BootstrapDecisionLedger(ledger.path).load() == [executed]
    with pytest.raises(SafetyError, match="content changed"):
        ledger.create(type(result)(**{**result.__dict__, "current_price": "121"}))
