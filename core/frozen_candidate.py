"""Immutable V7 candidate contract used by every certification experiment."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class FrozenCandidateError(ValueError):
    """Raised when an experiment attempts to relabel a changed V7 candidate."""


@dataclass(frozen=True)
class FrozenCandidate:
    payload: Mapping[str, Any]
    configuration_hash: str

    @property
    def bear_onset(self) -> int:
        return int(self.payload["phase_days"]["bear_onset_start"])

    @property
    def accumulation(self) -> int:
        return int(self.payload["phase_days"]["accumulation_start"])

    def verify_overrides(self, overrides: Mapping[str, Any] | None = None) -> None:
        values = dict(overrides or {})
        aliases = {"phase_bear_start": self.bear_onset, "phase_accumulation_start": self.accumulation,
                   "bear_onset": self.bear_onset, "accumulation": self.accumulation}
        changed = {key: value for key, value in values.items()
                   if key in aliases and int(value) != aliases[key]}
        if changed:
            raise FrozenCandidateError(f"frozen V7 540/900 override rejected: {changed}")


def load_frozen_candidate(path: Path | None = None) -> FrozenCandidate:
    root = Path(__file__).resolve().parents[1]
    source = path or root / "docs" / "v7_frozen_candidate.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    candidate = FrozenCandidate(payload=payload, configuration_hash=hashlib.sha256(canonical).hexdigest())
    if candidate.bear_onset != 540 or candidate.accumulation != 900:
        raise FrozenCandidateError("frozen candidate must remain 540/900")
    return candidate
