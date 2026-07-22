#!/usr/bin/env python
# ruff: noqa: E402
"""Capture a redacted before/after deployment identity for v6 and v7."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_operations import RUNTIME, atomic_json, canonical_hash


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(label: str) -> dict:
    from core.database import BotState, get_session, init_db
    init_db()
    with get_session() as session:
        bots = []
        for row in session.query(BotState).filter(BotState.strategy_name.like("swing_allocator_v6_%")).all():
            config = row.get_config()
            bots.append({"name": row.strategy_name, "symbol": row.symbol, "active": row.is_active,
                         "config_hash": canonical_hash(config), "last_run": str(row.last_run)})
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    dirty = bool(subprocess.run(["git", "diff", "--quiet"], check=False).returncode)
    result = {"label": label, "captured_at": datetime.now(timezone.utc).isoformat(), "git_commit": commit,
              "dirty_tree": dirty, "v6": bots,
              "dataset_sha256": sha256(Path("data/cache/BTC-USDT_1H.json")),
              "v6_strategy_sha256": sha256(Path("strategies/swing_allocator.py"))}
    result["snapshot_hash"] = canonical_hash(result)
    path = RUNTIME / f"deployment_{label}.json"
    atomic_json(path, result)
    print(json.dumps({"path": str(path), "snapshot_hash": result["snapshot_hash"]}, sort_keys=True))
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=("before", "after"))
    capture(parser.parse_args().label)
