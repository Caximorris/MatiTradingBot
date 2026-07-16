from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.backtest import BacktestResult
from data.market_data import OHLCVBar
from reporting import experiment_manifest as manifests
from strategies.funding_coverage import make_coverage_evidence


UTC = timezone.utc


def _bar(timestamp: int, close: str = "100") -> OHLCVBar:
    value = Decimal(close)
    return OHLCVBar(timestamp, value, value, value, value, Decimal("1"))


def _result(final_balance: str = "1100") -> BacktestResult:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)
    return BacktestResult(
        symbol="BTC-USDT",
        strategy_name="test_strategy",
        timeframe="1H",
        start_date=start,
        end_date=end,
        bars_tested=2,
        initial_balance=Decimal("1000"),
        final_balance=Decimal(final_balance),
        total_pnl=Decimal(final_balance) - Decimal("1000"),
        total_pnl_pct=Decimal("10"),
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        win_rate=Decimal("0"),
        profit_factor=Decimal("0"),
        max_drawdown_pct=Decimal("0"),
        sharpe_ratio=Decimal("0"),
        buy_hold_pnl_pct=Decimal("0"),
        equity_curve=[(start, Decimal("1000")), (end, Decimal(final_balance))],
    )


@pytest.fixture
def stable_provenance(monkeypatch):
    monkeypatch.setattr(
        manifests,
        "_repository_identity",
        lambda _root: {"head": "a" * 40, "dirty": False, "worktree_sha256": "b" * 64},
    )
    monkeypatch.setattr(
        manifests,
        "_environment_identity",
        lambda _root: {
            "python": "3.12.0",
            "implementation": "CPython",
            "platform": "test",
            "dependencies": {"example": "1.0"},
        },
    )


def _write(
    root: Path, result: BacktestResult, artifacts=(), external_inputs=(), external_contexts=(),
    context_requirements=None,
) -> Path:
    bars = [_bar(1), _bar(1), _bar(2, "101")]
    return manifests.write_experiment_manifest(
        result=result,
        requested_strategy="alias",
        resolved_strategy="test_strategy",
        config_overrides={"threshold": Decimal("0.10")},
        resolved_config={"threshold": Decimal("0.10")},
        symbol="BTC-USDT",
        timeframe="1H",
        requested_from=datetime(2024, 1, 1, tzinfo=UTC),
        requested_to=datetime(2024, 1, 2, tzinfo=UTC),
        warmup_bars=1,
        initial_balance=Decimal("1000.00"),
        cost_mode="realistic",
        fee_rate=Decimal("0.001"),
        slippage_bps=Decimal("5"),
        fill_next_open=False,
        bars=bars,
        artifacts=artifacts,
        external_inputs=external_inputs,
        external_contexts=external_contexts,
        context_requirements=context_requirements,
        repo_root=root,
    )


def _context(root: Path, context_type: str, observations, **overrides) -> dict:
    loader = root / "loaders" / f"{context_type}.py"
    loader.parent.mkdir(exist_ok=True)
    loader.write_text("VERSION = 1\n", encoding="utf-8")
    return {
        "context_type": context_type,
        "provider": "test-provider",
        "market": "BTC-USDT",
        "configured": True,
        "loaded": True,
        "consumed": True,
        "effective_from": datetime(2024, 1, 1, tzinfo=UTC),
        "effective_to": datetime(2024, 1, 2, tzinfo=UTC),
        "observations": observations,
        "loader_path": loader.relative_to(root).as_posix(),
        "loader_version": "test-loader/v1",
        "coverage": "covered",
        "freshness": "fresh",
        "source_path": None,
        **overrides,
    }


def test_manifest_is_canonical_stable_and_preserves_decimals(
    tmp_path: Path, stable_provenance
) -> None:
    artifact = tmp_path / "backtests" / "journal_test.json"
    artifact.parent.mkdir()
    artifact.write_text("{}\n", encoding="utf-8")

    first = _write(tmp_path, _result(), [artifact.relative_to(tmp_path)])
    first_bytes = first.read_bytes()
    second = _write(tmp_path, _result(), [artifact.relative_to(tmp_path)])
    doc = json.loads(first.read_text(encoding="utf-8"))

    assert second == first
    assert second.read_bytes() == first_bytes
    assert doc["run_id"] == first.stem
    assert doc["identity"]["capital"]["initial_balance"] == "1000.00"
    assert doc["identity"]["dataset"]["input_bars"] == 3
    assert doc["artifacts"][0]["path"] == "backtests/journal_test.json"
    assert not list(first.parent.glob("*.tmp"))


