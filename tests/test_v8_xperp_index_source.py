from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from execution.v8_xperp.adapter import SafetyError
from execution.v8_xperp.index_source import OKXIndexPriceSource, SOURCE


TRANSITION = datetime(2025, 10, 12, 0, 9, 27, tzinfo=UTC)


class Market:
    def __init__(self, row):
        self.row = row

    def get_index_tickers(self, *, instId):
        assert instId == "BTC-USD"
        return {"code": "0", "data": [self.row]}


def test_reference_uses_first_confirmed_hour_strictly_after_transition() -> None:
    rows = [
        [str(int((TRANSITION + timedelta(hours=2)).timestamp() * 1000)), "102", "0", "0", "0", "1"],
        [str(int((TRANSITION + timedelta(minutes=51)).timestamp() * 1000)), "101", "0", "0", "0", "1"],
        [str(int(TRANSITION.timestamp() * 1000)), "100", "0", "0", "0", "1"],
    ]
    paths: list[str] = []
    source = OKXIndexPriceSource(
        market_api=Market({}),
        http_get=lambda path: paths.append(path) or {"code": "0", "data": rows},
    )
    result = source.reference_after(
        TRANSITION, retrieved_at=TRANSITION + timedelta(days=1)
    )
    assert result.timestamp == TRANSITION + timedelta(minutes=51)
    assert result.price == 101
    assert result.source == SOURCE
    assert "history-index-candles" in paths[0]


def test_reference_missing_confirmed_data_fails_closed() -> None:
    source = OKXIndexPriceSource(
        market_api=Market({}),
        http_get=lambda _path: {
            "code": "0",
            "data": [[
                str(int((TRANSITION + timedelta(hours=1)).timestamp() * 1000)),
                "100", "0", "0", "0", "0",
            ]],
        },
    )
    with pytest.raises(SafetyError, match="no confirmed"):
        source.reference_after(TRANSITION, retrieved_at=TRANSITION + timedelta(days=1))


def test_current_index_requires_fresh_same_instrument_ticker() -> None:
    server = datetime(2026, 1, 1, tzinfo=UTC)
    row = {
        "instId": "BTC-USD",
        "idxPx": "65000",
        "ts": str(int((server - timedelta(seconds=1)).timestamp() * 1000)),
    }
    result = OKXIndexPriceSource(market_api=Market(row)).current(
        verified_server_time=server
    )
    assert result.price == Decimal("65000")
    assert result.instrument_id == "BTC-USD"
    stale = {**row, "ts": str(int((server - timedelta(seconds=6)).timestamp() * 1000))}
    with pytest.raises(SafetyError, match="stale"):
        OKXIndexPriceSource(market_api=Market(stale)).current(
            verified_server_time=server
        )
