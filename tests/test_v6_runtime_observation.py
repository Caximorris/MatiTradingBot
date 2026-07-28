from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.v7_certified_paper import PaperSafetyError
from tools.v6_runtime_observation import (
    build_v6_audit_inputs,
    collect_v6_runtime,
    observe_okx_demo_account,
    validate_demo_runtime_config,
)

NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


class Service:
    def __init__(self, active=True, identities=None):
        self.active, self.identities = (
            active,
            [{"pid": "1", "instance_id": "v6"}] if identities is None else identities,
        )

    def inspect(self, _):
        return {"known": True, "active": self.active}

    def process_identities(self, _):
        return self.identities


class Client:
    is_paper = True
    endpoint = "okx_demo"
    account_id = "account"

    def get_balance(self):
        return {"USDT": Decimal("100"), "BTC": Decimal("0"), "ETH": Decimal("1")}

    def get_positions(self):
        return []

    def get_open_orders(self, _):
        return []

    def get_order_history(self, _, limit=20):
        return []

    def get_fills(self, _, limit=20):
        return []

    def get_instrument(self, _):
        if hasattr(self, "precision"):
            return self.precision
        return {"tickSz": "0.1", "lotSz": "0.0001", "minSz": "0.0001"}

    def get_position_mode(self):
        return {"position_mode": "net_mode"}

    def get_fee_metadata(self, _):
        return {"maker": "-0.001", "taker": "-0.001"}

    def place_order(self, *_a, **_k):
        raise AssertionError("must never submit")


def runtime_files(tmp_path: Path):
    config = {
        "strategy": "swing_allocator_demo_btc_usdt",
        "instance_id": "v6",
        "execution": "okx_demo",
        "mode": "paper",
        "configuration_hash": "cfg",
    }
    state = {
        "cash": "100",
        "btc": "0",
        "target": "0",
        "last_completed_candle": "2026-07-27T00:00:00+00:00",
        "data_fresh": True,
    }
    for name, value in (("config.json", config), ("state.json", state)):
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / "journal.jsonl").write_text(
        '{"intent_id":"i","order_id":"o","fill_id":"f","status":"reconciled"}\n'
    )
    return tmp_path / "config.json", tmp_path / "state.json", tmp_path / "journal.jsonl"


def test_collect_observe_and_bundle_are_deterministic_and_audit_ready(tmp_path: Path):
    config, state, journal = runtime_files(tmp_path)
    runtime = collect_v6_runtime(
        config_path=config,
        state_path=state,
        journal_path=journal,
        service=Service(),
        source_commit="sha",
        now=NOW,
    )
    account = observe_okx_demo_account(Client(), symbol="BTC-USDT", now=NOW)
    manifest = build_v6_audit_inputs(runtime, account, tmp_path / "bundle")
    assert account["exchange"] == "OKX" and account["environment"] == "demo"
    assert account["simulated_trading"] is True and account["observation_hash"]
    assert manifest["verdict"] == "PASS" and account["unsupported_assets"] == {
        "ETH": "1"
    }
    assert {path.name for path in (tmp_path / "bundle").iterdir()} == {
        "v6-config.json",
        "v6-state.json",
        "account-observation.json",
        "manifest.json",
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: (p / "state.json").write_text('{"locked":true}'),
        lambda p: (p / "state.json").write_text(
            '{"data_fresh":false,"last_completed_candle":"x"}'
        ),
        lambda p: (p / "journal.jsonl").unlink(),
    ],
)
def test_runtime_fails_closed(tmp_path: Path, mutator):
    config, state, journal = runtime_files(tmp_path)
    mutator(tmp_path)
    with pytest.raises(PaperSafetyError):
        collect_v6_runtime(
            config_path=config,
            state_path=state,
            journal_path=journal,
            service=Service(),
            source_commit="sha",
            now=NOW,
        )


def test_runtime_rejects_inactive_or_ambiguous_process(tmp_path: Path):
    config, state, journal = runtime_files(tmp_path)
    for service in (Service(active=False), Service(identities=[])):
        with pytest.raises(PaperSafetyError):
            collect_v6_runtime(
                config_path=config,
                state_path=state,
                journal_path=journal,
                service=service,
                source_commit="sha",
                now=NOW,
            )


def test_observer_rejects_live_and_secret_fields():
    client = Client()
    client.endpoint = "live"
    with pytest.raises(PaperSafetyError):
        observe_okx_demo_account(client, symbol="BTC-USDT", now=NOW)
    client.endpoint = "okx_demo"
    client.precision = {"api_key": "no"}
    with pytest.raises(PaperSafetyError):
        observe_okx_demo_account(client, symbol="BTC-USDT", now=NOW)


def test_runtime_config_allows_only_boolean_secret_presence_markers():
    base = {
        "trading_mode": "paper", "simulated_trading": True, "demo_confirmed": True,
        "okx_demo_domain": "https://www.okx.com", "demo_api_key_present": True,
        "demo_secret_present": True, "demo_passphrase_present": True,
    }
    validate_demo_runtime_config(base)
    for key, value in (("demo_secret_present", "true"), ("demo_api_key_present", 1), ("demo_passphrase_present", False)):
        bad = base | {key: value}
        with pytest.raises(PaperSafetyError):
            validate_demo_runtime_config(bad)
    for key in ("demo_api_key", "demo_secret", "demo_passphrase", "credential_value"):
        with pytest.raises(PaperSafetyError):
            validate_demo_runtime_config(base | {key: "not-a-real-secret"})
