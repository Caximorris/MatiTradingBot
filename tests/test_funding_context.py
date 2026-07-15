from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from strategies import funding_context as funding


UTC = timezone.utc


def _dt(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


def _record(dt: datetime, rate: str) -> dict[str, str]:
    return {
        "fundingTime": str(int(dt.timestamp() * 1000)),
        "fundingRate": rate,
    }


def _single_page(records: list[dict[str, str]]):
    return lambda _inst, after: records if after is None else []


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    with funding._CACHE_LOCK:
        funding._SNAPSHOTS.clear()
    monkeypatch.setattr(funding, "_PAGINATION_DELAY_S", 0)
    yield
    with funding._CACHE_LOCK:
        funding._SNAPSHOTS.clear()


def test_rejects_naive_non_utc_and_inverted_windows() -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        funding.load_funding_history("BTC-USDT", datetime(2024, 1, 1), _dt(2))
    with pytest.raises(ValueError, match="must be UTC"):
        funding.load_funding_history(
            "BTC-USDT", _dt(1).astimezone(timezone(timedelta(hours=1))), _dt(2)
        )
    with pytest.raises(ValueError, match="from_dt < to_dt"):
        funding.load_funding_history("BTC-USDT", _dt(2), _dt(1))


def test_daily_average_uses_only_prior_complete_utc_day(monkeypatch) -> None:
    page = [
        _record(_dt(2, 0), "0.01"),
        _record(_dt(2, 8), "0.02"),
        _record(_dt(2, 16), "0.03"),
        _record(_dt(1, 16), "0.90"),
    ]
    monkeypatch.setattr(funding, "_fetch_page", _single_page(page))

    funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))

    assert funding.get_funding_rate_at(_dt(3, 4), "BTC-USDT") == pytest.approx(0.02)
    assert funding.get_funding_rate_at(_dt(2, 4), "BTC-USDT") == pytest.approx(0.90)


def test_cache_reuses_only_contained_symbol_coverage(monkeypatch) -> None:
    calls: list[tuple[str, int | None]] = []

    def fetch(inst_id: str, after: int | None) -> list[dict]:
        calls.append((inst_id, after))
        return []

    monkeypatch.setattr(funding, "_fetch_page", fetch)
    funding.load_funding_history("BTC-USDT", _dt(10), _dt(20))
    funding.load_funding_history("BTC-USDT", _dt(11), _dt(19))
    assert len(calls) == 1

    funding.load_funding_history("BTC-USDT", _dt(9), _dt(20))
    funding.load_funding_history("ETH-USDT", _dt(10), _dt(20))
    assert [call[0] for call in calls] == [
        "BTC-USDT-SWAP", "BTC-USDT-SWAP", "ETH-USDT-SWAP"
    ]


def test_failed_refresh_keeps_prior_snapshot_and_never_cross_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(
        funding,
        "_fetch_page",
        _single_page([_record(_dt(2), "0.01"), _record(_dt(1), "0.02")]),
    )
    funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))

    def fail(_inst: str, _after: int | None) -> list[dict]:
        raise funding.FundingFetchError("offline")

    monkeypatch.setattr(funding, "_fetch_page", fail)
    with pytest.raises(funding.FundingFetchError, match="offline"):
        funding.load_funding_history("BTC-USDT", _dt(3), _dt(8))
    with pytest.raises(funding.FundingFetchError, match="offline"):
        funding.load_funding_history("ETH-USDT", _dt(3), _dt(8))

    assert funding.get_funding_rate_at(_dt(3), "BTC-USDT") == pytest.approx(0.01)
    assert funding.get_funding_rate_at(_dt(3), "ETH-USDT") == 0.0


def test_pagination_deduplicates_settlements_and_requires_progress(monkeypatch) -> None:
    duplicate = _record(_dt(2), "0.01")
    pages = {
        None: [_record(_dt(3), "0.03"), duplicate],
        int(_dt(2).timestamp() * 1000): [duplicate],
    }
    monkeypatch.setattr(funding, "_fetch_page", lambda _inst, after: pages[after])

    with pytest.raises(funding.FundingFetchError, match="no progress"):
        funding.load_funding_history("BTC-USDT", _dt(1), _dt(4))

    assert funding._SNAPSHOTS == {}


def test_conflicting_duplicate_funding_time_rejects_snapshot(monkeypatch) -> None:
    records = [
        _record(_dt(2, 0), "0.01"),
        _record(_dt(2, 0), "0.03"),
        _record(_dt(1), "0.02"),
    ]
    monkeypatch.setattr(funding, "_fetch_page", _single_page(records))

    with pytest.raises(funding.FundingFetchError, match="conflicting funding rates"):
        funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))

    assert funding._SNAPSHOTS == {}


def test_identical_duplicate_funding_time_is_counted_once(monkeypatch) -> None:
    records = [
        _record(_dt(2, 0), "0.01"),
        _record(_dt(2, 0), "0.01"),
        _record(_dt(1), "0.02"),
    ]
    monkeypatch.setattr(funding, "_fetch_page", _single_page(records))

    funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))

    assert funding.get_funding_rate_at(_dt(3), "BTC-USDT") == pytest.approx(0.01)


def test_disjoint_same_symbol_windows_remain_available(monkeypatch) -> None:
    pages = iter([
        [
            _record(_dt(2), "0.01"),
            _record(_dt(1), "0.02"),
            _record(datetime(2023, 12, 29, tzinfo=UTC), "0.00"),
        ],
        [
            _record(datetime(2024, 2, 2, tzinfo=UTC), "0.03"),
            _record(datetime(2024, 1, 29, tzinfo=UTC), "0.00"),
        ],
    ])
    monkeypatch.setattr(funding, "_fetch_page", lambda _inst, _after: next(pages, []))

    funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))
    before = funding.get_funding_rate_at(_dt(3), "BTC-USDT")
    funding.load_funding_history(
        "BTC-USDT",
        datetime(2024, 2, 3, tzinfo=UTC),
        datetime(2024, 2, 4, tzinfo=UTC),
    )

    assert before == pytest.approx(0.01)
    assert funding.get_funding_rate_at(_dt(3), "BTC-USDT") == pytest.approx(0.01)
    assert funding.get_funding_rate_at(
        datetime(2024, 2, 3, tzinfo=UTC), "BTC-USDT"
    ) == pytest.approx(0.03)


def test_non_finite_rate_rejects_the_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        funding,
        "_fetch_page",
        _single_page([_record(_dt(2), "nan")]),
    )

    with pytest.raises(funding.FundingFetchError, match="non-finite"):
        funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))
    assert funding._SNAPSHOTS == {}
