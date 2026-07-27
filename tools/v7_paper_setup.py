#!/usr/bin/env python
# ruff: noqa: E402
"""Prepare the inactive V7 certified isolated paper candidate; never activate it."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_certified_paper import PaperSafetyError, make_config

CERTIFIED_NAME = "swing_cycle_core_v7_certified_isolated_paper"
# Compatibility names are retained solely for historical read-only evidence
# consumers.  ``register`` never creates either legacy route.
SHADOW_NAME = "swing_cycle_core_v7_btc_usdt_shadow"
PAPER_NAME = CERTIFIED_NAME


def config_for(mode_or_root: str | Path = ROOT) -> dict:
    if mode_or_root == "shadow":
        return {"instance_id": "v7_btc_usdt_shadow", "paper_portfolio_id": "swing_cycle_core_v7_btc_usdt_shadow",
                "execution": "v7_shadow", "service_managed": True, "operational_mode": "shadow",
                "transition_journal_path": "data/runtime/v7/v7_btc_usdt_shadow/transitions.jsonl", "phase_post_end": 180,
                "phase_bear_start": 540, "phase_accumulation_start": 900, "bear_onset_btc_pct": "0",
                "max_data_age_hours": 5, "max_strategic_orders_per_day": 4, "max_unresolved_orders": 1}
    root = ROOT if isinstance(mode_or_root, str) else mode_or_root
    config = make_config(root)
    return config.as_dict()


def register(session, *, root: Path = ROOT) -> dict:
    """Idempotently register one inactive candidate row without creating runtime state.

    The caller must explicitly invoke this tool later; this function does not
    touch a wallet or journal and has no activation parameter by design.
    """
    from core.database import BotState, get_or_create_bot_state
    config = make_config(root)
    config.validate()
    conflicting = session.query(BotState).filter_by(strategy_name=CERTIFIED_NAME, symbol="BTC-USDT").first()
    if conflicting is not None:
        existing = conflicting.get_config()
        if existing.get("configuration_hash") != config.configuration_hash:
            raise PaperSafetyError("existing conflicting certified candidate state")
        if conflicting.is_active:
            raise PaperSafetyError("automatic activation is prohibited")
        return {CERTIFIED_NAME: {"active": False, "idempotent": True, **config.as_dict()}}
    state = get_or_create_bot_state(session, CERTIFIED_NAME, "BTC-USDT", config=config.as_dict())
    state.set_config(config.as_dict())
    state.is_active = False
    return {CERTIFIED_NAME: {"active": False, "idempotent": False, **config.as_dict()}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-config", action="store_true", help="read-only; print frozen setup")
    parser.add_argument("--create-inactive", action="store_true", help="PERSISTENT STATE: register inactive candidate")
    args = parser.parse_args()
    if args.print_config:
        print(json.dumps(config_for(), sort_keys=True))
        return 0
    if not args.create_inactive:
        parser.error("choose --print-config or --create-inactive; activation is not implemented")
    from core.database import get_session, init_db
    init_db()
    with get_session() as session:
        result = register(session)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