def test_manifest_records_no_external_context_for_context_free_strategy(
    tmp_path: Path, stable_provenance
) -> None:
    manifest = _write(tmp_path, _result())

    assert json.loads(manifest.read_text(encoding="utf-8"))["identity"]["external_contexts"] == []


def test_context_requirement_statuses_include_not_configured_and_require_records(
    tmp_path: Path, stable_provenance
) -> None:
    manifest = _write(
        tmp_path,
        _result(),
        external_contexts=[_context(tmp_path, "macro", [("2024-01-01", 1.0)])],
        context_requirements={"macro": True, "market": False},
    )
    identity = json.loads(manifest.read_text(encoding="utf-8"))["identity"]

    assert identity["external_context_statuses"] == {"macro": "consumed", "market": "not_configured"}
    with pytest.raises(manifests.ManifestError, match="required external context was not recorded"):
        _write(tmp_path, _result(), context_requirements={"okx_funding": True})


def test_context_records_cover_bybit_okx_and_multiple_remote_contexts(
    tmp_path: Path, stable_provenance
) -> None:
    bybit_source = tmp_path / "data" / "cache" / "funding_bybit_BTCUSDT.json"
    bybit_source.parent.mkdir(parents=True)
    bybit_source.write_text("[[1, 0.01]]\n", encoding="utf-8")
    contexts = [
        _context(tmp_path, "bybit_funding", [(1, 0.01)], source_path=bybit_source),
        _context(tmp_path, "okx_funding", [("2024-01-01", 0.01)]),
        _context(tmp_path, "macro", [("2024-01-01", 1.2, 100.0)]),
        _context(tmp_path, "market", [("2024-01-01", 102.0)]),
        _context(tmp_path, "flow", [("2024-01-01", "2024-01-02", 0.1, "spike")]),
    ]
    manifest = _write(tmp_path, _result(), external_contexts=contexts)
    records = json.loads(manifest.read_text(encoding="utf-8"))["identity"]["external_contexts"]

    assert [record["context_type"] for record in records] == [
        "bybit_funding", "flow", "macro", "market", "okx_funding"
    ]
    bybit = records[0]
    assert bybit["source_file_sha256"] == manifests._file_sha256(bybit_source)
    assert all(record["status"] == "consumed" for record in records)
    assert all(record["ordered_content_sha256"] and record["snapshot_identity"] for record in records)


def test_loaded_but_unused_context_is_retained_without_certifying_consumption(
    tmp_path: Path, stable_provenance
) -> None:
    context = _context(tmp_path, "market", [("2024-01-01", 102.0)], consumed=False)
    manifest = _write(tmp_path, _result(), external_contexts=[context])
    record = json.loads(manifest.read_text(encoding="utf-8"))["identity"]["external_contexts"][0]

    assert record["status"] == "loaded_not_consumed"
    assert record["affected_strategy_decisions"] is False


def test_prelisting_context_requires_immutable_coverage_evidence(
    tmp_path: Path, stable_provenance
) -> None:
    context = _context(tmp_path, "okx_funding", [], coverage="pre_listing")
    with pytest.raises(manifests.ManifestError, match="pre-listing coverage lacks immutable evidence"):
        _write(tmp_path, _result(), external_contexts=[context])

    evidence = make_coverage_evidence(
        source="versioned metadata", instrument="BTC-USDT-SWAP", venue="OKX",
        series_start=datetime(2024, 1, 2, tzinfo=UTC), snapshot_identity="coverage-v1",
        generated_at=datetime(2024, 1, 3, tzinfo=UTC), validity_rule="before series start",
    )
    context["coverage_evidence"] = evidence.manifest_record() | {"coverage_status": "proven_pre_listing"}
    document = json.loads(_write(tmp_path, _result(), external_contexts=[context]).read_text(encoding="utf-8"))

    assert document["identity"]["external_contexts"][0]["coverage_evidence"]["venue"] == "OKX"
    context["coverage_evidence"]["content_sha256"] = "not-a-hash"
    with pytest.raises(manifests.ManifestError, match="pre-listing coverage is invalid"):
        _write(tmp_path, _result(), external_contexts=[context])


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"configured": False, "loaded": False, "consumed": False}, "not_configured"),
        ({"loaded": False, "consumed": False}, "configured_not_loaded"),
    ],
)
def test_non_consumed_context_states_are_explicit(
    tmp_path: Path, stable_provenance, overrides: dict, status: str
) -> None:
    context = _context(tmp_path, "market", [], **overrides)
    manifest = _write(tmp_path, _result(), external_contexts=[context])

    assert json.loads(manifest.read_text(encoding="utf-8"))["identity"]["external_contexts"][0]["status"] == status


