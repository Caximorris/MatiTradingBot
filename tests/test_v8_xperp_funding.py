from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from execution.v8_xperp.adapter import SafetyError
from execution.v8_xperp.funding import (
    FundingLedger,
    make_expectation,
    reconcile_funding,
    source_hash,
)

SETTLEMENT = 1_800_000_000_000


def expectation(*, side: str = "long", rate: str = "0.0001"):
    return make_expectation(
        environment="okx_demo",
        account_hash="account",
        instrument_id="BTC-XPERP",
        settlement_ms=SETTLEMENT,
        side=side,
        contracts=Decimal("0.0001"),
        position_notional=Decimal("10"),
        signed_rate=Decimal(rate),
        metadata_hash="metadata",
        rate_source_hash="rate",
        position_source_hash="position",
        mark_source_hash="mark",
    )


def history(rate: str = "0.0001", settlement: int = SETTLEMENT):
    return [{"instId": "BTC-XPERP", "fundingTime": str(settlement), "realizedRate": rate}]


def bill(amount: str, *, bill_id: str = "bill-1", subtype: str | None = None, ts: int = SETTLEMENT + 1):
    resolved_subtype = subtype or ("173" if Decimal(amount) < 0 else "174")
    return {
        "billId": bill_id,
        "type": "8",
        "subType": resolved_subtype,
        "instId": "BTC-XPERP",
        "ccy": "USDC",
        "pnl": amount,
        "ts": str(ts),
    }


def created(tmp_path: Path, record=None):
    ledger = FundingLedger(tmp_path / "funding.json")
    item = ledger.create(record or expectation())
    return ledger, item


@pytest.mark.parametrize("side, rate, expected", [
    ("long", "0.0001", "-0.0010"),
    ("short", "0.0001", "0.0010"),
    ("long", "-0.0001", "0.0010"),
    ("short", "-0.0001", "-0.0010"),
])
def test_expected_funding_signs(side: str, rate: str, expected: str) -> None:
    assert Decimal(expectation(side=side, rate=rate).expected_amount) == Decimal(expected)


def test_exact_bill_matches_once_and_restart_is_idempotent(tmp_path: Path) -> None:
    ledger, record = created(tmp_path)
    result = reconcile_funding(
        ledger=ledger, record=record, official_history=history(),
        bills=[bill("-0.001")], now_ms=SETTLEMENT + 10,
    )
    assert result.state == "RECONCILED"
    restarted = FundingLedger(ledger.path)
    again = reconcile_funding(
        ledger=restarted, record=restarted.load()[0], official_history=history(),
        bills=[bill("-0.001"), bill("-0.001")], now_ms=SETTLEMENT + 20,
    )
    assert again.state == "RECONCILED"
    assert again.bill_id == "bill-1"


@pytest.mark.parametrize("elapsed, state", [
    (-1, "EXPECTED"),
    (1, "DUE"),
    (120_001, "DELAYED"),
    (900_001, "MISSING"),
])
def test_missing_and_delayed_bill_states(tmp_path: Path, elapsed: int, state: str) -> None:
    ledger, record = created(tmp_path)
    result = reconcile_funding(
        ledger=ledger,
        record=record,
        official_history=[],
        bills=[],
        now_ms=SETTLEMENT + elapsed,
    )
    assert result.state == state


