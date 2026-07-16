"""Fail CI on new Ruff debt while keeping every legacy finding visible."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".ruff-baseline.json"


def finding_counts(rows: Iterable[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        filename = Path(row["filename"]).resolve()
        try:
            relative = filename.relative_to(ROOT).as_posix()
        except ValueError as exc:
            raise ValueError(f"Ruff finding is outside repository: {filename}") from exc
        counts[f"{relative}|{row['code']}"] += 1
    return counts


def regressions(current: Counter[str], baseline: dict[str, int]) -> dict[str, tuple[int, int]]:
    return {
        fingerprint: (count, int(baseline.get(fingerprint, 0)))
        for fingerprint, count in sorted(current.items())
        if count > int(baseline.get(fingerprint, 0))
    }


def main() -> int:
    baseline_doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline = baseline_doc["fingerprints"]
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format=json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode not in {0, 1}:
        print(completed.stderr, file=sys.stderr)
        print(f"Ruff execution failed with exit code {completed.returncode}", file=sys.stderr)
        return 2

    rows = json.loads(completed.stdout or "[]")
    current = finding_counts(rows)
    failures = regressions(current, baseline)
    print(
        f"Ruff debt: {len(rows)} remaining; checked-in baseline "
        f"{baseline_doc['total']}; reduction {baseline_doc['total'] - len(rows):+d}."
    )
    for row in rows:
        filename = Path(row["filename"]).resolve().relative_to(ROOT).as_posix()
        location = row.get("location", {})
        print(
            f"{filename}:{location.get('row', '?')}:{location.get('column', '?')} "
            f"{row['code']} {row['message']}"
        )

    if failures:
        print("New or increased Ruff fingerprints:", file=sys.stderr)
        for fingerprint, (count, allowed) in failures.items():
            print(f"  {fingerprint}: current={count}, allowed={allowed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
