from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import PaperSafetyError
from tools.v6_v7_demo_cutover import (
    V6_NAME,
    V7_NAME,
    V7_SERVICE_NAME,
    activate_v7,
    audit_v6,
    canonical_hash,
    create_v7_inactive,
    export_v6_evidence,
    preflight_v7,
    stop_v6,
    v7_transition,
)
from tools.v7_certified_demo_service import CertifiedV7DemoServiceManager


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


class FakeLinux:
    def __init__(self) -> None:
        self.active = False
        self.enabled = False
        self.processes: list[dict[str, str]] = []
        self.calls: list[str] = []

    def inspect(self, _name: str) -> dict[str, object]:
        return {"known": True, "active": self.active, "enabled": self.enabled}

    def install_unit(self, _name: str, _unit: str) -> None:
        self.calls.append("install")

    def daemon_reload(self) -> None:
        self.calls.append("reload")

    def disable(self, _name: str) -> None:
        self.calls.append("disable")

    def start(self, _name: str) -> None:
        self.calls.append("start")
        self.active = True
        self.processes = [{"pid": "7", "instance_id": "v7_certified_paper"}]

    def stop(self, _name: str) -> None:
        self.calls.append("stop")
        self.active = False
        self.processes = []

    def process_identities(self, _name: str) -> list[dict[str, str]]:
        return list(self.processes)

    def health(self, _name: str) -> dict[str, object]:
        return {"healthy": self.active}


def _root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir(parents=True)
    source = Path(__file__).parents[1] / "docs" / "v7_frozen_candidate.json"
    (tmp_path / "docs" / "v7_frozen_candidate.json").write_text(source.read_text())
    return tmp_path


def _account(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "demo_confirmed": True,
        "fingerprint": "fp",
        "cash": "100",
        "btc": "0",
        "target": "0",
        "open_orders": [],
        "positions": [],
        "unsupported_assets": [],
    }
    value.update(changes)
    return value


def _pass_audit() -> dict[str, object]:
    return audit_v6(
        service={"known": True, "active": True},
        v6_config={
            "execution": "okx_demo",
            "mode": "paper",
            "configuration_hash": "cfg",
        },
        local_state={
            "cash": "100",
            "btc": "0",
            "target": "0",
            "instance_id": "v6",
            "replay_available": False,
        },
        journal_rows=[
            {"intent_id": "i", "order_id": "o", "fill_id": "f", "status": "reconciled"}
        ],
        account=_account(),
        lease=None,
        source_commit="sha",
        now=NOW,
    )


def test_complete_mocked_lifecycle(tmp_path: Path):
    root, audit, lease = (
        _root(tmp_path),
        _pass_audit(),
        DemoAccountLease(tmp_path / "lease.jsonl"),
    )
    evidence = export_v6_evidence(
        audit, journal_rows=[], destination=tmp_path / "v6-evidence", now=NOW
    )
    lease.acquire(
        fingerprint="fp",
        owner_strategy_id=V6_NAME,
        owner_instance_id="v6",
        source_commit="sha",
        configuration_hash="cfg",
        now=NOW,
    )
    v6_active = {"value": True}
    stopped = stop_v6(
        audit=audit,
        audit_hash=audit["audit_hash"],
        evidence=evidence,
        instance_id="v6",
        fingerprint="fp",
        lease=lease,
        service_name="matibot-v6-paper.service",
        service_status=lambda: {"active": v6_active["value"]},
        stop_service=lambda: v6_active.update(value=False),
        no_pending_orders=lambda: True,
        now=NOW,
    )
    inactive = create_v7_inactive(
        audit=audit, evidence=evidence, stop_record=stopped, root=root, now=NOW
    )
    linux = FakeLinux()
    manager = CertifiedV7DemoServiceManager(linux)
    assert (
        manager.install_inactive(app_dir="/srv/matibot", run_user="trader")["active"]
        is False
    )
    preflight = preflight_v7(
        fingerprint="fp",
        account=_account(),
        v6_service={"active": False},
        lease=lease,
        root=root,
        inactive=inactive,
        now=NOW,
    )
    v7_active = {"value": False}
    activation = activate_v7(
        preflight=preflight,
        audit=audit,
        evidence=evidence,
        stop_record=stopped,
        inactive=inactive,
        acknowledgements={"fragile", "not_live_ready", "sole_owner"},
        lease=lease,
        root=root,
        start_service=lambda: v7_active.update(value=True),
        service_status=lambda: {"active": v7_active["value"]},
        now=NOW,
    )
    assert (
        lease.current()["owner_strategy_id"] == V7_NAME and activation["active"] is True
    )
    pause = v7_transition(
        action="pause",
        activation=activation,
        expected_hash=activation["activation_hash"],
        lease=lease,
        service_action=lambda: v7_active.update(value=False),
        service_status=lambda: {"active": v7_active["value"]},
        now=NOW,
    )
    resume = v7_transition(
        action="resume",
        activation=activation,
        expected_hash=activation["activation_hash"],
        predecessor=pause,
        predecessor_hash=pause["transition_hash"],
        lease=lease,
        service_action=lambda: v7_active.update(value=True),
        service_status=lambda: {"active": v7_active["value"]},
        now=NOW,
    )
    deactivated = v7_transition(
        action="deactivate",
        activation=activation,
        expected_hash=activation["activation_hash"],
        predecessor=resume,
        predecessor_hash=resume["transition_hash"],
        lease=lease,
        service_action=lambda: v7_active.update(value=False),
        service_status=lambda: {"active": v7_active["value"]},
        now=NOW,
    )
    assert (
        deactivated["active"] is False
        and lease.current() is None
        and V7_SERVICE_NAME.endswith(".service")
    )


