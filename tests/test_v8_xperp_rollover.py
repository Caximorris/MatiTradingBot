from datetime import UTC, datetime, timedelta
from decimal import Decimal

from execution.v8_xperp.adapter import Instrument
from execution.v8_xperp.rollover import expiry_status, rollover_dry_run


def instrument(*, days: int = 20) -> Instrument:
    return Instrument(
        "CURRENT", "BTC-FAMILY", "BTC-USD", "USDC", "linear",
        Decimal("1"), "BTC", Decimal("0.0001"), Decimal("0.0001"),
        Decimal("0.1"), Decimal("10"), datetime.now(UTC) + timedelta(days=days), "hash",
    )


def successor(current: Instrument, **overrides):
    row = {
        "instId": "NEXT", "instFamily": current.inst_family, "uly": current.uly,
        "settleCcy": current.settle_ccy, "ctType": current.ct_type,
        "ctVal": str(current.ct_val), "ctValCcy": current.ct_val_ccy,
        "lotSz": "0.0001", "minSz": "0.0001", "tickSz": "0.1",
        "expTime": str(int((current.exp_time + timedelta(days=90)).timestamp() * 1000)),
        "ruleType": "xperp", "state": "live",
    }
    row.update(overrides)
    return row


def markets():
    return {
        "CURRENT": {"bidPx": "64999", "askPx": "65001", "bidSz": "2", "askSz": "2", "indexPx": "65000"},
        "NEXT": {"bidPx": "65009", "askPx": "65011", "bidSz": "1", "askSz": "1", "indexPx": "65000"},
    }


def test_expiry_thresholds_are_ordered_and_fail_closed() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for days, expected in (
        (31, (False, False, False)),
        (30, (True, False, False)),
        (14, (True, True, False)),
        (7, (True, True, True)),
    ):
        candidate = instrument()
        candidate = Instrument(
            candidate.inst_id, candidate.inst_family, candidate.uly, candidate.settle_ccy,
            candidate.ct_type, candidate.ct_val, candidate.ct_val_ccy, candidate.lot_sz,
            candidate.min_sz, candidate.tick_sz, candidate.lever,
            now + timedelta(days=days), candidate.metadata_hash,
        )
        state = expiry_status(candidate, now=now)
        assert (state.warning, state.block_new_exposure, state.mandatory_flat) == expected


def test_rollover_dry_run_compares_and_sizes_without_an_order_client() -> None:
    current = instrument()
    report = rollover_dry_run(
        current=current,
        instrument_rows=[successor(current)],
        markets=markets(),
        current_contracts=Decimal("0.0153"),
    )
    assert report.status == "READY_DRY_RUN"
    assert report.successor_id == "NEXT"
    assert report.successor_contracts == Decimal("0.0153")
    assert report.collateral_compatible
    assert report.estimated_close_open_cost_usd > 0


def test_rollover_blocks_missing_or_incompatible_successor() -> None:
    current = instrument()
    missing = rollover_dry_run(
        current=current, instrument_rows=[], markets=markets(),
        current_contracts=Decimal("0.01"),
    )
    assert missing.status == "BLOCKED"
    assert "no valid" in missing.reason
    wrong = rollover_dry_run(
        current=current,
        instrument_rows=[successor(current, ruleType="normal")],
        markets=markets(),
        current_contracts=Decimal("0.01"),
    )
    assert wrong.status == "BLOCKED"
    assert wrong.successor_id is None


def test_rollover_blocks_incomplete_market_or_undersized_target() -> None:
    current = instrument()
    rows = [successor(current, minSz="1")]
    report = rollover_dry_run(
        current=current, instrument_rows=rows, markets=markets(),
        current_contracts=Decimal("0.01"),
    )
    assert report.status == "BLOCKED"
    assert "minimum" in report.reason
