#!/usr/bin/env python
"""Dedicated, fail-closed systemd boundary for the certified V7 OKX Demo candidate.

No subprocess, VM, exchange, or credential construction occurs in this module.
Callers inject the Linux service manager and the already-constructed certified
runner.  Direct execution is deliberately blocked.
"""

from __future__ import annotations

import hashlib
import json
import argparse
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Protocol, Sequence

from data.market_data import OHLCVBar
from core.demo_account_lease import DemoAccountLease, DemoLeaseError
from core.v7_certified_paper import PaperSafetyError, make_config
from core.v7_okx_demo import V7OKXDemoRunner
from tools.v6_v7_demo_cutover import ServiceGateway
from strategies.cycle_phase_clock import CyclePhaseClock
from strategies.swing_cycle_core import SwingCycleCoreBot, SwingCycleCoreConfig


SERVICE_NAME = "matibot-v7-certified-okx-demo.service"
SERVICE_INSTANCE_ID = "v7_certified_paper"
SERVICE_STRATEGY = "swing_cycle_core_v7_certified_okx_demo"
_FORBIDDEN_UNIT_TEXT = (
    "secret",
    "password",
    "passphrase",
    "api_key",
    "private_key",
    "access_token",
)
_PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")
_LINUX_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_LIVE_MARKERS = ("live", "production", "prod", "mainnet")
_REQUIRED_V7_MARKER = "v7_certified"
_MAX_STATUS_BYTES = 16_384


@dataclass(frozen=True)
class RenderedUnit:
    """Validated unit content, suitable for an explicitly requested write/install."""

    text: str
    content_hash: str


@dataclass(frozen=True)
class UnitRenderInputs:
    run_user: str
    app_dir: str
    python_path: str
    environment_file: str
    config_path: str
    state_path: str
    journal_path: str
    evidence_path: str
    report_path: str


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _verify_hash(record: dict[str, Any], field: str) -> None:
    unsigned = dict(record)
    supplied = unsigned.pop(field, None)
    if not isinstance(supplied, str) or supplied != canonical_hash(unsigned):
        raise PaperSafetyError(f"tampered or incomplete {field} record")


def _linux_path(value: str, *, label: str) -> str:
    path = PurePosixPath(value)
    lowered = value.lower()
    if (
        not value
        or not path.is_absolute()
        or "\\" in value
        or "\r" in value
        or "\n" in value
        or any(char.isspace() or char in "[]=;\"'" for char in value)
        or any(marker in lowered for marker in _FORBIDDEN_UNIT_TEXT + _LIVE_MARKERS)
    ):
        raise PaperSafetyError(
            f"systemd definition requires a safe absolute Linux {label}"
        )
    return str(path)


def render_service_unit(inputs: UnitRenderInputs) -> RenderedUnit:
    """Render the tracked template without accepting systemd or secret injection."""
    if not _LINUX_USER.fullmatch(inputs.run_user):
        raise PaperSafetyError("systemd definition requires a simple Linux run user")
    values = {
        "__RUN_USER__": inputs.run_user,
        "__APP_DIR__": _linux_path(inputs.app_dir, label="repository path"),
        "__PYTHON__": _linux_path(inputs.python_path, label="Python executable"),
        "__ENV_FILE__": _linux_path(inputs.environment_file, label="environment file"),
        "__CONFIG_PATH__": _linux_path(inputs.config_path, label="configuration path"),
        "__STATE_PATH__": _linux_path(inputs.state_path, label="state path"),
        "__JOURNAL_PATH__": _linux_path(inputs.journal_path, label="journal path"),
        "__EVIDENCE_PATH__": _linux_path(inputs.evidence_path, label="evidence path"),
        "__REPORT_PATH__": _linux_path(inputs.report_path, label="report path"),
    }
    isolated = (
        values["__STATE_PATH__"], values["__JOURNAL_PATH__"],
        values["__EVIDENCE_PATH__"], values["__REPORT_PATH__"],
    )
    if len(set(isolated)) != len(isolated) or any(_REQUIRED_V7_MARKER not in item for item in isolated):
        raise PaperSafetyError("V7 state, journal, evidence, and report paths must be unique and isolated")
    template = (Path(__file__).parents[1] / "deploy" / SERVICE_NAME).read_text(encoding="utf-8")
    unit = template
    for placeholder, value in values.items():
        unit = unit.replace(placeholder, value)
    if _PLACEHOLDER.search(unit):
        raise PaperSafetyError("systemd definition contains unresolved placeholders")
    if any(marker in unit.lower() for marker in _FORBIDDEN_UNIT_TEXT):
        raise PaperSafetyError("credentials are forbidden in systemd definitions")
    if "--run" not in unit or "v7_certified_demo_service.py" not in unit or "okx demo" not in unit.lower():
        raise PaperSafetyError("systemd definition is not the dedicated V7 OKX Demo runner")
    return RenderedUnit(text=unit, content_hash=hashlib.sha256(unit.encode()).hexdigest())


