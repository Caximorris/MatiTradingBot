"""Deterministic provenance manifests for offline backtest evidence."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import tomllib
import uuid
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("backtests/manifests")


class ManifestError(RuntimeError):
    """A run cannot be recorded as complete and reproducible."""


def write_experiment_manifest(
    *,
    result: Any,
    requested_strategy: str,
    resolved_strategy: str,
    config_overrides: dict[str, Any],
    resolved_config: dict[str, Any],
    symbol: str,
    timeframe: str,
    requested_from: datetime,
    requested_to: datetime,
    warmup_bars: int,
    initial_balance: Decimal,
    cost_mode: str,
    fee_rate: Decimal,
    slippage_bps: Decimal,
    fill_next_open: bool,
    bars: Iterable[Any],
    artifacts: Iterable[str | Path] = (),
    external_inputs: Iterable[str | Path] = (),
    seed: int | None = None,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Build and atomically persist one schema-v1 manifest."""
    root = repo_root.resolve()
    bars_list = list(bars)
    repository = _repository_identity(root)
    environment = _environment_identity(root)
    dataset = _dataset_identity(bars_list, result.bars_tested)

    identity = {
        "harness": "cli.runner._run_backtest/v1",
        "repository": repository,
        "environment": environment,
        "strategy": {
            "requested": requested_strategy,
            "resolved_name": resolved_strategy,
            "config_overrides": config_overrides,
            "resolved_config": resolved_config,
        },
        "instrument": {"symbol": symbol, "timeframe": timeframe},
        "window": {
            "requested_from_utc": _utc_iso(requested_from),
            "requested_to_utc": _utc_iso(requested_to),
            "effective_start_utc": _utc_iso(result.start_date),
            "effective_end_utc": _utc_iso(result.end_date),
            "warmup_bars": warmup_bars,
        },
        "capital": {"initial_balance": initial_balance},
        "execution": {
            "cost_mode": cost_mode,
            "fee_rate": fee_rate,
            "slippage_bps": slippage_bps,
            "fill_next_open": fill_next_open,
            "market_fill": "next_bar_open" if fill_next_open else "decision_bar_close",
            "limit_fill": {
                "trigger": "bar_touch",
                "price": "limit_price",
                "quantity": "full",
                "price_improvement": False,
                "queue_model": False,
                "partial_fills": False,
            },
        },
        "dataset": dataset,
        "external_inputs": sorted(
            (_external_input_record(item, root) for item in external_inputs),
            key=lambda item: item["path"],
        ),
        "seed": seed,
    }
    normalized_identity = _normalize(identity)
    run_id = _sha256_json(normalized_identity)

    metrics = _result_metrics(result)
    result_payload = {
        "metrics": metrics,
        "trades_sha256": _sequence_hash(result.trades),
        "equity_curve_sha256": _sequence_hash(result.equity_curve),
    }
    result_section = {
        "sha256": _sha256_json(result_payload),
        **result_payload,
    }
    manifest = _normalize(
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "identity": normalized_identity,
            "result": result_section,
            "artifacts": [_artifact_record(item, root) for item in artifacts],
        }
    )

    output_dir = (root / MANIFEST_DIR).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{run_id}.json"
    if destination.exists():
        _validate_existing(destination, run_id, manifest["result"]["sha256"])
        return destination

    payload = _canonical_bytes(manifest) + b"\n"
    temporary = output_dir / f".{run_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            _validate_existing(destination, run_id, manifest["result"]["sha256"])
        temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _validate_existing(destination: Path, run_id: str, result_hash: str) -> None:
    try:
        existing = json.loads(destination.read_text(encoding="utf-8"))
        existing_hash = existing["result"]["sha256"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"existing manifest is invalid: {destination}") from exc
    if existing_hash != result_hash:
        raise ManifestError(f"run_id {run_id} already exists with a different result")


