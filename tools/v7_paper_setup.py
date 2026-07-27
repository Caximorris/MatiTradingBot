#!/usr/bin/env python
"""Register, but never silently activate, isolated v7 shadow and local-paper bots."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_certified_paper import PaperSafetyError, make_config

SHADOW_NAME = "swing_cycle_core_v7_btc_usdt_shadow"
PAPER_NAME = "swing_cycle_core_v7_btc_usdt_paper"
CERTIFIED_NAME = "swing_cycle_core_v7_certified_isolated_paper"


def config_for(mode_or_root: str | Path) -> dict:
    """Return legacy config by mode or the separate certified inactive config by root."""
    if isinstance(mode_or_root, Path):
        return make_config(mode_or_root).as_dict()
    mode = mode_or_root
    if mode not in {"shadow", "paper"}:
        raise ValueError("mode must be shadow or paper")
    instance = f"v7_btc_usdt_{mode}"
    return {
        "instance_id": instance,
        "paper_portfolio_id": f"swing_cycle_core_{instance}",
        "execution": "v7_shadow" if mode == "shadow" else "v7_local_paper",
        "service_managed": True,
        "operational_mode": mode,
        "transition_journal_path": f"data/runtime/v7/{instance}/transitions.jsonl",
        "phase_post_end": 180,
        "phase_bear_start": 540,
        "phase_accumulation_start": 900,
        "bear_onset_btc_pct": "0",
        "max_data_age_hours": 5,
        "max_strategic_orders_per_day": 4,
        "max_unresolved_orders": 1,
    }


def register_certified(session, *, root: Path = ROOT) -> dict:
    """Idempotently register a separate inactive certified candidate only."""
    from core.database import BotState, get_or_create_bot_state

    config = make_config(root)
    config.validate()
    existing = session.query(BotState).filter_by(
        strategy_name=CERTIFIED_NAME, symbol="BTC-USDT"
    ).first()
    if existing is not None:
        if existing.get_config().get("configuration_hash") != config.configuration_hash:
            raise PaperSafetyError("existing conflicting certified candidate state")
        if existing.is_active:
            raise PaperSafetyError("automatic activation is prohibited")
        return {CERTIFIED_NAME: {"active": False, "idempotent": True, **config.as_dict()}}
    state = get_or_create_bot_state(session, CERTIFIED_NAME, "BTC-USDT", config=config.as_dict())
    state.set_config(config.as_dict())
    state.is_active = False
    return {CERTIFIED_NAME: {"active": False, "idempotent": False, **config.as_dict()}}


def register(session, *, activate_shadow: bool = False, activate_paper: bool = False) -> dict:
    from core.database import get_or_create_bot_state
    result = {}
    for name, mode, active in ((SHADOW_NAME, "shadow", activate_shadow),
                               (PAPER_NAME, "paper", activate_paper)):
        state = get_or_create_bot_state(session, name, "BTC-USDT", config=config_for(mode))
        state.set_config(config_for(mode))
        state.is_active = active
        result[name] = {"active": active, "config_hash": __import__("hashlib").sha256(
            json.dumps(config_for(mode), sort_keys=True).encode()).hexdigest()}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--activate-shadow", action="store_true")
    parser.add_argument("--activate-paper", action="store_true")
    parser.add_argument("--create-certified-inactive", action="store_true")
    args = parser.parse_args()
    from core.database import get_session, init_db
    init_db()
    with get_session() as session:
        if args.create_certified_inactive:
            if args.activate_shadow or args.activate_paper:
                parser.error("certified candidate cannot share a legacy activation request")
            result = register_certified(session)
        else:
            result = register(session, activate_shadow=args.activate_shadow, activate_paper=args.activate_paper)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
