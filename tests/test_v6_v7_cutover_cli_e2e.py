from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from tools import v6_runtime_observation as observation
from tools import v6_v7_demo_cutover as cutover
from tools.v6_v7_demo_cutover import ServiceGateway
from core.demo_account_lease import DemoAccountLease
from tools.v7_certified_demo_service import run as service_run


NOW = datetime(2026, 7, 27, 6, tzinfo=timezone.utc)


class _V6:
    def inspect(self, _name):
        return {"known": True, "active": True}

    def process_identities(self, _name):
        return [{"pid": "1", "instance_id": "v6"}]


class _OKX:
    is_paper = True
    endpoint = "okx_demo"
    account_id = "fake"

    def get_balance(self): return {"USDT": Decimal("100"), "BTC": Decimal("0")}
    def get_positions(self): return []
    def get_open_orders(self, _): return []
    def get_order_history(self, _, limit=20): return []
    def get_fills(self, _, limit=20): return []
    def get_instrument(self, _): return {"tickSz": "0.1", "lotSz": "0.0001", "minSz": "0.0001"}
    def get_position_mode(self): return {"position_mode": "net_mode"}
    def get_fee_metadata(self, _): return {"maker": "-0.001", "taker": "-0.001"}


def test_full_v6_cli_artifact_chain_is_parser_driven_and_secret_free(tmp_path: Path):
    config = tmp_path / "config.json"
    state = tmp_path / "state.json"
    journal = tmp_path / "journal.jsonl"
    config.write_text(json.dumps({"strategy": cutover.V6_NAME, "instance_id": "v6", "execution": "okx_demo", "mode": "paper", "configuration_hash": "cfg"}))
    state.write_text(json.dumps({"instance_id": "v6", "cash": "100", "btc": "0", "target": "0", "last_completed_candle": "x", "data_fresh": True}))
    journal.write_text('{"intent_id":"i","order_id":"o","fill_id":"f","status":"reconciled"}\n')
    runtime, account, bundle, audit = (tmp_path / "runtime.json", tmp_path / "account.json", tmp_path / "bundle", tmp_path / "audit.json")
    assert observation.run(["collect-v6-runtime", "--config-path", str(config), "--state-path", str(state), "--journal-path", str(journal), "--repository-path", "/srv/matibot", "--source-commit", "sha", "--output", str(runtime)], service=_V6()) == 0
    assert observation.run(["observe-okx-demo-account", "--output", str(account)], client=_OKX()) == 0
    assert observation.run(["build-v6-audit-inputs", "--runtime-observation", str(runtime), "--account-observation", str(account), "--output", str(bundle)]) == 0
    active = {"value": True}
    gateway = ServiceGateway(identity=lambda _: {"known": True, "active": active["value"]}, status=lambda _: {"known": True, "active": active["value"]}, stop=lambda _: active.update(value=False), start=lambda _: active.update(value=True))
    args = ["audit-v6", "--lease", str(tmp_path / "lease.jsonl"), "--manifest", str(bundle / "manifest.json"), "--v6-config", str(bundle / "v6-config.json"), "--v6-state", str(bundle / "v6-state.json"), "--v6-journal", str(journal), "--account", str(bundle / "account-observation.json"), "--account-fingerprint", json.loads(account.read_text())["fingerprint"], "--output", str(audit)]
    assert cutover.run(args, gateway=gateway, now=NOW) == 0
    assert cutover.run(["show-audit", "--lease", str(tmp_path / "lease.jsonl"), "--audit", str(audit)], gateway=gateway) == 0
    evidence = tmp_path / "evidence"
    assert cutover.run(["export-v6-evidence", "--lease", str(tmp_path / "lease.jsonl"), "--audit", str(audit), "--v6-journal", str(journal), "--output", str(evidence)], gateway=gateway, now=NOW) == 0
    lease = DemoAccountLease(tmp_path / "lease.jsonl")
    lease.acquire(fingerprint=json.loads(account.read_text())["fingerprint"], owner_strategy_id=cutover.V6_NAME, owner_instance_id="v6", source_commit="sha", configuration_hash="cfg", now=NOW)
    stopped = tmp_path / "stopped.json"
    assert cutover.run(["stop-v6", "--lease", str(tmp_path / "lease.jsonl"), "--audit", str(audit), "--audit-hash", json.loads(audit.read_text())["audit_hash"], "--evidence", str(evidence / "v6_demo_evidence.json"), "--instance-id", "v6", "--account-fingerprint", json.loads(account.read_text())["fingerprint"], "--output", str(stopped)], gateway=gateway, now=NOW) == 0
    assert active["value"] is False and lease.current() is None
    called = []
    assert service_run(["--run"], service_factory=lambda parsed: called.append(parsed.run)) == 0
    assert called == [True]
    assert json.loads(audit.read_text())["verdict"] == "PASS"
    assert all("secret" not in path.read_text().lower() for path in tmp_path.rglob("*.json"))
