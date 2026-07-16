from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from types import SimpleNamespace

import pytest

from cli.runner import _run_backtest
from core.backtest import BacktestResult
from data.market_data import OHLCVBar
from reporting.experiment_manifest import capture_external_contexts, external_context_requirements
from strategies.funding_coverage import make_coverage_evidence


UTC = timezone.utc


def _bars() -> list[OHLCVBar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        OHLCVBar(
            timestamp=int((start + timedelta(hours=index)).timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(21)
    ]


def _result() -> BacktestResult:
    start = datetime(2024, 1, 1, 20, tzinfo=UTC)
    return BacktestResult(
        symbol="BTC-USDT",
        strategy_name="resolved_strategy",
        timeframe="1H",
        start_date=start,
        end_date=start,
        bars_tested=1,
        initial_balance=Decimal("1000"),
        final_balance=Decimal("1000"),
        total_pnl=Decimal("0"),
        total_pnl_pct=Decimal("0"),
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        win_rate=Decimal("0"),
        profit_factor=Decimal("0"),
        max_drawdown_pct=Decimal("0"),
        sharpe_ratio=Decimal("0"),
        buy_hold_pnl_pct=Decimal("0"),
    )


@pytest.fixture
def isolated_runner(monkeypatch):
    monkeypatch.setattr("strategies.macro_context.load_macro_context", lambda *_args: None)
    monkeypatch.setattr("strategies.market_context.load_market_context", lambda *_args: None)
    monkeypatch.setattr("strategies.funding_context.load_funding_history", lambda *_args: None)
    monkeypatch.setattr("strategies.onchain_flow.load_flow_context", lambda *_args: None)
    meta = SimpleNamespace(
        name="resolved_strategy",
        warmup_days=0,
        display_name="Resolved Strategy",
        make_config=lambda _symbol, _config: SimpleNamespace(to_dict=lambda: {"resolved": True}),
        make_bot=lambda *_args: None,
    )
    monkeypatch.setattr("strategies.registry.get", lambda _name: meta)


def test_runner_emits_manifest_after_success(monkeypatch, isolated_runner) -> None:
    class Engine:
        def __init__(self, **_kwargs) -> None:
            self.last_strategy = SimpleNamespace(
                name="resolved_strategy",
                _cfg=SimpleNamespace(to_dict=lambda: {"resolved": True}),
            )

        def run(self, on_tick=None):
            if on_tick:
                on_tick(1, 1)
            return _result()

    captured = {}
    monkeypatch.setattr("core.backtest.BacktestEngine", Engine)
    monkeypatch.setattr(
        "reporting.experiment_manifest.write_experiment_evidence",
        lambda **kwargs: captured.update(kwargs) or "backtests/manifests/test.json",
    )

    result = _run_backtest(
        "BTC-USDT",
        "1H",
        "alias",
        1000.0,
        {},
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 2, tzinfo=UTC),
        prefetched_bars=_bars(),
        show_progress=False,
    )

    assert result is not None
    assert captured["requested_strategy"] == "alias"
    assert captured["resolved_strategy"] == "resolved_strategy"
    assert captured["warmup_bars"] == 20
    assert len(captured["bars"]) == 21
    assert captured["external_context_builder"]() == []


def test_context_requirements_are_strategy_specific() -> None:
    assert not any(external_context_requirements("resolved_strategy", {}).values())
    assert external_context_requirements("swing_allocator", {"use_funding_overlay": True}) == {
        "macro": False, "market": False, "flow": False, "okx_funding": False,
        "bybit_funding": True,
    }
    assert external_context_requirements(
        "swing_allocator", {"use_funding_overlay": True, "funding_overlay_source": "okx"}
    ) == {
        "macro": False, "market": False, "flow": False, "okx_funding": True,
        "bybit_funding": False,
    }
    assert external_context_requirements("pro_trend", {}) == {
        "macro": True, "market": True, "flow": False, "okx_funding": True,
        "bybit_funding": False,
    }
    assert external_context_requirements(
        "swing_allocator", {"use_mvrv": True, "use_vix": True, "use_flow_vol_overlay": True}
    ) == {
        "macro": True, "market": True, "flow": True, "okx_funding": False,
        "bybit_funding": False,
    }
    assert external_context_requirements("prop_swing", {"model_funding": False})["bybit_funding"] is False
    assert external_context_requirements("prop_swing", {"model_funding": True})["bybit_funding"] is True


def test_context_capture_marks_unqueried_context_loaded_but_unused(monkeypatch) -> None:
    import strategies.macro_context as macro

    day = datetime(2024, 1, 1).date()
    monkeypatch.setattr(macro, "_MANIFEST_ACCESSES", [])
    monkeypatch.setattr(
        macro,
        "_INSTANCES",
        {"BTC": SimpleNamespace(_mvrv={day: 1.2}, _realized={day: 100.0}, _loaded=True)},
    )

    records = capture_external_contexts(
        requirements={"macro": True},
        resolved_strategy="pro_trend",
        symbol="BTC-USDT",
        effective_from=datetime(2024, 1, 1, tzinfo=UTC),
        effective_to=datetime(2024, 1, 2, tzinfo=UTC),
        config={},
    )

    assert records[0]["loaded"] is True
    assert records[0]["consumed"] is False


def test_bybit_capture_uses_the_actual_strategy_loader(monkeypatch) -> None:
    import strategies.funding_extreme as funding

    monkeypatch.setattr(funding, "_MANIFEST_LOADS", {"BTC-USDT": [(1704067200000, 0.01)]})
    monkeypatch.setattr(funding, "_MANIFEST_CONSUMED", {"BTC-USDT": [-1]})
    record = capture_external_contexts(
        requirements={"bybit_funding": True},
        resolved_strategy="funding_extreme",
        symbol="BTC-USDT",
        effective_from=datetime(2024, 1, 1, tzinfo=UTC),
        effective_to=datetime(2024, 1, 1, 12, tzinfo=UTC),
        config={},
    )[0]

    assert record["loader_path"] == "strategies/funding_extreme.py"
    assert record["consumed"] is True


def test_swing_okx_overlay_capture_uses_the_effective_cache_slice(tmp_path, monkeypatch) -> None:
    import json
    from strategies import swing_funding_overlay as overlay

    cache = tmp_path / "funding_okx_BTC-USDT-SWAP.json"
    cache.write_text(json.dumps([
        [1704153600000, 0.01], [1704182400000, -0.01], [1704211200000, 0.02],
    ]), encoding="utf-8")
    monkeypatch.setattr(overlay, "funding_cache_path", lambda _symbol, _source="bybit": cache)
    monkeypatch.setattr(
        overlay, "_MANIFEST_ACCESSES",
        {"okx:BTC-USDT-SWAP": [datetime(2024, 1, 2, tzinfo=UTC)]},
    )

    record = capture_external_contexts(
        requirements={"okx_funding": True}, resolved_strategy="swing_allocator",
        symbol="BTC-USDT", effective_from=datetime(2024, 1, 2, tzinfo=UTC),
        effective_to=datetime(2024, 1, 2, 8, tzinfo=UTC),
        config={"use_funding_overlay": True, "funding_overlay_source": "okx"},
    )[0]

    assert record["context_type"] == "okx_funding"
    assert record["provider"] == "OKX funding snapshot"
    assert record["market"] == "BTC-USDT-SWAP"
    assert record["consumed"] is True
    assert record["source_path"] == cache


def test_prop_swing_loaded_bybit_feed_is_unused_without_funding_model(monkeypatch) -> None:
    import strategies.funding_extreme as funding

    monkeypatch.setattr(funding, "_MANIFEST_LOADS", {"BTC-USDT": [(1704067200000, 0.01)]})
    monkeypatch.setattr(funding, "_MANIFEST_CONSUMED", {})
    record = capture_external_contexts(
        requirements={"bybit_funding": False}, resolved_strategy="prop_swing", symbol="BTC-USDT",
        effective_from=datetime(2024, 1, 1, tzinfo=UTC),
        effective_to=datetime(2024, 1, 1, 12, tzinfo=UTC), config={"model_funding": False},
    )[0]

    assert record["configured"] is False
    assert record["loaded"] is True
    assert record["consumed"] is False


def test_okx_capture_exports_immutable_prelisting_evidence(monkeypatch) -> None:
    import strategies.funding_context as funding

    inst_id = "BTC-USDT-SWAP"
    evidence = make_coverage_evidence(
        source="versioned test venue snapshot", instrument=inst_id, venue="OKX",
        series_start=datetime(2024, 1, 6, tzinfo=UTC), snapshot_identity="okx-test-v1",
        generated_at=datetime(2024, 1, 10, tzinfo=UTC), validity_rule="before series start",
    )
    snapshot = funding._FundingSnapshot(
        inst_id, datetime(2023, 12, 29, tzinfo=UTC), datetime(2024, 1, 7, tzinfo=UTC),
        datetime(2024, 1, 6, tzinfo=UTC), datetime(2024, 1, 6, tzinfo=UTC), True,
        MappingProxyType({"2024-01-06": 0.01}), evidence,
    )
    monkeypatch.setattr(funding, "_SNAPSHOTS", {inst_id: (snapshot,)})
    monkeypatch.setattr(funding, "_MANIFEST_ACCESSES", {inst_id: [datetime(2024, 1, 4, tzinfo=UTC)]})

    record = capture_external_contexts(
        requirements={"okx_funding": True}, resolved_strategy="pro_trend", symbol="BTC-USDT",
        effective_from=datetime(2024, 1, 4, tzinfo=UTC), effective_to=datetime(2024, 1, 4, tzinfo=UTC), config={},
    )[0]

    assert record["coverage"] == "pre_listing"
    assert record["coverage_evidence"] == evidence.manifest_record() | {
        "metadata_snapshot_version": "funding-coverage-metadata/v1",
        "coverage_status": "proven_pre_listing", "coverage_detail": "before series start",
    }


def test_bybit_tracker_reset_prevents_cross_run_consumption_leak(monkeypatch) -> None:
    import strategies.funding_extreme as funding

    monkeypatch.setattr(funding, "_MANIFEST_LOADS", {"BTC-USDT": [(1704067200000, 0.01)]})
    monkeypatch.setattr(funding, "_MANIFEST_CONSUMED", {"BTC-USDT": [-1]})

    funding.reset_manifest_load("BTC-USDT")

    assert funding._MANIFEST_LOADS == {}
    assert funding._MANIFEST_CONSUMED == {}


def test_runner_propagates_engine_failure_without_manifest(monkeypatch, isolated_runner) -> None:
    class Engine:
        last_strategy = None

        def __init__(self, **_kwargs) -> None:
            pass

        def run(self, on_tick=None):
            raise RuntimeError("engine failed")

    called = False

    def manifest(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("core.backtest.BacktestEngine", Engine)
    monkeypatch.setattr("reporting.experiment_manifest.write_experiment_evidence", manifest)

    with pytest.raises(RuntimeError, match="engine failed"):
        _run_backtest(
            "BTC-USDT",
            "1H",
            "alias",
            1000.0,
            {},
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            prefetched_bars=_bars(),
            show_progress=False,
        )
    assert called is False


def test_non_pro_strategy_does_not_require_okx_funding(monkeypatch, isolated_runner) -> None:
    class Engine:
        def __init__(self, **_kwargs) -> None:
            self.last_strategy = SimpleNamespace(
                name="resolved_strategy",
                _cfg=SimpleNamespace(to_dict=lambda: {"resolved": True}),
            )

        def run(self, on_tick=None):
            return _result()

    monkeypatch.setattr("core.backtest.BacktestEngine", Engine)
    monkeypatch.setattr(
        "strategies.funding_context.load_funding_history",
        lambda *_args: (_ for _ in ()).throw(AssertionError("irrelevant funding load")),
    )
    monkeypatch.setattr(
        "reporting.experiment_manifest.write_experiment_evidence",
        lambda **_kwargs: "backtests/manifests/test.json",
    )

    result = _run_backtest(
        "BTC-USDT",
        "1H",
        "alias",
        1000.0,
        {},
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 2, tzinfo=UTC),
        prefetched_bars=_bars(),
        show_progress=False,
    )

    assert result is not None


def test_swing_okx_overlay_does_not_fetch_mutable_funding_during_backtest(
    monkeypatch, isolated_runner
) -> None:
    """Swing consumes its immutable local snapshot; runner must not refresh it."""
    config = {"use_funding_overlay": True, "funding_overlay_source": "okx"}

    class Engine:
        def __init__(self, **_kwargs) -> None:
            self.last_strategy = SimpleNamespace(
                name="swing_allocator", _cfg=SimpleNamespace(to_dict=lambda: config)
            )

        def run(self, on_tick=None):
            return _result()

    meta = SimpleNamespace(
        name="swing_allocator", warmup_days=0, display_name="Swing Allocator",
        make_config=lambda _symbol, _config: SimpleNamespace(to_dict=lambda: config),
        make_bot=lambda *_args: None,
    )
    monkeypatch.setattr("strategies.registry.get", lambda _name: meta)
    monkeypatch.setattr("core.backtest.BacktestEngine", Engine)
    monkeypatch.setattr(
        "strategies.funding_context.load_funding_history",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Swing must not fetch funding during a run")),
    )
    monkeypatch.setattr(
        "reporting.experiment_manifest.write_experiment_evidence",
        lambda **_kwargs: "backtests/manifests/test.json",
    )

    result = _run_backtest(
        "BTC-USDT", "1H", "swing", 1000.0, config,
        datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC),
        prefetched_bars=_bars(), show_progress=False,
    )

    assert result is not None


