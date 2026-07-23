from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.block_bootstrap import sample_blocks
from data.market_data import OHLCVBar


def test_block_bootstrap_is_deterministic_and_preserves_contiguous_rows():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = [OHLCVBar(int((start + timedelta(hours=i)).timestamp() * 1000), Decimal(i), Decimal(i), Decimal(i), Decimal(i), Decimal(1)) for i in range(12)]
    first = sample_blocks(bars, block_hours=3, seed=7)
    second = sample_blocks(bars, block_hours=3, seed=7)
    assert first == second
    assert len(first) == len(bars)
    assert any(first[i + 1].timestamp - first[i].timestamp == 3600_000 for i in range(len(first) - 1))