def render_service_definition(**kwargs: str) -> str:
    """Compatibility wrapper for callers that only need unit text."""
    return render_service_unit(UnitRenderInputs(**kwargs)).text


class LinuxSystemdGateway:
    """Narrow subprocess boundary for the one certified candidate service."""

    def __init__(self, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run, timeout: float = 15.0) -> None:
        self._runner = runner
        self._timeout = timeout

    @staticmethod
    def _service(name: str) -> str:
        if name != SERVICE_NAME:
            raise PaperSafetyError("only the certified V7 service is permitted")
        return name

    def _run(self, args: Sequence[str], *, allowed: set[tuple[str, ...]], check: bool = True) -> subprocess.CompletedProcess[str]:
        command = tuple(args)
        if command not in allowed:
            raise PaperSafetyError("systemd command is not allowlisted")
        try:
            result = self._runner(list(command), capture_output=True, text=True, timeout=self._timeout, shell=False, check=False)
        except subprocess.TimeoutExpired as exc:
            raise PaperSafetyError("systemd command timed out") from exc
        if check and result.returncode != 0:
            raise PaperSafetyError("systemd command failed")
        return result

    def inspect(self, service_name: str) -> dict[str, Any]:
        name = self._service(service_name)
        enabled = self._run(("systemctl", "is-enabled", name), allowed={("systemctl", "is-enabled", name)}, check=False)
        active = self._run(("systemctl", "is-active", name), allowed={("systemctl", "is-active", name)}, check=False)
        known = active.returncode != 4 and enabled.returncode != 4
        return {"known": known, "enabled": enabled.returncode == 0, "active": active.returncode == 0}

    def install_rendered_unit(self, source: Path, content_hash: str, *, dry_run: bool = False) -> dict[str, Any]:
        if not source.is_absolute() or not source.is_file():
            raise PaperSafetyError("rendered unit must be an existing absolute path")
        content = source.read_text(encoding="utf-8")
        if hashlib.sha256(content.encode()).hexdigest() != content_hash or _PLACEHOLDER.search(content):
            raise PaperSafetyError("rendered unit hash or placeholders are invalid")
        target = f"/etc/systemd/system/{SERVICE_NAME}"
        command = ("install", "-m", "0644", str(source), target)
        if dry_run:
            return {"planned": True, "command": list(command)}
        self._run(command, allowed={command})
        return {"installed": True, "service": SERVICE_NAME}

    def install_unit(self, service_name: str, unit_text: str) -> None:
        """Protocol adapter; CLI installation additionally binds an operator hash."""
        self._service(service_name)
        if _PLACEHOLDER.search(unit_text) or any(marker in unit_text.lower() for marker in _FORBIDDEN_UNIT_TEXT):
            raise PaperSafetyError("unresolved placeholders cannot be installed")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".service", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(unit_text)
        try:
            self.install_rendered_unit(temporary, hashlib.sha256(unit_text.encode()).hexdigest())
        finally:
            temporary.unlink(missing_ok=True)

    def daemon_reload(self, *, dry_run: bool = False) -> dict[str, Any]:
        command = ("systemctl", "daemon-reload")
        if dry_run:
            return {"planned": True, "command": list(command)}
        self._run(command, allowed={command})
        return {"reloaded": True}

    def disable(self, service_name: str, *, dry_run: bool = False) -> dict[str, Any]:
        name = self._service(service_name)
        command = ("systemctl", "disable", name)
        if dry_run:
            return {"planned": True, "command": list(command)}
        self._run(command, allowed={command})
        return {"disabled": True, "service": name}

    def start(self, service_name: str, *, dry_run: bool = False) -> dict[str, Any]:
        name = self._service(service_name)
        command = ("systemctl", "start", name)
        if dry_run:
            return {"planned": True, "command": list(command)}
        self._run(command, allowed={command})
        return {"started": True, "service": name}

    def stop(self, service_name: str, *, dry_run: bool = False) -> dict[str, Any]:
        name = self._service(service_name)
        command = ("systemctl", "stop", name)
        if dry_run:
            return {"planned": True, "command": list(command)}
        self._run(command, allowed={command})
        return {"stopped": True, "service": name}

    def process_identities(self, service_name: str) -> list[dict[str, Any]]:
        name = self._service(service_name)
        result = self._run(("systemctl", "show", "--property=MainPID", "--value", name), allowed={("systemctl", "show", "--property=MainPID", "--value", name)}, check=False)
        main_pid = result.stdout.strip()
        pattern = "tools/v7_certified_demo_service.py --run"
        matches = self._run(("pgrep", "-f", pattern), allowed={("pgrep", "-f", pattern)}, check=False)
        pids = [pid for pid in matches.stdout.splitlines() if pid.isdecimal()]
        if main_pid and main_pid != "0" and main_pid not in pids:
            raise PaperSafetyError("systemd main process identity does not match certified runner")
        return [{"pid": pid, "instance_id": SERVICE_INSTANCE_ID} for pid in pids]

    def health(self, service_name: str) -> dict[str, Any]:
        name = self._service(service_name)
        result = self._run(("systemctl", "status", "--no-pager", "--lines=20", name), allowed={("systemctl", "status", "--no-pager", "--lines=20", name)}, check=False)
        output = (result.stdout + result.stderr)[:_MAX_STATUS_BYTES]
        return {"returncode": result.returncode, "status": output}


