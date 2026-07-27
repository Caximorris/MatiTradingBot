#!/usr/bin/env python
"""Fail-closed, dependency-injected V6-to-V7 OKX Demo cutover CLI.

This file deliberately has no SSH, systemctl, HTTP, or OKX client construction.
Production wrappers must inject those capabilities; the checked-in CLI defaults
to an unavailable service gateway and is therefore safe to exercise locally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.demo_account_lease import DemoAccountLease, DemoLeaseError  # noqa: E402
from core.v7_certified_paper import PaperSafetyError, make_config  # noqa: E402

V6_NAME = "swing_allocator_demo_btc_usdt"
V7_NAME = "swing_cycle_core_v7_certified_okx_demo"


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_no_secrets(value: object) -> None:
    """Reject credential-shaped fixture fields before they can reach output/state."""
    forbidden = (
        "secret",
        "password",
        "passphrase",
        "api_key",
        "private_key",
        "access_token",
    )
    if isinstance(value, dict):
        for key, child in value.items():
            if any(marker in str(key).lower() for marker in forbidden):
                raise PaperSafetyError(
                    "credential-shaped field is not permitted in cutover evidence"
                )
            _assert_no_secrets(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_no_secrets(child)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PaperSafetyError(f"invalid or unavailable JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise PaperSafetyError(f"invalid JSON object: {path}")
    _assert_no_secrets(value)
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise PaperSafetyError(f"journal unavailable: {path}")
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except ValueError as exc:
        raise PaperSafetyError(f"invalid journal: {path}") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise PaperSafetyError("journal contains a non-object row")
    _assert_no_secrets(rows)
    return rows


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _assert_no_secrets(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _verify_hash(record: dict[str, Any], field: str) -> None:
    supplied = record.get(field)
    unsigned = dict(record)
    unsigned.pop(field, None)
    if not isinstance(supplied, str) or supplied != canonical_hash(unsigned):
        raise PaperSafetyError(f"tampered or incomplete {field} record")


def _verify_evidence(evidence: dict[str, Any]) -> None:
    if not isinstance(evidence.get("evidence_hash"), str):
        raise PaperSafetyError("matching exported V6 evidence is required")
    if evidence.get("schema") == "v6-demo-evidence/v1":
        _verify_hash(evidence, "evidence_hash")


def _unique(rows: list[dict[str, Any]], *fields: str) -> bool:
    values = [tuple(str(row.get(field, "")) for field in fields) for row in rows]
    return len(values) == len(set(values))


@dataclass(frozen=True)
class ServiceGateway:
    """Injectable VM/service boundary. The default never mutates a machine."""

    identity: Callable[[str], dict[str, Any]]
    status: Callable[[str], dict[str, Any]]
    stop: Callable[[str], None]
    start: Callable[[str], None]


def unavailable_gateway() -> ServiceGateway:
    def unavailable(_name: str) -> dict[str, Any]:
        return {"known": False, "active": None}

    def mutate(_name: str) -> None:
        raise PaperSafetyError("service gateway was not injected")

    return ServiceGateway(unavailable, unavailable, mutate, mutate)


def audit_v6(
    *,
    service: dict[str, Any],
    v6_config: dict[str, Any],
    local_state: dict[str, Any],
    journal_rows: list[dict[str, Any]],
    account: dict[str, Any],
    lease: dict[str, Any] | None,
    source_commit: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic, read-only V6 audit report from observed state."""
    _assert_no_secrets((service, v6_config, local_state, journal_rows, account, lease))
    reasons: list[str] = []
    if not service.get("known"):
        reasons.append("V6 service identity is unknown")
    if v6_config.get("execution") != "okx_demo" or v6_config.get("mode") not in {
        None,
        "paper",
        "okx_demo",
    }:
        reasons.append("V6 is not confirmed as OKX Demo mode")
    if not account.get("demo_confirmed"):
        reasons.append("OKX Demo endpoint confirmation is missing")
    if not source_commit or not v6_config.get("configuration_hash"):
        reasons.append("V6 source/configuration identity is not recorded")
    if account.get("open_orders"):
        reasons.append("pending OKX Demo orders exist")
    if local_state.get("locked") or local_state.get("state") == "ERROR_LOCKED":
        reasons.append("V6 has an active corruption/circuit-breaker lock")
    if local_state.get("cash") != account.get("cash") or local_state.get(
        "btc"
    ) != account.get("btc"):
        reasons.append("local V6 wallet does not reconcile to OKX Demo")
    if local_state.get("target") != account.get("target"):
        reasons.append("V6 target does not reconcile to current exchange exposure")
    if (
        not _unique(journal_rows, "intent_id")
        or not _unique(journal_rows, "order_id")
        or not _unique(journal_rows, "fill_id")
    ):
        reasons.append("duplicate V6 intent/order/fill identity")
    if any(
        row.get("status") in {"pending", "ambiguous", "unreconciled"}
        for row in journal_rows
    ):
        reasons.append("V6 journal has unresolved pending state")
    if any(
        row.get("event") in {"ERROR_LOCKED", "repeated_exception"}
        for row in journal_rows
    ):
        reasons.append("V6 journal records an unresolved operational incident")
    report = {
        "schema": "v6-demo-audit/v1",
        "strategy": V6_NAME,
        "generated_at": (now or _utc_now()).isoformat(),
        "service": service,
        "source_commit": source_commit,
        "configuration_hash": v6_config.get("configuration_hash"),
        "mode": "okx_demo",
        "account_fingerprint": account.get("fingerprint"),
        "account": account,
        "local_state": local_state,
        "journal_row_count": len(journal_rows),
        "lease": lease,
        "replay_comparison": "UNAVAILABLE"
        if not local_state.get("replay_available")
        else local_state.get("replay_comparison"),
        "reasons": reasons,
        "verdict": "PASS" if not reasons else "FAIL",
    }
    report["audit_hash"] = canonical_hash(report)
    return report


