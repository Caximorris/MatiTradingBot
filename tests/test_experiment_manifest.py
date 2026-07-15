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


def _write(root: Path, result: BacktestResult, artifacts=(), external_inputs=()) -> Path:
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
        repo_root=root,
    )


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
            "exists": True,
            "path": "data/cache/funding.json",
            "sha256": manifests._file_sha256(funding),
            "size_bytes": funding.stat().st_size,
        }
    ]


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
