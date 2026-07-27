"""Read-only V6-2 certification boundary.

This is intentionally a *blocker adapter*, not a replacement implementation:
the frozen defaults require the protected historical funding snapshot, which is
not available in this worktree.  It accepts only immutable certified snapshots
and refuses to manufacture a target intent from different inputs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from core.certification import StrategySnapshot, TargetIntent


class FrozenV6EvidenceUnavailable(RuntimeError):
    pass


FROZEN_V6_SOURCE = "strategies/swing_allocator.py"
FROZEN_V6_GIT_BLOB_SHA1 = "e08b455ac914788d80c58e1ec18543d1b512e8f2"


def assert_frozen_v6_source(root: Path | None = None) -> str:
    path = (root or Path(__file__).resolve().parents[1]) / FROZEN_V6_SOURCE
    if not path.exists():
        raise FrozenV6EvidenceUnavailable("frozen V6 source is missing")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FrozenV6CausalResearchAdapter:
    """Snapshot-only V6 boundary unavailable without the protected input."""

    decision_interval_bars = 1
    history_limit = 0

    def should_evaluate(self, snapshot: StrategySnapshot) -> bool:
        return snapshot.decision_at.hour % 4 == 0

    def decide(self, snapshot: StrategySnapshot) -> TargetIntent | None:
        raise FrozenV6EvidenceUnavailable(
            "frozen V6-2 target intent unavailable: protected funding snapshot is absent; "
            "the current-input, funding-disabled fallback is not V6-2 parity"
        )
