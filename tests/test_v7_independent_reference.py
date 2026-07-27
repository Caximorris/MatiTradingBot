from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.frozen_candidate import FrozenCandidateError
from tools.v7_independent_reference import Bar, Spec, frozen_spec, normalize, run


def test_reference_collapses_only_identical_duplicates_and_next_open_fills():
    start = int(datetime(2012, 11, 28, 16, tzinfo=timezone.utc).timestamp() * 1000)
    bars = [Bar(start + hour * 3_600_000, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1")) for hour in range(100)]
    assert len(normalize([bars[0], bars[1], bars[1], *bars[2:]])) == len(bars)
    spec = Spec(warmup_bars=0, phase_post_end=1, phase_bear_start=2, phase_accumulation_start=3)
    trades, _ = run(bars, spec)
    assert trades[0]["fill_timestamp"] > trades[0]["decision_timestamp"]


def test_reference_rejects_conflicting_duplicate():
    bar = Bar(1, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))
    bad = Bar(1, Decimal("2"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))
    with pytest.raises(ValueError, match="conflicting"):
        normalize([bar, bad])


def test_frozen_reference_spec_rejects_parameter_relabeling():
    assert frozen_spec().phase_bear_start == 540
    with pytest.raises(FrozenCandidateError):
        frozen_spec({"phase_accumulation_start": 960})
