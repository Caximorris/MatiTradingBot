"""Atomic append-only V8 order-intent ledger."""

from __future__ import annotations
import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from .adapter import SafetyError

SCHEMA = 1
TERMINAL = {"FILLED", "CANCELED", "REJECTED", "RECONCILED"}
STATES = TERMINAL | {
    "CREATED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "OPEN",
    "PARTIALLY_FILLED",
    "CANCEL_PENDING",
    "UNKNOWN",
}


@dataclass(frozen=True)
class Intent:
    transition_id: str
    client_order_id: str
    instrument_id: str
    target: str
    action: str
    side: str
    contracts: str
    reduce_only: bool
    order_type: str
    price: str | None = None
    metadata_hash: str = ""
    state: str = "CREATED"
    created_at: str = ""
    updated_at: str = ""
    exchange_order_id: str | None = None
    filled_contracts: str = "0"
    last_result: str | None = None
    reconciled_at: str | None = None
    schema: int = SCHEMA


class IntentLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[Intent]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SafetyError("corrupt V8 intent journal") from exc
        try:
            allowed = {field.name for field in fields(Intent)}
            if any(not isinstance(row, dict) or set(row) - allowed for row in rows):
                raise TypeError("unknown intent fields")
            intents = [Intent(**row) for row in rows]
        except Exception as exc:
            raise SafetyError("unsupported V8 intent journal schema") from exc
        if any(i.schema != SCHEMA or i.state not in STATES for i in intents):
            raise SafetyError("unsupported V8 intent journal schema/state")
        active = [i.transition_id for i in intents if i.state not in TERMINAL]
        if len(active) != len(set(active)):
            raise SafetyError("duplicate non-terminal V8 transition")
        return intents

    def create(self, intent: Intent) -> Intent:
        intent = replace(
            intent,
            created_at=intent.created_at or datetime.now(UTC).isoformat(),
            updated_at=intent.updated_at or datetime.now(UTC).isoformat(),
        )
        rows = self.load()
        if intent.state != "CREATED" or any(
            i.client_order_id == intent.client_order_id for i in rows
        ):
            raise SafetyError("invalid or duplicate V8 intent")
        if any(
            i.transition_id == intent.transition_id and i.state not in TERMINAL
            for i in rows
        ):
            raise SafetyError("non-terminal V8 transition exists")
        self._write([*rows, intent])
        return intent

    def transition(self, client_order_id: str, state: str, **changes: object) -> Intent:
        if state not in STATES:
            raise SafetyError("invalid V8 intent state")
        mutable = {
            "exchange_order_id",
            "filled_contracts",
            "last_result",
        }
        if set(changes) - mutable:
            raise SafetyError("invalid V8 intent transition fields")
        rows = self.load()
        found = None
        out = []
        for item in rows:
            if item.client_order_id == client_order_id:
                found = replace(
                    item,
                    state=state,
                    updated_at=datetime.now(UTC).isoformat(),
                    reconciled_at=datetime.now(UTC).isoformat()
                    if state == "RECONCILED"
                    else item.reconciled_at,
                    **changes,
                )
                out.append(found)
            else:
                out.append(item)
        if found is None:
            raise SafetyError("unknown V8 intent")
        self._write(out)
        return found

    def _write(self, rows: list[Intent]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([asdict(i) for i in rows], f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