@pytest.mark.parametrize("coverage", ["missing", "stale", "invalid", "partial"])
def test_consumed_context_without_usable_evidence_fails_closed(
    tmp_path: Path, stable_provenance, coverage: str
) -> None:
    context = _context(tmp_path, "macro", [], loaded=False, coverage=coverage, freshness=coverage)

    with pytest.raises(manifests.ManifestError, match="not certifiable"):
        _write(tmp_path, _result(), external_contexts=[context])


def test_effective_context_slice_hash_is_order_sensitive_and_deterministic(
    tmp_path: Path, stable_provenance
) -> None:
    ordered = _context(tmp_path, "macro", [("2024-01-01", 1.0), ("2024-01-02", 2.0)])
    reversed_rows = _context(tmp_path, "macro", [("2024-01-02", 2.0), ("2024-01-01", 1.0)])
    first = _write(tmp_path, _result(), external_contexts=[ordered])
    duplicate = _write(tmp_path, _result(), external_contexts=[ordered])
    reordered = _write(tmp_path, _result(), external_contexts=[reversed_rows])

    assert first == duplicate
    assert first.read_bytes() == duplicate.read_bytes()
    assert first != reordered


def test_slice_coverage_rejects_a_gap_inside_the_effective_window() -> None:
    rows = [("2024-01-01", 1.0), ("2024-01-20", 2.0), ("2024-02-01", 3.0)]

    assert manifests._slice_coverage(
        rows, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC), max_gap_days=7,
    ) == "partial"


def test_same_identity_with_different_result_fails_closed(
    tmp_path: Path, stable_provenance
) -> None:
    _write(tmp_path, _result("1100"))
    with pytest.raises(manifests.ManifestError, match="different result"):
        _write(tmp_path, _result("1200"))


def test_ordered_dataset_hash_includes_duplicates() -> None:
    one = manifests._dataset_identity([_bar(1), _bar(1), _bar(2)], 2)
    without_duplicate = manifests._dataset_identity([_bar(1), _bar(2)], 2)
    reordered = manifests._dataset_identity([_bar(2), _bar(1), _bar(1)], 2)

    assert one["sha256"] != without_duplicate["sha256"]
    assert one["sha256"] != reordered["sha256"]


def test_external_input_content_and_absence_change_run_identity(
    tmp_path: Path, stable_provenance
) -> None:
    funding = tmp_path / "data" / "cache" / "funding.json"
    missing = _write(tmp_path, _result(), external_inputs=[funding])
    funding.parent.mkdir(parents=True)
    funding.write_text("[]\n", encoding="utf-8")
    present = _write(tmp_path, _result(), external_inputs=[funding])
    document = json.loads(present.read_text(encoding="utf-8"))

    assert missing != present
    assert document["identity"]["external_inputs"] == [
        {
            "kind": "file",
            "exists": True,
            "path": "data/cache/funding.json",
            "sha256": manifests._file_sha256(funding),
            "size_bytes": funding.stat().st_size,
            "coverage": None,
        }
    ]


