from datetime import UTC, datetime, timedelta
from decimal import Decimal

from execution.v8_xperp.bootstrap import IndexPriceSample
from execution.v8_xperp.diagnostic import compare_cold_start


def test_short_cold_start_compares_frozen_policies_without_optimization() -> None:
    at = datetime(2026, 7, 1, tzinfo=UTC)
    transition = datetime(2024, 4, 20, 0, 9, 27, tzinfo=UTC) + timedelta(days=540)

    def sample_after(timestamp, retrieved_at):
        price = Decimal("100") if timestamp < at - timedelta(days=1) else Decimal("60")
        return IndexPriceSample(
            "okx_eea_btc_usd_index",
            "BTC-USD",
            timestamp + timedelta(hours=1),
            price,
            retrieved_at + timedelta(hours=1),
            ("a" if price == 100 else "b") * 64,
        )

    result = compare_cold_start(at, sample_after=sample_after)
    assert result["phase"]["direction"] == "short"
    assert result["reference"]["timestamp"] == transition + timedelta(hours=1)
    assert Decimal(result["policies"]["dynamic"]["leverage"]) == Decimal("0.3")
    assert result["policies"]["flat_until_transition"]["leverage"] == "0"
    assert result["policies"]["fixed_1x"]["leverage"] == "1"
    assert result["policies"]["immediate_2x"]["leverage"] == "2"
