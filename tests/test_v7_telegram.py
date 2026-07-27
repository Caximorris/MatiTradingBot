from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import PaperSafetyError, make_config
from tools.v6_v7_demo_cutover import V7_NAME, canonical_hash
from tools.v7_telegram import control_path, format_status, status, transition


class _Gateway:
    def __init__(self, active: bool = True) -> None:
        self.active = active

    def inspect(self, _name: str) -> dict[str, bool]:
        return {"known": True, "enabled": False, "active": self.active}

    def stop(self, _name: str) -> None:
        self.active = False

    def start(self, _name: str) -> None:
        self.active = True


def _root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    source = Path(__file__).parents[1] / "docs" / "v7_frozen_candidate.json"
    (tmp_path / "docs" / "v7_frozen_candidate.json").write_text(source.read_text())
    return tmp_path


def _activation(root: Path) -> dict:
    config = make_config(root)
    lease = DemoAccountLease(root / "data" / "runtime" / "v7_certified" / "account_ownership.jsonl")
    acquired = lease.acquire(
        fingerprint="fingerprint", owner_strategy_id=V7_NAME,
        owner_instance_id=config.instance_id, source_commit=config.source_hash,
        configuration_hash=config.configuration_hash,
    )
    record = {
        "strategy": V7_NAME, "instance_id": config.instance_id,
        "account_fingerprint": "fingerprint", "lease_hash": acquired["record_hash"],
    }
    record["activation_hash"] = canonical_hash(record)
    control_path("activation", root).parent.mkdir(parents=True, exist_ok=True)
    control_path("activation", root).write_text(json.dumps(record))
    return record


def test_status_reports_isolated_runtime_without_exchange_client(tmp_path: Path):
    root = _root(tmp_path)
    config = make_config(root)
    config.wallet_path.parent.mkdir(parents=True)
    config.wallet_path.write_text(json.dumps({
        "cash": "100", "btc": "0.1", "locked": True, "lock_reason": "stale_data",
        "lock_timestamp": "2026-07-27T00:00:00+00:00", "pending": None, "journal_sequence": 3,
    }))
    activation = _activation(root)

    rendered = format_status(status(root, gateway=_Gateway()))

    assert "activo" in rendered and activation["activation_hash"][:12] in rendered
    assert "LOCKED" in rendered and "stale_data" in rendered


def test_pause_resume_and_deactivate_preserve_transition_chain(tmp_path: Path):
    root = _root(tmp_path)
    activation = _activation(root)
    gateway = _Gateway()
    prefix = activation["activation_hash"][:12]

    pause = transition("pause", prefix, root=root, gateway=gateway)
    assert gateway.active is False and control_path("pause", root).is_file()
    with pytest.raises(PaperSafetyError, match="already exists"):
        transition("pause", prefix, root=root, gateway=gateway)
    resume = transition("resume", prefix, root=root, gateway=gateway)
    assert gateway.active is True and resume["predecessor_hash"] == pause["transition_hash"]
    deactivated = transition("deactivate", prefix, root=root, gateway=gateway)
    assert gateway.active is False and deactivated["predecessor_hash"] == resume["transition_hash"]
    assert DemoAccountLease(root / "data" / "runtime" / "v7_certified" / "account_ownership.jsonl").current() is None


def test_transition_refuses_wrong_confirmation_or_missing_predecessor(tmp_path: Path):
    root = _root(tmp_path)
    _activation(root)
    with pytest.raises(PaperSafetyError, match="12-character"):
        transition("pause", "wrong", root=root, gateway=_Gateway())
    with pytest.raises(PaperSafetyError, match="pause.json"):
        transition("resume", _activation(root)["activation_hash"][:12], root=root, gateway=_Gateway(False))
