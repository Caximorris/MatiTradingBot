from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import subprocess

import pytest

from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import PaperSafetyError, make_config
from core.v7_okx_demo import V7OKXDemoRunner
from data.market_data import OHLCVBar
from tools.v7_certified_demo_service import (
    LinuxSystemdGateway,
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_STRATEGY,
    CertifiedV7DemoServiceManager,
    CertifiedV7DemoServiceRunner,
    StartupInputs,
    UnitRenderInputs,
    V7RuntimeLoop,
    canonical_hash,
    cutover_gateway,
    render_service_unit,
    run,
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
    inputs = UnitRenderInputs(
        run_user="trader", app_dir="/srv/matibot", python_path="/srv/matibot/.venv/bin/python",
        environment_file="/etc/matibot/v7-demo.env", config_path="/srv/matibot/data/runtime/v7_certified/config.json",
        state_path="/srv/matibot/data/runtime/v7_certified/state.json", journal_path="/srv/matibot/data/runtime/v7_certified/journal.jsonl",
        evidence_path="/srv/matibot/data/runtime/v7_certified/evidence", report_path="/srv/matibot/data/runtime/v7_certified/reports",
    )
    rendered = render_service_unit(inputs)
    unit = rendered.text
    template = (Path(__file__).parents[1] / "deploy" / SERVICE_NAME).read_text()
    assert SERVICE_NAME not in unit and "enable" not in unit and "C:\\" not in unit and len(rendered.content_hash) == 64
    assert "v7_certified_demo_service.py --run" in unit and "secret" not in unit.lower()
    assert "__" not in unit and template != unit
    with pytest.raises(PaperSafetyError):
        render_service_unit(UnitRenderInputs(**{**inputs.__dict__, "app_dir": "C:\\bot"}))


def test_install_is_idempotent_inactive_and_inspection_does_not_mutate():
    linux = FakeLinux()
    manager = CertifiedV7DemoServiceManager(linux)
    before = manager.inspect()
    assert before["state"]["active"] is False and not any(
        call[0] in {"install", "start", "stop", "disable"} for call in linux.calls
    )
    inputs = UnitRenderInputs(
        run_user="trader", app_dir="/srv/matibot", python_path="/srv/matibot/.venv/bin/python",
        environment_file="/etc/matibot/v7-demo.env", config_path="/srv/matibot/data/runtime/v7_certified/config.json",
        state_path="/srv/matibot/data/runtime/v7_certified/state.json", journal_path="/srv/matibot/data/runtime/v7_certified/journal.jsonl",
        evidence_path="/srv/matibot/data/runtime/v7_certified/evidence", report_path="/srv/matibot/data/runtime/v7_certified/reports",
    )
    first = manager.install_inactive(render_inputs=inputs)
    second = manager.install_inactive(render_inputs=inputs)
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


def test_renderer_rejects_injection_credentials_and_non_isolated_paths():
    base = dict(
        run_user="trader", app_dir="/srv/matibot", python_path="/srv/matibot/.venv/bin/python",
        environment_file="/etc/matibot/v7-demo.env", config_path="/srv/matibot/data/runtime/v7_certified/config.json",
        state_path="/srv/matibot/data/runtime/v7_certified/state.json", journal_path="/srv/matibot/data/runtime/v7_certified/journal.jsonl",
        evidence_path="/srv/matibot/data/runtime/v7_certified/evidence", report_path="/srv/matibot/data/runtime/v7_certified/reports",
    )
    for changed in (
        {"run_user": "trader\nExecStart=/bin/sh"}, {"config_path": "relative.json"},
        {"environment_file": "/etc/matibot/api_key.env"}, {"config_path": "/srv/live/config.json"},
        {"report_path": base["evidence_path"]},
    ):
        with pytest.raises(PaperSafetyError):
            render_service_unit(UnitRenderInputs(**(base | changed)))


def test_gateway_is_allowlisted_and_detects_identity_mismatch_timeout_and_duplicates(tmp_path: Path):
    calls: list[list[str]] = []
    responses = iter((
        subprocess.CompletedProcess([], 0, "17\n", ""),
        subprocess.CompletedProcess([], 0, "17\n18\n", ""),
    ))

    def runner(args, **_kwargs):
        calls.append(args)
        return next(responses)

    gateway = LinuxSystemdGateway(runner=runner)
    identities = gateway.process_identities(SERVICE_NAME)
    assert len(identities) == 2 and calls[0][0] == "systemctl" and calls[1][0] == "pgrep"
    with pytest.raises(PaperSafetyError):
        gateway.start("matibot-v6-paper.service")
    with pytest.raises(PaperSafetyError):
        LinuxSystemdGateway(runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("systemctl", 1))).stop(SERVICE_NAME)
    with pytest.raises(PaperSafetyError):
        LinuxSystemdGateway(runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "failure")).start(SERVICE_NAME)