def test_pro_trend_with_external_filters_disabled_does_not_load_funding(
    monkeypatch, isolated_runner
) -> None:
    class Engine:
        def __init__(self, **_kwargs) -> None:
            self.last_strategy = SimpleNamespace(
                name="pro_trend",
                _cfg=SimpleNamespace(to_dict=lambda: {"disable_external_filters": True}),
            )

        def run(self, on_tick=None):
            return _result()

    meta = SimpleNamespace(
        name="pro_trend",
        warmup_days=0,
        display_name="Pro Trend",
        make_config=lambda _symbol, _config: SimpleNamespace(
            to_dict=lambda: {"disable_external_filters": True}
        ),
        make_bot=lambda *_args: None,
    )
    monkeypatch.setattr("strategies.registry.get", lambda _name: meta)
    monkeypatch.setattr("core.backtest.BacktestEngine", Engine)
    monkeypatch.setattr(
        "strategies.funding_context.load_funding_history",
        lambda *_args: (_ for _ in ()).throw(AssertionError("disabled Pro Trend funding load")),
    )
    monkeypatch.setattr(
        "reporting.experiment_manifest.write_experiment_evidence",
        lambda **_kwargs: "backtests/manifests/test.json",
    )

    result = _run_backtest(
        "BTC-USDT",
        "1H",
        "pro",
        1000.0,
        {"disable_external_filters": True},
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 2, tzinfo=UTC),
        prefetched_bars=_bars(),
        show_progress=False,
    )

    assert result is not None


def test_manifest_failure_marks_successful_simulation_incomplete(
    monkeypatch, isolated_runner
) -> None:
    class Engine:
        def __init__(self, **_kwargs) -> None:
            self.last_strategy = SimpleNamespace(
                name="resolved_strategy",
                _cfg=SimpleNamespace(to_dict=lambda: {"resolved": True}),
            )

        def run(self, on_tick=None):
            return _result()

    monkeypatch.setattr("core.backtest.BacktestEngine", Engine)
    monkeypatch.setattr(
        "reporting.experiment_manifest.write_experiment_evidence",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("manifest failed")),
    )

    with pytest.raises(RuntimeError, match="manifest failed"):
        _run_backtest(
            "BTC-USDT",
            "1H",
            "alias",
            1000.0,
            {},
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            prefetched_bars=_bars(),
            show_progress=False,
        )
