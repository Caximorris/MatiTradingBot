"""Keep persistent Codex instructions small enough to be useful on every task."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".codex" / "instruction-budget.json"


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def violations(root: Path = ROOT, config_path: Path = CONFIG) -> list[str]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for relative, limit in config["files"].items():
        count = line_count(root / relative)
        if count > limit:
            failures.append(f"{relative}: {count} lines exceeds {limit}")

    skills = sorted((root / ".codex" / "skills").glob("*/SKILL.md"))
    counts = {path.relative_to(root).as_posix(): line_count(path) for path in skills}
    for relative, count in counts.items():
        if count > config["skill_max_lines"]:
            failures.append(
                f"{relative}: {count} lines exceeds per-skill limit {config['skill_max_lines']}"
            )
    total = sum(counts.values())
    if total > config["skill_total_lines"]:
        failures.append(
            f"versioned skills: {total} lines exceeds total limit {config['skill_total_lines']}"
        )
    return failures


def main() -> int:
    failures = violations()
    if failures:
        print("Instruction budget exceeded:", file=sys.stderr)
        print("\n".join(f"  {failure}" for failure in failures), file=sys.stderr)
        return 1
    print("Instruction budget: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
