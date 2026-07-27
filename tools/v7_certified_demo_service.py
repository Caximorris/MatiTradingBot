#!/usr/bin/env python
"""Dedicated, fail-closed systemd boundary for the certified V7 OKX Demo candidate.

No subprocess, VM, exchange, or credential construction occurs in this module.
Callers inject the Linux service manager and the already-constructed certified
runner.  Direct execution is deliberately blocked.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from core.demo_account_lease import DemoAccountLease
from core.v7_certified_paper import PaperSafetyError, make_config
from core.v7_okx_demo import V7OKXDemoRunner
from tools.v6_v7_demo_cutover import ServiceGateway


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


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _verify_hash(record: dict[str, Any], field: str) -> None:
    unsigned = dict(record)
    supplied = unsigned.pop(field, None)
    if not isinstance(supplied, str) or supplied != canonical_hash(unsigned):
        raise PaperSafetyError(f"tampered or incomplete {field} record")


def _linux_path(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or "\\" in value or "\r" in value or "\n" in value:
        raise PaperSafetyError(
            "systemd definition requires an absolute Linux application path"
        )
    return str(path)


def render_service_definition(*, app_dir: str, run_user: str) -> str:
    """Generate a credential-free, disabled-by-default dedicated systemd unit."""
    app_dir = _linux_path(app_dir)
    if not run_user or any(char.isspace() for char in run_user):
        raise PaperSafetyError("systemd definition requires a simple run user")
    unit = f"""[Unit]
Description=MatiTradingBot certified V7 OKX Demo candidate (inactive by default)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={run_user}
WorkingDirectory={app_dir}
Environment=PYTHONUNBUFFERED=1
ExecStart={app_dir}/.venv/bin/python tools/v7_certified_demo_service.py --run
Restart=on-failure
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true
MemoryMax=350M

[Install]
WantedBy=multi-user.target
"""
    if any(marker in unit.lower() for marker in _FORBIDDEN_UNIT_TEXT):
        raise PaperSafetyError("credentials are forbidden in systemd definitions")
    return unit


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

    def install_inactive(self, *, app_dir: str, run_user: str) -> dict[str, Any]:
        state = self.linux.inspect(SERVICE_NAME)
        if state.get("active") is True:
            raise PaperSafetyError("refuse to replace an active certified V7 service")
        unit = render_service_definition(app_dir=app_dir, run_user=run_user)
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


def main() -> int:
    raise SystemExit("blocked: certified V7 service dependencies must be injected")


if __name__ == "__main__":
    main()
