"""Read-only, injectable V6 runtime and OKX Demo observation adapters."""

from __future__ import annotations

import hashlib
import json
import argparse
import os
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from core.v7_certified_paper import PaperSafetyError
from tools.v6_v7_demo_cutover import V6_NAME, canonical_hash

V6_SERVICE = "matibot-v6-paper.service"
_SECRET = ("secret", "password", "passphrase", "api_key", "private_key", "access_token", "credential")
_PRESENCE_MARKERS = frozenset({
    "demo_api_key_present", "demo_secret_present", "demo_passphrase_present",
})


class ReadOnlyService(Protocol):
    def inspect(self, name: str) -> dict[str, Any]: ...
    def process_identities(self, name: str) -> list[dict[str, Any]]: ...


class OKXDemoReadOnlyFacade:
    """Capability-minimal wrapper; intentionally contains no trading operations."""

    def __init__(
        self,
        *,
        balance,
        positions,
        open_orders,
        order_history,
        account_id: str = "demo",
        precision: dict | None = None,
        minimum_size: dict | None = None,
    ) -> None:
        self._balance, self._positions = balance, positions
        self._open_orders, self._order_history = open_orders, order_history
        self.account_id, self.precision, self.minimum_size = (
            account_id,
            precision or {},
            minimum_size or {},
        )
        self.is_paper, self.endpoint = True, "okx_demo"

    def get_balance(self):
        return self._balance()

    def get_positions(self):
        return self._positions()

    def get_open_orders(self, symbol):
        return self._open_orders(symbol)

    def get_order_history(self, symbol, limit=20):
        return self._order_history(symbol, limit=limit)


def validate_demo_runtime_config(value: dict[str, Any]) -> None:
    _safe(value)
    endpoint = str(value.get("okx_demo_domain", ""))
    if (
        value.get("trading_mode") != "paper"
        or value.get("simulated_trading") is not True
        or value.get("demo_confirmed") is not True
    ):
        raise PaperSafetyError("runtime is not explicitly confirmed as OKX Demo")
    if endpoint not in {"https://www.okx.com", "https://my.okx.com"}:
        raise PaperSafetyError("unapproved or production OKX endpoint")
    if any(type(value.get(key)) is not bool or value[key] is not True for key in _PRESENCE_MARKERS):
        raise PaperSafetyError("required demo credentials are unavailable")


class LinuxV6ReadOnlyGateway:
    """Explicit Linux-only, inspection-only systemd adapter for the V6 unit."""

    def __init__(self, runner=subprocess.run, timeout: float = 15.0) -> None:
        self.runner, self.timeout = runner, timeout

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PaperSafetyError("systemd inspection timed out") from exc

    def inspect(self, name: str) -> dict[str, Any]:
        if name != V6_SERVICE:
            raise PaperSafetyError("unknown V6 service identity")
        active = self._run(["systemctl", "is-active", name])
        enabled = self._run(["systemctl", "is-enabled", name])
        return {
            "known": active.returncode != 4 and enabled.returncode != 4,
            "active": active.returncode == 0,
            "enabled": enabled.returncode == 0,
        }

    def process_identities(self, name: str) -> list[dict[str, Any]]:
        if name != V6_SERVICE:
            raise PaperSafetyError("unknown V6 service identity")
        result = self._run(["systemctl", "show", "--property=MainPID", "--value", name])
        pid = result.stdout.strip()
        return [] if not pid or pid == "0" else [{"pid": pid}]


