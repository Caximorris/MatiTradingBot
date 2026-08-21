from pathlib import Path

from execution.v8_xperp.telegram import (
    COMMAND_MENU,
    TelegramConfig,
    V8TelegramRouter,
)
from execution.v8_xperp.doctor import alert_transition


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

    def doctor(self):
        return {
            "status": "STALE",
            "reason": "V8 health record is stale",
            "health_status": "HEALTHY",
            "health_fresh": False,
            "health_age_seconds": 121,
            "canary_state": "STOPPED",
            "paused": True,
            "anchors_match": True,
            "findings": ("V8 health record is stale",),
        }

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
    assert "V8 X-Perp Demo · Control Room" in response
    assert "okx_demo · synthetic_demo_cycle" in response
    audit = (tmp_path / "telegram" / "audit.jsonl").read_text()
    assert '"command": "status"' in audit
    assert "never-exposed" not in audit


def test_dashboard_uses_readable_rounded_risk_labels(tmp_path) -> None:
    subject = router(tmp_path, Gateway(
        position_contracts="0.0156",
        position_notional_usd="1002.68376",
        actual_leverage="0.01007847295059681758169975278",
        canary_cap_usd="1000",
        liquidation_distance_pct="47.60315861881718924536462271",
        funding_status="REAL_PARITY_OBSERVED",
        next_transition="2026-07-31T15:53:38+00:00",
    ))

    dashboard = subject.handle(update_id=1, chat_id=42, text="/status")

    assert "$1,002.68" in dashboard
    assert "<b>1.01%</b> of equity" in dashboard
    assert "entry cap <b>$1,000.00" in dashboard
    assert "Liquidation buffer: <b>47.60%" in dashboard
    assert "Verified against exchange settlement" in dashboard
    assert "31 Jul 2026 · 15:53 UTC" in dashboard
    assert "010078472950" not in dashboard


def test_read_reports_summarize_expiry_and_kill_switches(tmp_path) -> None:
    subject = router(tmp_path, Gateway(
        expiry={
            "days_remaining": "1701.976386119375",
            "expiry": "2031-03-28T08:00:00+00:00",
            "block_new_exposure": False,
        },
        kill_switches={
            "manual_stop": False,
            "operator": {"manual_stop": False, "paused": False},
        },
    ))

    expiry = subject.handle(update_id=1, chat_id=42, text="/expiry")
    switches = subject.handle(update_id=2, chat_id=42, text="/kill_switches")

    assert "1,702.0 days left · new exposure allowed" in expiry
    assert "Manual stop: off · Pause: off" in switches


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
    subject = router(tmp_path, Gateway(
        status="BLOCKED",
        reconciled=False,
        health_reason="market-data freshness gate failed",
    ))
    assert subject.handle(update_id=1, chat_id=42, text="/health")
    dashboard = subject.handle(update_id=2, chat_id=42, text="/status")
    assert "Block reason" in dashboard
    assert "market-data freshness gate failed" in dashboard
    blocked = subject.handle(update_id=3, chat_id=42, text="/resume")
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


def test_v8_menu_and_startup_report_are_visual_and_legacy_free(tmp_path) -> None:
    subject = router(tmp_path)
    menu = subject.handle(update_id=1, chat_id=42, text="/menu")
    assert "V8 X-Perp Demo · Control Room" in menu
    assert "/flat" in subject.handle(update_id=2, chat_id=42, text="/help")
    assert subject.startup_report() == subject._format_read("status", subject.gateway.snapshot())
    commands = {command for command, _ in COMMAND_MENU}
    assert {"start", "menu", "status", "position", "safety", "funding", "flat"} <= commands
    assert not commands & {"bots", "equity", "status_v6", "status_demo", "prop"}


def test_every_documented_read_command_routes_without_mutation(tmp_path) -> None:
    gateway = Gateway()
    subject = router(tmp_path, gateway)
    commands = (
        "help", "status", "health", "version", "mode", "phase", "schedule",
        "next_transition", "position", "orders", "intents", "funding", "margin",
        "expiry", "canary", "kill_switches", "reconciliation", "doctor",
    )
    for update_id, command in enumerate(commands, start=1):
        assert subject.handle(
            update_id=update_id, chat_id=42, text=f"/{command}"
        )
    assert gateway.calls == []


def test_doctor_is_local_read_only_diagnosis(tmp_path) -> None:
    gateway = Gateway()

    response = router(tmp_path, gateway).handle(
        update_id=1, chat_id=42, text="/doctor"
    )

    assert "V8 Doctor" in response
    assert "V8 health record is stale" in response
    assert gateway.calls == []


def test_doctor_alert_is_idempotent_and_never_implies_execution() -> None:
    report = {"status": "STALE", "reason": "V8 health record is stale"}

    fingerprint, first = alert_transition(report, None)
    _, repeated = alert_transition(report, fingerprint)

    assert "did not start, resume, flatten" in first
    assert repeated is None
