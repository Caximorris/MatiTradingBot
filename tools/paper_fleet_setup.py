#!/usr/bin/env python
"""Reconcile the paper fleet to v6 simulated + v6 OKX Demo + Prop Firm.

This command changes BotState only. Historical trades, journals, and wallet files are
preserved. It is idempotent and safe to run after every deployment before restarting
``matibot``.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class FleetSpec:
    name: str
    symbol: str
    config: dict


def desired_fleet(
    symbol: str = "BTC-USDT",
    account_size: float = 50_000.0,
    phase: str = "p1",
    daily_dd: float = 0.06,
    max_loss: float = 0.12,
) -> list[FleetSpec]:
    from tools.okx_demo_setup import bot_name as demo_name, demo_config
    from tools.prop_cft_setup import bot_name as prop_name, prop_config
    from tools.swing_paper_setup import _bot_name as swing_name, _v6_config

    symbol = symbol.upper()
    return [
        FleetSpec(swing_name("v6", symbol), symbol, _v6_config()),
        FleetSpec(demo_name(symbol), symbol, demo_config()),
        FleetSpec(
            prop_name(symbol), symbol,
            prop_config(account_size, phase, daily_dd, max_loss),
        ),
    ]


def reconcile_fleet(session, specs: list[FleetSpec]) -> dict:
    """Apply exact active fleet while preserving non-legacy history and state rows."""
    from core.database import BotState, get_or_create_bot_state

    desired_keys = {(spec.name, spec.symbol) for spec in specs}
    for spec in specs:
        state = get_or_create_bot_state(
            session, spec.name, spec.symbol, config=spec.config,
        )
        state.set_config(spec.config)
        state.is_active = True

    removed: list[str] = []
    deactivated: list[str] = []
    retired_names = {
        "swing_allocator_btc_usdt",
        "swing_allocator_v5_btc_usdt",
        "swing_allocator",
    }
    for state in list(session.query(BotState).all()):
        key = (state.strategy_name, state.symbol)
        if key in desired_keys:
            continue
        if state.symbol == "BTC-USDT" and state.strategy_name in retired_names:
            removed.append(state.strategy_name)
            session.delete(state)
        elif state.is_active:
            state.is_active = False
            deactivated.append(state.strategy_name)

    session.flush()
    return {
        "active": [spec.name for spec in specs],
        "removed": sorted(removed),
        "deactivated": sorted(deactivated),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC-USDT")
    parser.add_argument("--account-size", type=float, default=50_000.0)
    parser.add_argument("--phase", default="p1", choices=("p1", "p2", "funded"))
    parser.add_argument("--daily-dd", type=float, default=0.06)
    parser.add_argument("--max-loss", type=float, default=0.12)
    args = parser.parse_args()

    from core.database import get_session, init_db

    specs = desired_fleet(
        args.symbol, args.account_size, args.phase, args.daily_dd, args.max_loss,
    )
    init_db()
    with get_session() as session:
        result = reconcile_fleet(session, specs)

    print(json.dumps(result, sort_keys=True))
    print("Fleet lista: v6 simulated + v6 OKX Demo + Prop Firm. Reiniciar matibot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
