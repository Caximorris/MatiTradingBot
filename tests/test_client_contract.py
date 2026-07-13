"""Contract shared by live, demo and backtest trading clients.

The strategies intentionally depend on this small surface. Operational helpers and
backtest cursor controls may differ, but every difference must be listed explicitly
so a new client method cannot drift silently between execution modes.
"""
from __future__ import annotations

import pytest

from core.backtest import BacktestClient
from core.exchange import OKXClient
from core.okx_demo_client import OKXDemoClient


STRATEGY_CLIENT_CONTRACT = {
    "adjust_balance",
    "cancel_order",
    "current_time",
    "fill_paper_limit_orders",
    "get_balance",
    "get_funding_rate",
    "get_ohlcv",
    "get_open_orders",
    "get_positions",
    "get_ticker",
    "is_paper",
    "place_order",
}

EXPECTED_PUBLIC_SURFACE = {
    OKXClient: STRATEGY_CLIENT_CONTRACT | {
        "get_order_history", "get_paper_orders", "is_available", "set_paper_balance",
    },
    OKXDemoClient: STRATEGY_CLIENT_CONTRACT | {
        "get_order_history", "get_paper_orders", "is_available",
    },
    BacktestClient: STRATEGY_CLIENT_CONTRACT | {
        "advance", "current_bar", "current_bar_ts",
    },
}


def _public_surface(client_type: type) -> set[str]:
    return {
        name
        for name, value in vars(client_type).items()
        if not name.startswith("_")
        and (callable(value) or isinstance(value, property) or name == "is_paper")
    }


@pytest.mark.parametrize("client_type", EXPECTED_PUBLIC_SURFACE)
def test_all_clients_implement_strategy_contract(client_type: type) -> None:
    missing = STRATEGY_CLIENT_CONTRACT - _public_surface(client_type)
    assert not missing, f"{client_type.__name__} missing strategy client methods: {sorted(missing)}"


@pytest.mark.parametrize("client_type, expected", EXPECTED_PUBLIC_SURFACE.items())
def test_client_specific_surface_is_explicit(client_type: type, expected: set[str]) -> None:
    assert _public_surface(client_type) == expected