class LinuxServiceInterface(Protocol):
    """Injected VM-facing boundary; implementations own all real system commands."""

    def inspect(self, service_name: str) -> dict[str, Any]: ...

    def install_unit(self, service_name: str, unit_text: str) -> None: ...

    def daemon_reload(self) -> None: ...

    def disable(self, service_name: str) -> None: ...

    def start(self, service_name: str) -> None: ...

    def stop(self, service_name: str) -> None: ...

    def process_identities(self, service_name: str) -> list[dict[str, Any]]: ...

    def health(self, service_name: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class StartupInputs:
    activation: dict[str, Any]
    account: dict[str, Any]
    v6_service: dict[str, Any]
    shadow_service: dict[str, Any]
    lease: DemoAccountLease


class CertifiedV7DemoServiceRunner:
    """Validates the exact V7 Demo ownership state before a service may start."""

    def __init__(
        self, *, root: Path, runner: V7OKXDemoRunner, inputs: StartupInputs
    ) -> None:
        self.root, self.runner, self.inputs = root, runner, inputs

    def validate_startup(self) -> dict[str, Any]:
        if type(self.runner) is not V7OKXDemoRunner:
            raise PaperSafetyError("dedicated service accepts only V7OKXDemoRunner")
        config = make_config(self.root, instance_id=SERVICE_INSTANCE_ID)
        config.validate()
        if self.runner.config != config:
            raise PaperSafetyError(
                "certified runner configuration does not match dedicated service"
            )
        activation, account = self.inputs.activation, self.inputs.account
        _verify_hash(activation, "activation_hash")
        required = {
            "candidate_hash": config.candidate_hash,
            "configuration_hash": config.configuration_hash,
            "source_hash": config.source_hash,
            "execution_contract_hash": config.source_hash,
            "strategy": SERVICE_STRATEGY,
            "instance_id": SERVICE_INSTANCE_ID,
            "active": True,
            "paused": False,
        }
        if any(activation.get(key) != value for key, value in required.items()):
            raise PaperSafetyError(
                "activation record does not match the certified V7 service"
            )
        if activation.get("account_fingerprint") != account.get("fingerprint"):
            raise PaperSafetyError("activation account fingerprint mismatch")
        if not account.get("demo_confirmed") or account.get("endpoint") not in {
            "okx_demo",
            "demo",
        }:
            raise PaperSafetyError("production or unconfirmed endpoint is prohibited")
        required_account_fields = {
            "cash",
            "btc",
            "open_orders",
            "positions",
            "unsupported_assets",
        }
        if not required_account_fields.issubset(account):
            raise PaperSafetyError("inherited account observation is incomplete")
        if account["open_orders"] or account["unsupported_assets"]:
            raise PaperSafetyError(
                "pending orders or unsupported inherited assets prevent startup"
            )
        if account["positions"] not in ([], [{"btc": account["btc"]}]):
            raise PaperSafetyError(
                "ambiguous inherited account position prevents startup"
            )
        baseline = activation.get("activation_baseline")
        if not isinstance(baseline, dict) or any(
            baseline.get(key) != account[key] for key in required_account_fields
        ):
            raise PaperSafetyError(
                "activation baseline does not reconcile to inherited account state"
            )
        if self.inputs.v6_service.get("active") is not False:
            raise PaperSafetyError("V6 service state is active or ambiguous")
        if self.inputs.shadow_service.get("active") is not False:
            raise PaperSafetyError(
                "legacy v7_shadow service state is active or ambiguous"
            )
        current = self.inputs.lease.current()
        if current is None or current.get("owner_strategy_id") != SERVICE_STRATEGY:
            raise PaperSafetyError(
                "certified V7 does not own the OKX Demo account lease"
            )
        if current.get("owner_instance_id") != SERVICE_INSTANCE_ID:
            raise PaperSafetyError("OKX Demo lease is owned by a different instance")
        if current.get("account_fingerprint") != account.get("fingerprint"):
            raise PaperSafetyError("OKX Demo lease fingerprint mismatch")
        if activation.get("lease_hash") != current.get("record_hash"):
            raise PaperSafetyError(
                "activation record is not bound to the current account lease"
            )
        return {
            "status": "READY",
            "service": SERVICE_NAME,
            "instance_id": SERVICE_INSTANCE_ID,
        }


class V7RuntimeLoop:
    """One closed-candle V7 cycle; dependencies are explicit for offline tests."""

    def __init__(
        self, *, startup: CertifiedV7DemoServiceRunner, runner: V7OKXDemoRunner,
        candles: Callable[[], list[OHLCVBar]], v6_status: Callable[[], dict[str, Any]],
        state_path: Path, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        target_for: Callable[[datetime, Decimal, Decimal, Decimal], Decimal] | None = None,
    ) -> None:
        self.startup, self.runner, self.candles, self.v6_status = startup, runner, candles, v6_status
        self.state_path, self.now = state_path, now
        self.target_for = target_for or self._certified_target

    @staticmethod
    def _certified_target(at: datetime, cash: Decimal, btc: Decimal, price: Decimal) -> Decimal:
        # Reuse the frozen V7 phase target implementation; sizing is operational,
        # not a strategy rule, and uses only the completed decision price.
        phase = CyclePhaseClock().phase_at(at)[1]
        strategy = object.__new__(SwingCycleCoreBot)
        strategy._cfg = SwingCycleCoreConfig(operational_mode="paper")
        pct = strategy.target_for_phase(phase)
        return Decimal("0") if pct == 0 else (cash / price + btc)

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _write_state(self, state: dict[str, Any]) -> None:
        state["heartbeat_at"] = self.now().astimezone(timezone.utc).isoformat()
        _write_rendered_json(self.state_path, state)

    def cycle(self) -> dict[str, Any]:
        self.startup.validate_startup()
        if self.v6_status().get("active") is not False:
            raise PaperSafetyError("V6 became active while certified V7 was running")
        now = self.now().astimezone(timezone.utc)
        bars = self.candles()
        if not bars:
            raise PaperSafetyError("completed V7 candles are unavailable")
        if any(bar.timestamp >= int(now.timestamp() * 1000) - 3_600_000 for bar in bars):
            raise PaperSafetyError("incomplete candle is prohibited")
        if any(right.timestamp <= left.timestamp for left, right in zip(bars, bars[1:])):
            raise PaperSafetyError("duplicate or non-monotonic candle is prohibited")
        decision = datetime.fromtimestamp(bars[-1].timestamp / 1000, tz=timezone.utc)
        state = self._read_state()
        if decision.hour % 4:
            state.update(last_cycle="skipped_cadence", last_candle=decision.isoformat())
            self._write_state(state)
            return state
        if state.get("last_processed_candle") == decision.isoformat():
            state.update(last_cycle="duplicate", last_candle=decision.isoformat())
            self._write_state(state)
            return state
        age = (now - decision).total_seconds()
        if age > 5 * 3600:
            raise PaperSafetyError("stale completed candle")
        balances = self.runner.client.get_balance()
        cash, btc = Decimal(balances.get("USDT", "0")), Decimal(balances.get("BTC", "0"))
        target = self.target_for(decision, cash, btc, bars[-1].close)
        result: dict[str, Any] = {"last_candle": decision.isoformat(), "target_btc": str(target)}
        if target == btc:
            result["order"] = "not_required"
        else:
            intent = f"v7-{decision.strftime('%Y%m%dT%H%M%SZ')}"
            result["order"] = self.runner.submit_transition(
                intent_id=intent, target_btc=target, decision_at=decision,
                execution_at=now,
            )
        result.update(last_processed_candle=decision.isoformat(), last_cycle="reconciled")
        state.update(result)
        self._write_state(state)
        return state


def _write_rendered_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


class CertifiedV7DemoServiceManager:
    """Narrow wrapper around a Linux service interface for this unit only."""

    def __init__(self, linux: LinuxServiceInterface) -> None:
        self.linux = linux

    def inspect(self) -> dict[str, Any]:
        """Read-only status and identity inspection; no unit mutation occurs."""
        state = self.linux.inspect(SERVICE_NAME)
        identities = self.linux.process_identities(SERVICE_NAME)
        health = self.linux.health(SERVICE_NAME)
        return {
            "service": SERVICE_NAME,
            "state": state,
            "processes": identities,
            "duplicate_instance": len(identities) > 1,
            "health": health,
        }

    def install_inactive(
        self,
        *,
        render_inputs: UnitRenderInputs | None = None,
        app_dir: str | None = None,
        run_user: str | None = None,
    ) -> dict[str, Any]:
        state = self.linux.inspect(SERVICE_NAME)
        if state.get("active") is True:
            raise PaperSafetyError("refuse to replace an active certified V7 service")
        if render_inputs is None:
            if not app_dir or not run_user:
                raise PaperSafetyError("installation requires explicit render inputs")
            runtime = f"{app_dir}/data/runtime/v7_certified"
            render_inputs = UnitRenderInputs(
                run_user=run_user,
                app_dir=app_dir,
                python_path=f"{app_dir}/.venv/bin/python",
                environment_file="/etc/matibot/v7-demo.env",
                config_path=f"{runtime}/config.json",
                state_path=f"{runtime}/state.json",
                journal_path=f"{runtime}/journal.jsonl",
                evidence_path=f"{runtime}/evidence",
                report_path=f"{runtime}/reports",
            )
        unit = render_service_unit(render_inputs).text
        self.linux.install_unit(SERVICE_NAME, unit)
        self.linux.daemon_reload()
        self.linux.disable(SERVICE_NAME)
        return {
            "service": SERVICE_NAME,
            "installed": True,
            "enabled": False,
            "active": False,
        }

    def start(self, startup: CertifiedV7DemoServiceRunner) -> dict[str, Any]:
        startup.validate_startup()
        state = self.linux.inspect(SERVICE_NAME)
        if state.get("active") is True:
            raise PaperSafetyError("certified V7 service is already active")
        if len(self.linux.process_identities(SERVICE_NAME)):
            raise PaperSafetyError(
                "duplicate or stale certified V7 process prevents startup"
            )
        self.linux.start(SERVICE_NAME)
        identities = self.linux.process_identities(SERVICE_NAME)
        if (
            self.linux.inspect(SERVICE_NAME).get("active") is not True
            or len(identities) != 1
            or identities[0].get("instance_id") != SERVICE_INSTANCE_ID
        ):
            raise PaperSafetyError(
                "certified V7 service process identity is ambiguous after start"
            )
        return {"service": SERVICE_NAME, "active": True, "process": identities[0]}

    def stop(self) -> dict[str, Any]:
        self.linux.stop(SERVICE_NAME)
        if self.linux.inspect(SERVICE_NAME).get("active") is not False:
            raise PaperSafetyError("certified V7 service stop state is ambiguous")
        return {"service": SERVICE_NAME, "active": False}


def cutover_gateway(manager: CertifiedV7DemoServiceManager) -> ServiceGateway:
    """Adapt the completed cutover CLI to the dedicated service only."""
    return ServiceGateway(
        identity=lambda name: (
            manager.linux.inspect(name)
            if name == SERVICE_NAME
            else {"known": False, "active": None}
        ),
        status=lambda name: (
            manager.linux.inspect(name)
            if name == SERVICE_NAME
            else {"known": False, "active": None}
        ),
        start=lambda name: (
            manager.linux.start(name)
            if name == SERVICE_NAME
            else (_ for _ in ()).throw(PaperSafetyError("wrong service"))
        ),
        stop=lambda name: (
            manager.linux.stop(name)
            if name == SERVICE_NAME
            else (_ for _ in ()).throw(PaperSafetyError("wrong service"))
        ),
    )


def _read_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PaperSafetyError("required record is unavailable or invalid") from exc
    if not isinstance(record, dict):
        raise PaperSafetyError("required record is not an object")
    return record


def _write_rendered(path: Path, rendered: RenderedUnit) -> None:
    if not path.is_absolute():
        raise PaperSafetyError("render output path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered.text, encoding="utf-8", newline="\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("render", "install-inactive", "inspect", "start", "stop"))
    parser.add_argument("--run", action="store_true", help="run the dedicated certified V7 OKX Demo service")
    parser.add_argument("--linux-systemd", action="store_true", help="explicitly permit the Linux systemd gateway")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--unit", type=Path)
    parser.add_argument("--unit-hash")
    parser.add_argument("--activation", type=Path)
    parser.add_argument("--activation-hash")
    parser.add_argument("--lease", type=Path)
    parser.add_argument("--account", type=Path)
    for name in ("run-user", "app-dir", "python-path", "environment-file", "config-path", "state-path", "journal-path", "evidence-path", "report-path"):
        parser.add_argument(f"--{name}")
    return parser


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _gateway(args: Any, injected: LinuxSystemdGateway | None) -> LinuxSystemdGateway:
    if not args.linux_systemd:
        raise PaperSafetyError("Linux systemd mode must be explicitly requested")
    return injected or LinuxSystemdGateway()


def _require_activation_and_lease(args: Any) -> None:
    if not args.activation or not args.activation_hash or not args.lease:
        raise PaperSafetyError("start requires activation, activation hash, and account lease")
    activation = _read_record(args.activation)
    _verify_hash(activation, "activation_hash")
    if activation["activation_hash"] != args.activation_hash or not activation.get("active") or activation.get("paused"):
        raise PaperSafetyError("activation record is not valid for service start")
    lease = DemoAccountLease(args.lease).current()
    if not lease or lease.get("owner_strategy_id") != SERVICE_STRATEGY or lease.get("owner_instance_id") != SERVICE_INSTANCE_ID:
        raise PaperSafetyError("account lease is not owned by the certified V7 service")
    if activation.get("lease_hash") != lease.get("record_hash"):
        raise PaperSafetyError("activation record is not bound to the account lease")


def run(argv: Sequence[str] | None = None, *, gateway: LinuxSystemdGateway | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.run:
            if args.command is not None:
                raise PaperSafetyError("--run cannot be combined with a service management command")
            _run_service(args)
            return 0
        if args.command is None:
            raise PaperSafetyError("a service management command is required")
        if args.command == "render":
            if not args.output:
                raise PaperSafetyError("render requires an explicit output path")
            values = {field: getattr(args, field) for field in UnitRenderInputs.__dataclass_fields__}
            if any(value is None for value in values.values()):
                raise PaperSafetyError("render requires all unit runtime inputs")
            rendered = render_service_unit(UnitRenderInputs(**values))
            if args.dry_run:
                _emit({"command": "render", "content_hash": rendered.content_hash, "planned": True})
            else:
                _write_rendered(args.output, rendered)
                _emit({"command": "render", "content_hash": rendered.content_hash, "output": str(args.output)})
            return 0
        linux = _gateway(args, gateway)
        if args.command == "inspect":
            _emit({"service": SERVICE_NAME, "state": linux.inspect(SERVICE_NAME), "processes": linux.process_identities(SERVICE_NAME), "health": linux.health(SERVICE_NAME)})
            return 0
        if args.command == "install-inactive":
            if not args.unit or not args.unit_hash:
                raise PaperSafetyError("install-inactive requires unit and rendered-unit hash")
            result = linux.install_rendered_unit(args.unit, args.unit_hash, dry_run=args.dry_run)
            if not args.dry_run:
                linux.daemon_reload()
                linux.disable(SERVICE_NAME)
            _emit({"command": args.command, "service": SERVICE_NAME, "result": result, "disabled": True, "active": False})
            return 0
        if args.command == "start":
            _require_activation_and_lease(args)
            _emit({"command": "start", "service": SERVICE_NAME, "result": linux.start(SERVICE_NAME, dry_run=args.dry_run)})
            return 0
        _emit({"command": "stop", "service": SERVICE_NAME, "result": linux.stop(SERVICE_NAME, dry_run=args.dry_run)})
        return 0
    except (PaperSafetyError, DemoLeaseError) as exc:
        _emit({"command": "--run" if args.run else args.command, "error": str(exc), "status": "BLOCKED"})
        return 2


def _run_service(args: Any) -> None:
    """Validate the staged activation, adopt the baseline, then retain the lease.

    No inherited BTC is liquidated and every ownership change terminates the unit.
    """
    paths = (args.config_path, args.state_path, args.journal_path, args.evidence_path, args.report_path)
    if any(path is None for path in paths):
        raise PaperSafetyError("--run requires all isolated runtime paths")
    if any(not Path(path).is_absolute() or "v7_certified" not in str(path) for path in paths):
        raise PaperSafetyError("--run requires isolated absolute V7 paths")
    runtime = Path(args.config_path).parent
    activation = _read_record(runtime / "activation.json")
    account = _read_record(args.account or runtime / "account-observation.json")
    lease = DemoAccountLease(args.lease or runtime / "account_ownership.jsonl")
    from config.settings import Settings
    from core.okx_demo_client import OKXDemoClient
    from tools.v6_v7_demo_cutover import LinuxCutoverGateway
    root = Path.cwd()
    config = make_config(root, instance_id=SERVICE_INSTANCE_ID)
    client = OKXDemoClient(Settings(), mirror_name=SERVICE_INSTANCE_ID, runtime_dir=runtime)
    runner = V7OKXDemoRunner(config, client, lease, str(account.get("fingerprint", "")))
    systemd = LinuxCutoverGateway()
    guarded = CertifiedV7DemoServiceRunner(
        root=root, runner=runner,
        inputs=StartupInputs(activation=activation, account=account,
                             v6_service=systemd.status("matibot-v6-paper.service"),
                             shadow_service={"active": False}, lease=lease),
    )
    guarded.validate_startup()
    runner.adopt_account(target_btc=Decimal(str(account["btc"])), now=datetime.now(timezone.utc))
    loop = V7RuntimeLoop(
        startup=guarded, runner=runner,
        candles=lambda: client.get_ohlcv("BTC-USDT", timeframe="1H", limit=6000),
        v6_status=lambda: systemd.status("matibot-v6-paper.service"),
        state_path=Path(args.state_path),
    )
    while True:
        loop.cycle()
        time.sleep(30)


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
