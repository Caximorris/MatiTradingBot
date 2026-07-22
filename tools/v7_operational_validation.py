#!/usr/bin/env python
# ruff: noqa: E402
"""Run the frozen v7 operational test battery and persist only observed gate flags."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.v7_operations import RUNTIME, PromotionState, canonical_hash

STATE_PATH = RUNTIME / "promotion_state.json"
TESTS = (
    "tests/test_swing_cycle_core.py",
    "tests/test_v7_operations.py",
)


def main() -> int:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, check=False)
    state = PromotionState.load(STATE_PATH)
    passed = completed.returncode == 0
    state.checks["replay_suite_passed"] = passed
    state.checks["adapter_parity_passed"] = passed
    state.checks["fault_injection_passed"] = passed
    before = RUNTIME / "deployment_before.json"
    after = RUNTIME / "deployment_after.json"
    try:
        left, right = json.loads(before.read_text()), json.loads(after.read_text())
        state.checks["dataset_identity_unchanged"] = (
            left.get("dataset_sha256") is not None
            and left.get("dataset_sha256") == right.get("dataset_sha256")
            and left.get("v6_strategy_sha256") == right.get("v6_strategy_sha256")
            and left.get("v6") == right.get("v6")
        )
    except (OSError, ValueError):
        state.checks["dataset_identity_unchanged"] = False
    from config.settings import load_settings
    settings = load_settings()
    state.checks["paper_account_verified"] = bool(settings.is_paper)
    state.configuration_hash = canonical_hash({"tests": TESTS, "checks": state.checks})
    state.save(STATE_PATH)
    print(json.dumps({"passed": passed, "checks": state.checks}, sort_keys=True))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
