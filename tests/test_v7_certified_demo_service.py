from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import PaperSafetyError, make_config
from core.v7_okx_demo import V7OKXDemoRunner
from tools.v7_certified_demo_service import (
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_STRATEGY,
    CertifiedV7DemoServiceManager,
    CertifiedV7DemoServiceRunner,
    StartupInputs,
    canonical_hash,
    cutover_gateway,
    render_service_definition,
)


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


class FakeLinux:
    def __init__(self) -> None:
        self.active = False
        self.enabled = False
        self.calls: list[tuple[str, str]] = []
        self.processes: list[dict[str, str]] = []
        self.unit = ""

    def inspect(self, name: str) -> dict[str, object]:
        self.calls.append(("inspect", name))
        return {"known": True, "active": self.active, "enabled": self.enabled}

    def install_unit(self, name: str, unit: str) -> None:
        self.calls.append(("install", name))
        self.unit = unit

    def daemon_reload(self) -> None:
        self.calls.append(("reload", SERVICE_NAME))

    def disable(self, name: str) -> None:
        self.calls.append(("disable", name))
        self.enabled = False

    def start(self, name: str) -> None:
        self.calls.append(("start", name))
        self.active = True
        self.processes = [{"pid": "7", "instance_id": SERVICE_INSTANCE_ID}]

    def stop(self, name: str) -> None:
        self.calls.append(("stop", name))
        self.active = False
        self.processes = []

    def process_identities(self, name: str) -> list[dict[str, str]]:
        self.calls.append(("processes", name))
        return list(self.processes)

    def health(self, name: str) -> dict[str, object]:
        self.calls.append(("health", name))
        return {"healthy": self.active}


def _root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir(parents=True)
    source = Path(__file__).parents[1] / "docs" / "v7_frozen_candidate.json"
    (tmp_path / "docs" / "v7_frozen_candidate.json").write_text(source.read_text())
    return tmp_path


def _startup(
    tmp_path: Path,
    *,
    v6_active: bool = False,
    shadow_active: bool = False,
    endpoint: str = "okx_demo",
):
    root = _root(tmp_path)
    config = make_config(root, instance_id=SERVICE_INSTANCE_ID)
    runner = object.__new__(V7OKXDemoRunner)
    runner.config = config
    lease = DemoAccountLease(tmp_path / "lease.jsonl")
    acquired = lease.acquire(
        fingerprint="fp",
        owner_strategy_id=SERVICE_STRATEGY,
        owner_instance_id=SERVICE_INSTANCE_ID,
        source_commit=config.source_hash,
        configuration_hash=config.configuration_hash,
        now=NOW,
    )
    account = {
        "fingerprint": "fp",
        "demo_confirmed": True,
        "endpoint": endpoint,
        "cash": "100",
        "btc": "0",
        "open_orders": [],
        "positions": [],
        "unsupported_assets": [],
    }
    activation = {
        "strategy": SERVICE_STRATEGY,
        "instance_id": SERVICE_INSTANCE_ID,
        "candidate_hash": config.candidate_hash,
        "configuration_hash": config.configuration_hash,
        "source_hash": config.source_hash,
        "execution_contract_hash": config.source_hash,
        "account_fingerprint": "fp",
        "lease_hash": acquired["record_hash"],
        "activation_baseline": {
            key: account[key]
            for key in ("cash", "btc", "open_orders", "positions", "unsupported_assets")
        },
        "active": True,
        "paused": False,
    }
    activation["activation_hash"] = canonical_hash(activation)
    inputs = StartupInputs(
        activation=activation,
        account=account,
        v6_service={"active": v6_active},
        shadow_service={"active": shadow_active},
        lease=lease,
    )
    return CertifiedV7DemoServiceRunner(root=root, runner=runner, inputs=inputs), inputs


