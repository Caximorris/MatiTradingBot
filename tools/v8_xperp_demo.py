#!/usr/bin/env python
"""V8-only OKX EEA X-Perp operations; continuous mode is disabled by default."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.v8_xperp import SafetyError, V8XPerpDemoAdapter  # noqa: E402
from execution.v8_xperp.intents import IntentLedger, TERMINAL  # noqa: E402
from execution.v8_xperp.recovery import (  # noqa: E402
    IntentExecution,
    archive_reconciled,
    sanitized_status,
)


def _json(value: object) -> None:
    def convert(item: object) -> object:
        return asdict(item) if hasattr(item, "__dataclass_fields__") else str(item)
    print(json.dumps(asdict(value) if hasattr(value, "__dataclass_fields__") else value, default=convert, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="read-only authenticated gate")
    sub.add_parser("reconcile", help="read-only preflight plus reconciliation snapshot")
    sub.add_parser("status", help="read-only account and market status")
    sub.add_parser("validate-journal", help="validate the atomic intent journal")
    sub.add_parser("list-intents", help="list non-terminal persisted intents")
    sub.add_parser("startup-recovery", help="lock and run read-only startup recovery")
    recover = sub.add_parser("recover-intent", help="read-only recovery of one client-order ID")
    recover.add_argument("client_order_id")
    sub.add_parser("recovery-status", help="sanitized local recovery-status report")
    archive = sub.add_parser("archive-intents", help="archive reconciled terminal intents")
    archive.add_argument("--destination", type=Path)
    sub.add_parser("final-reconcile", help="lock and reconcile final V8 account state")
    target = sub.add_parser("targets", help="calculate but do not place V8 targets")
    target.add_argument("--target", choices=["flat", "long 1x", "long 2x", "short 2x"], action="append")
    sub.add_parser("smoke", help="minimum-size long/flat then short/flat Demo test")
    flatten = sub.add_parser("flatten", help="reserved emergency command; never auto-runs")
    flatten.add_argument("--confirm-v8-emergency-flatten", action="store_true")
    run = sub.add_parser("run", help="continuous Demo operation")
    run.add_argument("--enable-continuous-demo", action="store_true")
    args = parser.parse_args()
    if args.command == "run":
        raise SafetyError("continuous V8 Demo operation remains disabled in this milestone")
    adapter = V8XPerpDemoAdapter()
    ledger = IntentLedger(adapter.intent_path)
    if args.command in {"validate-journal", "list-intents", "recovery-status", "archive-intents"}:
        if args.command == "archive-intents":
            destination = args.destination or adapter.runtime_root / "archive" / "reconciled-intents.json"
            _json({"archived": archive_reconciled(ledger, destination), "destination": str(destination)})
        elif args.command == "recovery-status":
            _json(sanitized_status(adapter.intent_path, ledger))
        else:
            rows = ledger.load()
            _json(
                {"integrity": "pass", "intent_count": len(rows)}
                if args.command == "validate-journal"
                else [row for row in rows if row.state not in TERMINAL]
            )
        return 0
    if args.command in {"startup-recovery", "final-reconcile"}:
        with adapter.locked():
            _json(adapter.startup_recovery(adapter._discover()))
        return 0
    if args.command == "recover-intent":
        intent = next((row for row in ledger.load() if row.client_order_id == args.client_order_id), None)
        if intent is None:
            raise SafetyError("unknown V8 intent")
        with adapter.locked():
            result = IntentExecution(adapter=adapter, ledger=ledger).reconcile(
                intent, before_position=Decimal("0"), permit_absent=False
            )
            _json(result)
        return 0
    if args.command == "flatten":
        if not args.confirm_v8_emergency_flatten:
            raise SafetyError("emergency flatten requires the explicit confirmation flag")
        with adapter.locked():
            instrument = adapter._discover()
            adapter.startup_recovery(instrument)
            report = type("RecoveryReport", (), {"instrument": instrument})()
            _json(adapter.emergency_flatten(report, lock_already_held=True))
        return 0
    if args.command == "smoke":
        _json(adapter.smoke())
        return 0
    report = adapter.preflight()
    if args.command == "targets":
        _json([adapter.calculate_target(report, value) for value in (args.target or ["flat", "long 1x", "long 2x", "short 2x"])])
    else:
        _json(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyError as exc:
        print(f"BLOCKED: {exc}")
        raise SystemExit(2)
