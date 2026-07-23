"""Emit a small, deterministic file/test/command pack for a common engineering task."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKS = {
    "strategy": {
        "files": [
            "AGENTS.md", "SESSION.md", "strategies/base_strategy.py", "strategies/registry.py",
            "strategies/indicators.py", "core/backtest.py", "cli/runner.py",
            "docs/forward-test/candidate-paper-workflow.md",
        ],
        "tests": ["tests/test_registry.py", "tests/test_client_contract.py"],
        "commands": [
            "python -m pytest -q <strategy tests> tests/test_registry.py tests/test_client_contract.py",
            "python main.py backtest --strategy <name> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --costs realistic",
            "python main.py backtest --strategy <name> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --costs conservative",
        ],
        "constraints": [
            "Use an isolated BaseStrategy/config/StrategyMeta; do not change frozen defaults.",
            "Use closed bars, deterministic cache, Decimal money, and the common client contract.",
            "Paper readiness requires lookahead plus proportionate overfitting falsification; it is not default/live approval.",
        ],
    },
    "backtest": {
        "files": [
            "AGENTS.md", "SESSION.md", "core/backtest.py", "cli/runner.py",
            "data/ohlcv_cache.py", "reporting/experiment_manifest.py",
        ],
        "tests": [
            "tests/test_backtest_execution.py", "tests/test_backtest_pnl.py",
            "tests/test_runner_manifest.py", "tests/test_client_contract.py",
        ],
        "commands": [
            "python main.py backtest --strategy <name> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --costs realistic",
            "python -m pytest -q tests/test_backtest_execution.py tests/test_backtest_pnl.py tests/test_runner_manifest.py",
        ],
        "constraints": [
            "Pair runs on identical cache, window, warmup, config, and costs.",
            "Do not mutate canonical cache, journals, manifests, or runtime state.",
        ],
    },
    "paper": {
        "files": [
            "AGENTS.md", "SESSION.md", "docs/forward-test/candidate-paper-workflow.md",
            "tools/v7_paper_setup.py", "tools/v7_promotion_controller.py", "cli/live_cmds.py",
        ],
        "tests": [
            "tests/test_v7_operations.py", "tests/test_paper_bots.py", "tests/test_client_contract.py",
        ],
        "commands": [
            "python -m pytest -q tests/test_v7_operations.py tests/test_paper_bots.py tests/test_client_contract.py",
            "python main.py status",
        ],
        "constraints": [
            "Candidate setup/activation, VM pull, and service actions are explicit operational actions.",
            "Use a unique instance, wallet, portfolio, and journal; never add candidates to paper_fleet_setup.py.",
        ],
    },
}


def build_pack(name: str) -> dict[str, object]:
    pack = PACKS[name]
    return {"task": name, "root": str(ROOT), **pack}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=sorted(PACKS))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    pack = build_pack(args.task)
    if args.json:
        print(json.dumps(pack, indent=2))
        return 0
    for key in ("files", "tests", "commands", "constraints"):
        print(f"{key}:")
        print("\n".join(f"- {value}" for value in pack[key]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
