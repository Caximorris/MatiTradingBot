"""V8-only Telegram authorization, confirmation, audit, and command routing."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping, Protocol

from .adapter import SafetyError

READ_ONLY = {
    "help", "status", "health", "version", "mode", "phase", "schedule",
    "next_transition", "position", "orders", "intents", "funding", "margin",
    "expiry", "canary", "kill_switches", "reconciliation",
}
MUTATIONS = {
    "pause", "resume", "flat", "emergency_flatten", "reconcile", "manual_stop",
    "set_mode", "set_synthetic_anchor",
}
STRONG = {"flat", "emergency_flatten", "manual_stop", "set_mode", "set_synthetic_anchor"}
MAX_MESSAGE = 4096


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    token: str = field(default="", repr=False)
    allowed_chat_ids: frozenset[int] = frozenset()
    confirmation_seconds: int = 120
    rate_limit_per_minute: int = 20

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> "TelegramConfig":
        values = source if source is not None else os.environ
        raw_ids = values.get("V8_TELEGRAM_ALLOWED_CHAT_IDS", "")
        try:
            ids = frozenset(
                int(item.strip()) for item in raw_ids.split(",") if item.strip()
            )
            expiry = int(values.get("V8_TELEGRAM_CONFIRMATION_SECONDS", "120"))
        except ValueError as exc:
            raise SafetyError("invalid V8 Telegram allowlist or confirmation expiry") from exc
        config = cls(
            enabled=values.get("V8_TELEGRAM_ENABLED", "").lower() == "true",
            token=values.get("V8_TELEGRAM_BOT_TOKEN", "").strip(),
            allowed_chat_ids=ids,
            confirmation_seconds=expiry,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.enabled and (not self.token or not self.allowed_chat_ids):
            raise SafetyError("enabled V8 Telegram requires dedicated token and chat allowlist")
        if self.confirmation_seconds < 30 or self.confirmation_seconds > 600:
            raise SafetyError("V8 Telegram confirmation expiry must be 30-600 seconds")


@dataclass(frozen=True)
class PendingConfirmation:
    nonce_hash: str
    chat_id: int
    action: str
    arguments: tuple[str, ...]
    description: str
    expires_at: str
    strong: bool


class AuditLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, *, chat_id: int, command: str, outcome: str) -> None:
        previous = ""
        if self.path.exists():
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if lines:
                previous = str(json.loads(lines[-1]).get("record_hash", ""))
        record = {
            "accepted_at": datetime.now(UTC).isoformat(),
            "chat_hash": hashlib.sha256(str(chat_id).encode()).hexdigest()[:16],
            "command": command[:128],
            "outcome": outcome[:128],
            "previous_hash": previous,
        }
        record["record_hash"] = hashlib.sha256(
            json.dumps(record, sort_keys=True).encode()
        ).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class ConfirmationStore:
    def __init__(self, path: Path, expiry_seconds: int) -> None:
        self.path = path
        self.expiry_seconds = expiry_seconds

    def _load(self) -> list[PendingConfirmation]:
        if not self.path.exists():
            return []
        try:
            return [
                PendingConfirmation(**row)
                for row in json.loads(self.path.read_text(encoding="utf-8"))
            ]
        except Exception as exc:
            raise SafetyError("corrupt V8 Telegram confirmation state") from exc

    def create(
        self, chat_id: int, action: str, arguments: tuple[str, ...], description: str
    ) -> str:
        nonce = secrets.token_urlsafe(7)
        expiry = datetime.now(UTC) + timedelta(seconds=self.expiry_seconds)
        pending = PendingConfirmation(
            hashlib.sha256(nonce.encode()).hexdigest(),
            chat_id,
            action,
            arguments,
            description,
            expiry.isoformat(),
            action in STRONG,
        )
        live = [
            row for row in self._load()
            if datetime.fromisoformat(row.expires_at) > datetime.now(UTC)
            and row.chat_id != chat_id
        ]
        _atomic_json(self.path, [*(asdict(row) for row in live), asdict(pending)])
        return nonce

    def consume(self, chat_id: int, nonce: str) -> PendingConfirmation:
        digest = hashlib.sha256(nonce.encode()).hexdigest()
        rows = self._load()
        match = next(
            (
                row for row in rows
                if row.chat_id == chat_id and secrets.compare_digest(row.nonce_hash, digest)
            ),
            None,
        )
        if match is None:
            raise SafetyError("unknown or already-consumed confirmation nonce")
        remaining = [row for row in rows if row != match]
        _atomic_json(self.path, [asdict(row) for row in remaining])
        if datetime.fromisoformat(match.expires_at) <= datetime.now(UTC):
            raise SafetyError("confirmation nonce expired")
        return match


class UpdateGate:
    def __init__(self, path: Path, rate_limit: int) -> None:
        self.path = path
        self.rate_limit = rate_limit
        self.recent: dict[int, deque[float]] = defaultdict(deque)

    def accept(self, update_id: int, chat_id: int) -> bool:
        previous = -1
        if self.path.exists():
            try:
                previous = int(json.loads(self.path.read_text())["last_update_id"])
            except Exception as exc:
                raise SafetyError("corrupt V8 Telegram update state") from exc
        if update_id <= previous:
            return False
        now = time.monotonic()
        recent = self.recent[chat_id]
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= self.rate_limit:
            raise SafetyError("V8 Telegram rate limit exceeded")
        recent.append(now)
        _atomic_json(self.path, {"last_update_id": update_id})
        return True


class Gateway(Protocol):
    def snapshot(self) -> dict[str, object]: ...
    def mutate(self, action: str, arguments: tuple[str, ...]) -> str: ...


class V8TelegramRouter:
    def __init__(
        self,
        *,
        config: TelegramConfig,
        gateway: Gateway,
        runtime_root: Path,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.audit = AuditLedger(runtime_root / "telegram" / "audit.jsonl")
        self.confirmations = ConfirmationStore(
            runtime_root / "telegram" / "confirmations.json",
            config.confirmation_seconds,
        )
        self.updates = UpdateGate(
            runtime_root / "telegram" / "updates.json",
            config.rate_limit_per_minute,
        )

    def handle(self, *, update_id: int, chat_id: int, text: str) -> str | None:
        if chat_id not in self.config.allowed_chat_ids:
            return None
        if not self.updates.accept(update_id, chat_id):
            return None
        if len(text) > MAX_MESSAGE:
            raise SafetyError("V8 Telegram message exceeds size limit")
        parts = text.strip().split()
        if not parts or not parts[0].startswith("/"):
            return self._reply("Only documented V8 commands are accepted.")
        command = parts[0][1:].split("@", 1)[0].lower()
        arguments = tuple(parts[1:])
        try:
            if command == "confirm":
                if len(arguments) != 1:
                    raise SafetyError("/confirm requires exactly one nonce")
                pending = self.confirmations.consume(chat_id, arguments[0])
                result = self.gateway.mutate(
                    pending.action, tuple(pending.arguments)
                )
                self.audit.append(
                    chat_id=chat_id,
                    command=f"confirm:{pending.action}",
                    outcome="accepted",
                )
                return self._reply(f"CONFIRMED: {result}")
            if command in READ_ONLY:
                snapshot = self.gateway.snapshot()
                result = self._format_read(command, snapshot)
                self.audit.append(chat_id=chat_id, command=command, outcome="read")
                return self._reply(result)
            if command in MUTATIONS:
                self._validate_arguments(command, arguments)
                snapshot = self.gateway.snapshot()
                if not self._mutations_ready(command, snapshot):
                    raise SafetyError("executor is unhealthy; Telegram is read-only")
                description = self._describe(command, arguments)
                nonce = self.confirmations.create(
                    chat_id, command, arguments, description
                )
                self.audit.append(
                    chat_id=chat_id, command=command, outcome="confirmation-issued"
                )
                strength = "STRONG " if command in STRONG else ""
                return self._reply(
                    f"{strength}CONFIRMATION REQUIRED: {description}\n"
                    f"/confirm {nonce}\nExpires in {self.config.confirmation_seconds}s."
                )
            self.audit.append(chat_id=chat_id, command=command, outcome="rejected")
            return self._reply("REJECTED: command is not part of the V8-only interface.")
        except SafetyError as exc:
            self.audit.append(chat_id=chat_id, command=command, outcome="blocked")
            return self._reply(f"BLOCKED: {str(exc)[:300]}")

    @staticmethod
    def _validate_arguments(command: str, arguments: tuple[str, ...]) -> None:
        expected = 1 if command in {"set_mode", "set_synthetic_anchor"} else 0
        if len(arguments) != expected:
            raise SafetyError(f"/{command} expects {expected} argument(s)")
        if command == "set_mode" and arguments[0] not in {
            "real_cycle", "synthetic_demo_cycle",
        }:
            raise SafetyError("invalid V8 schedule mode")

    @staticmethod
    def _mutations_ready(command: str, snapshot: dict[str, object]) -> bool:
        if command in {"set_mode", "set_synthetic_anchor"}:
            return bool(snapshot.get("service_stopped")) and bool(
                snapshot.get("reconciled")
            )
        return (
            snapshot.get("status") not in {"BLOCKED", "UNKNOWN", "NO_HEALTH_RECORD"}
            and bool(snapshot.get("reconciled"))
        )

    @staticmethod
    def _describe(command: str, arguments: tuple[str, ...]) -> str:
        suffix = f" {' '.join(arguments)}" if arguments else ""
        descriptions = {
            "pause": "pause new V8 exposure",
            "resume": "resume V8 after preflight/reconciliation gates",
            "flat": "persist the normal V8 flat target",
            "emergency_flatten": "invoke V8 emergency flatten and require manual recovery",
            "reconcile": "request full V8 reconciliation",
            "manual_stop": "stop new V8 execution and require manual recovery",
            "set_mode": "archive and switch V8 schedule mode",
            "set_synthetic_anchor": "set the future UTC synthetic anchor",
        }
        return descriptions[command] + suffix

    @staticmethod
    def _format_read(command: str, value: dict[str, object]) -> str:
        if command == "help":
            return (
                "V8 X-Perp only. Read: /status /health /version /mode /phase "
                "/schedule /next_transition /position /orders /intents /funding "
                "/margin /expiry /canary /kill_switches /reconciliation. "
                "Confirmed controls: /pause /resume /flat /emergency_flatten "
                "/reconcile /manual_stop /set_mode /set_synthetic_anchor."
            )
        if command in {"status", "health"}:
            keys = (
                "environment", "schedule_mode", "status", "service_state",
                "reconciled", "instrument", "current_target", "position_contracts",
                "position_notional_usd", "canary_cap_usd", "actual_leverage",
                "liquidation_distance_pct", "rest_fresh", "websocket_fresh",
                "funding_status", "next_transition", "kill_switches",
            )
        else:
            groups = {
                "version": ("version", "environment"),
                "mode": ("environment", "schedule_mode", "service_state"),
                "phase": ("schedule_mode", "phase", "current_target"),
                "schedule": ("schedule_mode", "synthetic_anchor", "cycle_number", "phase", "next_day_2", "next_day_3", "next_halving", "transition_due"),
                "next_transition": ("schedule_mode", "next_transition", "transition_due"),
                "position": ("instrument", "position_contracts", "position_notional_usd", "actual_leverage"),
                "orders": ("open_orders",),
                "intents": ("non_terminal_intents",),
                "funding": ("funding_status",),
                "margin": ("margin_tier_count", "actual_leverage", "liquidation_distance_pct"),
                "expiry": ("expiry",),
                "canary": ("canary_cap_usd", "current_target", "actual_capped_target"),
                "kill_switches": ("kill_switches",),
                "reconciliation": ("reconciled", "rest_fresh", "websocket_fresh", "service_state"),
            }
            keys = groups[command]
        return "\n".join(f"{key}: {value.get(key, 'unknown')}" for key in keys)

    @staticmethod
    def _reply(value: str) -> str:
        return value[:MAX_MESSAGE]


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
