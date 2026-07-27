"""Append-only single-owner lease for the shared OKX Demo account."""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DemoLeaseError(RuntimeError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def account_fingerprint(*, domain: str, key_id: str) -> str:
    """Fingerprint non-secret account identity; callers must never pass a secret."""
    return _hash({"exchange": "OKX", "environment": "demo", "domain": domain, "key_id": key_id})


class DemoAccountLease:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        except (OSError, ValueError) as exc:
            raise DemoLeaseError("corrupt demo-account lease journal") from exc
        prior_hash: str | None = None
        for row in rows:
            supplied = row.pop("record_hash", None)
            if not isinstance(supplied, str) or supplied != _hash(row):
                raise DemoLeaseError("tampered demo-account lease journal")
            if row.get("previous_record_hash") != prior_hash:
                raise DemoLeaseError("broken demo-account lease journal chain")
            row["record_hash"] = supplied
            prior_hash = supplied
        return rows

    def current(self) -> dict[str, Any] | None:
        rows = self.records()
        return rows[-1] if rows and rows[-1].get("status") == "acquired" else None

    def acquire(self, *, fingerprint: str, owner_strategy_id: str, owner_instance_id: str,
                source_commit: str, configuration_hash: str, now: datetime | None = None) -> dict[str, Any]:
        with self._exclusive():
            current = self.current()
            if current is not None:
                if current.get("owner_strategy_id") == owner_strategy_id and current.get("owner_instance_id") == owner_instance_id:
                    return current
                raise DemoLeaseError("OKX Demo account already has an active owner")
            record = {"exchange": "OKX", "environment": "demo", "account_fingerprint": fingerprint,
                      "owner_strategy_id": owner_strategy_id, "owner_instance_id": owner_instance_id,
                      "source_commit": source_commit, "configuration_hash": configuration_hash,
                      "acquired_timestamp": (now or datetime.now(timezone.utc)).isoformat(), "released_timestamp": None,
                      "status": "acquired"}
            return self._append(record)

    def release(self, *, fingerprint: str, owner_strategy_id: str, owner_instance_id: str,
                now: datetime | None = None) -> dict[str, Any]:
        with self._exclusive():
            current = self.current()
            if current is None or current.get("account_fingerprint") != fingerprint or current.get("owner_strategy_id") != owner_strategy_id or current.get("owner_instance_id") != owner_instance_id:
                raise DemoLeaseError("only the current demo-account owner may release its lease")
            record = {key: value for key, value in current.items() if key != "record_hash"}
            record.update(status="released", released_timestamp=(now or datetime.now(timezone.utc)).isoformat())
            return self._append(record)

    def _append(self, record: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.records()
        record = dict(record, previous_record_hash=rows[-1]["record_hash"] if rows else None)
        record = dict(record, record_hash=_hash(record))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    @contextmanager
    def _exclusive(self):
        """Cross-process lock; a stale lock fails closed instead of stealing ownership."""
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise DemoLeaseError("demo-account lease is busy or stale; operator review required") from exc
        try:
            os.write(descriptor, str(time.time()).encode())
            yield
        finally:
            os.close(descriptor)
            try:
                lock.unlink()
            except OSError:
                pass
