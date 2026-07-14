#!/usr/bin/env python
"""Reconcile the paper fleet to v6 simulated + v6 OKX Demo.

This command changes BotState only. Historical trades, journals, and wallet files are
preserved. It is idempotent and safe to run after every deployment before restarting
``matibot``.

Prop Firm (``prop_swing_btc_usdt``) retired from the active fleet 2026-07-14: its CFT
gate promotion numbers (74.8% pass / 2.0% breach) were computed with a funding-accrual
bug (`load_funding()` returned unsorted settlements, so `model_funding=True` never
actually applied — see EXPERIMENTS.md EXP-013). Re-run with the fix: 45.4% pass / 14.8%
breach, below the >=60% adoption gate. Deactivated here rather than deleted — its
BotState, wallet, and journal are preserved for audit/rollback (`docs/prop/hyrotrader-plan.md`).
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


def desired_fleet(symbol: str = "BTC-USDT") -> list[FleetSpec]:
    from tools.okx_demo_setup import bot_name as demo_name, demo_config
    from tools.swing_paper_setup import _bot_name as swing_name, _v6_config

    symbol = symbol.upper()
    return [
        FleetSpec(swing_name("v6", symbol), symbol, _v6_config()),
        FleetSpec(demo_name(symbol), symbol, demo_config()),
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
    args = parser.parse_args()

    from core.database import get_session, init_db

    specs = desired_fleet(args.symbol)
    init_db()
    with get_session() as session:
        result = reconcile_fleet(session, specs)

    print(json.dumps(result, sort_keys=True))
    print("Fleet lista: v6 simulated + v6 OKX Demo. Reiniciar matibot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