def test_cli_render_is_deterministic_and_never_uses_linux_gateway(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    output = tmp_path / "unit.service"
    args = [
        "render", "--output", str(output), "--run-user", "trader", "--app-dir", "/srv/matibot",
        "--python-path", "/srv/matibot/.venv/bin/python", "--environment-file", "/etc/matibot/v7.env",
        "--config-path", "/srv/matibot/data/runtime/v7_certified/config.json",
        "--state-path", "/srv/matibot/data/runtime/v7_certified/state.json",
        "--journal-path", "/srv/matibot/data/runtime/v7_certified/journal.jsonl",
        "--evidence-path", "/srv/matibot/data/runtime/v7_certified/evidence",
        "--report-path", "/srv/matibot/data/runtime/v7_certified/reports",
    ]
    assert run(args) == 0 and output.is_file()
    first = capsys.readouterr().out
    assert run(args) == 0 and capsys.readouterr().out == first
    assert run(["start", "--linux-systemd", "--dry-run"]) == 2


class _Startup:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def validate_startup(self):
        if self.error:
            raise self.error


class _Runner:
    def __init__(self, cash="100", btc="1", error: Exception | None = None):
        self.client = type("Client", (), {"get_balance": lambda s: {"USDT": Decimal(cash), "BTC": Decimal(btc)}})()
        self.calls = []
        self.error = error

    def submit_transition(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"status": "reconciled", "fill_id": "fill-1"}


def _bars(hour=4):
    return [OHLCVBar(int(datetime(2026, 7, 27, hour, tzinfo=timezone.utc).timestamp() * 1000), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"))]


def _loop(tmp_path, runner, *, bars=None, now=datetime(2026, 7, 27, 6, tzinfo=timezone.utc), v6=False, target=None):
    return V7RuntimeLoop(startup=_Startup(), runner=runner, candles=lambda: bars or _bars(),
        v6_status=lambda: {"active": v6}, state_path=tmp_path / "state.json", now=lambda: now,
        target_for=target or (lambda _at, _cash, btc, _price: btc))


def test_runtime_cycle_no_order_heartbeat_and_restart_idempotency(tmp_path: Path):
    runner = _Runner()
    loop = _loop(tmp_path, runner)
    first = loop.cycle()
    assert first["order"] == "not_required" and first["heartbeat_at"] and not runner.calls
    assert _loop(tmp_path, runner).cycle()["last_cycle"] == "duplicate" and not runner.calls


def test_runtime_cycle_submits_exactly_one_reconciled_transition(tmp_path: Path):
    runner = _Runner(btc="1")
    result = _loop(tmp_path, runner, target=lambda *_: Decimal("0")).cycle()
    assert len(runner.calls) == 1 and result["order"]["fill_id"] == "fill-1"


@pytest.mark.parametrize("bars,now", [(_bars(4), datetime(2026, 7, 27, 4, 30, tzinfo=timezone.utc)), (_bars(4) + _bars(4), NOW)])
def test_runtime_rejects_incomplete_or_duplicate_candles(tmp_path: Path, bars, now):
    with pytest.raises(PaperSafetyError):
        _loop(tmp_path, _Runner(), bars=bars, now=now).cycle()


@pytest.mark.parametrize("runner,v6,now", [(_Runner(error=PaperSafetyError("fill failed")), False, datetime(2026, 7, 27, 6, tzinfo=timezone.utc)), (_Runner(), True, NOW), (_Runner(), False, datetime(2026, 7, 28, 12, tzinfo=timezone.utc))])
def test_runtime_fails_closed_for_fill_v6_or_stale_data(tmp_path: Path, runner, v6, now):
    with pytest.raises(PaperSafetyError):
        _loop(tmp_path, runner, v6=v6, now=now, target=lambda *_: Decimal("0")).cycle()
