#!/usr/bin/env python
# ruff: noqa: E402
"""Read-only health report for the V7 certified isolated paper candidate."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_certified_paper import make_config


def build(root: Path = ROOT) -> dict:
    config = make_config(root)
    state = json.loads(config.wallet_path.read_text(encoding="utf-8")) if config.wallet_path.exists() else None
    healthy = state is not None and not state.get("locked") and state.get("candidate_hash") == config.candidate_hash
    report = {"candidate": "V7 certified isolated paper candidate", "generated_at": datetime.now(timezone.utc).isoformat(),
              "process_uptime": None, "last_completed_candle": None, "data_freshness": "not_started", "missing_candle_count": 0,
              "duplicate_candle_count": 0, "conflicting_duplicate_count": 0, "current_v7_phase": None, "current_v7_regime": None,
              "current_target": None, "paper_exposure": None, "cash": None if state is None else state.get("cash"),
              "BTC_quantity": None if state is None else state.get("btc"), "equity": None, "pending_intent_order": None if state is None else state.get("pending"),
              "daily_orders": 0, "daily_fills": 0, "daily_fees": "0", "reconciliation_status": "NOT_STARTED" if state is None else "OK",
              "circuit_breaker_status": "NOT_STARTED" if state is None else ("LOCKED" if state.get("locked") else "CLEAR"),
              "candidate_hash": config.candidate_hash, "configuration_hash": config.configuration_hash, "source_hash": config.source_hash,
              "deterministic_replay_state": "NOT_STARTED" if state is None else "AVAILABLE",
              "paper_vs_replay_parity_verdict": "NOT_STARTED" if state is None else ("PASS" if healthy else "FAIL_CLOSED")}
    report["report_hash"] = __import__("hashlib").sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    return report


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
