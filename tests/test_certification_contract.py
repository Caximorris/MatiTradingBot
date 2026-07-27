from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import typer

from cli.certification_cmds import certify_candidate
from core.certification import CertificationError, CertifiedEngine, TargetIntent
from data.market_data import OHLCVBar


def _bars():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [OHLCVBar(int((start + timedelta(hours=i)).timestamp() * 1000), Decimal(str(100 + i)), Decimal("110"), Decimal("90"), Decimal(str(100 + i)), Decimal("1")) for i in range(4)]


def test_certified_engine_only_fills_at_next_open_and_reserves_fee():
    class Strategy:
        def decide(self, snapshot):
            return TargetIntent("one", Decimal("1")) if len(snapshot.bars) == 1 else None
    engine = CertifiedEngine(_bars(), initial_cash=Decimal("102"), fee_rate=Decimal(".001"), slippage_bps=Decimal("0"))
    order, = engine.run(Strategy())
    assert order.fill_price == Decimal("101")
    assert order.fill_at > order.submitted_at
    assert engine.cash >= 0


def test_identical_duplicate_candles_cannot_shift_decision_cadence():
    bars = _bars()
    duplicate = [bars[0], bars[1], bars[1], bars[2], bars[3]]
    engine = CertifiedEngine(duplicate, initial_cash=Decimal("102"), fee_rate=Decimal(".001"), slippage_bps=Decimal("0"))
    assert len(engine._bars) == len(bars)


def test_conflicting_or_non_monotonic_candles_fail_closed():
    bars = _bars()
    conflicting = bars[:1] + [OHLCVBar(bars[0].timestamp, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))]
    with pytest.raises(CertificationError, match="conflicting duplicate"):
        CertifiedEngine(conflicting, initial_cash=Decimal("1"), fee_rate=Decimal("0"), slippage_bps=Decimal("0"))
    with pytest.raises(CertificationError, match="non-monotonic"):
        CertifiedEngine([bars[1], bars[0]], initial_cash=Decimal("1"), fee_rate=Decimal("0"), slippage_bps=Decimal("0"))


@pytest.mark.parametrize("attack", ["next", "current", "external", "duplicate", "mutate", "bypass"])
def test_adversarial_strategies_are_rejected(attack):
    class Attack:
        def decide(self, snapshot):
            if attack == "next":
                _ = snapshot.bars[len(snapshot.bars)]
            if attack == "current":
                assert snapshot.latest.close == Decimal("999")
            if attack == "external":
                assert "future" in snapshot.external
            if attack == "mutate":
                snapshot.external["x"] = 1
            if attack == "bypass":
                return Decimal("100")
            return TargetIntent("same" if attack == "duplicate" else "one", Decimal("1"))
    engine = CertifiedEngine(_bars(), initial_cash=Decimal("1000"), fee_rate=Decimal(".001"), slippage_bps=Decimal("0"), external_events=[("future", datetime(2025, 1, 1, tzinfo=timezone.utc), 1)])
    with pytest.raises((CertificationError, IndexError, AssertionError, TypeError)):
        engine.run(Attack())


def test_legacy_strategy_is_persistently_invalid_and_blocks_registration(tmp_path: Path):
    with pytest.raises(typer.Exit) as error:
        certify_candidate(strategy="pro_trend", out=tmp_path)
    assert error.value.exit_code == 2
    record = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert '"status": "INVALID"' in record
    assert '"shadow_paper_registration_blocked": true' in record
