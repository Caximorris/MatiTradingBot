"""Executor-authoritative local request state for the V8 Telegram companion."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .adapter import SafetyError


@dataclass(frozen=True)
class OperatorControlState:
    paused: bool = False
    manual_stop: bool = False
    updated_at: str | None = None
    last_action: str | None = None


class OperatorControlStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "operator_control.json"

    def load(self) -> OperatorControlState:
        if not self.path.exists():
            return OperatorControlState()
        try:
            return OperatorControlState(
                **json.loads(self.path.read_text(encoding="utf-8"))
            )
        except Exception as exc:
            raise SafetyError("corrupt V8 operator control state") from exc

    def update(self, action: str) -> OperatorControlState:
        current = self.load()
        if action == "pause":
            updated = replace(current, paused=True)
        elif action == "resume":
            if current.manual_stop:
                raise SafetyError("manual stop requires manual recovery outside Telegram")
            updated = replace(current, paused=False)
        elif action == "manual_stop":
            updated = replace(current, paused=True, manual_stop=True)
        elif action == "manual_recovery":
            updated = replace(current, paused=True, manual_stop=False)
        else:
            raise SafetyError("unsupported V8 operator control action")
        updated = replace(
            updated,
            updated_at=datetime.now(UTC).isoformat(),
            last_action=action,
        )
        _atomic_json(self.path, asdict(updated))
        return updated

    def request(self, action: str) -> Path:
        if action not in {"flat", "emergency_flatten", "reconcile"}:
            raise SafetyError("unsupported V8 executor request")
        filename = "operator_flat.request" if action == "flat" else f"{action}.request"
        path = self.root / filename
        _atomic_json(
            path,
            {"action": action, "requested_at": datetime.now(UTC).isoformat()},
        )
        return path


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
