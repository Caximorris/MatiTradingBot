"""Fail-closed Telegram operations for the isolated V7 OKX Demo candidate.

This module deliberately exposes no activation command.  Activation stays in the
reviewed VM cutover runbook; Telegram may only inspect the candidate and apply
the already hash-chained pause, resume, and deactivate transitions.
"""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path
from typing import Any

from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import PaperSafetyError, make_config
from core.v7_operations import atomic_json
from tools.v6_v7_demo_cutover import v7_transition
from tools.v7_certified_demo_service import LinuxSystemdGateway, SERVICE_NAME


ROOT = Path(__file__).resolve().parents[1]
_CONFIRM_PREFIX_LENGTH = 12


def _read_record(path: Path, *, required: bool = False) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        if required:
            raise PaperSafetyError(f"required V7 record unavailable: {path.name}")
        return None
    if not isinstance(value, dict):
        if required:
            raise PaperSafetyError(f"required V7 record is invalid: {path.name}")
        return None
    return value


def control_dir(root: Path = ROOT) -> Path:
    return root / "data" / "runtime" / "v7_certified" / "control"


def control_path(name: str, root: Path = ROOT) -> Path:
    return control_dir(root) / f"{name}.json"


def _latest_report(config) -> dict[str, Any] | None:
    reports = sorted(config.report_path.glob("*.json"), key=lambda path: path.name)
    return _read_record(reports[-1]) if reports else None


def status(root: Path = ROOT, *, gateway: LinuxSystemdGateway | None = None) -> dict[str, Any]:
    """Read the isolated candidate state without constructing an exchange client."""
    config = make_config(root)
    config.validate()
    service = (gateway or LinuxSystemdGateway()).inspect(SERVICE_NAME)
    wallet = _read_record(config.wallet_path)
    activation = _read_record(control_path("activation", root))
    transition = next(
        (
            record for record in (
                _read_record(control_path(name, root))
                for name in ("deactivate", "resume", "pause")
            )
            if record is not None
        ),
        None,
    )
    owner = DemoAccountLease(
        root / "data" / "runtime" / "v7_certified" / "account_ownership.jsonl"
    ).current()
    report = _latest_report(config)
    return {
        "service": service,
        "activation": activation,
        "latest_transition": transition,
        "lease": None if owner is None else {
            "strategy": owner.get("owner_strategy_id"),
            "instance": owner.get("owner_instance_id"),
        },
        "wallet": None if wallet is None else {
            key: wallet.get(key) for key in (
                "cash", "btc", "locked", "lock_reason", "lock_timestamp", "pending",
                "journal_sequence",
            )
        },
        "latest_report": None if report is None else {
            key: report.get(key) for key in (
                "generated_at", "paper_vs_replay_parity_verdict", "circuit_breaker_status",
                "daily_orders", "daily_fills",
            )
        },
    }


def format_status(value: dict[str, Any]) -> str:
    service = value["service"]
    wallet = value["wallet"]
    activation = value["activation"]
    transition = value["latest_transition"]
    report = value["latest_report"]
    lines = ["<b>V7 CERTIFIED — OKX DEMO</b>"]
    lines.append(
        "Servicio: " + ("🟢 activo" if service.get("active") else "🔴 inactivo")
        + ("" if service.get("known") else " (unidad desconocida)")
    )
    if activation:
        lines.append(f"Activation hash: <code>{html.escape(str(activation.get('activation_hash', ''))[:_CONFIRM_PREFIX_LENGTH])}</code>")
    else:
        lines.append("Activation: no disponible (candidato no activado o control no instalado)")
    if transition:
        lines.append(f"Última transición: {html.escape(str(transition.get('action', '?')))}")
    if value["lease"]:
        lease = value["lease"]
        lines.append(f"Lease: {html.escape(str(lease['strategy']))} / {html.escape(str(lease['instance']))}")
    else:
        lines.append("Lease: ausente")
    if wallet is None:
        lines.append("Estado candidato: no iniciado")
    else:
        lines.append(f"Wallet: BTC {html.escape(str(wallet['btc']))} | efectivo {html.escape(str(wallet['cash']))}")
        lines.append("Circuit breaker: " + ("🔴 LOCKED — " + html.escape(str(wallet["lock_reason"])) if wallet["locked"] else "🟢 CLEAR"))
        if wallet["pending"]:
            lines.append("Pendiente: <code>sí</code>")
        lines.append(f"Journal sequence: {html.escape(str(wallet['journal_sequence']))}")
    if report:
        lines.append("Reporte: parity " + html.escape(str(report["paper_vs_replay_parity_verdict"]))
                     + " | breaker " + html.escape(str(report["circuit_breaker_status"])))
    return "\n".join(lines)


def logs(lines: int, *, gateway: LinuxSystemdGateway | None = None) -> str:
    """Return a bounded, service-specific journal tail without shell interpolation."""
    count = max(5, min(lines, 200))
    try:
        completed = subprocess.run(
            ["journalctl", "-u", SERVICE_NAME, "-n", str(count), "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PaperSafetyError("V7 journal is unavailable") from exc
    output = (completed.stdout + completed.stderr).strip()
    if not output:
        return "V7 journal vacío o inaccesible."
    return f"<b>LOGS V7</b> (últimas {count})\n<pre>{html.escape(output[-3500:])}</pre>"


def transition(
    action: str,
    confirmation_prefix: str,
    *,
    root: Path = ROOT,
    gateway: LinuxSystemdGateway | None = None,
) -> dict[str, Any]:
    """Apply one audited lifecycle transition after an operator checks `/v7_status`."""
    activation = _read_record(control_path("activation", root), required=True)
    assert activation is not None
    if action == "pause" and control_path("pause", root).exists():
        raise PaperSafetyError("a V7 pause transition already exists; do not overwrite lifecycle evidence")
    activation_hash = activation.get("activation_hash")
    if not isinstance(activation_hash, str) or confirmation_prefix != activation_hash[:_CONFIRM_PREFIX_LENGTH]:
        raise PaperSafetyError("run /v7_status and supply its exact 12-character activation hash prefix")
    predecessor_name = {"resume": "pause", "deactivate": "resume"}.get(action)
    if action == "deactivate" and not control_path("resume", root).is_file():
        predecessor_name = "pause"
    predecessor = (
        _read_record(control_path(predecessor_name, root), required=True)
        if predecessor_name else None
    )
    predecessor_hash = None if predecessor is None else predecessor.get("transition_hash")
    if predecessor is not None and not isinstance(predecessor_hash, str):
        raise PaperSafetyError("preceding V7 transition hash is invalid")
    linux = gateway or LinuxSystemdGateway()
    lease = DemoAccountLease(root / "data" / "runtime" / "v7_certified" / "account_ownership.jsonl")
    operation = linux.start if action == "resume" else linux.stop
    record = v7_transition(
        action=action,
        activation=activation,
        expected_hash=activation_hash,
        lease=lease,
        service_action=lambda: operation(SERVICE_NAME),
        service_status=lambda: linux.inspect(SERVICE_NAME),
        predecessor=predecessor,
        predecessor_hash=predecessor_hash,
    )
    atomic_json(control_path(action, root), record)
    return record
