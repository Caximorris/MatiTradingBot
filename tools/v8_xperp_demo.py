#!/usr/bin/env python
"""V8-only OKX EEA X-Perp operations; continuous mode is disabled by default."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.v8_xperp import SafetyError, V8XPerpDemoAdapter  # noqa: E402
from execution.v8_xperp.intents import IntentLedger, TERMINAL  # noqa: E402
from execution.v8_xperp.canary import CanaryConfig  # noqa: E402
from execution.v8_xperp.funding import FundingLedger  # noqa: E402
from execution.v8_xperp.bootstrap import BootstrapConfig  # noqa: E402
from execution.v8_xperp.index_source import OKXIndexPriceSource  # noqa: E402
from execution.v8_xperp.private_stream import PrivateStreamSupervisor  # noqa: E402
from execution.v8_xperp.recovery import (  # noqa: E402
    IntentExecution,
    archive_reconciled,
    sanitized_status,
)
from execution.v8_xperp.rollover import (  # noqa: E402
    discover_successor,
    expiry_status,
    rollover_dry_run,
)
from execution.v8_xperp.service import (  # noqa: E402
    CanaryStateStore,
    V8XPerpCanaryService,
)
from execution.v8_xperp.runtime import (  # noqa: E402
    V8OperationalController,
    request_operator_flat,
)
from execution.v8_xperp.schedule import (  # noqa: E402
    REAL_CYCLE,
    SYNTHETIC_DEMO_CYCLE,
    ScheduleConfig,
    ScheduleModeStore,
    runtime_namespace,
    synthetic_event,
    synthetic_preview,
)
from execution.v8_xperp.target_transport import TransportStateStore  # noqa: E402
from execution.v8_xperp.operator import OperatorControlStore  # noqa: E402


def _json(value: object) -> None:
    def convert(item: object) -> object:
        return asdict(item) if hasattr(item, "__dataclass_fields__") else str(item)
    print(json.dumps(asdict(value) if hasattr(value, "__dataclass_fields__") else value, default=convert, indent=2, sort_keys=True))


def _rollover_market(adapter: V8XPerpDemoAdapter, instrument_id: str, index_id: str) -> dict[str, str]:
    ticker = adapter._ok(adapter.market_api.get_ticker(instrument_id), "rollover ticker")
    book = adapter._ok(adapter.market_api.get_orderbook(instrument_id, sz="5"), "rollover book")
    index = adapter._ok(adapter.market_api.get_index_tickers(instId=index_id), "rollover index")
    if len(ticker) != 1 or len(book) != 1 or len(index) != 1:
        raise SafetyError("rollover market response is ambiguous")
    return {
        "bidPx": str(book[0]["bids"][0][0]),
        "askPx": str(book[0]["asks"][0][0]),
        "bidSz": str(book[0]["bids"][0][1]),
        "askSz": str(book[0]["asks"][0][1]),
        "indexPx": str(index[0]["idxPx"]),
    }


async def _wait_stream(stream: PrivateStreamSupervisor) -> None:
    deadline = asyncio.get_running_loop().time() + 45
    while asyncio.get_running_loop().time() < deadline:
        if not stream.state.stale and stream.state.subscribed:
            stream.assert_healthy()
            return
        await asyncio.sleep(0.1)
    raise SafetyError("private WebSocket did not become healthy")


async def _run_canary(*, one_shot: bool) -> dict[str, object]:
    config = CanaryConfig.from_env()
    if not config.enabled:
        raise SafetyError("V8_XPERP_CONTINUOUS_DEMO_ENABLED=true is required")
    adapter = V8XPerpDemoAdapter()
    with adapter.locked():
        report = adapter.preflight()
        adapter.startup_recovery(report.instrument)
        key, secret, passphrase = adapter._credentials()
        stream = PrivateStreamSupervisor(
            api_key=key,
            secret=secret,
            passphrase=passphrase,
            instrument_id=report.instrument.inst_id,
            reconcile=lambda: adapter.startup_recovery(report.instrument),
        )
        stop = asyncio.Event()
        task = asyncio.create_task(stream.run(stop))
        service = V8XPerpCanaryService(adapter=adapter, config=config)
        try:
            await _wait_stream(stream)
            # The preflight report is needed to identify the instrument and
            # recover ownership, but its market snapshot may be older than
            # the five-second canary freshness limit by the time the private
            # stream is healthy. Refresh it immediately before startup.
            report = adapter.operational_report(report.instrument)
            service.start(
                report=report,
                tiers=adapter.margin_tiers(report),
                authenticated_leverage=adapter.selected_leverage(report),
                stream=stream,
                reconciled_at=datetime.now(UTC),
            )
            if one_shot:
                service.stop()
            else:
                while True:
                    await asyncio.sleep(1)
                    stream.assert_healthy()
        except KeyboardInterrupt:
            service.stop()
        finally:
            if service.state.status == "RUNNING" and adapter._position(report.instrument) == 0:
                service.stop()
            stop.set()
            if stream.state.connected:
                with suppress(Exception):
                    await stream.force_disconnect()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return {
            "status": service.state.status,
            "instrument": report.instrument.inst_id,
            "maximum_notional_observed": service.state.maximum_notional_observed,
            "one_shot": one_shot,
        }


def _base_runtime_root() -> Path:
    return Path(os.getenv("V8_XPERP_RUNTIME_ROOT", "data/runtime/v8_xperp_demo"))


def _schedule_config() -> ScheduleConfig:
    base = _base_runtime_root()
    configured = ScheduleConfig.from_env()
    persisted = ScheduleModeStore(base).load()
    if (base / "schedule_mode.json").exists():
        if configured.mode != persisted.mode:
            raise SafetyError("persisted and configured V8 schedule modes disagree")
        if (
            persisted.synthetic_anchor_utc
            and configured.synthetic_anchor_utc != persisted.synthetic_anchor_utc
        ):
            raise SafetyError("persisted and configured synthetic anchors disagree")
    return configured


def _runtime_root() -> Path:
    return runtime_namespace(_base_runtime_root(), _schedule_config())


def _read_health() -> dict[str, object]:
    path = _runtime_root() / "health.json"
    if not path.exists():
        return {"status": "NO_HEALTH_RECORD", "path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SafetyError("V8 operational health record is corrupt") from exc
    if not isinstance(value, dict):
        raise SafetyError("V8 operational health record is malformed")
    return value


def _print_operational_status() -> None:
    value = _read_health()
    monitoring = value.get("monitoring") or {}
    decision = value.get("decision") or {}
    phase = value.get("phase") or {}
    funding = value.get("funding") or {}
    print(f"status: {value.get('status', 'HEALTHY' if monitoring else 'UNKNOWN')}")
    print(f"server_time: {value.get('server_time', value.get('checked_at', 'unknown'))}")
    print(f"phase: {phase.get('name', 'unknown')} ({phase.get('direction', 'unknown')})")
    print(f"transport: {decision.get('action', 'unknown')} - {decision.get('reason', '')}")
    print(f"instrument: {monitoring.get('instrument', 'unknown')}")
    print(f"position_contracts: {monitoring.get('position_contracts', 'unknown')}")
    print(f"position_notional_usd: {monitoring.get('position_notional_usd', 'unknown')}")
    print(f"actual_leverage: {monitoring.get('actual_leverage', 'unknown')}")
    print(f"open_futures_orders: {monitoring.get('open_futures_orders', 'unknown')}")
    print(f"funding: {funding.get('status', 'unknown')}")
    print(f"manual_stop: {monitoring.get('manual_stop', 'unknown')}")


def _write_failure_health(message: str) -> None:
    path = _runtime_root() / "health.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "checked_at": datetime.now(UTC).isoformat(),
                "reason": message,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safety_exit_code(message: str) -> int:
    manual_markers = (
        "manual emergency stop is latched",
        "Telegram manual stop is latched",
        "daily canary loss limit is latched",
        "total canary loss limit is latched",
        "unknown exchange position",
        "unknown exchange order",
        "multiple unexpected FUTURES positions",
        "ownership is not proven",
        "process lock",
        "corrupt V8",
    )
    return 3 if any(marker in message for marker in manual_markers) else 2


async def _run_operational(*, execute: bool, one_shot: bool) -> dict[str, object]:
    config = CanaryConfig.from_env()
    if not config.enabled:
        raise SafetyError("V8_XPERP_CONTINUOUS_DEMO_ENABLED=true is required")
    try:
        interval = float(os.getenv("V8_XPERP_CYCLE_SECONDS", "10"))
    except ValueError as exc:
        raise SafetyError("V8_XPERP_CYCLE_SECONDS is invalid") from exc
    if interval < 5 or interval > 60:
        raise SafetyError("V8_XPERP_CYCLE_SECONDS must be between 5 and 60")

    schedule_config = _schedule_config()
    adapter = V8XPerpDemoAdapter(
        runtime_root=runtime_namespace(_base_runtime_root(), schedule_config)
    )
    with adapter.locked():
        instrument = adapter._discover()
        adapter.startup_recovery(instrument)
        report = adapter.operational_report(instrument)
        key, secret, passphrase = adapter._credentials()
        stream = PrivateStreamSupervisor(
            api_key=key,
            secret=secret,
            passphrase=passphrase,
            instrument_id=instrument.inst_id,
            reconcile=lambda: adapter.startup_recovery(instrument),
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(signum, stop.set)
        task = asyncio.create_task(stream.run(stop))
        service = V8XPerpCanaryService(adapter=adapter, config=config)
        controller = V8OperationalController(
            adapter=adapter,
            service=service,
            index_source=OKXIndexPriceSource(market_api=adapter.market_api),
            canary_config=config,
            bootstrap_config=BootstrapConfig.from_env(),
            schedule_config=schedule_config,
        )
        last_result: dict[str, object] = {}
        try:
            await _wait_stream(stream)
            server_time, drift = adapter.verified_server_time()
            service.start(
                report=report,
                tiers=adapter.margin_tiers(report),
                authenticated_leverage=adapter.selected_leverage(report),
                stream=stream,
                clock_drift_seconds=drift,
                reconciled_at=report.checked_at,
            )
            while not stop.is_set():
                stream.assert_healthy()
                report = adapter.operational_report(instrument)
                server_time, drift = adapter.verified_server_time()
                last_result = controller.cycle(
                    report=report,
                    server_time=server_time,
                    clock_drift_seconds=drift,
                    execute=execute,
                )
                if one_shot:
                    break
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except TimeoutError:
                    pass
        finally:
            if one_shot and adapter._position(instrument) == 0:
                service.stop()
            stop.set()
            if stream.state.connected:
                with suppress(Exception):
                    await stream.force_disconnect()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return last_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="read-only authenticated gate")
    sub.add_parser("reconcile", help="read-only preflight plus reconciliation snapshot")
    sub.add_parser("status", help="read-only account and market status")
    sub.add_parser("canary-config", help="validate hard canary configuration")
    sub.add_parser("canary-status", help="read local canary lifecycle state")
    sub.add_parser("health", help="read machine-readable unattended health state")
    sub.add_parser("operational-status", help="read human-readable unattended status")
    sub.add_parser("schedule-mode-status", help="read persisted/configured schedule mode")
    sub.add_parser("schedule-preview", help="read-only current schedule preview")
    dry = sub.add_parser("synthetic-dry-run", help="simulate synthetic cycles without orders")
    dry.add_argument("--cycles", type=int, default=3)
    mode = sub.add_parser("set-mode", help="persist a stopped, reconciled schedule-mode switch")
    mode.add_argument("mode", choices=[REAL_CYCLE, SYNTHETIC_DEMO_CYCLE])
    mode.add_argument("--acknowledge", required=True)
    mode.add_argument("--confirm-v8-schedule-mode", action="store_true")
    anchor = sub.add_parser("set-synthetic-anchor", help="persist a future UTC synthetic anchor")
    anchor.add_argument("anchor")
    anchor.add_argument("--acknowledge", required=True)
    anchor.add_argument("--confirm-v8-synthetic-anchor", action="store_true")
    sub.add_parser("preactivation", help="one authenticated no-order operational cycle")
    operator_flat = sub.add_parser(
        "operator-flat", help="persist a flat request for the unattended controller"
    )
    operator_flat.add_argument("--confirm-v8-operator-flat", action="store_true")
    sub.add_parser("funding-status", help="read funding interfaces and exact-once ledger status")
    sub.add_parser("margin-status", help="read current tier/leverage/risk status")
    sub.add_parser("expiry-status", help="read current expiry gates")
    sub.add_parser("rollover-dry-run", help="read-only successor and rollover plan")
    sub.add_parser("graceful-shutdown", help="stop local canary state only when Demo is flat")
    manual = sub.add_parser("manual-emergency-stop", help="flatten known V8 state and latch manual stop")
    manual.add_argument("--confirm-v8-emergency-stop", action="store_true")
    recovery = sub.add_parser(
        "manual-recovery", help="clear a manual stop only after flat reconciliation"
    )
    recovery.add_argument("--confirm-v8-manual-recovery", action="store_true")
    sub.add_parser("validate-journal", help="validate the atomic intent journal")
    sub.add_parser("list-intents", help="list non-terminal persisted intents")
    sub.add_parser("startup-recovery", help="lock and run read-only startup recovery")
    recover = sub.add_parser("recover-intent", help="read-only recovery of one client-order ID")
    recover.add_argument("client_order_id")
    sub.add_parser("recovery-status", help="sanitized local recovery-status report")
    archive = sub.add_parser("archive-intents", help="archive reconciled terminal intents")
    archive.add_argument("--destination", type=Path)
    sub.add_parser("final-reconcile", help="lock and reconcile final V8 account state")
    target = sub.add_parser("targets", help="calculate but do not place V8 targets")
    target.add_argument("--target", choices=["flat", "long 1x", "long 2x", "short 2x"], action="append")
    sub.add_parser("smoke", help="minimum-size long/flat then short/flat Demo test")
    flatten = sub.add_parser("flatten", help="reserved emergency command; never auto-runs")
    flatten.add_argument("--confirm-v8-emergency-flatten", action="store_true")
    run = sub.add_parser("run", help="continuous Demo operation")
    run.add_argument("--enable-continuous-demo", action="store_true")
    start = sub.add_parser("canary-start", help="start, validate, and stop a one-shot canary")
    start.add_argument("--enable-continuous-demo", action="store_true")
    args = parser.parse_args()
    if args.command == "schedule-mode-status":
        _json({
            "configured": _schedule_config(),
            "persisted": ScheduleModeStore(_base_runtime_root()).load(),
            "runtime_namespace": str(_runtime_root()),
        })
        return 0
    if args.command in {"schedule-preview", "synthetic-dry-run"}:
        config = _schedule_config()
        if config.mode != SYNTHETIC_DEMO_CYCLE:
            _json({"schedule_mode": config.mode, "synthetic": None})
            return 0
        now = datetime.now(UTC)
        if args.command == "schedule-preview":
            state = TransportStateStore(_runtime_root() / "target_transport_state.json").load()
            previous = (
                datetime.fromisoformat(state.last_observed_at)
                if state.last_observed_at
                else None
            )
            preview = asdict(
                synthetic_preview(
                    config, now=now, previous_observed_at=previous
                )
            )
            health = _read_health()
            monitoring = health.get("monitoring") or {}
            preview.update({
                "current_target": monitoring.get("active_target", preview["current_target"]),
                "actual_capped_target": health.get("capped"),
                "current_position": monitoring.get("position_contracts", "unknown"),
                "current_position_notional_usd": monitoring.get(
                    "position_notional_usd", "unknown"
                ),
            })
            _json(preview)
        else:
            if args.cycles < 1 or args.cycles > 30:
                raise SafetyError("synthetic dry-run cycles must be between 1 and 30")
            _json([
                synthetic_event(config, cycle, event)
                for cycle in range(args.cycles)
                for event in (
                    "synthetic_halving",
                    "bear_transition",
                    "accumulation_transition",
                )
            ])
        return 0
    if args.command == "set-synthetic-anchor":
        if not args.confirm_v8_synthetic_anchor:
            raise SafetyError("synthetic anchor change requires explicit confirmation")
        adapter = V8XPerpDemoAdapter(runtime_root=_runtime_root())
        with adapter.locked():
            instrument = adapter._discover()
            adapter.startup_recovery(instrument)
            orders = adapter._ok(
                adapter.trade.get_order_list(instType="FUTURES", state="live"),
                "synthetic anchor open orders",
            )
            non_terminal = [
                item for item in IntentLedger(adapter.intent_path).load()
                if item.state not in TERMINAL
            ]
            state = CanaryStateStore(adapter.runtime_root / "canary_state.json").load()
            _json(ScheduleModeStore(_base_runtime_root()).set_anchor(
                args.anchor,
                service_stopped=state.status != "RUNNING",
                reconciled=True,
                position_contracts=str(adapter._position(instrument)),
                open_orders=len(orders),
                non_terminal_intents=len(non_terminal),
                acknowledgement=args.acknowledge,
                now=datetime.now(UTC),
            ))
        return 0
    if args.command in {"run", "canary-start"}:
        if not args.enable_continuous_demo:
            raise SafetyError("continuous Demo requires the explicit CLI enable flag")
        operation = (
            _run_canary(one_shot=True)
            if args.command == "canary-start"
            else _run_operational(execute=True, one_shot=False)
        )
        _json(asyncio.run(operation))
        return 0
    if args.command == "preactivation":
        _json(asyncio.run(_run_operational(execute=False, one_shot=True)))
        return 0
    if args.command == "health":
        _json(_read_health())
        return 0
    if args.command == "operational-status":
        _print_operational_status()
        return 0
    if args.command == "operator-flat":
        if not args.confirm_v8_operator_flat:
            raise SafetyError("operator flat requires the explicit confirmation flag")
        _json(request_operator_flat(_runtime_root()))
        return 0
    adapter = V8XPerpDemoAdapter(runtime_root=_runtime_root())
    ledger = IntentLedger(adapter.intent_path)
    if args.command == "canary-config":
        _json(CanaryConfig.from_env())
        return 0
    if args.command == "set-mode":
        if not args.confirm_v8_schedule_mode:
            raise SafetyError("schedule mode switch requires explicit confirmation")
        with adapter.locked():
            instrument = adapter._discover()
            adapter.startup_recovery(instrument)
            position = adapter._position(instrument)
            orders = adapter._ok(
                adapter.trade.get_order_list(instType="FUTURES", state="live"),
                "schedule switch open orders",
            )
            non_terminal = [
                item for item in ledger.load() if item.state not in TERMINAL
            ]
            state = CanaryStateStore(adapter.runtime_root / "canary_state.json").load()
            _json(ScheduleModeStore(_base_runtime_root()).switch(
                new_mode=args.mode,
                service_stopped=state.status != "RUNNING",
                reconciled=True,
                position_contracts=str(position),
                open_orders=len(orders),
                non_terminal_intents=len(non_terminal),
                acknowledgement=args.acknowledge,
                config=ScheduleConfig(
                    mode=args.mode,
                    synthetic_enabled=(
                        os.getenv("V8_SYNTHETIC_DEMO_CYCLE_ENABLED", "").lower()
                        == "true"
                    ),
                    synthetic_anchor_utc=(
                        os.getenv("V8_SYNTHETIC_CYCLE_ANCHOR_UTC", "").strip() or None
                    ),
                ),
                now=datetime.now(UTC),
            ))
        return 0
    if args.command == "canary-status":
        _json(CanaryStateStore(adapter.runtime_root / "canary_state.json").load())
        return 0
    if args.command in {"validate-journal", "list-intents", "recovery-status", "archive-intents"}:
        if args.command == "archive-intents":
            destination = args.destination or adapter.runtime_root / "archive" / "reconciled-intents.json"
            _json({"archived": archive_reconciled(ledger, destination), "destination": str(destination)})
        elif args.command == "recovery-status":
            _json(sanitized_status(adapter.intent_path, ledger))
        else:
            rows = ledger.load()
            _json(
                {"integrity": "pass", "intent_count": len(rows)}
                if args.command == "validate-journal"
                else [row for row in rows if row.state not in TERMINAL]
            )
        return 0
    if args.command in {"startup-recovery", "final-reconcile"}:
        with adapter.locked():
            _json(adapter.startup_recovery(adapter._discover()))
        return 0
    if args.command == "recover-intent":
        intent = next((row for row in ledger.load() if row.client_order_id == args.client_order_id), None)
        if intent is None:
            raise SafetyError("unknown V8 intent")
        with adapter.locked():
            result = IntentExecution(adapter=adapter, ledger=ledger).reconcile(
                intent, before_position=Decimal("0"), permit_absent=False
            )
            _json(result)
        return 0
    if args.command == "flatten":
        if not args.confirm_v8_emergency_flatten:
            raise SafetyError("emergency flatten requires the explicit confirmation flag")
        with adapter.locked():
            instrument = adapter._discover()
            adapter.startup_recovery(instrument)
            report = type("RecoveryReport", (), {"instrument": instrument})()
            _json(adapter.emergency_flatten(report))
        return 0
    if args.command == "manual-emergency-stop":
        if not args.confirm_v8_emergency_stop:
            raise SafetyError("manual emergency stop requires explicit confirmation")
        with adapter.locked():
            instrument = adapter._discover()
            adapter.startup_recovery(instrument)
            report = type("RecoveryReport", (), {"instrument": instrument})()
            result = adapter.emergency_flatten(report)
            state_store = CanaryStateStore(adapter.runtime_root / "canary_state.json")
            state = state_store.load()
            state_store.write(type(state)(
                **{
                    **asdict(state),
                    "status": "STOPPED",
                    "manual_stop": True,
                    "stopped_at": datetime.now(UTC).isoformat(),
                }
            ))
            _json(result)
        return 0
    if args.command == "manual-recovery":
        if not args.confirm_v8_manual_recovery:
            raise SafetyError("manual recovery requires explicit confirmation")
        with adapter.locked():
            instrument = adapter._discover()
            adapter.startup_recovery(instrument)
            if adapter._position(instrument) != 0:
                raise SafetyError("manual recovery requires a flat V8 position")
            orders = adapter._ok(
                adapter.trade.get_order_list(instType="FUTURES", state="live"),
                "manual recovery open orders",
            )
            if orders:
                raise SafetyError("manual recovery requires zero FUTURES open orders")
            state_store = CanaryStateStore(adapter.runtime_root / "canary_state.json")
            state = state_store.load()
            state_store.write(type(state)(
                **{
                    **asdict(state),
                    "status": "STOPPED",
                    "manual_stop": False,
                    "stopped_at": datetime.now(UTC).isoformat(),
                }
            ))
            OperatorControlStore(adapter.runtime_root).update("manual_recovery")
            _json(state_store.load())
        return 0
    if args.command == "graceful-shutdown":
        with adapter.locked():
            instrument = adapter._discover()
            adapter.startup_recovery(instrument)
            if adapter._position(instrument) != 0:
                raise SafetyError("graceful shutdown requires a flat V8 position")
            state_store = CanaryStateStore(adapter.runtime_root / "canary_state.json")
            state = state_store.load()
            state_store.write(type(state)(
                **{**asdict(state), "status": "STOPPED", "stopped_at": datetime.now(UTC).isoformat()}
            ))
            _json(state_store.load())
        return 0
    if args.command == "smoke":
        _json(adapter.smoke())
        return 0
    report = adapter.preflight()
    if args.command == "funding-status":
        snapshot = adapter.funding_reconciliation(report)
        records = FundingLedger(adapter.runtime_root / "funding.json").load()
        _json({
            "snapshot": snapshot,
            "expectations": len(records),
            "states": {state: len([row for row in records if row.state == state]) for state in sorted({row.state for row in records})},
            "actual_parity": "OBSERVED" if any(row.state == "RECONCILED" for row in records) else "UNOBSERVED",
        })
    elif args.command == "margin-status":
        _json(adapter.margin_evidence(report))
    elif args.command == "expiry-status":
        _json(expiry_status(report.instrument))
    elif args.command == "rollover-dry-run":
        rows = adapter._ok(adapter.account.get_instruments("FUTURES"), "rollover instrument catalogue")
        markets = {report.instrument.inst_id: _rollover_market(adapter, report.instrument.inst_id, report.instrument.uly)}
        with suppress(SafetyError):
            successor = discover_successor(report.instrument, rows)
            markets[str(successor["instId"])] = _rollover_market(
                adapter, str(successor["instId"]), report.instrument.uly
            )
        _json(rollover_dry_run(
            current=report.instrument,
            instrument_rows=rows,
            markets=markets,
            current_contracts=Decimal("0"),
        ))
    elif args.command == "targets":
        _json([adapter.calculate_target(report, value) for value in (args.target or ["flat", "long 1x", "long 2x", "short 2x"])])
    else:
        _json(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyError as exc:
        with suppress(Exception):
            _write_failure_health(str(exc))
        print(f"BLOCKED: {exc}")
        raise SystemExit(_safety_exit_code(str(exc)))
