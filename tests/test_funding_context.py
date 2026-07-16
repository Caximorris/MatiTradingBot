from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from strategies import funding_context as funding
from strategies.funding_coverage import (
    CoverageEvidenceError,
    coverage_fingerprint,
    make_coverage_evidence,
)


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


def _evidence(
    *, instrument: str = "BTC-USDT-SWAP", venue: str = "OKX", start: datetime | None = None,
):
    return make_coverage_evidence(
        source="versioned test venue snapshot", instrument=instrument, venue=venue,
        series_start=start or _dt(6), snapshot_identity="test-listing-snapshot-v1",
        generated_at=_dt(10), validity_rule="timestamp is before immutable funding-series start",
    )


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
        _record(_dt(3, 16), "0.04"),
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

    records = [_record(_dt(19), "0.01"), _record(_dt(18), "0.02")]

    def fetch(inst_id: str, after: int | None) -> list[dict]:
        calls.append((inst_id, after))
        return records if after is None else []

    monkeypatch.setattr(funding, "_fetch_page", fetch)
    funding.load_funding_history("BTC-USDT", _dt(10), _dt(20))
    funding.load_funding_history("BTC-USDT", _dt(11), _dt(19))
    assert len([call for call in calls if call[1] is None]) == 1

    funding.load_funding_history("BTC-USDT", _dt(9), _dt(20))
    funding.load_funding_history("ETH-USDT", _dt(10), _dt(20))
    assert [call[0] for call in calls if call[1] is None] == [
        "BTC-USDT-SWAP", "BTC-USDT-SWAP", "ETH-USDT-SWAP"
    ]


def test_failed_refresh_keeps_prior_snapshot_and_never_cross_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(
        funding,
        "_fetch_page",
        _single_page([
            _record(_dt(3), "0.03"),
            _record(_dt(2), "0.01"),
            _record(_dt(1), "0.02"),
        ]),
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
    with pytest.raises(funding.FundingFetchError, match="has not been loaded"):
        funding.get_funding_rate_at(_dt(3), "ETH-USDT")


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
        _record(_dt(3, 0), "0.04"),
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
        _record(_dt(3, 0), "0.04"),
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
            _record(_dt(3), "0.04"),
            _record(_dt(2), "0.01"),
            _record(_dt(1), "0.02"),
            _record(datetime(2023, 12, 29, tzinfo=UTC), "0.00"),
        ],
        [
            _record(datetime(2024, 2, 3, tzinfo=UTC), "0.04"),
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


def test_empty_or_stale_snapshot_is_rejected_without_cache_mutation(monkeypatch) -> None:
    monkeypatch.setattr(funding, "_fetch_page", _single_page([]))
    with pytest.raises(funding.FundingFetchError, match="is empty"):
        funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))
    assert funding._SNAPSHOTS == {}
    monkeypatch.setattr(
        funding, "_fetch_page", _single_page([_record(_dt(1), "0.01")])
    )
    with pytest.raises(funding.FundingFetchError, match="is stale"):
        funding.load_funding_history("BTC-USDT", _dt(3), _dt(4))
    assert funding._SNAPSHOTS == {}


def test_before_proven_listing_is_neutral_only_with_immutable_evidence(monkeypatch) -> None:
    evidence = _evidence()
    monkeypatch.setattr(funding, "coverage_evidence_for", lambda *_args: evidence)
    monkeypatch.setattr(funding, "_fetch_page", _single_page([_record(_dt(6), "0.01")]))

    funding.load_funding_history("BTC-USDT", _dt(6), _dt(7))

    assert funding.get_funding_rate_at(_dt(4), "BTC-USDT") == 0.0
    snapshot = funding._SNAPSHOTS["BTC-USDT-SWAP"][0]
    assert funding.funding_coverage_status(snapshot, _dt(4))[0] == "proven_pre_listing"


def test_before_first_row_without_evidence_is_truncated_not_neutral(monkeypatch) -> None:
    monkeypatch.setattr(funding, "coverage_evidence_for", lambda *_args: None)
    monkeypatch.setattr(funding, "_fetch_page", _single_page([_record(_dt(6), "0.01")]))

    funding.load_funding_history("BTC-USDT", _dt(6), _dt(7))

    with pytest.raises(funding.FundingFetchError, match="truncated_snapshot: unavailable_evidence"):
        funding.get_funding_rate_at(_dt(4), "BTC-USDT")


def test_complete_snapshot_and_conflicting_coverage_metadata(monkeypatch) -> None:
    first, second = _evidence(start=_dt(1)), _evidence(start=_dt(2))
    pages = iter([[_record(_dt(6), "0.01")], [_record(_dt(7), "0.02")]])
    monkeypatch.setattr(
        funding, "_fetch_page", lambda _inst, after: next(pages) if after is None else []
    )
    monkeypatch.setattr(funding, "coverage_evidence_for", lambda *_args: first)
    funding.load_funding_history("BTC-USDT", _dt(6), _dt(7))
    snapshot = funding._SNAPSHOTS["BTC-USDT-SWAP"][0]
    assert funding.funding_coverage_status(snapshot, _dt(7))[0] == "complete_covered_period"

    monkeypatch.setattr(funding, "coverage_evidence_for", lambda *_args: second)
    with pytest.raises(funding.FundingFetchError, match="coverage evidence conflicts"):
        funding.load_funding_history("BTC-USDT", _dt(7), _dt(8))


@pytest.mark.parametrize("evidence", [_evidence(instrument="ETH-USDT-SWAP"), _evidence(venue="Bybit")])
def test_mismatched_coverage_metadata_is_rejected(monkeypatch, evidence) -> None:
    monkeypatch.setattr(funding, "coverage_evidence_for", lambda *_args: evidence)
    monkeypatch.setattr(funding, "_fetch_page", _single_page([_record(_dt(6), "0.01")]))

    with pytest.raises(funding.FundingFetchError, match="malformed coverage evidence"):
        funding.load_funding_history("BTC-USDT", _dt(6), _dt(7))


def test_coverage_fingerprint_is_deterministic_and_content_sensitive() -> None:
    first = _evidence()
    duplicate = _evidence()
    changed = _evidence(start=_dt(5))

    assert first.content_sha256 == duplicate.content_sha256 == coverage_fingerprint(first)
    assert changed.content_sha256 != first.content_sha256
    with pytest.raises(CoverageEvidenceError):
        replace(first, content_sha256="0" * 64).validate("BTC-USDT-SWAP", "OKX")


def test_funding_requirement_is_strategy_and_config_specific() -> None:
    assert funding.requires_okx_funding("pro_trend", {}) is True
    assert funding.requires_okx_funding("pro_trend", {"disable_external_filters": True}) is False
    assert funding.requires_okx_funding("swing_allocator", {}) is False
