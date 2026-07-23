#!/usr/bin/env python
# ruff: noqa: E402
"""Persist a read-only daily v6-versus-v7 operational comparison."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_operations import RUNTIME, atomic_json, canonical_hash


def _journal_tail(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    except (OSError, IndexError, ValueError):
        return {}


def build() -> dict:
    from core.database import BotState, get_session, init_db
    init_db()
    with get_session() as session:
        rows = {row.strategy_name: row for row in session.query(BotState).all()}
    v6 = next((row for name, row in rows.items() if name.startswith("swing_allocator_v6_")), None)
    v7 = {name: row for name, row in rows.items() if name.startswith("swing_cycle_core_v7_")}
    v7_view = {}
    for name, row in v7.items():
        cfg = row.get_config()
        instance = cfg.get("instance_id", "unknown")
        event = _journal_tail(Path(cfg.get("transition_journal_path", "")))
        v7_view[name] = {"active": row.is_active, "last_run": str(row.last_run),
                         "mode": cfg.get("operational_mode"), "target": event.get("new_target"),
                         "phase": event.get("new_phase"), "state": event.get("status"),
                         "journal": cfg.get("transition_journal_path"), "instance_id": instance}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "v6": None if v6 is None else {"active": v6.is_active, "last_run": str(v6.last_run),
                                               "config_hash": canonical_hash(v6.get_config())},
              "v7": v7_view,
              "divergence_explanation": "Expected policy divergence: v6 uses its frozen regime/funding allocator; v7 uses the frozen 540/900 cycle clock. Any execution-state mismatch is not expected.",
              "alerts": []}
    report["report_hash"] = canonical_hash(report)
    path = RUNTIME / "reports" / f"v6_v7_{datetime.now(timezone.utc).date().isoformat()}.json"
    atomic_json(path, report)
    report["path"] = str(path)
    return report


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