@pytest.mark.parametrize(
    "audit",
    [
        audit_v6(
            service={"known": False},
            v6_config={},
            local_state={},
            journal_rows=[],
            account={},
            lease=None,
            source_commit="",
            now=NOW,
        ),
        {"verdict": "BLOCKED", "audit_hash": "bad"},
    ],
)
def test_non_pass_audit_blocks_export_and_stop(
    tmp_path: Path, audit: dict[str, object]
):
    with pytest.raises(PaperSafetyError):
        export_v6_evidence(audit, journal_rows=[], destination=tmp_path, now=NOW)
    with pytest.raises(PaperSafetyError):
        stop_v6(
            audit=audit,
            audit_hash=str(audit.get("audit_hash")),
            evidence={},
            instance_id="v6",
            fingerprint="fp",
            lease=DemoAccountLease(tmp_path / "lease.jsonl"),
            service_name="v6",
            service_status=lambda: {"active": False},
            stop_service=lambda: None,
            no_pending_orders=lambda: True,
            now=NOW,
        )


@pytest.mark.parametrize(
    "account",
    [
        _account(open_orders=[{"id": "pending"}]),
        _account(unsupported_assets=["ETH"]),
        _account(cash="99"),
    ],
)
def test_pending_assets_or_reconciliation_mismatch_block_cutover(
    tmp_path: Path, account: dict[str, object]
):
    audit = audit_v6(
        service={"known": True},
        v6_config={"execution": "okx_demo", "configuration_hash": "cfg"},
        local_state={"cash": "100", "btc": "0", "target": "0"},
        journal_rows=[],
        account=account,
        lease=None,
        source_commit="sha",
        now=NOW,
    )
    assert audit["verdict"] == "FAIL"
    if account.get("open_orders") or account.get("unsupported_assets"):
        with pytest.raises(PaperSafetyError):
            preflight_v7(
                fingerprint="fp",
                account=account,
                v6_service={"active": False},
                lease=DemoAccountLease(tmp_path / "lease"),
                root=_root(tmp_path / "root"),
            )


def test_hash_order_and_dry_run_contracts_are_deterministic(tmp_path: Path):
    audit = _pass_audit()
    evidence = export_v6_evidence(audit, journal_rows=[], destination=tmp_path, now=NOW)
    assert json.dumps(audit, sort_keys=True) == json.dumps(audit, sort_keys=True)
    with pytest.raises(PaperSafetyError):
        stop_v6(
            audit=audit,
            audit_hash="wrong",
            evidence=evidence,
            instance_id="v6",
            fingerprint="fp",
            lease=DemoAccountLease(tmp_path / "lease"),
            service_name="v6",
            service_status=lambda: {"active": False},
            stop_service=lambda: None,
            no_pending_orders=lambda: True,
            now=NOW,
        )
    tampered = {
        "audit_hash": audit["audit_hash"],
        "evidence_hash": evidence["evidence_hash"],
    }
    tampered["cutover_hash"] = canonical_hash(tampered)
    with pytest.raises(PaperSafetyError):
        create_v7_inactive(
            audit=audit,
            evidence={"audit_hash": audit["audit_hash"], "evidence_hash": "wrong"},
            stop_record=tampered,
            root=_root(tmp_path / "root"),
            now=NOW,
        )
