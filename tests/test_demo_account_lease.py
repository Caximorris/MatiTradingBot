from datetime import datetime, timezone

import pytest

from core.demo_account_lease import DemoAccountLease, DemoLeaseError, account_fingerprint


def test_demo_lease_is_exclusive_append_only_and_releasable(tmp_path):
    lease = DemoAccountLease(tmp_path / "lease.jsonl")
    fp = account_fingerprint(domain="demo.okx", key_id="redacted-key-id")
    lease.acquire(fingerprint=fp, owner_strategy_id="v6", owner_instance_id="demo", source_commit="a", configuration_hash="b", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    again = lease.acquire(fingerprint=fp, owner_strategy_id="v6", owner_instance_id="demo", source_commit="a", configuration_hash="b")
    assert again["record_hash"] == lease.current()["record_hash"]
    with pytest.raises(DemoLeaseError):
        lease.acquire(fingerprint=fp, owner_strategy_id="v7", owner_instance_id="certified", source_commit="a", configuration_hash="b")
    lease.release(fingerprint=fp, owner_strategy_id="v6", owner_instance_id="demo")
    assert lease.current() is None