def test_unit_is_linux_only_credential_free_and_inactive_by_default():
    unit = render_service_definition(app_dir="/srv/matibot", run_user="trader")
    template = (Path(__file__).parents[1] / "deploy" / SERVICE_NAME).read_text()
    assert SERVICE_NAME not in unit and "enable" not in unit and "C:\\" not in unit
    assert "v7_certified_demo_service.py --run" in unit and "secret" not in unit.lower()
    assert (
        template.replace("__APP_DIR__", "/srv/matibot").replace(
            "__RUN_USER__", "trader"
        )
        == unit
    )
    with pytest.raises(PaperSafetyError):
        render_service_definition(app_dir="C:\\bot", run_user="trader")


def test_install_is_idempotent_inactive_and_inspection_does_not_mutate():
    linux = FakeLinux()
    manager = CertifiedV7DemoServiceManager(linux)
    before = manager.inspect()
    assert before["state"]["active"] is False and not any(
        call[0] in {"install", "start", "stop", "disable"} for call in linux.calls
    )
    first = manager.install_inactive(app_dir="/srv/matibot", run_user="trader")
    second = manager.install_inactive(app_dir="/srv/matibot", run_user="trader")
    assert (
        first
        == second
        == {
            "service": SERVICE_NAME,
            "installed": True,
            "enabled": False,
            "active": False,
        }
    )
    assert not any(call[0] == "start" for call in linux.calls)


def test_start_requires_certified_activation_lease_and_single_process(tmp_path: Path):
    startup, _ = _startup(tmp_path)
    linux = FakeLinux()
    manager = CertifiedV7DemoServiceManager(linux)
    started = manager.start(startup)
    assert started["service"] == SERVICE_NAME and started["active"] is True
    assert manager.stop() == {"service": SERVICE_NAME, "active": False}
    assert all(
        name == SERVICE_NAME
        for action, name in linux.calls
        if action in {"start", "stop"}
    )


@pytest.mark.parametrize(
    "kwargs", [{"v6_active": True}, {"shadow_active": True}, {"endpoint": "okx_live"}]
)
def test_start_refuses_v6_shadow_or_production_endpoint(
    tmp_path: Path, kwargs: dict[str, object]
):
    startup, _ = _startup(tmp_path, **kwargs)
    with pytest.raises(PaperSafetyError):
        startup.validate_startup()


def test_start_refuses_hash_mismatch_and_duplicate_process(tmp_path: Path):
    startup, inputs = _startup(tmp_path)
    inputs.activation["candidate_hash"] = "wrong"
    with pytest.raises(PaperSafetyError):
        startup.validate_startup()
    startup, _ = _startup(tmp_path / "second")
    linux = FakeLinux()
    linux.processes = [{"pid": "1"}, {"pid": "2"}]
    with pytest.raises(PaperSafetyError, match="duplicate"):
        CertifiedV7DemoServiceManager(linux).start(startup)


def test_start_refuses_v6_lease_and_ambiguous_inherited_account(tmp_path: Path):
    startup, inputs = _startup(tmp_path)
    inputs.lease.release(
        fingerprint="fp",
        owner_strategy_id=SERVICE_STRATEGY,
        owner_instance_id=SERVICE_INSTANCE_ID,
        now=NOW,
    )
    inputs.lease.acquire(
        fingerprint="fp",
        owner_strategy_id="swing_allocator_demo_btc_usdt",
        owner_instance_id="v6-instance",
        source_commit="v6",
        configuration_hash="v6-config",
        now=NOW,
    )
    with pytest.raises(PaperSafetyError, match="does not own"):
        startup.validate_startup()
    startup, inputs = _startup(tmp_path / "ambiguous")
    inputs.account.pop("cash")
    with pytest.raises(PaperSafetyError, match="incomplete"):
        startup.validate_startup()


def test_cutover_gateway_only_exposes_dedicated_service():
    linux = FakeLinux()
    gateway = cutover_gateway(CertifiedV7DemoServiceManager(linux))
    assert gateway.status(SERVICE_NAME)["known"] is True
    assert gateway.status("matibot-v6-paper.service")["known"] is False