def test_manifest_records_dataset_coverage_funding_slice_and_config_fingerprint(
    tmp_path: Path, stable_provenance
) -> None:
    funding = tmp_path / "data" / "cache" / "funding_bybit_BTCUSDT.json"
    funding.parent.mkdir(parents=True)
    funding.write_text("[[1000, 0.01], [2000, -0.02]]\n", encoding="utf-8")

    manifest = _write(tmp_path, _result(), external_inputs=[funding])
    document = json.loads(manifest.read_text(encoding="utf-8"))
    identity = document["identity"]

    assert identity["strategy"]["config_sha256"] == manifests._sha256_json({
        "overrides": {"threshold": Decimal("0.10")},
        "resolved": {"threshold": Decimal("0.10")},
    })
    assert identity["repository"] == {
        "head": "a" * 40, "dirty": False, "worktree_sha256": "b" * 64,
    }
    assert identity["environment"]["python"] == "3.12.0"
    assert identity["execution"]["market_fill"] == "decision_bar_close"
    assert identity["dataset"]["coverage"] == {
        "first_utc": "1970-01-01T00:00:00.001000Z",
        "last_utc": "1970-01-01T00:00:00.002000Z",
    }
    assert identity["external_inputs"][0]["coverage"]["settlement_count"] == 2
    assert identity["funding_slice"] == [{
        "availability": "point_in_time_settlements_only",
        "coverage": identity["external_inputs"][0]["coverage"],
        "path": "data/cache/funding_bybit_BTCUSDT.json",
        "requested_from_utc": "2024-01-01T00:00:00Z",
        "requested_to_utc": "2024-01-02T00:00:00Z",
    }]


def test_failed_manifest_removes_only_created_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    journal = tmp_path / "backtests" / "journal_pending.json"
    journal.parent.mkdir()
    journal.write_text("{}\n", encoding="utf-8")
    report = tmp_path / "reports" / "existing.md"
    report.parent.mkdir()
    report.write_text("do not remove\n", encoding="utf-8")

    monkeypatch.setattr(
        manifests,
        "write_experiment_manifest",
        lambda **_kwargs: (_ for _ in ()).throw(manifests.ManifestError("publish failed")),
    )

    with pytest.raises(manifests.ManifestError, match="publish failed"):
        manifests.write_experiment_evidence(
            created_artifacts=[journal],
            result=_result(),
            requested_strategy="alias",
            resolved_strategy="test_strategy",
            config_overrides={},
            resolved_config={},
            symbol="BTC-USDT",
            timeframe="1H",
            requested_from=datetime(2024, 1, 1, tzinfo=UTC),
            requested_to=datetime(2024, 1, 2, tzinfo=UTC),
            warmup_bars=1,
            initial_balance=Decimal("1000"),
            cost_mode="realistic",
            fee_rate=Decimal("0.001"),
            slippage_bps=Decimal("5"),
            fill_next_open=False,
            bars=[_bar(1)],
            artifacts=[journal],
            repo_root=tmp_path,
        )

    assert not journal.exists()
    assert report.read_text(encoding="utf-8") == "do not remove\n"
    markers = list((tmp_path / "backtests" / "incomplete").glob("*.json"))
    assert len(markers) == 1
    assert json.loads(markers[0].read_text(encoding="utf-8"))["status"] == "incomplete_uncertified"


def test_context_capture_failure_removes_journal_before_manifest_publication(tmp_path: Path) -> None:
    journal = tmp_path / "backtests" / "journal_pending.json"
    journal.parent.mkdir()
    journal.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="capture failed"):
        manifests.write_experiment_evidence(
            created_artifacts=[journal],
            external_context_builder=lambda: (_ for _ in ()).throw(RuntimeError("capture failed")),
            repo_root=tmp_path,
        )

    assert not journal.exists()
    marker = next((tmp_path / "backtests" / "incomplete").glob("*.json"))
    assert json.loads(marker.read_text(encoding="utf-8"))["failure_message"] == "capture failed"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN")])
def test_non_finite_values_are_rejected(value) -> None:
    with pytest.raises(manifests.ManifestError, match="non-finite"):
        manifests._canonical_bytes({"value": value})


def test_artifacts_must_remain_inside_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-evidence.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        with pytest.raises(manifests.ManifestError, match="outside repository"):
            manifests._artifact_record(outside, tmp_path)
    finally:
        outside.unlink(missing_ok=True)


def test_repository_identity_tracks_source_changes_but_ignores_generated_files(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "research@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Research Test"], cwd=tmp_path, check=True
    )
    (tmp_path / ".gitignore").write_text("generated/\n", encoding="utf-8")
    source = tmp_path / "model.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)

    clean = manifests._repository_identity(tmp_path)
    generated = tmp_path / "generated" / "artifact.json"
    generated.parent.mkdir()
    generated.write_text("{}\n", encoding="utf-8")
    ignored = manifests._repository_identity(tmp_path)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    changed = manifests._repository_identity(tmp_path)

    assert ignored == clean
    assert changed["dirty"] is True
    assert changed["worktree_sha256"] != clean["worktree_sha256"]