def _safe(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).lower()
            if name in _PRESENCE_MARKERS:
                if type(child) is not bool:
                    raise PaperSafetyError("credential presence marker must be boolean")
                continue
            if any(word in name for word in _SECRET):
                raise PaperSafetyError("credential-shaped output is prohibited")
            _safe(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _safe(child)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PaperSafetyError(
            "required runtime JSON is unavailable or invalid"
        ) from exc
    if not isinstance(value, dict):
        raise PaperSafetyError("required runtime JSON must be an object")
    _safe(value)
    return value


def _summary(path: Path) -> dict[str, Any]:
    """Integrity-only JSONL summary; never returns raw journal rows."""
    if not path.is_file():
        raise PaperSafetyError("V6 journal is unavailable")
    digest, rows, unresolved = hashlib.sha256(), 0, False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError
            _safe(row)
            rows += 1
            digest.update(line.encode())
            unresolved |= row.get("status") in {"pending", "ambiguous", "unreconciled"}
    except ValueError as exc:
        raise PaperSafetyError("V6 journal is corrupt") from exc
    return {
        "path": str(path),
        "row_count": rows,
        "sha256": digest.hexdigest(),
        "unresolved": unresolved,
    }


def collect_v6_runtime(
    *,
    config_path: Path,
    state_path: Path,
    journal_path: Path,
    service: ReadOnlyService,
    source_commit: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    config, state = _json(config_path), _json(state_path)
    if config.get("execution") != "okx_demo" or config.get("mode") not in {
        "paper",
        "okx_demo",
        None,
    }:
        raise PaperSafetyError("V6 configuration is not confirmed OKX Demo paper mode")
    if config.get("strategy") not in {None, V6_NAME} or config.get("instance_id") in (
        None,
        "",
    ):
        raise PaperSafetyError("V6 configuration identity is missing or ambiguous")
    status = service.inspect(V6_SERVICE)
    identities = service.process_identities(V6_SERVICE)
    if not status.get("known") or status.get("active") is not True:
        raise PaperSafetyError("V6 service is unknown or inactive")
    if len(identities) != 1 or identities[0].get("instance_id") not in {
        None,
        config["instance_id"],
    }:
        raise PaperSafetyError("V6 process identity is ambiguous")
    if (
        state.get("pending")
        or state.get("pending_order")
        or state.get("state") == "ERROR_LOCKED"
        or state.get("locked")
    ):
        raise PaperSafetyError("V6 runtime has pending or locked state")
    candle = state.get("last_completed_candle")
    if not candle or state.get("data_fresh") is False:
        raise PaperSafetyError("V6 completed-candle freshness is unavailable")
    runtime = {
        "schema": "v6-runtime-observation/v1",
        "collected_at": (now or datetime.now(timezone.utc)).isoformat(),
        "service": {**status, "name": V6_SERVICE, "process": identities[0]},
        "source_commit": source_commit,
        "config": config,
        "state": state,
        "journal": _summary(journal_path),
    }
    runtime["content_hash"] = canonical_hash(runtime)
    return runtime


def observe_okx_demo_account(
    client: Any, *, symbol: str, now: datetime | None = None
) -> dict[str, Any]:
    """Use only observation methods from the existing OKXDemoClient contract."""
    required = (
        "get_balance", "get_positions", "get_open_orders", "get_order_history",
        "get_fills", "get_instrument", "get_position_mode", "get_fee_metadata",
    )
    if any(not callable(getattr(client, method, None)) for method in required):
        raise PaperSafetyError("incomplete OKX Demo client contract")
    if getattr(client, "is_paper", True) is not True or getattr(
        client, "endpoint", "okx_demo"
    ) not in {"okx_demo", "demo"}:
        raise PaperSafetyError("production endpoint is prohibited")
    balances = client.get_balance()
    if not isinstance(balances, dict) or not balances:
        raise PaperSafetyError("OKX Demo balances are unavailable or ambiguous")
    _safe(balances)
    cash, btc = balances.get("USDT", Decimal("0")), balances.get("BTC", Decimal("0"))
    unsupported = {
        key: str(value)
        for key, value in balances.items()
        if key not in {"USDT", "BTC"} and Decimal(str(value)) != 0
    }
    instrument = client.get_instrument(symbol)
    if not isinstance(instrument, dict):
        raise PaperSafetyError("instrument metadata is unavailable or ambiguous")
    _safe(instrument)
    account = {
        "schema": "okx-demo-account-observation/v1",
        "observed_at": (now or datetime.now(timezone.utc)).isoformat(),
        "exchange": "OKX",
        "environment": "demo",
        "simulated_trading": True,
        "endpoint": "okx_demo",
        "demo_confirmed": True,
        "fingerprint": hashlib.sha256(
            (str(getattr(client, "account_id", "demo")) + symbol).encode()
        ).hexdigest()[:16],
        "cash": str(cash),
        "btc": str(btc),
        "target": str(btc),
        "open_orders": client.get_open_orders(symbol),
        "positions": client.get_positions(),
        "recent_orders": client.get_order_history(symbol, limit=20),
        "recent_fills": client.get_fills(symbol, limit=20),
        "fee_metadata": client.get_fee_metadata(symbol),
        "position_mode": client.get_position_mode(),
        "unsupported_assets": unsupported,
        "available_balance": str(cash),
        "precision": {"tick_size": instrument.get("tickSz"), "lot_size": instrument.get("lotSz")},
        "minimum_size": {"minimum_size": instrument.get("minSz")},
    }
    _safe(account)
    account["observation_hash"] = canonical_hash(account)
    return account


def build_v6_audit_inputs(
    runtime: dict[str, Any], account: dict[str, Any], destination: Path
) -> dict[str, Any]:
    _safe((runtime, account))
    if runtime.get("content_hash") != canonical_hash(
        {key: value for key, value in runtime.items() if key != "content_hash"}
    ) or account.get("observation_hash") != canonical_hash(
        {key: value for key, value in account.items() if key != "observation_hash"}
    ):
        raise PaperSafetyError("runtime or account observation hash is invalid")
    destination.mkdir(parents=True, exist_ok=True)
    config, state = runtime["config"], runtime["state"]
    files = {
        "v6-config.json": config,
        "v6-state.json": state,
        "account-observation.json": account,
    }
    hashes = {}
    for name, value in files.items():
        text = json.dumps(value, sort_keys=True, indent=2)
        (destination / name).write_text(text, encoding="utf-8", newline="\n")
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = {
        "schema": "v6-audit-inputs/v1",
        "files": hashes,
        "source_commit": runtime["source_commit"],
        "instance_id": config["instance_id"],
        "service_identity": runtime["service"],
        "account_fingerprint": account["fingerprint"],
        "collection_timestamp": runtime["collected_at"],
        "demo_confirmed": account["demo_confirmed"],
        "verdict": "PASS",
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
    )
    return manifest


def _emit(value: dict[str, Any], as_json: bool) -> None:
    print(
        json.dumps(value, sort_keys=True)
        if as_json
        else json.dumps(value, indent=2, sort_keys=True)
    )


def _path(value: str) -> Path:
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "collect-v6-runtime",
            "observe-okx-demo-account",
            "build-v6-audit-inputs",
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--linux-runtime", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--service-name", default=V6_SERVICE)
    parser.add_argument("--repository-path")
    parser.add_argument("--config-path")
    parser.add_argument("--state-path")
    parser.add_argument("--journal-path")
    parser.add_argument("--runtime-observation")
    parser.add_argument("--account-observation")
    parser.add_argument("--output")
    parser.add_argument("--symbol", default="BTC-USDT")
    parser.add_argument("--source-commit")
    parser.add_argument("--mock-input")
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--okx-demo-runtime", action="store_true")
    parser.add_argument("--runtime-config")
    return parser


def run(
    argv: list[str] | None = None,
    *,
    service: ReadOnlyService | None = None,
    client: Any = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "collect-v6-runtime":
            if args.service_name != V6_SERVICE or not all(
                (
                    args.repository_path,
                    args.config_path,
                    args.state_path,
                    args.journal_path,
                    args.output,
                    args.source_commit,
                )
            ):
                raise PaperSafetyError(
                    "collect-v6-runtime requires the dedicated V6 service and explicit paths"
                )
            if not args.linux_runtime and service is None:
                raise PaperSafetyError("Linux runtime must be explicitly requested")
            gateway = service or LinuxV6ReadOnlyGateway()
            result = collect_v6_runtime(
                config_path=_path(args.config_path),
                state_path=_path(args.state_path),
                journal_path=_path(args.journal_path),
                service=gateway,
                source_commit=args.source_commit,
            )
            if not args.dry_run:
                _path(args.output).write_text(
                    json.dumps(result, sort_keys=True, indent=2), encoding="utf-8"
                )
        elif args.command == "observe-okx-demo-account":
            if args.test_mode and args.okx_demo_runtime:
                raise PaperSafetyError(
                    "test mode and OKX Demo runtime are mutually exclusive"
                )
            if args.mock_input and not args.test_mode:
                raise PaperSafetyError("mock input requires explicit test mode")
            if args.okx_demo_runtime:
                if not args.runtime_config:
                    raise PaperSafetyError(
                        "OKX Demo runtime requires runtime configuration"
                    )
                validate_demo_runtime_config(_json(_path(args.runtime_config)))
                if client is None:
                    from tools.okx_demo_readonly import OKXDemoReadOnlyClient

                    runtime = _json(_path(args.runtime_config))
                    runtime |= {
                        "demo_api_key": os.getenv("OKX_DEMO_API_KEY"),
                        "demo_secret": os.getenv("OKX_DEMO_SECRET_KEY"),
                        "demo_passphrase": os.getenv("OKX_DEMO_PASSPHRASE"),
                    }
                    client = OKXDemoReadOnlyClient(runtime)
            if client is None:
                if not args.mock_input:
                    raise PaperSafetyError(
                        "authenticated observation requires an injected read-only demo facade"
                    )

                class MockClient:
                    is_paper, endpoint = True, "okx_demo"

                    def __init__(self, value):
                        self.value = value

                    def get_balance(self):
                        return {
                            k: Decimal(str(v))
                            for k, v in self.value["balances"].items()
                        }

                    def get_positions(self):
                        return self.value.get("positions", [])

                    def get_open_orders(self, _):
                        return self.value.get("open_orders", [])

                    def get_order_history(self, _, limit=20):
                        return self.value.get("recent_orders", [])[:limit]

                    def place_order(self, *_a, **_k):
                        raise AssertionError("forbidden")

                client = MockClient(_json(_path(args.mock_input)))
            if not args.output:
                raise PaperSafetyError("observation requires --output")
            result = observe_okx_demo_account(client, symbol=args.symbol)
            if not args.dry_run:
                _path(args.output).write_text(
                    json.dumps(result, sort_keys=True, indent=2), encoding="utf-8"
                )
        else:
            if not all(
                (args.runtime_observation, args.account_observation, args.output)
            ):
                raise PaperSafetyError("bundle requires both observations and output")
            result = build_v6_audit_inputs(
                _json(_path(args.runtime_observation)),
                _json(_path(args.account_observation)),
                _path(args.output),
            )
        _emit(result, args.json)
        return 0
    except (PaperSafetyError, OSError, ValueError) as exc:
        _emit({"status": "BLOCKED", "error": str(exc)}, True)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
