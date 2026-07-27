from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import PaperSafetyError, make_config
from core.v7_okx_demo import V7OKXDemoRunner
from tools.v6_v7_demo_cutover import (
    V6_NAME, activate_v7, audit_v6, export_v6_evidence, preflight_v7, stop_v6,
)


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def _account():
    return {"demo_confirmed": True, "fingerprint": "fp", "cash": "100", "btc": "0", "target": "0",
            "open_orders": [], "positions": [], "unsupported_assets": []}


def _pass_audit():
    return audit_v6(service={"known": True, "active": True}, v6_config={"execution": "okx_demo", "mode": "paper", "configuration_hash": "cfg"},
                    local_state={"cash": "100", "btc": "0", "target": "0", "instance_id": "v6-instance", "replay_available": False},
                    journal_rows=[{"intent_id": "i", "order_id": "o", "fill_id": "f", "status": "reconciled"}],
                    account=_account(), lease=None, source_commit="sha", now=NOW)


def test_audit_pass_fail_and_evidence_export(tmp_path: Path):
    audit = _pass_audit()
    assert audit["verdict"] == "PASS" and audit["replay_comparison"] == "UNAVAILABLE"
    bad = audit_v6(service={"known": False}, v6_config={}, local_state={}, journal_rows=[{"intent_id": "x", "order_id": "x", "fill_id": "x", "status": "pending"}],
                   account={}, lease=None, source_commit="", now=NOW)
    assert bad["verdict"] == "FAIL" and bad["reasons"]
    evidence = export_v6_evidence(audit, journal_rows=[], destination=tmp_path)
    assert Path(evidence["path"]).is_file() and evidence["audit_hash"] == audit["audit_hash"]


def test_stop_requires_pass_hash_evidence_no_pending_and_releases_lease(tmp_path: Path):
    audit = _pass_audit()
    evidence = export_v6_evidence(audit, journal_rows=[], destination=tmp_path / "e")
    lease = DemoAccountLease(tmp_path / "lease.jsonl")
    lease.acquire(fingerprint="fp", owner_strategy_id=V6_NAME, owner_instance_id="v6-instance", source_commit="sha", configuration_hash="cfg", now=NOW)
    calls: list[str] = []
    record = stop_v6(audit=audit, audit_hash=audit["audit_hash"], evidence=evidence, instance_id="v6-instance", fingerprint="fp", lease=lease,
                     service_name="v6.service", service_status=lambda: {"active": False}, stop_service=lambda: calls.append("stop"), no_pending_orders=lambda: True)
    assert calls == ["stop"] and lease.current() is None and record["cutover_hash"]
    with pytest.raises(PaperSafetyError):
        stop_v6(audit=audit, audit_hash="wrong", evidence=evidence, instance_id="v6-instance", fingerprint="fp", lease=lease,
                service_name="v6.service", service_status=lambda: {"active": False}, stop_service=lambda: None, no_pending_orders=lambda: True)


def test_preflight_and_activation_are_exclusive_and_hash_bound(tmp_path: Path):
    root = tmp_path
    (root / "docs").mkdir()
    (root / "docs" / "v7_frozen_candidate.json").write_text((Path(__file__).parents[1] / "docs" / "v7_frozen_candidate.json").read_text())
    audit = _pass_audit()
    evidence = export_v6_evidence(audit, journal_rows=[], destination=tmp_path / "e")
    lease = DemoAccountLease(tmp_path / "lease.jsonl")
    preflight = preflight_v7(fingerprint="fp", account=_account(), v6_service={"active": False}, lease=lease, root=root)
    manifest = activate_v7(preflight=preflight, audit=audit, evidence=evidence, stop_record={"audit_hash": audit["audit_hash"]},
                           acknowledgements={"fragile", "not_live_ready", "sole_owner"}, lease=lease, root=root, now=NOW)
    assert manifest["ends_at"].startswith("2026-08-26") and lease.current()["owner_instance_id"] == make_config(root).instance_id
    with pytest.raises(Exception):
        preflight_v7(fingerprint="fp", account=_account(), v6_service={"active": False}, lease=lease, root=root)


class _DemoClient:
    is_paper = True
    def __init__(self): self.orders = []
    def get_balance(self): return {"USDT": Decimal("100"), "BTC": Decimal("0")}
    def get_open_orders(self, _): return []
    def get_positions(self): return []
    def place_order(self, *_args, **_kwargs): raise AssertionError("not reached")


def test_runner_refuses_non_dedicated_demo_client(tmp_path: Path):
    root = tmp_path
    (root / "docs").mkdir()
    (root / "docs" / "v7_frozen_candidate.json").write_text((Path(__file__).parents[1] / "docs" / "v7_frozen_candidate.json").read_text())
    with pytest.raises(PaperSafetyError, match="dedicated OKX Demo"):
        V7OKXDemoRunner(make_config(root), _DemoClient(), DemoAccountLease(tmp_path / "lease.jsonl"), "fp")  # type: ignore[arg-type]
