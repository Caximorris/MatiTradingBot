from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from cli.runner import _run_backtest
from core.backtest import BacktestResult
from data.market_data import OHLCVBar


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
        "reporting.experiment_manifest.write_experiment_manifest",
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
    assert captured["external_inputs"] == []


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
    monkeypatch.setattr("reporting.experiment_manifest.write_experiment_manifest", manifest)

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
        "reporting.experiment_manifest.write_experiment_manifest",
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
        "reporting.experiment_manifest.write_experiment_manifest",
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
