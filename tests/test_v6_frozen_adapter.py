from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.certification import SnapshotBar, StrategySnapshot
from core.v6_frozen_adapter import FrozenV6CausalResearchAdapter, FrozenV6EvidenceUnavailable, assert_frozen_v6_source


def test_frozen_v6_adapter_is_snapshot_only_and_fails_closed_without_protected_input():
    adapter = FrozenV6CausalResearchAdapter()
    snapshot = StrategySnapshot(datetime(2024, 1, 1, tzinfo=timezone.utc),
                                (SnapshotBar(datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1")),),
                                {}, Decimal("100"), Decimal("0"))
    with pytest.raises(FrozenV6EvidenceUnavailable, match="protected funding snapshot"):
        adapter.decide(snapshot)


def test_frozen_v6_source_remains_present_without_registering_adapter():
    assert len(assert_frozen_v6_source()) == 64
