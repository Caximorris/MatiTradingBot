from datetime import UTC, datetime
from decimal import Decimal

import pytest

from execution.v8_xperp.adapter import Instrument, SafetyError
from execution.v8_xperp.margins import assess_margin, parse_margin_tiers, select_margin_tier


def instrument() -> Instrument:
    return Instrument(
        "BTC-USD_UM_XPERP-test", "BTC-USD_UM_XPERP", "BTC-USD", "USDC",
        "linear", Decimal("1"), "BTC", Decimal("0.0001"), Decimal("0.0001"),
        Decimal("0.1"), Decimal("10"), datetime(2031, 1, 1, tzinfo=UTC), "hash",
    )


def rows() -> list[dict[str, str]]:
    return [
        {
            "tier": "1", "instFamily": "BTC-USD_UM_XPERP", "uly": "BTC-USD",
            "minSz": "0", "maxSz": "4000", "maxLever": "10",
            "imr": "0.1", "mmr": "0.004",
        },
        {
            "tier": "2", "instFamily": "BTC-USD_UM_XPERP", "uly": "BTC-USD",
            "minSz": "4000.0001", "maxSz": "8000", "maxLever": "9",
            "imr": "0.111111111111111111", "mmr": "0.01",
        },
    ]


def test_tiers_validate_and_select_exact_boundaries() -> None:
    tiers = parse_margin_tiers(reversed(rows()), instrument=instrument())
    assert [tier.tier for tier in tiers] == [1, 2]
    assert select_margin_tier(
        tiers, position_size=Decimal("4000"), quantum=Decimal("0.0001")
    ).tier == 1
    assert select_margin_tier(
        tiers, position_size=Decimal("4000.0001"), quantum=Decimal("0.0001")
    ).tier == 2


@pytest.mark.parametrize("next_min, message", [
    ("3999.9999", "overlap"),
    ("4000.0002", "gap"),
])
def test_tier_overlap_or_gap_fails_closed(next_min: str, message: str) -> None:
    broken = rows()
    broken[1]["minSz"] = next_min
    with pytest.raises(SafetyError, match=message):
        parse_margin_tiers(broken, instrument=instrument())


def test_missing_fields_wrong_family_and_unknown_deduction_fail_closed() -> None:
    missing = rows()
    del missing[0]["mmr"]
    with pytest.raises(SafetyError, match="missing"):
        parse_margin_tiers(missing, instrument=instrument())
    wrong = rows()
    wrong[0]["instFamily"] = "OTHER"
    with pytest.raises(SafetyError, match="another"):
        parse_margin_tiers(wrong, instrument=instrument())
    deduction = rows()
    deduction[0]["maintMgnDeduct"] = "1"
    with pytest.raises(SafetyError, match="undocumented"):
        parse_margin_tiers(deduction, instrument=instrument())


def test_long_and_short_liquidation_fixtures_are_exact() -> None:
    tiers = parse_margin_tiers(rows(), instrument=instrument())
    common = dict(
        instrument=instrument(),
        tiers=tiers,
        contracts=Decimal("0.0001"),
        mark_price=Decimal("100000"),
        entry_price=Decimal("100000"),
        leverage=Decimal("2"),
        available_usdc=Decimal("100"),
        reserve_usdc=Decimal("1"),
        minimum_liquidation_distance_pct=Decimal("35"),
        liquidation_fee_rate=Decimal("0.0005"),
    )
    long = assess_margin(side="long", **common)
    short = assess_margin(side="short", **common)
    assert long.actual_notional == Decimal("10")
    assert long.required_initial_margin == Decimal("5")
    assert long.required_maintenance_margin == Decimal("0.0450")
    assert long.conservative_liquidation_price == (
        Decimal("5") / Decimal("0.00009955")
    )
    assert short.conservative_liquidation_price == (
        Decimal("15") / Decimal("0.00010045")
    )
    assert long.liquidation_distance_pct > 35
    assert short.liquidation_distance_pct > 35


def test_exchange_fields_and_disagreement_are_fail_closed() -> None:
    tiers = parse_margin_tiers(rows(), instrument=instrument())
    base = {
        "instId": instrument().inst_id,
        "instType": "FUTURES",
        "mgnMode": "isolated",
        "ccy": "USDC",
        "posSide": "net",
        "pos": "0.0001",
        "notionalUsd": "10",
        "lever": "2",
        "margin": "5",
        "mgnRatio": "100",
        "mmr": "0.04",
        "liqPx": str(Decimal("5") / Decimal("0.00009955")),
        "markPx": "100000",
        "avgPx": "100000",
    }
    kwargs = dict(
        instrument=instrument(), tiers=tiers, contracts=Decimal("0.0001"),
        side="long", mark_price=Decimal("100000"), leverage=Decimal("2"),
        available_usdc=Decimal("100"), reserve_usdc=Decimal("1"),
        exchange_position=base, liquidation_fee_rate=Decimal("0.0005"),
    )
    assessment = assess_margin(**kwargs)
    assert assessment.exchange_liquidation_price is not None
    assert assessment.required_maintenance_margin == Decimal("0.0450")
    assert assessment.exchange_maintenance_margin == Decimal("0.04")
    with pytest.raises(SafetyError, match="notionals disagree"):
        assess_margin(**{**kwargs, "exchange_position": {**base, "notionalUsd": "20"}})
    with pytest.raises(SafetyError, match="liquidation prices disagree"):
        assess_margin(**{**kwargs, "exchange_position": {**base, "liqPx": "90000"}})


def test_liquidation_distance_below_threshold_blocks() -> None:
    with pytest.raises(SafetyError, match="distance"):
        assess_margin(
            instrument=instrument(),
            tiers=parse_margin_tiers(rows(), instrument=instrument()),
            contracts=Decimal("0.0001"),
            side="long",
            mark_price=Decimal("100000"),
            leverage=Decimal("10"),
            available_usdc=Decimal("100"),
            reserve_usdc=Decimal("1"),
            liquidation_fee_rate=Decimal("0.0005"),
        )
