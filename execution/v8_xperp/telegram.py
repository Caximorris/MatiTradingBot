"""V8-only Telegram authorization, confirmation, audit, and command routing."""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Protocol

from .adapter import SafetyError

READ_ONLY = {
    "start", "menu", "help", "status", "report", "health", "safety", "version", "mode", "phase", "schedule",
    "next_transition", "position", "orders", "intents", "funding", "margin",
    "expiry", "canary", "kill_switches", "reconciliation",
}
MUTATIONS = {
    "pause", "resume", "flat", "emergency_flatten", "reconcile", "manual_stop",
    "set_mode", "set_synthetic_anchor",
}
STRONG = {"flat", "emergency_flatten", "manual_stop", "set_mode", "set_synthetic_anchor"}
MAX_MESSAGE = 4096

COMMAND_MENU = (
    ("start", "Open the V8 control room"),
    ("menu", "Show V8 tools"),
    ("status", "Live V8 dashboard"),
    ("position", "Position and exposure"),
    ("schedule", "Cycle schedule"),
    ("safety", "Safety gates and kill switches"),
    ("funding", "Funding reconciliation"),
    ("orders", "Open V8 orders"),
    ("intents", "V8 transition state"),
    ("pause", "Pause new exposure (confirm)"),
    ("resume", "Resume after checks (confirm)"),
    ("flat", "Request controlled flat (confirm)"),
    ("reconcile", "Request full reconciliation (confirm)"),
    ("manual_stop", "Latch manual stop (confirm)"),
    ("help", "All V8 commands and controls"),
)


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


def _text(value: object) -> str:
    return "unknown" if value is None else str(value)


def _decimal(value: object, places: int) -> str:
    try:
        return f"{Decimal(str(value)):,.{places}f}"
    except (InvalidOperation, ValueError):
        return _text(value)


def _instant(value: object) -> str:
    if not isinstance(value, str):
        return _text(value)
    try:
        return datetime.fromisoformat(value).astimezone(UTC).strftime("%d %b %Y · %H:%M UTC")
    except ValueError:
        return value


