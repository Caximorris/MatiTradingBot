from pathlib import Path

from execution.v8_xperp.telegram import (
    TelegramConfig,
    V8TelegramRouter,
)


class Gateway:
    def __init__(self, **changes):
        self.calls = []
        self.value = {
            "status": "HEALTHY",
            "service_state": "RUNNING",
            "service_stopped": False,
            "reconciled": True,
            "environment": "okx_demo",
            "schedule_mode": "synthetic_demo_cycle",
            "instrument": "BTC-XPERP",
            "current_target": "long 2x",
            "position_contracts": "0.01",
            "position_notional_usd": "650",
            "canary_cap_usd": "1000",
            "rest_fresh": True,
            "websocket_fresh": True,
        }
        self.value.update(changes)

    def snapshot(self):
        return self.value

    def mutate(self, action, arguments):
        self.calls.append((action, arguments))
        return f"{action} persisted"


def router(tmp_path: Path, gateway=None) -> V8TelegramRouter:
    return V8TelegramRouter(
        config=TelegramConfig(
            enabled=True,
            token="never-exposed",
            allowed_chat_ids=frozenset({42}),
            confirmation_seconds=120,
        ),
        gateway=gateway or Gateway(),
        runtime_root=tmp_path,
    )


def test_non_allowlisted_chat_is_silently_rejected(tmp_path) -> None:
    assert router(tmp_path).handle(
        update_id=1, chat_id=99, text="/status"
    ) is None


def test_read_only_command_is_v8_scoped_and_audited(tmp_path) -> None:
    response = router(tmp_path).handle(
        update_id=1, chat_id=42, text="/status"
    )
    assert "environment: okx_demo" in response
    assert "schedule_mode: synthetic_demo_cycle" in response
    audit = (tmp_path / "telegram" / "audit.jsonl").read_text()
    assert '"command": "status"' in audit
    assert "never-exposed" not in audit


def test_mutation_requires_one_time_confirmation(tmp_path) -> None:
    gateway = Gateway()
    subject = router(tmp_path, gateway)
    issued = subject.handle(update_id=1, chat_id=42, text="/pause")
    nonce = issued.split("/confirm ", 1)[1].splitlines()[0]
    confirmed = subject.handle(
        update_id=2, chat_id=42, text=f"/confirm {nonce}"
    )
    replay = subject.handle(
        update_id=3, chat_id=42, text=f"/confirm {nonce}"
    )
    assert confirmed == "CONFIRMED: pause persisted"
    assert gateway.calls == [("pause", ())]
    assert replay.startswith("BLOCKED:")


def test_stronger_confirmation_marks_flat_action(tmp_path) -> None:
    issued = router(tmp_path).handle(
        update_id=1, chat_id=42, text="/emergency_flatten"
    )
    assert issued.startswith("STRONG CONFIRMATION REQUIRED:")


def test_duplicate_and_non_monotonic_updates_are_suppressed(tmp_path) -> None:
    subject = router(tmp_path)
    assert subject.handle(update_id=5, chat_id=42, text="/status")
    assert subject.handle(update_id=5, chat_id=42, text="/status") is None
    assert subject.handle(update_id=4, chat_id=42, text="/health") is None


def test_unhealthy_executor_forces_read_only_degraded_mode(tmp_path) -> None:
    subject = router(tmp_path, Gateway(status="BLOCKED", reconciled=False))
    assert subject.handle(update_id=1, chat_id=42, text="/health")
    blocked = subject.handle(update_id=2, chat_id=42, text="/resume")
    assert blocked == "BLOCKED: executor is unhealthy; Telegram is read-only"


def test_schedule_mode_requires_stopped_reconciled_executor(tmp_path) -> None:
    running = router(tmp_path, Gateway(service_stopped=False))
    assert "read-only" in running.handle(
        update_id=1, chat_id=42, text="/set_mode real_cycle"
    )
    stopped = router(tmp_path / "stopped", Gateway(service_stopped=True))
    assert "STRONG CONFIRMATION" in stopped.handle(
        update_id=1, chat_id=42, text="/set_mode real_cycle"
    )


def test_legacy_and_discretionary_commands_are_rejected(tmp_path) -> None:
    subject = router(tmp_path)
    for update_id, command in enumerate(
        ("/v7", "/bots", "/spot", "/buy BTC 10", "/update", "/restart"),
        start=1,
    ):
        assert subject.handle(
            update_id=update_id, chat_id=42, text=command
        ).startswith("REJECTED:")


def test_every_documented_read_command_routes_without_mutation(tmp_path) -> None:
    gateway = Gateway()
    subject = router(tmp_path, gateway)
    commands = (
        "help", "status", "health", "version", "mode", "phase", "schedule",
        "next_transition", "position", "orders", "intents", "funding", "margin",
        "expiry", "canary", "kill_switches", "reconciliation",
    )
    for update_id, command in enumerate(commands, start=1):
        assert subject.handle(
            update_id=update_id, chat_id=42, text=f"/{command}"
        )
    assert gateway.calls == []