def export_v6_evidence(
    audit: dict[str, Any],
    *,
    journal_rows: list[dict[str, Any]],
    destination: Path,
    daily_reports: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    _verify_hash(audit, "audit_hash")
    if audit.get("verdict") != "PASS":
        raise PaperSafetyError("V6 evidence export requires a PASS audit")
    package = {
        "schema": "v6-demo-evidence/v1",
        "audit": audit,
        "audit_hash": audit["audit_hash"],
        "exported_at": (now or _utc_now()).isoformat(),
        "orders_and_fills": journal_rows,
        "daily_reports": daily_reports or [],
        "known_limitations": [
            "replay may be unavailable when protected inputs are absent"
        ],
    }
    package["evidence_hash"] = canonical_hash(package)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "v6_demo_evidence.json"
    _write_json(path, package)
    return {
        "path": str(path),
        "audit_hash": audit["audit_hash"],
        "evidence_hash": package["evidence_hash"],
    }


def stop_v6(
    *,
    audit: dict[str, Any],
    audit_hash: str,
    evidence: dict[str, Any],
    instance_id: str,
    fingerprint: str,
    lease: DemoAccountLease,
    service_name: str,
    service_status: Callable[[], dict[str, Any]],
    stop_service: Callable[[], None],
    no_pending_orders: Callable[[], bool],
    now: datetime | None = None,
) -> dict[str, Any]:
    _verify_hash(audit, "audit_hash")
    if audit.get("verdict") != "PASS" or audit.get("audit_hash") != audit_hash:
        raise PaperSafetyError("exact PASS audit hash is required")
    _verify_evidence(evidence)
    if evidence.get("audit_hash") != audit_hash:
        raise PaperSafetyError("matching exported V6 evidence is required")
    if audit.get("account_fingerprint") != fingerprint or instance_id != audit.get(
        "local_state", {}
    ).get("instance_id"):
        raise PaperSafetyError("exact V6 instance and account fingerprint are required")
    if not no_pending_orders():
        raise PaperSafetyError("V6 stop refused while an exchange order is pending")
    stop_service()
    stopped = service_status()
    if stopped.get("active") is not False:
        raise PaperSafetyError(
            f"{service_name} stop state is ambiguous; lease remains acquired"
        )
    if not no_pending_orders():
        raise PaperSafetyError("V6 stop produced or left a pending exchange order")
    release = lease.release(
        fingerprint=fingerprint,
        owner_strategy_id=V6_NAME,
        owner_instance_id=instance_id,
        now=now,
    )
    record = {
        "schema": "v6-demo-cutover-stop/v1",
        "audit_hash": audit_hash,
        "evidence_hash": evidence["evidence_hash"],
        "service": service_name,
        "instance_id": instance_id,
        "account_fingerprint": fingerprint,
        "lease_release_hash": release["record_hash"],
        "stopped_at": (now or _utc_now()).isoformat(),
    }
    record["cutover_hash"] = canonical_hash(record)
    return record


def create_v7_inactive(
    *,
    audit: dict[str, Any],
    evidence: dict[str, Any],
    stop_record: dict[str, Any],
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    _verify_hash(audit, "audit_hash")
    _verify_hash(stop_record, "cutover_hash")
    _verify_evidence(evidence)
    if (
        audit.get("verdict") != "PASS"
        or evidence.get("audit_hash") != audit.get("audit_hash")
        or stop_record.get("audit_hash") != audit.get("audit_hash")
    ):
        raise PaperSafetyError(
            "matching V6 audit, evidence, and guarded stop are required"
        )
    config = make_config(root)
    config.validate()
    record = {
        "schema": "v7-demo-inactive/v1",
        "strategy": V7_NAME,
        "instance_id": config.instance_id,
        "active": False,
        "created_at": (now or _utc_now()).isoformat(),
        "audit_hash": audit["audit_hash"],
        "evidence_hash": evidence.get("evidence_hash"),
        "cutover_hash": stop_record["cutover_hash"],
        "candidate_hash": config.candidate_hash,
        "configuration_hash": config.configuration_hash,
        "source_hash": config.source_hash,
    }
    record["inactive_hash"] = canonical_hash(record)
    return record


def preflight_v7(
    *,
    fingerprint: str,
    account: dict[str, Any],
    v6_service: dict[str, Any],
    lease: DemoAccountLease,
    root: Path = ROOT,
    inactive: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = make_config(root)
    config.validate()
    if inactive is not None:
        _verify_hash(inactive, "inactive_hash")
        if (
            inactive.get("active")
            or inactive.get("configuration_hash") != config.configuration_hash
        ):
            raise PaperSafetyError(
                "V7 inactive record does not match the certified candidate"
            )
    if not fingerprint or not account.get("demo_confirmed"):
        raise PaperSafetyError("explicit OKX Demo account confirmation is required")
    if v6_service.get("active") is not False or lease.current() is not None:
        raise PaperSafetyError(
            "V7 refuses activation while an account owner or V6 service remains active"
        )
    allowed_positions = (None, [], [{"btc": account.get("btc", "0")}])
    if (
        account.get("open_orders")
        or account.get("unsupported_assets")
        or account.get("positions") not in allowed_positions
    ):
        raise PaperSafetyError(
            "unsupported assets, positions, or open orders prevent V7 takeover"
        )
    report = {
        "schema": "v7-demo-preflight/v1",
        "verdict": "PASS",
        "checked_at": (now or _utc_now()).isoformat(),
        "account_fingerprint": fingerprint,
        "account": account,
        "candidate_hash": config.candidate_hash,
        "configuration_hash": config.configuration_hash,
        "source_hash": config.source_hash,
        "inactive_hash": inactive.get("inactive_hash") if inactive else None,
    }
    report["preflight_hash"] = canonical_hash(report)
    return report


def activate_v7(
    *,
    preflight: dict[str, Any],
    audit: dict[str, Any],
    evidence: dict[str, Any],
    stop_record: dict[str, Any],
    acknowledgements: set[str],
    lease: DemoAccountLease,
    root: Path = ROOT,
    inactive: dict[str, Any] | None = None,
    start_service: Callable[[], None] | None = None,
    service_status: Callable[[], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    required = {"fragile", "not_live_ready", "sole_owner"}
    _verify_hash(audit, "audit_hash")
    _verify_hash(stop_record, "cutover_hash")
    _verify_hash(preflight, "preflight_hash")
    if acknowledgements != required:
        raise PaperSafetyError(
            "all fragile/not-live-ready/sole-owner acknowledgements are required"
        )
    _verify_evidence(evidence)
    if (
        audit.get("verdict") != "PASS"
        or evidence.get("audit_hash") != audit.get("audit_hash")
        or stop_record.get("audit_hash") != audit.get("audit_hash")
    ):
        raise PaperSafetyError(
            "matching V6 PASS audit, evidence, and stop proof are required"
        )
    config = make_config(root)
    if inactive is not None:
        _verify_hash(inactive, "inactive_hash")
        if inactive.get("audit_hash") != audit.get("audit_hash"):
            raise PaperSafetyError("V7 inactive record is not chained to this V6 audit")
        if preflight.get("inactive_hash") != inactive.get("inactive_hash"):
            raise PaperSafetyError(
                "V7 preflight is not chained to this inactive record"
            )
    if (
        preflight.get("verdict") != "PASS"
        or preflight.get("candidate_hash") != config.candidate_hash
        or preflight.get("configuration_hash") != config.configuration_hash
    ):
        raise PaperSafetyError("V7 preflight/hash mismatch")
    started = now or _utc_now()
    lease_record = lease.acquire(
        fingerprint=preflight["account_fingerprint"],
        owner_strategy_id=V7_NAME,
        owner_instance_id=config.instance_id,
        source_commit=config.source_hash,
        configuration_hash=config.configuration_hash,
        now=started,
    )
    if start_service is not None:
        start_service()
        if service_status is None or service_status().get("active") is not True:
            raise PaperSafetyError(
                "V7 start state is ambiguous; lease remains acquired"
            )
    manifest = {
        "schema": "v7-demo-activation/v1",
        "strategy": V7_NAME,
        "instance_id": config.instance_id,
        "started_at": started.isoformat(),
        "ends_at": (started + timedelta(days=30)).isoformat(),
        "account_fingerprint": preflight["account_fingerprint"],
        "activation_baseline": preflight["account"],
        "prior_v6_performance_excluded": True,
        "candidate_hash": config.candidate_hash,
        "configuration_hash": config.configuration_hash,
        "source_hash": config.source_hash,
        "audit_hash": audit["audit_hash"],
        "evidence_hash": evidence.get("evidence_hash"),
        "cutover_hash": stop_record["cutover_hash"],
        "preflight_hash": preflight["preflight_hash"],
        "inactive_hash": inactive.get("inactive_hash") if inactive else None,
        "lease_hash": lease_record["record_hash"],
        "active": True,
        "paused": False,
    }
    manifest["activation_hash"] = canonical_hash(manifest)
    return manifest


def v7_transition(
    *,
    action: str,
    activation: dict[str, Any],
    expected_hash: str,
    lease: DemoAccountLease,
    service_action: Callable[[], None],
    service_status: Callable[[], dict[str, Any]],
    predecessor: dict[str, Any] | None = None,
    predecessor_hash: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply a reversible V7 lifecycle transition with exact predecessor binding."""
    if action not in {"pause", "resume", "deactivate"}:
        raise ValueError("unsupported V7 transition")
    _verify_hash(activation, "activation_hash")
    if expected_hash != activation.get("activation_hash"):
        raise PaperSafetyError("exact activation hash is required")
    if action == "pause" and predecessor is not None:
        raise PaperSafetyError(
            "pause begins from the activation record, not an older transition"
        )
    if action in {"resume", "deactivate"}:
        if predecessor is None or predecessor_hash is None:
            raise PaperSafetyError(
                f"{action} requires the exact preceding V7 transition hash"
            )
        _verify_hash(predecessor, "transition_hash")
        if predecessor.get("transition_hash") != predecessor_hash:
            raise PaperSafetyError("exact preceding V7 transition hash is required")
        if predecessor.get("activation_hash") != expected_hash:
            raise PaperSafetyError(
                "preceding V7 transition is not chained to this activation"
            )
        if action == "resume" and predecessor.get("action") != "pause":
            raise PaperSafetyError("resume requires a preceding pause transition")
        if action == "deactivate" and predecessor.get("action") not in {
            "pause",
            "resume",
        }:
            raise PaperSafetyError(
                "deactivate requires a preceding pause or resume transition"
            )
    current = lease.current()
    if (
        current is None
        or current.get("owner_strategy_id") != V7_NAME
        or current.get("owner_instance_id") != activation.get("instance_id")
    ):
        raise PaperSafetyError("V7 lease ownership is absent or ambiguous")
    service_action()
    status = service_status()
    required_active = action == "resume"
    if status.get("active") is not required_active:
        raise PaperSafetyError("V7 service transition state is ambiguous")
    record = {
        "schema": "v7-demo-transition/v1",
        "action": action,
        "activation_hash": expected_hash,
        "predecessor_hash": predecessor_hash,
        "instance_id": activation["instance_id"],
        "account_fingerprint": activation["account_fingerprint"],
        "at": (now or _utc_now()).isoformat(),
        "active": required_active,
        "paused": action == "pause",
    }
    if action == "deactivate":
        released = lease.release(
            fingerprint=activation["account_fingerprint"],
            owner_strategy_id=V7_NAME,
            owner_instance_id=activation["instance_id"],
            now=now,
        )
        record["lease_release_hash"] = released["record_hash"]
    record["transition_hash"] = canonical_hash(record)
    return record


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _planned(command: str, **values: Any) -> dict[str, Any]:
    return {"command": command, "dry_run": True, "mutation": "not_applied", **values}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "audit-v6",
            "show-audit",
            "export-v6-evidence",
            "stop-v6",
            "create-v7-inactive",
            "preflight-v7",
            "activate-v7",
            "status",
            "pause-v7",
            "resume-v7",
            "deactivate-v7",
        ),
    )
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--audit-hash")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--stop-record", type=Path)
    parser.add_argument("--inactive", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--activation", type=Path)
    parser.add_argument("--activation-hash")
    parser.add_argument("--transition", type=Path)
    parser.add_argument("--transition-hash")
    parser.add_argument("--v6-config", type=Path)
    parser.add_argument("--v6-state", type=Path)
    parser.add_argument("--v6-journal", type=Path)
    parser.add_argument("--account", type=Path)
    parser.add_argument("--account-fingerprint")
    parser.add_argument("--instance-id")
    parser.add_argument("--lease", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ack-fragile", action="store_true")
    parser.add_argument("--ack-not-live-ready", action="store_true")
    parser.add_argument("--ack-sole-owner", action="store_true")
    return parser


def _required(args: argparse.Namespace, *names: str) -> None:
    missing = [
        f"--{name.replace('_', '-')}"
        for name in names
        if getattr(args, name) is None or getattr(args, name) == ""
    ]
    if missing:
        raise PaperSafetyError(f"{args.command} requires {', '.join(missing)}")


def run(
    argv: Sequence[str] | None = None,
    *,
    gateway: ServiceGateway | None = None,
    now: datetime | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    gateway = gateway or unavailable_gateway()
    lease = DemoAccountLease(args.lease)
    try:
        if args.command == "audit-v6":
            _required(
                args,
                "v6_config",
                "v6_state",
                "v6_journal",
                "account",
                "account_fingerprint",
            )
            account = _read_json(args.account)
            account["fingerprint"] = args.account_fingerprint
            report = audit_v6(
                service=gateway.identity("matibot-v6-paper.service"),
                v6_config=_read_json(args.v6_config),
                local_state=_read_json(args.v6_state),
                journal_rows=_read_jsonl(args.v6_journal),
                account=account,
                lease=lease.current(),
                source_commit=_read_json(args.v6_config).get("source_commit", ""),
                now=now,
            )
            _emit(report)
            return 0 if report["verdict"] == "PASS" else 1
        if args.command == "show-audit":
            _required(args, "audit")
            audit = _read_json(args.audit)
            _verify_hash(audit, "audit_hash")
            _emit(audit)
            return 0 if audit.get("verdict") == "PASS" else 1
        if args.command == "export-v6-evidence":
            _required(args, "audit", "v6_journal", "output")
            audit = _read_json(args.audit)
            _verify_hash(audit, "audit_hash")
            if args.dry_run:
                _emit(
                    _planned(
                        args.command,
                        audit_hash=audit["audit_hash"],
                        output=str(args.output),
                    )
                )
                return 0
            _emit(
                export_v6_evidence(
                    audit,
                    journal_rows=_read_jsonl(args.v6_journal),
                    destination=args.output,
                    now=now,
                )
            )
            return 0
        if args.command == "stop-v6":
            _required(
                args,
                "audit",
                "audit_hash",
                "evidence",
                "instance_id",
                "account_fingerprint",
                "output",
            )
            audit, evidence = _read_json(args.audit), _read_json(args.evidence)
            if args.dry_run:
                _emit(
                    _planned(
                        args.command,
                        audit_hash=args.audit_hash,
                        output=str(args.output),
                    )
                )
                return 0
            account = audit.get("account", {})
            record = stop_v6(
                audit=audit,
                audit_hash=args.audit_hash,
                evidence=evidence,
                instance_id=args.instance_id,
                fingerprint=args.account_fingerprint,
                lease=lease,
                service_name="matibot-v6-paper.service",
                service_status=lambda: gateway.status("matibot-v6-paper.service"),
                stop_service=lambda: gateway.stop("matibot-v6-paper.service"),
                no_pending_orders=lambda: not bool(account.get("open_orders")),
                now=now,
            )
            _write_json(args.output, record)
            _emit(record)
            return 0
        if args.command == "create-v7-inactive":
            _required(args, "audit", "evidence", "stop_record", "output")
            audit, evidence, stop = (
                _read_json(args.audit),
                _read_json(args.evidence),
                _read_json(args.stop_record),
            )
            record = create_v7_inactive(
                audit=audit,
                evidence=evidence,
                stop_record=stop,
                root=args.root,
                now=now,
            )
            if args.dry_run:
                _emit(
                    _planned(
                        args.command,
                        inactive_hash=record["inactive_hash"],
                        output=str(args.output),
                    )
                )
                return 0
            _write_json(args.output, record)
            _emit(record)
            return 0
        if args.command == "preflight-v7":
            _required(args, "account", "account_fingerprint")
            inactive = _read_json(args.inactive) if args.inactive else None
            report = preflight_v7(
                fingerprint=args.account_fingerprint,
                account=_read_json(args.account),
                v6_service=gateway.status("matibot-v6-paper.service"),
                lease=lease,
                root=args.root,
                inactive=inactive,
                now=now,
            )
            _emit(report)
            return 0
        if args.command == "activate-v7":
            _required(
                args,
                "audit",
                "evidence",
                "stop_record",
                "preflight",
                "inactive",
                "output",
            )
            audit, evidence, stop, preflight, inactive = (
                _read_json(args.audit),
                _read_json(args.evidence),
                _read_json(args.stop_record),
                _read_json(args.preflight),
                _read_json(args.inactive),
            )
            if args.dry_run:
                _emit(
                    _planned(
                        args.command,
                        preflight_hash=preflight.get("preflight_hash"),
                        output=str(args.output),
                    )
                )
                return 0
            manifest = activate_v7(
                preflight=preflight,
                audit=audit,
                evidence=evidence,
                stop_record=stop,
                inactive=inactive,
                acknowledgements={
                    name
                    for name, enabled in (
                        ("fragile", args.ack_fragile),
                        ("not_live_ready", args.ack_not_live_ready),
                        ("sole_owner", args.ack_sole_owner),
                    )
                    if enabled
                },
                lease=lease,
                root=args.root,
                start_service=lambda: gateway.start("matibot-v7-paper.service"),
                service_status=lambda: gateway.status("matibot-v7-paper.service"),
                now=now,
            )
            _write_json(args.output, manifest)
            _emit(manifest)
            return 0
        if args.command == "status":
            status = {
                "schema": "v7-demo-status/v1",
                "v6_service": gateway.status("matibot-v6-paper.service"),
                "v7_service": gateway.status("matibot-v7-paper.service"),
                "lease": lease.current(),
            }
            if args.activation:
                status["activation"] = _read_json(args.activation)
            status["status_hash"] = canonical_hash(status)
            _emit(status)
            return 0
        _required(args, "activation", "activation_hash", "output")
        activation = _read_json(args.activation)
        action = args.command.removesuffix("-v7")
        if action in {"resume", "deactivate"}:
            _required(args, "transition", "transition_hash")
        if args.dry_run:
            _emit(
                _planned(
                    args.command,
                    activation_hash=args.activation_hash,
                    output=str(args.output),
                )
            )
            return 0
        operation = gateway.start if action == "resume" else gateway.stop
        record = v7_transition(
            action=action,
            activation=activation,
            expected_hash=args.activation_hash,
            lease=lease,
            service_action=lambda: operation("matibot-v7-paper.service"),
            service_status=lambda: gateway.status("matibot-v7-paper.service"),
            predecessor=_read_json(args.transition) if args.transition else None,
            predecessor_hash=args.transition_hash,
            now=now,
        )
        _write_json(args.output, record)
        _emit(record)
        return 0
    except (PaperSafetyError, DemoLeaseError) as exc:
        _emit({"command": args.command, "error": str(exc), "status": "BLOCKED"})
        return 2


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
