#!/usr/bin/env python
# ruff: noqa: E402
"""Operator-safe diagnostics and reconciliation for v7 ERROR_LOCKED."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_operations import RUNTIME, canonical_hash


def _state_name(instance: str) -> str:
    return "swing_cycle_core_" + instance.lower().replace("-", "_")


def inspect(instance: str) -> dict:
    from core.database import BotState, get_session, init_db
    from tools.paper_bots import paper_state_path
    init_db()
    with get_session() as session:
        row = session.query(BotState).filter_by(strategy_name=_state_name(instance), symbol="BTC-USDT").first()
        registered = session.query(BotState).filter_by(strategy_name=f"swing_cycle_core_{instance}_btc_usdt", symbol="BTC-USDT").first()
        config = registered.get_config() if registered else {}
        state = row.get_config() if row else {}
    wallet = paper_state_path(config.get("paper_portfolio_id"), Path("data") / "runtime")
    balances = json.loads(wallet.read_text(encoding="utf-8")) if wallet.exists() else {}
    return {"instance": instance, "registered": bool(registered), "config": config, "strategy_state": state,
            "wallet_path": str(wallet), "wallet": balances,
            "journal_path": config.get("transition_journal_path"), "read_only": True}


def reconcile(instance: str, *, apply: bool) -> dict:
    snapshot = inspect(instance)
    state = snapshot["strategy_state"]
    safe = state.get("state") == "ERROR_LOCKED" and bool(snapshot["registered"])
    audit = {"audit_id": canonical_hash({"instance": instance, "state": state, "at": datetime.now(timezone.utc).isoformat()}),
             "instance": instance, "mode": "paper" if apply else "dry-run", "safe_to_unlock": safe,
             "action": "clear lock only; no order will be submitted" if safe else "keep lock",
             "snapshot": snapshot}
    path = RUNTIME / instance / "reconciliation.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit, sort_keys=True, default=str) + "\n")
    return audit


def unlock(instance: str, audit_id: str) -> dict:
    audit_path = RUNTIME / instance / "reconciliation.jsonl"
    rows = []
    try:
        rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, ValueError):
        pass
    record = next((row for row in reversed(rows) if row.get("audit_id") == audit_id), None)
    if not record or not record.get("safe_to_unlock") or record.get("mode") != "paper":
        raise RuntimeError("blind unlock rejected: a successful --paper reconciliation is required")
    from core.database import BotState, get_session, init_db
    init_db()
    with get_session() as session:
        row = session.query(BotState).filter_by(strategy_name=_state_name(instance), symbol="BTC-USDT").first()
        if row is None:
            raise RuntimeError("strategy state not found")
        row.set_config({"version": 1, "state": "STABLE_RISK_ON", "phase": None,
                        "last_block": None, "order_id": None, "error": None})
    return {"unlocked": True, "instance": instance, "audit_id": audit_id, "orders_submitted": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "diagnose", "reconcile", "unlock"))
    parser.add_argument("--instance", required=True)
    parser.add_argument("--paper", action="store_true")
    parser.add_argument("--after-reconciliation")
    args = parser.parse_args()
    if args.command in {"status", "diagnose"}:
        result = inspect(args.instance)
    elif args.command == "reconcile":
        result = reconcile(args.instance, apply=args.paper)
    else:
        result = unlock(args.instance, str(args.after_reconciliation or ""))
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
