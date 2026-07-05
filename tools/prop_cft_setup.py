#!/usr/bin/env python
"""Register the PropSwing CFT paper bot in BotState.

This does not start the scheduler. Use `--enable` only when you want the
already-running VM service to pick it up on the next restart/tick cycle.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--account-size", type=float, default=50_000.0)
    p.add_argument("--phase", default="p1", choices=("p1", "p2", "funded"))
    p.add_argument("--daily-dd", type=float, default=0.06)
    p.add_argument("--max-loss", type=float, default=0.12)
    p.add_argument("--enable", action="store_true")
    args = p.parse_args()

    from core.database import get_or_create_bot_state, get_session, init_db

    config = {
        "entry_mode": "breakout",
        "risk_per_trade": 0.018,
        "tp1_r": 1.5,
        "allow_shorts": True,
        "max_notional_pct": 0.8,
        "model_funding": True,
        "entry_halving_phases": "bear_onset,accumulation",
        "persist_live_prop_log": True,
        "cft_monitor_enabled": True,
        "cft_account_size": args.account_size,
        "cft_phase": args.phase,
        "cft_daily_dd_pct": args.daily_dd,
        "cft_max_loss_pct": args.max_loss,
    }
    bot_name = f"prop_swing_{args.symbol.upper().replace('-', '_').lower()}"
    init_db()
    with get_session() as s:
        state = get_or_create_bot_state(s, bot_name, args.symbol.upper(), config=config)
        state.set_config(config)
        state.is_active = bool(args.enable)
    print(f"registered,{bot_name},{args.symbol.upper()},active={args.enable}")
    print(json.dumps(config, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
