#!/usr/bin/env python
"""Bounded authenticated V8 Demo recovery exercises; never enables continuous mode."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.v8_xperp.adapter import (  # noqa: E402
    CLIENT_PREFIX,
    SafetyError,
    V8XPerpDemoAdapter,
    _decimal,
)
from execution.v8_xperp.private_stream import PrivateStreamSupervisor  # noqa: E402
from execution.v8_xperp.intents import IntentLedger  # noqa: E402


def _write_evidence(root: Path, name: str, payload: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


async def _wait_healthy(stream: PrivateStreamSupervisor, *, after_reconnects: int = -1) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        state = stream.state
        if not state.stale and state.subscribed and state.reconnects > after_reconnects:
            stream.assert_healthy()
            return
        await asyncio.sleep(0.1)
    raise SafetyError(
        f"private WebSocket did not become healthy before the exercise deadline: {stream.state}"
    )


async def _stop_stream(
    stream: PrivateStreamSupervisor,
    stop: asyncio.Event,
    task: asyncio.Task[None],
) -> None:
    stop.set()
    if stream.state.connected:
        with suppress(Exception):
            await stream.force_disconnect()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _counts(adapter: V8XPerpDemoAdapter, instrument_id: str, client_id: str) -> dict[str, int]:
    order = adapter._ok(
        adapter.trade.get_order(instrument_id, clOrdId=client_id),
        "exercise order by client ID",
    )
    fills = adapter._ok(
        adapter.trade.get_fills(instType="FUTURES", instId=instrument_id),
        "exercise fills",
    )
    return {
        "accepted_orders": len(
            {row.get("ordId") for row in order if row.get("clOrdId") == client_id}
        ),
        "fills": len([row for row in fills if row.get("clOrdId") == client_id]),
    }


async def _wait_counts(
    adapter: V8XPerpDemoAdapter,
    instrument_id: str,
    client_id: str,
) -> dict[str, int]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        counts = _counts(adapter, instrument_id, client_id)
        if counts == {"accepted_orders": 1, "fills": 1}:
            return counts
        await asyncio.sleep(0.25)
    raise SafetyError("accepted order/fill evidence did not settle to exactly one")


def _final_state(adapter: V8XPerpDemoAdapter, instrument_id: str) -> dict[str, Any]:
    positions = adapter._ok(
        adapter.account.get_positions(instType="FUTURES", instId=instrument_id),
        "final position",
    )
    position = _decimal(positions[0].get("pos")) if positions else _decimal("0")
    orders = adapter._ok(
        adapter.trade.get_order_list(instType="FUTURES", state="live"),
        "final open orders",
    )
    return {
        "position": str(position),
        "v8_open_orders": len(
            [row for row in orders if str(row.get("clOrdId", "")).startswith(CLIENT_PREFIX)]
        ),
        "all_futures_open_orders": len(orders),
    }


async def flat_reconnect(runtime_root: Path, evidence_root: Path) -> Path:
    adapter = V8XPerpDemoAdapter(runtime_root=runtime_root)
    with adapter.locked():
        report = adapter.preflight()
        key, secret, passphrase = adapter._credentials()
        reconciliations = 0

        def reconcile() -> None:
            nonlocal reconciliations
            adapter.startup_recovery(report.instrument)
            reconciliations += 1

        stream = PrivateStreamSupervisor(
            api_key=key,
            secret=secret,
            passphrase=passphrase,
            instrument_id=report.instrument.inst_id,
            reconcile=reconcile,
        )
        stop = asyncio.Event()
        task = asyncio.create_task(stream.run(stop))
        try:
            await _wait_healthy(stream)
            initial = stream.state
            await stream.force_disconnect()
            blocked = False
            try:
                stream.assert_healthy()
            except SafetyError:
                blocked = True
            await _wait_healthy(stream, after_reconnects=initial.reconnects)
            adapter.startup_recovery(report.instrument)
            final = _final_state(adapter, report.instrument.inst_id)
            if not blocked or final != {
                "position": "0",
                "v8_open_orders": 0,
                "all_futures_open_orders": 0,
            }:
                raise SafetyError("flat reconnect exercise did not finish blocked/reconciled/flat")
            payload = {
                "exercise": "authenticated_flat_reconnect",
                "environment": "okx_demo",
                "instrument": report.instrument.inst_id,
                "initial_subscribed": initial.subscribed,
                "blocked_after_forced_disconnect": blocked,
                "reconnects": stream.state.reconnects,
                "rest_reconciliations": reconciliations + 1,
                "final": final,
                "continuous_mode": "disabled",
            }
            return _write_evidence(evidence_root, "flat_reconnect", payload)
        finally:
            await _stop_stream(stream, stop, task)


async def open_position_reconnect(runtime_root: Path, evidence_root: Path) -> Path:
    adapter = V8XPerpDemoAdapter(runtime_root=runtime_root)
    opening_id: str | None = None
    opening_counts: dict[str, int] = {}
    with adapter.locked():
        report = adapter.preflight()
        key, secret, passphrase = adapter._credentials()

        def reconcile() -> None:
            adapter.startup_recovery(report.instrument)

        stream = PrivateStreamSupervisor(
            api_key=key,
            secret=secret,
            passphrase=passphrase,
            instrument_id=report.instrument.inst_id,
            reconcile=reconcile,
        )
        stop = asyncio.Event()
        task = asyncio.create_task(stream.run(stop))
        try:
            await _wait_healthy(stream)
            opening_id, _ = adapter.place_minimum(report, side="buy", reduce_only=False)
            opening_counts = await _wait_counts(adapter, report.instrument.inst_id, opening_id)
            position_before = adapter._position(report.instrument)
            initial_reconnects = stream.state.reconnects
            await stream.force_disconnect()
            blocked = False
            try:
                stream.assert_healthy()
            except SafetyError:
                blocked = True
            await _wait_healthy(stream, after_reconnects=initial_reconnects)
            recovery = adapter.startup_recovery(report.instrument)
            position_after = adapter._position(report.instrument)
            counts_after = await _wait_counts(adapter, report.instrument.inst_id, opening_id)
            if counts_after != opening_counts or opening_counts != {"accepted_orders": 1, "fills": 1}:
                raise SafetyError("open-position reconnect detected duplicate opening exposure")
            adapter.place_minimum(report, side="sell", reduce_only=True)
            final = _final_state(adapter, report.instrument.inst_id)
            if not blocked or position_before == 0 or position_after != position_before:
                raise SafetyError("open-position reconnect adoption invariant failed")
            if final["position"] != "0" or final["all_futures_open_orders"] != 0:
                raise SafetyError("open-position reconnect did not restore a flat account")
            payload = {
                "exercise": "authenticated_open_position_reconnect",
                "environment": "okx_demo",
                "instrument": report.instrument.inst_id,
                "opening_client_id_suffix": opening_id[-8:],
                "opening_submission_count": opening_counts["accepted_orders"],
                "opening_fill_count": opening_counts["fills"],
                "position_before_disconnect": str(position_before),
                "blocked_after_forced_disconnect": blocked,
                "position_after_reconnect": str(position_after),
                "startup_recovery": recovery,
                "counts_after_reconnect": counts_after,
                "final": final,
                "continuous_mode": "disabled",
            }
            return _write_evidence(evidence_root, "open_position_reconnect", payload)
        finally:
            await _stop_stream(stream, stop, task)
            if opening_id and adapter._position(report.instrument) != 0:
                adapter._startup_recovered = True
                side = "sell" if adapter._position(report.instrument) > 0 else "buy"
                adapter.place_minimum(report, side=side, reduce_only=True)


def _restart_open_worker(runtime_root: Path) -> None:
    """Exit without unwinding after acceptance, leaving SUBMITTING durable."""
    adapter = V8XPerpDemoAdapter(runtime_root=runtime_root)
    stage = runtime_root / "restart_stage1.json"
    with adapter.locked():
        report = adapter.preflight()
        intent = adapter._create_intent(
            instrument=report.instrument,
            action="buy-open-restart-exercise",
            target="long",
            side="buy",
            contracts=report.instrument.min_sz,
            reduce_only=False,
            order_type="market",
        )
        _write_json(
            stage,
            {
                "pid": os.getpid(),
                "submission_attempts": 1,
                "client_id_suffix": intent.client_order_id[-8:],
                "position_before_termination": "unknown",
                "accepted_orders": 0,
                "fills": 0,
            },
        )

        def crash_after_response(_response: dict[str, Any]) -> None:
            deadline = time.monotonic() + 15
            counts = {"accepted_orders": 0, "fills": 0}
            position = _decimal("0")
            while time.monotonic() < deadline:
                counts = _counts(adapter, report.instrument.inst_id, intent.client_order_id)
                position = adapter._position(report.instrument)
                if counts == {"accepted_orders": 1, "fills": 1} and position != 0:
                    break
                time.sleep(0.25)
            _write_json(
                stage,
                {
                    "pid": os.getpid(),
                    "submission_attempts": 1,
                    "client_id_suffix": intent.client_order_id[-8:],
                    "position_before_termination": str(position),
                    **counts,
                },
            )
            os._exit(91)

        adapter._intent_execution().submit_order(
            intent,
            before_position=_decimal("0"),
            after_response=crash_after_response,
        )


def _restart_adopt_worker(runtime_root: Path) -> None:
    adapter = V8XPerpDemoAdapter(runtime_root=runtime_root)
    stage = runtime_root / "restart_stage2.json"
    instrument = adapter._discover()
    with adapter.locked():
        recovery = adapter.startup_recovery(instrument)
        position_after = adapter._position(instrument)
        intents = IntentLedger(adapter.intent_path).load()
        opening = next(item for item in intents if item.action == "buy-open-restart-exercise")
        counts = _counts(adapter, instrument.inst_id, opening.client_order_id)
        if counts != {"accepted_orders": 1, "fills": 1} or position_after == 0:
            raise SafetyError("restart adoption did not prove exactly one opening order and fill")
        report = type("RecoveryReport", (), {"instrument": instrument})()
        adapter.place_minimum(report, side="sell", reduce_only=True)
        final = _final_state(adapter, instrument.inst_id)
        if final["position"] != "0" or final["all_futures_open_orders"] != 0:
            raise SafetyError("restart adoption did not restore a flat account")
        _write_json(
            stage,
            {
                "pid": os.getpid(),
                "startup_recovery": recovery,
                "client_id_suffix": opening.client_order_id[-8:],
                "opening_submission_count_after_restart": counts["accepted_orders"],
                "opening_fill_count_after_restart": counts["fills"],
                "position_after_restart": str(position_after),
                "final": final,
            },
        )


def process_restart_adoption(runtime_root: Path, evidence_root: Path) -> Path:
    script = Path(__file__).resolve()
    common = [sys.executable, str(script), "--runtime-root", str(runtime_root)]
    first = subprocess.Popen(
        [*common, "_restart-open-worker"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first_stdout, first_stderr = first.communicate(timeout=60)
    first_ended = first.poll() is not None
    second = subprocess.Popen(
        [*common, "_restart-adopt-worker"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second_stdout, second_stderr = second.communicate(timeout=60)
    second_ended = second.poll() is not None
    if first.returncode != 91 or second.returncode != 0:
        raise SafetyError(
            "process-restart worker failed; "
            f"first={first.returncode}:{first_stderr[-300:]}, "
            f"second={second.returncode}:{second_stderr[-300:]}"
        )
    stage1 = json.loads((runtime_root / "restart_stage1.json").read_text(encoding="utf-8"))
    stage2 = json.loads((runtime_root / "restart_stage2.json").read_text(encoding="utf-8"))
    payload = {
        "exercise": "authenticated_process_restart_adoption",
        "environment": "okx_demo",
        "submission_count": stage1["submission_attempts"],
        "accepted_opening_orders": stage2["opening_submission_count_after_restart"],
        "opening_fill_count": stage2["opening_fill_count_after_restart"],
        "client_id_suffix": stage1["client_id_suffix"],
        "position_before_termination": stage1["position_before_termination"],
        "position_after_restart": stage2["position_after_restart"],
        "startup_recovery": stage2["startup_recovery"],
        "final": stage2["final"],
        "first_executor_exit_code": first.returncode,
        "first_executor_ended": first_ended,
        "second_executor_exit_code": second.returncode,
        "second_executor_ended": second_ended,
        "executor_processes_remaining": 0 if first_ended and second_ended else 1,
        "worker_stdout_sanitized": {
            "first_lines": len(first_stdout.splitlines()),
            "second_lines": len(second_stdout.splitlines()),
        },
        "continuous_mode": "disabled",
    }
    return _write_evidence(evidence_root, "process_restart_adoption", payload)


def final_status(runtime_root: Path, evidence_root: Path) -> Path:
    adapter = V8XPerpDemoAdapter(runtime_root=runtime_root)
    with adapter.locked():
        instrument = adapter._discover()
        recovery = adapter.startup_recovery(instrument)
        final = _final_state(adapter, instrument.inst_id)
        if final["position"] != "0" or final["all_futures_open_orders"] != 0:
            raise SafetyError("final authenticated account reconciliation is not flat")
        payload = {
            "exercise": "final_authenticated_account_reconciliation",
            "environment": "okx_demo",
            "instrument": instrument.inst_id,
            "exclusive_lock_acquired": True,
            "startup_recovery": recovery,
            "final": final,
            "continuous_mode": "disabled",
        }
    payload["exclusive_lock_released"] = True
    return _write_evidence(evidence_root, "final_account", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "exercise",
        choices=[
            "flat-reconnect",
            "open-position-reconnect",
            "process-restart-adoption",
            "final-status",
            "_restart-open-worker",
            "_restart-adopt-worker",
        ],
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("data/runtime/v8_xperp_recovery"),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("artifacts/v8_xperp_recovery"),
    )
    args = parser.parse_args()
    if args.exercise == "_restart-open-worker":
        _restart_open_worker(args.runtime_root)
        return 0
    if args.exercise == "_restart-adopt-worker":
        _restart_adopt_worker(args.runtime_root)
        return 0
    if args.exercise == "process-restart-adoption":
        path = process_restart_adoption(args.runtime_root, args.evidence_root)
    elif args.exercise == "final-status":
        path = final_status(args.runtime_root, args.evidence_root)
    else:
        function = flat_reconnect if args.exercise == "flat-reconnect" else open_position_reconnect
        path = asyncio.run(function(args.runtime_root, args.evidence_root))
    print(json.dumps({"status": "PASS", "artifact": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyError as exc:
        print(f"BLOCKED: {exc}")
        raise SystemExit(2)
