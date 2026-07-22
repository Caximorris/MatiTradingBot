from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from tools.cross_asset_swing_matrix import (
    BALANCE,
    COST_MODE,
    FROM_DATE,
    RUNS,
    TO_DATE,
    _result_metrics,
)


def test_matrix_contract_is_the_frozen_five_run_common_window() -> None:
    assert FROM_DATE.isoformat() == "2021-07-01T00:00:00+00:00"
    assert TO_DATE.isoformat() == "2026-01-01T00:00:00+00:00"
    assert BALANCE == Decimal("10000")
    assert COST_MODE == "realistic"
    assert RUNS == (
        ("BTC-USDT", "frozen_v6_2", {}),
        ("ETH-USDT", "phase_free", {
            "use_halving": False,
            "use_phase_policy_router": False,
            "use_funding_overlay": False,
        }),
        ("ETH-USDT", "btc_phase", {
            "phase_symbol": "BTC-USDT",
            "use_halving": True,
            "use_phase_policy_router": True,
            "use_funding_overlay": False,
        }),
        ("SOL-USDT", "phase_free", {
            "use_halving": False,
            "use_phase_policy_router": False,
            "use_funding_overlay": False,
        }),
        ("SOL-USDT", "btc_phase", {
            "phase_symbol": "BTC-USDT",
            "use_halving": True,
            "use_phase_policy_router": True,
            "use_funding_overlay": False,
        }),
    )


def test_matrix_reports_allocator_and_matched_coin_buy_hold_metrics() -> None:
    result = SimpleNamespace(
        buy_hold_pnl_pct=Decimal("50.0"),
        final_balance=Decimal("12500"),
        cagr=Decimal("5.5"),
        max_drawdown_pct=Decimal("20.0"),
        calmar=Decimal("0.28"),
        final_asset_qty=Decimal("4"),
        bnh_initial_asset=Decimal("5"),
        asset_vs_bnh_ratio=Decimal("0.8"),
    )

    assert _result_metrics(result) == {
        "coin_buy_hold_pct": "50.0",
        "final_balance": "12500",
        "cagr_pct": "5.5",
        "max_drawdown_pct": "20.0",
        "calmar": "0.28",
        "final_asset_qty": "4",
        "bnh_initial_asset": "5",
        "asset_vs_bnh_ratio": "0.8",
    }
