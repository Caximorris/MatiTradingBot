#!/usr/bin/env python
"""Dedicated V8 X-Perp Telegram companion; never routes legacy commands."""

from __future__ import annotations

import json
import os
import sys
import asyncio
import html
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402
from telegram import BotCommand, ReplyKeyboardMarkup, Update  # noqa: E402
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters  # noqa: E402

from execution.v8_xperp.adapter import SafetyError, V8XPerpDemoAdapter  # noqa: E402
from execution.v8_xperp.intents import IntentLedger, TERMINAL  # noqa: E402
from execution.v8_xperp.operator import OperatorControlStore  # noqa: E402
from execution.v8_xperp.doctor import alert_transition, inspect_runtime  # noqa: E402
from execution.v8_xperp.schedule import (  # noqa: E402
    ScheduleConfig,
    ScheduleModeStore,
    parse_utc,
    runtime_namespace,
)
from execution.v8_xperp.service import CanaryStateStore  # noqa: E402
from execution.v8_xperp.telegram import (  # noqa: E402
    COMMAND_MENU,
    TelegramConfig,
    V8TelegramRouter,
)


def base_root() -> Path:
    return Path(os.getenv("V8_XPERP_RUNTIME_ROOT", "data/runtime/v8_xperp_demo"))


def schedule_config() -> ScheduleConfig:
    configured = ScheduleConfig.from_env()
    store = ScheduleModeStore(base_root())
    persisted = store.load()
    if store.path.exists():
        if persisted.mode != configured.mode:
            raise SafetyError("persisted and configured V8 schedule modes disagree")
        if (
            persisted.synthetic_anchor_utc
            and (
                configured.synthetic_anchor_utc is None
                or parse_utc(configured.synthetic_anchor_utc)
                != parse_utc(persisted.synthetic_anchor_utc)
            )
        ):
            raise SafetyError("persisted and configured synthetic anchors disagree")
    return configured


def active_root() -> Path:
    return runtime_namespace(base_root(), schedule_config())


def command_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        (
            ("/status", "/position"),
            ("/schedule", "/safety"),
            ("/funding", "/orders"),
            ("/pause", "/flat"),
            ("/menu", "/help"),
        ),
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="V8 command…",
    )


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


async def doctor_monitor(application, config: TelegramConfig, gateway: "LocalGateway", root: Path) -> None:
    """Notify only on local-doctor state transitions; never contacts OKX."""
    path = root / "telegram" / "doctor_monitor.json"
    previous: str | None = None
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            previous = value.get("fingerprint") if isinstance(value, dict) else None
        except Exception:
            previous = None
    while True:
        try:
            report = gateway.doctor()
            fingerprint, message = alert_transition(report, previous)
            if message:
                formatted = html.escape(message)
                for chat_id in sorted(config.allowed_chat_ids):
                    await application.bot.send_message(
                        chat_id=chat_id, text=f"⚠️ <b>V8 Doctor</b>\n{formatted}", parse_mode="HTML"
                    )
            previous = fingerprint
            _atomic_json(path, {"fingerprint": fingerprint, "checked_at": datetime.now(UTC).isoformat()})
        except Exception as exc:
            logger.warning("V8 doctor monitor failed visibly: {}", type(exc).__name__)
        await asyncio.sleep(60)