def _repository_identity(root: Path) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    tracked_diff = _git(root, "diff", "--binary", "HEAD", "--", ".")
    untracked_raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = sorted(path for path in untracked_raw.decode("utf-8").split("\0") if path)

    digest = hashlib.sha256()
    digest.update(b"head\0" + head.encode("ascii") + b"\0tracked\0" + tracked_diff)
    for relative in untracked:
        path = (root / relative).resolve()
        if not path.is_file() or not path.is_relative_to(root):
            continue
        digest.update(b"\0untracked\0" + relative.replace("\\", "/").encode("utf-8") + b"\0")
        digest.update(_file_sha256(path).encode("ascii"))

    return {
        "head": head,
        "dirty": bool(tracked_diff or untracked),
        "worktree_sha256": digest.hexdigest(),
    }


def _environment_identity(root: Path) -> dict[str, Any]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject.get("project", {}).get("dependencies", [])
    versions: dict[str, str] = {}
    for requirement in declared:
        name = re.split(r"[<>=!~;\[\s]", requirement, maxsplit=1)[0]
        if not name:
            raise ManifestError(f"invalid declared dependency: {requirement!r}")
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "NOT_INSTALLED"
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "dependencies": dict(sorted(versions.items(), key=lambda item: item[0].lower())),
    }


def _dataset_identity(bars: list[Any], bars_tested: int) -> dict[str, Any]:
    digest = hashlib.sha256()
    for bar in bars:
        record = [
            int(bar.timestamp),
            str(bar.open),
            str(bar.high),
            str(bar.low),
            str(bar.close),
            str(bar.volume),
        ]
        digest.update(_canonical_bytes(record) + b"\n")
    return {
        "sha256": digest.hexdigest(),
        "input_bars": len(bars),
        "tested_bars": bars_tested,
        "first_timestamp_ms": int(bars[0].timestamp) if bars else None,
        "last_timestamp_ms": int(bars[-1].timestamp) if bars else None,
    }


def _result_metrics(result: Any) -> dict[str, Any]:
    excluded = {"trades", "equity_curve"}
    if not is_dataclass(result):
        raise ManifestError("backtest result must be a dataclass")
    return {
        field.name: getattr(result, field.name)
        for field in fields(result)
        if field.name not in excluded
    }


def _artifact_record(value: str | Path, root: Path) -> dict[str, Any]:
    supplied = Path(value)
    absolute = supplied.resolve() if supplied.is_absolute() else (root / supplied).resolve()
    if not absolute.is_relative_to(root):
        raise ManifestError(f"artifact is outside repository: {value}")
    if not absolute.is_file():
        raise ManifestError(f"artifact does not exist: {value}")
    relative = absolute.relative_to(root).as_posix()
    return {
        "kind": "journal" if absolute.name.startswith("journal_") else "artifact",
        "path": relative,
        "sha256": _file_sha256(absolute),
        "size_bytes": absolute.stat().st_size,
    }


def _external_input_record(value: str | Path, root: Path) -> dict[str, Any]:
    supplied = Path(value)
    absolute = supplied.resolve() if supplied.is_absolute() else (root / supplied).resolve()
    if not absolute.is_relative_to(root):
        raise ManifestError(f"external input is outside repository: {value}")
    relative = absolute.relative_to(root).as_posix()
    if not absolute.exists():
        return {"path": relative, "exists": False, "sha256": None, "size_bytes": 0}
    if not absolute.is_file():
        raise ManifestError(f"external input is not a file: {value}")
    return {
        "path": relative,
        "exists": True,
        "sha256": _file_sha256(absolute),
        "size_bytes": absolute.stat().st_size,
    }


def _sequence_hash(values: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(_canonical_bytes(value) + b"\n")
    return digest.hexdigest()


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ManifestError("non-finite Decimal is not valid evidence")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ManifestError("non-finite float is not valid evidence")
        return value
    if isinstance(value, datetime):
        return _utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Path):
        if value.is_absolute():
            raise ManifestError("absolute paths are forbidden in manifests")
        return value.as_posix()
    if is_dataclass(value):
        return {field.name: _normalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ManifestError("manifest object keys must be strings")
            normalized[key] = _normalize(item)
        return dict(sorted(normalized.items()))
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    raise ManifestError(f"unsupported manifest value: {type(value).__name__}")


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ManifestError("manifest datetimes must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _normalize(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError("value cannot be encoded as canonical JSON") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ManifestError(f"git provenance failed: {' '.join(args)}") from exc
