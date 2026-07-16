#!/usr/bin/env python
"""Register isolated Swing v5/v6 paper bots in BotState."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _bot_name(instance_id: str, symbol: str) -> str:
    sym = symbol.upper().replace("-", "_").lower()
    return f"swing_allocator_{instance_id}_{sym}"


def _v5_config() -> dict:
    return {
        "instance_id": "v5",
        "paper_portfolio_id": "swing_v5",
        "persist_live_rebalance_log": True,
        "use_phase_policy_router": False,
        "use_funding_overlay": False,
    }


def _v6_config() -> dict:
    cfg = _v5_config()
    cfg.update({
        "instance_id": "v6",
        "paper_portfolio_id": "swing_v6",
        "use_phase_policy_router": True,
        "phase_policy_profile": "v5_equiv",
        "use_funding_overlay": True,
        "funding_overlay_source": "okx",
        "funding_overlay_phases": "accumulation",
        "funding_overlay_delta": 0.05,
        "funding_low_pctile": 0.10,
        "funding_high_pctile": 0.90,
        "funding_overlay_lookback_settlements": 90,
        "funding_overlay_ttl_days": 7,
        "funding_overlay_dedup_days": 7,
    })
    return cfg


def _register(symbol: str, instance_id: str, config: dict, enable: bool) -> str:
    from core.database import get_or_create_bot_state, get_session

    name = _bot_name(instance_id, symbol)
    with get_session() as s:
        state = get_or_create_bot_state(s, name, symbol.upper(), config=config)
        state.set_config(config)
        state.is_active = bool(enable)
    return name


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC-USDT")
    p.add_argument("--enable", action="store_true")
    p.add_argument("--include-v5", action="store_true")
    p.add_argument("--v6-only", action="store_true")
    args = p.parse_args()

    from core.database import init_db

    init_db()
    registered: list[tuple[str, dict]] = []
    if args.include_v5 and not args.v6_only:
        cfg = _v5_config()
        registered.append((_register(args.symbol, "v5", cfg, args.enable), cfg))
    cfg = _v6_config()
    registered.append((_register(args.symbol, "v6", cfg, args.enable), cfg))

    for name, config in registered:
        print(f"registered,{name},{args.symbol.upper()},active={args.enable}")
        print(json.dumps(config, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