@contextmanager
def telegram_process_lock() -> Iterator[None]:
    path = base_root() / "telegram.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SafetyError("duplicate V8 Telegram process") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SafetyError("duplicate V8 Telegram process") from exc
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class LocalGateway:
    def doctor(self) -> dict[str, object]:
        return inspect_runtime(base_root(), schedule_config()).as_dict()

    def snapshot(self) -> dict[str, object]:
        root = active_root()
        health_path = root / "health.json"
        health: dict[str, object] = {}
        if health_path.exists():
            try:
                health = json.loads(health_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise SafetyError("V8 health artifact is unreadable") from exc
        monitoring = health.get("monitoring") if isinstance(health.get("monitoring"), dict) else {}
        phase = health.get("phase") if isinstance(health.get("phase"), dict) else {}
        funding = health.get("funding") if isinstance(health.get("funding"), dict) else {}
        websocket = monitoring.get("websocket") if isinstance(monitoring.get("websocket"), dict) else {}
        canary = CanaryStateStore(root / "canary_state.json").load()
        intents = IntentLedger(root / "intents.json").load()
        non_terminal = len([item for item in intents if item.state not in TERMINAL])
        open_orders = int(monitoring.get("open_futures_orders", 0) or 0)
        reconciled = bool(monitoring) and open_orders == 0 and non_terminal == 0
        stopped_position: str | None = None
        if canary.status != "RUNNING":
            adapter = V8XPerpDemoAdapter(runtime_root=root)
            with adapter.locked():
                instrument = adapter._discover()
                adapter.startup_recovery(instrument)
                stopped_position = str(adapter._position(instrument))
                stopped_orders = adapter._ok(
                    adapter.trade.get_order_list(instType="FUTURES", state="live"),
                    "stopped Telegram reconciliation orders",
                )
                open_orders = len(stopped_orders)
                reconciled = open_orders == 0 and non_terminal == 0
        rest_fresh = False
        rest_checked = monitoring.get("rest_checked_at")
        if isinstance(rest_checked, str):
            try:
                rest_age = (
                    datetime.now(UTC)
                    - datetime.fromisoformat(rest_checked).astimezone(UTC)
                ).total_seconds()
                rest_fresh = 0 <= rest_age <= float(
                    os.getenv("V8_XPERP_MAX_RECONCILIATION_SECONDS", "30")
                )
            except (ValueError, TypeError):
                rest_fresh = False
        configured_mode = schedule_config().mode
        reported_mode = health.get("schedule_mode", configured_mode)
        state_disagreement = reported_mode != configured_mode
        reconciled = reconciled and (rest_fresh or canary.status != "RUNNING")
        if state_disagreement:
            reconciled = False
        current_target = monitoring.get("active_target")
        if isinstance(current_target, dict):
            current_target = (
                f"{current_target.get('direction')} "
                f"{current_target.get('strategy_leverage')}x"
            )
        next_transition = (
            phase.get("next_day_2_transition")
            if phase.get("current_phase") == "long_phase"
            else phase.get("next_day_3_transition")
        )
        return {
            "version": "v8",
            "environment": monitoring.get("environment", "okx_demo"),
            "schedule_mode": reported_mode,
            "status": (
                "BLOCKED"
                if state_disagreement
                else health.get("status", "HEALTHY" if monitoring else "NO_HEALTH_RECORD")
            ),
            "health_reason": health.get("reason"),
            "health_checked_at": health.get("checked_at", health.get("server_time")),
            "service_state": canary.status,
            "service_stopped": canary.status != "RUNNING",
            "reconciled": reconciled,
            "instrument": monitoring.get("instrument"),
            "current_target": current_target,
            "actual_capped_target": current_target,
            "position_contracts": (
                stopped_position
                if stopped_position is not None
                else monitoring.get("position_contracts")
            ),
            "position_notional_usd": monitoring.get("position_notional_usd"),
            "actual_leverage": monitoring.get("actual_leverage"),
            "canary_cap_usd": os.getenv("V8_XPERP_MAX_NOTIONAL_USD", "1000"),
            "liquidation_distance_pct": monitoring.get("liquidation_distance_pct"),
            "rest_fresh": rest_fresh,
            "websocket_fresh": bool(websocket) and not websocket.get("stale", True),
            "funding_status": funding.get("status"),
            "next_transition": next_transition,
            "kill_switches": {
                "manual_stop": monitoring.get("manual_stop", canary.manual_stop),
                "operator": asdict(OperatorControlStore(root).load()),
            },
            "phase": phase.get("current_phase", phase.get("name")),
            "synthetic_anchor": phase.get("synthetic_anchor"),
            "cycle_number": phase.get("synthetic_cycle_number"),
            "next_day_2": phase.get("next_day_2_transition"),
            "next_day_3": phase.get("next_day_3_transition"),
            "next_halving": phase.get("next_synthetic_halving"),
            "transition_due": phase.get("transition_due"),
            "open_orders": open_orders,
            "non_terminal_intents": non_terminal,
            "margin_tier_count": monitoring.get("margin_tier_count"),
            "expiry": monitoring.get("expiry"),
            "doctor": self.doctor(),
        }

    def mutate(self, action: str, arguments: tuple[str, ...]) -> str:
        root = active_root()
        controls = OperatorControlStore(root)
        if action in {"pause", "resume", "manual_stop"}:
            if action == "resume":
                snapshot = self.snapshot()
                if not snapshot["reconciled"] or snapshot["status"] == "BLOCKED":
                    raise SafetyError("resume preflight/reconciliation gates failed")
            controls.update(action)
            return action
        if action in {"flat", "emergency_flatten", "reconcile"}:
            controls.request(action)
            return f"{action} request persisted for the authoritative executor"
        if action == "set_synthetic_anchor":
            state = self.snapshot()
            updated = ScheduleModeStore(base_root()).set_anchor(
                arguments[0],
                service_stopped=bool(state["service_stopped"]),
                reconciled=bool(state["reconciled"]),
                position_contracts=str(state.get("position_contracts") or "0"),
                open_orders=int(state.get("open_orders") or 0),
                non_terminal_intents=int(state.get("non_terminal_intents") or 0),
                acknowledgement="confirmed V8 Telegram operator command",
                now=datetime.now(UTC),
            )
            return f"synthetic anchor persisted: {updated.synthetic_anchor_utc}"
        if action == "set_mode":
            current = schedule_config()
            adapter = V8XPerpDemoAdapter(runtime_root=root)
            with adapter.locked():
                instrument = adapter._discover()
                adapter.startup_recovery(instrument)
                position = adapter._position(instrument)
                orders = adapter._ok(
                    adapter.trade.get_order_list(instType="FUTURES", state="live"),
                    "Telegram schedule-switch orders",
                )
                non_terminal = len(
                    [item for item in IntentLedger(adapter.intent_path).load() if item.state not in TERMINAL]
                )
                canary = CanaryStateStore(root / "canary_state.json").load()
                updated = ScheduleModeStore(base_root()).switch(
                    new_mode=arguments[0],
                    service_stopped=canary.status != "RUNNING",
                    reconciled=True,
                    position_contracts=str(position),
                    open_orders=len(orders),
                    non_terminal_intents=non_terminal,
                    acknowledgement="confirmed V8 Telegram operator command",
                    config=ScheduleConfig(
                        mode=arguments[0],
                        synthetic_enabled=current.synthetic_enabled,
                        synthetic_anchor_utc=current.synthetic_anchor_utc,
                    ),
                    now=datetime.now(UTC),
                )
            return f"schedule mode persisted: {updated.mode}; update environment before restart"
        raise SafetyError("unsupported V8 Telegram mutation")


def main() -> int:
    config = TelegramConfig.from_env()
    if not config.enabled:
        raise SafetyError("V8 Telegram is disabled")
    router = V8TelegramRouter(
        config=config,
        gateway=LocalGateway(),
        runtime_root=active_root(),
    )

    async def post_init(application) -> None:
        try:
            await application.bot.set_my_commands(
                [BotCommand(command, description) for command, description in COMMAND_MENU]
            )
        except Exception as exc:
            logger.warning("unable to publish V8 Telegram commands: {}", type(exc).__name__)
        try:
            report = router.startup_report()
        except SafetyError as exc:
            report = (
                "<b>⚠️ V8 X-Perp Telegram started in degraded mode</b>\n"
                f"<code>{str(exc)[:300]}</code>\nUse /health for details."
            )
        for chat_id in sorted(config.allowed_chat_ids):
            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=report,
                    parse_mode="HTML",
                    reply_markup=command_keyboard(),
                )
            except Exception as exc:
                logger.warning("unable to send V8 Telegram startup report: {}", type(exc).__name__)
        application.create_task(doctor_monitor(application, config, router.gateway, active_root()))

    application = ApplicationBuilder().token(config.token).post_init(post_init).build()

    async def dispatch(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.effective_message is None:
            return
        response = router.handle(
            update_id=update.update_id,
            chat_id=update.effective_chat.id,
            text=update.effective_message.text or "",
        )
        if response:
            text = update.effective_message.text or ""
            command = text.strip().split(maxsplit=1)[0].lower().split("@", 1)[0]
            await update.effective_message.reply_text(
                response,
                parse_mode="HTML",
                reply_markup=command_keyboard() if command in {"/start", "/menu", "/help"} else None,
            )

    application.add_handler(MessageHandler(filters.COMMAND, dispatch))
    with telegram_process_lock():
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            close_loop=True,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyError as exc:
        print(f"BLOCKED: {str(exc)[:300]}")
        raise SystemExit(2)