def _value(key: str, value: object) -> str:
    if key in {"position_notional_usd", "canary_cap_usd"}:
        return f"${_decimal(value, 2)}"
    if key == "position_contracts":
        return _decimal(value, 4)
    if key == "actual_leverage":
        try:
            return f"{Decimal(str(value)) * 100:.2f}%"
        except (InvalidOperation, ValueError):
            return _text(value)
    if key == "liquidation_distance_pct":
        return f"{_decimal(value, 2)}%"
    if key in {"next_transition", "next_day_2", "next_day_3", "next_halving", "synthetic_anchor"}:
        return _instant(value)
    if key == "schedule_mode" and value == "synthetic_demo_cycle":
        return "Synthetic demo cycle"
    if key == "phase" and isinstance(value, str):
        return value.replace("_", " ").title()
    if key == "funding_status" and value == "REAL_PARITY_OBSERVED":
        return "Verified against exchange settlement"
    if key == "expiry" and isinstance(value, dict):
        days = _decimal(value.get("days_remaining"), 1)
        expiry = _instant(value.get("expiry"))
        exposure = "blocked" if value.get("block_new_exposure") else "allowed"
        return f"{days} days left · new exposure {exposure} · {expiry}"
    if key == "kill_switches" and isinstance(value, dict):
        operator = value.get("operator") if isinstance(value.get("operator"), dict) else {}
        manual_stop = bool(value.get("manual_stop")) or bool(operator.get("manual_stop"))
        paused = bool(operator.get("paused"))
        return f"Manual stop: {'ON' if manual_stop else 'off'} · Pause: {'ON' if paused else 'off'}"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return _text(value)


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

    def startup_report(self) -> str:
        return self._dashboard(self.gateway.snapshot())

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
                "<b>🧭 V8 X-Perp Demo · Command guide</b>\n\n"
                "<b>Dashboard</b>\n/start  /menu  /status  /report\n\n"
                "<b>Read-only</b>\n/health  /safety  /position  /schedule  /funding\n"
                "/orders  /intents  /margin  /expiry  /canary  /kill_switches\n"
                "/reconciliation  /phase  /mode  /next_transition  /version\n\n"
                "<b>Confirmed controls</b>\n/pause  /resume  /flat  /reconcile\n"
                "/manual_stop  /emergency_flatten\n\n"
                "Schedule changes are intentionally restricted to a stopped, reconciled service: "
                "/set_mode &lt;mode&gt; and /set_synthetic_anchor &lt;UTC&gt;."
            )
        if command in {"start", "menu", "status", "report"}:
            return V8TelegramRouter._dashboard(value)
        if command in {"health", "safety"}:
            return V8TelegramRouter._safety(value)
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
        return "\n".join(
            f"<b>{html.escape(key.replace('_', ' ').title())}</b>\n"
            f"<code>{html.escape(_value(key, value.get(key)))}</code>"
            for key in keys
        )

    @staticmethod
    def _dashboard(value: dict[str, object]) -> str:
        status = str(value.get("status", "UNKNOWN"))
        service = str(value.get("service_state", "UNKNOWN"))
        status_icon = "🟢" if status == "HEALTHY" else "🟡" if status == "DEGRADED" else "🔴"
        service_icon = "🟢" if service == "RUNNING" else "🟡" if service == "STOPPED" else "🔴"
        reconciliation = "✅ Reconciled" if value.get("reconciled") else "⚠️ Attention needed"
        rest = "✅" if value.get("rest_fresh") else "⚠️"
        websocket = "✅" if value.get("websocket_fresh") else "⚠️"
        lines = [
            "<b>🧭 V8 X-Perp Demo · Control Room</b>",
            f"<i>{html.escape(str(value.get('environment', 'unknown')))} · "
            f"{html.escape(str(value.get('schedule_mode', 'unknown')))}</i>",
            "",
            "<b>Execution</b>",
            f"{status_icon} Status: <b>{html.escape(status)}</b>   "
            f"{service_icon} Service: <b>{html.escape(service)}</b>",
            f"🎯 Target: <b>{html.escape(_text(value.get('current_target')))}</b>",
            f"📍 Position: <code>{html.escape(_value('position_contracts', value.get('position_contracts')))}</code> contracts · "
            f"<b>{html.escape(_value('position_notional_usd', value.get('position_notional_usd')))}</b>",
            f"⚖️ Account use: <b>{html.escape(_value('actual_leverage', value.get('actual_leverage')))}</b> of equity · "
            f"entry cap <b>{html.escape(_value('canary_cap_usd', value.get('canary_cap_usd')))}</b>",
            "",
            "<b>Safety & reconciliation</b>",
            f"{reconciliation} · REST {rest} · WebSocket {websocket}",
            f"🛡 Liquidation buffer: <b>{html.escape(_value('liquidation_distance_pct', value.get('liquidation_distance_pct')))}</b>",
            f"💸 Funding: <b>{html.escape(_value('funding_status', value.get('funding_status')))}</b>",
            "",
            "<b>Schedule</b>",
            f"⏭ Next transition: <code>{html.escape(_value('next_transition', value.get('next_transition')))}</code>",
            f"📄 Instrument: <code>{html.escape(_text(value.get('instrument')))}</code>",
        ]
        reason = value.get("health_reason")
        if status == "BLOCKED" and reason:
            lines.extend((
                "",
                f"⚠️ Block reason: <code>{html.escape(str(reason))}</code>",
                "Controls remain read-only until the executor recovers and reconciles.",
            ))
        lines.extend(("", "Use /menu for controls · /help for every V8 command."))
        return "\n".join(lines)

    @staticmethod
    def _safety(value: dict[str, object]) -> str:
        ok = "✅" if value.get("reconciled") else "⚠️"
        return "\n".join((
            "<b>🛡 V8 Safety Report</b>",
            f"{ok} Account reconciliation: <b>{html.escape(_value('reconciled', value.get('reconciled')))}</b>",
            f"REST market check current: <b>{html.escape(_value('rest_fresh', value.get('rest_fresh')))}</b>",
            f"Private WebSocket current: <b>{html.escape(_value('websocket_fresh', value.get('websocket_fresh')))}</b>",
            f"Open V8 orders: <b>{html.escape(_value('open_orders', value.get('open_orders')))}</b>",
            f"Pending transitions: <b>{html.escape(_value('non_terminal_intents', value.get('non_terminal_intents')))}</b>",
            f"Kill switches: <code>{html.escape(_value('kill_switches', value.get('kill_switches')))}</code>",
        ))

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