def test_sign_amount_timestamp_and_rate_changes_fail_closed(tmp_path: Path) -> None:
    ledger, record = created(tmp_path / "sign")
    assert reconcile_funding(
        ledger=ledger, record=record, official_history=history(),
        bills=[bill("0.001", subtype="173")], now_ms=SETTLEMENT + 1,
    ).state == "SIGN_MISMATCH"

    ledger, record = created(tmp_path / "amount")
    assert reconcile_funding(
        ledger=ledger, record=record, official_history=history(),
        bills=[bill("-0.002")], now_ms=SETTLEMENT + 1,
    ).state == "AMOUNT_MISMATCH"

    ledger, record = created(tmp_path / "bill-time")
    assert reconcile_funding(
        ledger=ledger, record=record, official_history=history(),
        bills=[bill("-0.001", ts=SETTLEMENT + 900_001)], now_ms=SETTLEMENT + 900_001,
    ).state == "TIMESTAMP_MISMATCH"

    ledger, record = created(tmp_path / "settlement-time")
    assert reconcile_funding(
        ledger=ledger, record=record, official_history=history(settlement=SETTLEMENT + 1),
        bills=[], now_ms=SETTLEMENT + 1,
    ).state == "TIMESTAMP_MISMATCH"

    ledger, record = created(tmp_path / "rate")
    rebased = reconcile_funding(
        ledger=ledger, record=record, official_history=history(rate="0.0002"),
        bills=[], now_ms=SETTLEMENT + 1,
    )
    assert rebased.state == "DELAYED"
    assert rebased.signed_rate == "0.0002"
    assert rebased.expected_amount == "-0.0020"
    assert rebased.rate_revision == "0.0001->0.0002"


def test_rate_revision_rebases_then_matches_final_bill(tmp_path: Path) -> None:
    ledger, record = created(tmp_path / "rate-bill")
    result = reconcile_funding(
        ledger=ledger,
        record=record,
        official_history=history(rate="0.0002"),
        bills=[bill("-0.0020")],
        now_ms=SETTLEMENT + 1,
    )
    assert result.state == "RECONCILED"
    assert result.signed_rate == "0.0002"
    assert result.rate_revision == "0.0001->0.0002"


def test_settlement_amount_tolerance_reconciles_retried_mismatch(tmp_path: Path) -> None:
    ledger, record = created(tmp_path / "amount-tolerance")
    first = reconcile_funding(
        ledger=ledger,
        record=record,
        official_history=history(),
        bills=[bill("-0.0010005")],
        now_ms=SETTLEMENT + 1,
    )
    assert first.state == "RECONCILED"
    assert first.last_result == "exact-once funding reconciled within settlement tolerance"

    retried = reconcile_funding(
        ledger=ledger,
        record=replace(first, state="AMOUNT_MISMATCH"),
        official_history=history(),
        bills=[bill("-0.0010005")],
        now_ms=SETTLEMENT + 2,
    )
    assert retried.state == "RECONCILED"


def test_distinct_duplicate_bill_and_changed_duplicate_conflict(tmp_path: Path) -> None:
    ledger, record = created(tmp_path / "distinct")
    result = reconcile_funding(
        ledger=ledger, record=record, official_history=history(),
        bills=[bill("-0.001", bill_id="a"), bill("-0.001", bill_id="b")],
        now_ms=SETTLEMENT + 1,
    )
    assert result.state == "CONFLICT"

    ledger, record = created(tmp_path / "changed")
    reconciled = reconcile_funding(
        ledger=ledger, record=record, official_history=history(),
        bills=[bill("-0.001")], now_ms=SETTLEMENT + 1,
    )
    changed = reconcile_funding(
        ledger=ledger, record=reconciled, official_history=history(),
        bills=[{**bill("-0.001"), "notes": "changed"}], now_ms=SETTLEMENT + 2,
    )
    assert changed.state == "CONFLICT"


def test_one_bill_cannot_match_two_expectations(tmp_path: Path) -> None:
    ledger, first = created(tmp_path)
    reconcile_funding(
        ledger=ledger, record=first, official_history=history(),
        bills=[bill("-0.001")], now_ms=SETTLEMENT + 1,
    )
    second = ledger.create(replace(expectation(), settlement_ms=SETTLEMENT + 10))
    result = reconcile_funding(
        ledger=ledger,
        record=second,
        official_history=history(settlement=SETTLEMENT + 10),
        bills=[bill("-0.001", ts=SETTLEMENT + 11)],
        now_ms=SETTLEMENT + 11,
    )
    assert result.state == "CONFLICT"


def test_corruption_duplicate_identity_and_source_hash_are_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "funding.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(SafetyError, match="corrupt"):
        FundingLedger(path).load()
    assert source_hash({"b": 2, "a": 1}) == source_hash({"a": 1, "b": 2})
