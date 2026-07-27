#!/usr/bin/env python
"""Guarded V6-to-V7 cutover for the single shared OKX Demo account.

The module is deliberately usable with fake providers in tests.  Its CLI is the
only operational surface; it never contacts a live endpoint and never derives a
credential fingerprint from secret material.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.demo_account_lease import DemoAccountLease  # noqa: E402
from core.v7_certified_paper import PaperSafetyError, make_config  # noqa: E402

RUNTIME = Path("data") / "runtime" / "v7_certified"
V6_NAME = "swing_allocator_demo_btc_usdt"
V7_NAME = "swing_cycle_core_v7_certified_okx_demo"


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PaperSafetyError(f"invalid JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise PaperSafetyError(f"journal unavailable: {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        raise PaperSafetyError("journal contains a non-object row")
    return rows


def _service_identity(name: str, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    try:
        result = runner(["systemctl", "show", name, "--property=Id,ActiveState,SubState,MainPID", "--no-page"],
                        capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {"known": False, "active": None, "service": name}
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return {"known": result.returncode == 0 and bool(values.get("Id")), "active": values.get("ActiveState") == "active",
            "service": values.get("Id", name), "pid": values.get("MainPID")}


def _unique(rows: list[dict[str, Any]], *fields: str) -> bool:
    values = [tuple(str(row.get(field, "")) for field in fields) for row in rows]
    return len(values) == len(set(values))


def audit_v6(*, service: dict[str, Any], v6_config: dict[str, Any], local_state: dict[str, Any],
             journal_rows: list[dict[str, Any]], account: dict[str, Any], lease: dict[str, Any] | None,
             source_commit: str, now: datetime | None = None) -> dict[str, Any]:
    """Build a deterministic, read-only V6 audit report from observed state."""
    reasons: list[str] = []
    if not service.get("known"):
        reasons.append("V6 service identity is unknown")
    if v6_config.get("execution") != "okx_demo" or v6_config.get("mode") not in {None, "paper", "okx_demo"}:
        reasons.append("V6 is not confirmed as OKX Demo mode")
    if not account.get("demo_confirmed"):
        reasons.append("OKX Demo endpoint confirmation is missing")
    if not source_commit or not v6_config.get("configuration_hash"):
        reasons.append("V6 source/configuration identity is not recorded")
    if account.get("open_orders"):
        reasons.append("pending OKX Demo orders exist")
    if local_state.get("locked") or local_state.get("state") == "ERROR_LOCKED":
        reasons.append("V6 has an active corruption/circuit-breaker lock")
    if local_state.get("cash") != account.get("cash") or local_state.get("btc") != account.get("btc"):
        reasons.append("local V6 wallet does not reconcile to OKX Demo")
    if local_state.get("target") != account.get("target"):
        reasons.append("V6 target does not reconcile to current exchange exposure")
    if not _unique(journal_rows, "intent_id") or not _unique(journal_rows, "order_id") or not _unique(journal_rows, "fill_id"):
        reasons.append("duplicate V6 intent/order/fill identity")
    if any(row.get("status") in {"pending", "ambiguous", "unreconciled"} for row in journal_rows):
        reasons.append("V6 journal has unresolved pending state")
    if any(row.get("event") in {"ERROR_LOCKED", "repeated_exception"} for row in journal_rows):
        reasons.append("V6 journal records an unresolved operational incident")
    report = {"schema": "v6-demo-audit/v1", "strategy": V6_NAME, "generated_at": (now or _utc_now()).isoformat(),
              "service": service, "source_commit": source_commit, "configuration_hash": v6_config.get("configuration_hash"),
              "mode": "okx_demo", "account_fingerprint": account.get("fingerprint"), "account": account,
              "local_state": local_state, "journal_row_count": len(journal_rows), "lease": lease,
              "replay_comparison": "UNAVAILABLE" if not local_state.get("replay_available") else local_state.get("replay_comparison"),
              "reasons": reasons, "verdict": "PASS" if not reasons else "FAIL"}
    report["audit_hash"] = canonical_hash(report)
    return report


def export_v6_evidence(audit: dict[str, Any], *, journal_rows: list[dict[str, Any]], destination: Path,
                       daily_reports: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if audit.get("verdict") != "PASS":
        raise PaperSafetyError("V6 evidence export requires a PASS audit")
    destination.mkdir(parents=True, exist_ok=True)
    package = {"schema": "v6-demo-evidence/v1", "audit": audit, "audit_hash": audit["audit_hash"],
               "exported_at": _utc_now().isoformat(), "orders_and_fills": journal_rows,
               "daily_reports": daily_reports or [], "known_limitations": ["replay may be unavailable when protected inputs are absent"]}
    package["evidence_hash"] = canonical_hash(package)
    path = destination / "v6_demo_evidence.json"
    path.write_text(json.dumps(package, indent=2, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "audit_hash": audit["audit_hash"], "evidence_hash": package["evidence_hash"]}


def stop_v6(*, audit: dict[str, Any], audit_hash: str, evidence: dict[str, Any], instance_id: str,
            fingerprint: str, lease: DemoAccountLease, service_name: str, service_status: Callable[[], dict[str, Any]],
            stop_service: Callable[[], None], no_pending_orders: Callable[[], bool]) -> dict[str, Any]:
    """Only mutating V6 action.  It fails before stopping if any prerequisite is absent."""
    if audit.get("verdict") != "PASS" or audit.get("audit_hash") != audit_hash:
        raise PaperSafetyError("exact PASS audit hash is required")
    if evidence.get("audit_hash") != audit_hash or not evidence.get("evidence_hash"):
        raise PaperSafetyError("matching exported V6 evidence is required")
    if audit.get("account_fingerprint") != fingerprint or instance_id != audit.get("local_state", {}).get("instance_id"):
        raise PaperSafetyError("exact V6 instance and account fingerprint are required")
    if not no_pending_orders():
        raise PaperSafetyError("V6 stop refused while an exchange order is pending")
    stop_service()
    stopped = service_status()
    if stopped.get("active"):
        raise PaperSafetyError(f"{service_name} did not stop; lease remains acquired")
    if not no_pending_orders():
        raise PaperSafetyError("V6 stop produced or left a pending exchange order")
    release = lease.release(fingerprint=fingerprint, owner_strategy_id=V6_NAME, owner_instance_id=instance_id)
    record = {"schema": "v6-demo-cutover-stop/v1", "audit_hash": audit_hash, "evidence_hash": evidence["evidence_hash"],
              "service": service_name, "instance_id": instance_id, "account_fingerprint": fingerprint,
              "lease_release_hash": release["record_hash"], "stopped_at": _utc_now().isoformat()}
    record["cutover_hash"] = canonical_hash(record)
    return record


def preflight_v7(*, fingerprint: str, account: dict[str, Any], v6_service: dict[str, Any], lease: DemoAccountLease,
                 root: Path = ROOT) -> dict[str, Any]:
    config = make_config(root)
    config.validate()
    if not fingerprint or not account.get("demo_confirmed"):
        raise PaperSafetyError("explicit OKX Demo account confirmation is required")
    if v6_service.get("active") or lease.current() is not None:
        raise PaperSafetyError("V7 refuses activation while an account owner or V6 service remains active")
    if account.get("open_orders") or account.get("unsupported_assets") or account.get("positions") not in (None, [], [{"btc": account.get("btc", "0")}]):
        raise PaperSafetyError("unsupported assets, positions, or open orders prevent V7 takeover")
    return {"verdict": "PASS", "account_fingerprint": fingerprint, "account": account,
            "candidate_hash": config.candidate_hash, "configuration_hash": config.configuration_hash,
            "source_hash": config.source_hash}


def activate_v7(*, preflight: dict[str, Any], audit: dict[str, Any], evidence: dict[str, Any], stop_record: dict[str, Any],
                acknowledgements: set[str], lease: DemoAccountLease, root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    required = {"fragile", "not_live_ready", "sole_owner"}
    if acknowledgements != required:
        raise PaperSafetyError("all fragile/not-live-ready/sole-owner acknowledgements are required")
    if audit.get("verdict") != "PASS" or evidence.get("audit_hash") != audit.get("audit_hash") or stop_record.get("audit_hash") != audit.get("audit_hash"):
        raise PaperSafetyError("matching V6 PASS audit, evidence, and stop proof are required")
    config = make_config(root)
    if preflight.get("verdict") != "PASS" or preflight.get("candidate_hash") != config.candidate_hash or preflight.get("configuration_hash") != config.configuration_hash:
        raise PaperSafetyError("V7 preflight/hash mismatch")
    started = now or _utc_now()
    lease_record = lease.acquire(fingerprint=preflight["account_fingerprint"], owner_strategy_id=V7_NAME,
                                 owner_instance_id=config.instance_id, source_commit=config.source_hash,
                                 configuration_hash=config.configuration_hash, now=started)
    manifest = {"schema": "v7-demo-activation/v1", "strategy": V7_NAME, "instance_id": config.instance_id,
                "started_at": started.isoformat(), "ends_at": (started + timedelta(days=30)).isoformat(),
                "account_fingerprint": preflight["account_fingerprint"], "activation_baseline": preflight["account"],
                "prior_v6_performance_excluded": True, "candidate_hash": config.candidate_hash,
                "configuration_hash": config.configuration_hash, "source_hash": config.source_hash,
                "lease_hash": lease_record["record_hash"], "active": True}
    manifest["activation_hash"] = canonical_hash(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit-v6", "export-v6", "stop-v6", "preflight-v7", "activate-v7"))
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--audit-hash")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--v6-config", type=Path)
    parser.add_argument("--v6-state", type=Path)
    parser.add_argument("--v6-journal", type=Path)
    parser.add_argument("--account", type=Path)
    parser.add_argument("--account-fingerprint")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ack-cutover", action="store_true")
    args = parser.parse_args()
    if args.command == "audit-v6":
        if not all((args.v6_config, args.v6_state, args.v6_journal, args.account, args.account_fingerprint)):
            parser.error("audit-v6 requires explicit V6 config/state/journal/account files and account fingerprint")
        account = _read_json(args.account)
        account["fingerprint"] = args.account_fingerprint
        report = audit_v6(service=_service_identity("matibot-v6-paper.service"), v6_config=_read_json(args.v6_config),
                          local_state=_read_json(args.v6_state), journal_rows=_read_jsonl(args.v6_journal), account=account,
                          lease=DemoAccountLease(RUNTIME / "account_ownership.jsonl").current(), source_commit=_git_sha())
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    raise SystemExit("mutating commands require the reviewed VM-only operator procedure in the runbook")


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
