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
from datetime import date, datetime, timedelta, timezone
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
    external_contexts: Iterable[dict[str, Any]] = (),
    context_requirements: dict[str, bool] | None = None,
    seed: int | None = None,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Build and atomically persist one schema-v1 manifest."""
    root = repo_root.resolve()
    bars_list = list(bars)
    repository = _repository_identity(root)
    environment = _environment_identity(root)
    dataset = _dataset_identity(bars_list, result.bars_tested)
    external_records = sorted(
        (_external_input_record(item, root) for item in external_inputs),
        key=lambda item: item["path"],
    )
    context_records = sorted(
        (_external_context_record(item, root) for item in external_contexts),
        key=lambda item: (item["context_type"], item.get("market") or ""),
    )
    _validate_consumed_contexts(context_records)
    statuses = _context_statuses(context_requirements or {}, context_records)
    config_fingerprint = _sha256_json(
        {"overrides": config_overrides, "resolved": resolved_config}
    )
    identity = {
        "harness": "cli.runner._run_backtest/v1",
        "repository": repository,
        "environment": environment,
        "strategy": {
            "requested": requested_strategy,
            "resolved_name": resolved_strategy,
            "config_overrides": config_overrides,
            "resolved_config": resolved_config,
            "config_sha256": config_fingerprint,
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
        "external_inputs": external_records,
        "external_contexts": context_records,
        "external_context_statuses": statuses,
        "funding_slice": _funding_slice(
            external_records, requested_from, requested_to
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
def write_experiment_evidence(
    *,
    created_artifacts: Iterable[str | Path],
    external_context_builder: Any = None,
    **manifest_kwargs: Any,
) -> Path:
    """Publish a manifest or remove artifacts created by the failed run.
    Only caller-designated, newly-created artifacts under ``backtests/`` are
    eligible for cleanup. Historical reports and manifests are never touched.
    """
    root = Path(manifest_kwargs.get("repo_root", REPO_ROOT)).resolve()
    created = _created_artifact_paths(created_artifacts, root)
    try:
        if external_context_builder is not None:
            manifest_kwargs["external_contexts"] = external_context_builder()
        return write_experiment_manifest(**manifest_kwargs)
    except Exception as original_error:
        cleanup_errors: list[Path] = []
        for path in created:
            try:
                path.unlink()
            except OSError:
                cleanup_errors.append(path)
        if cleanup_errors:
            _write_incomplete_marker(root, created, original_error)
            paths = ", ".join(str(path.relative_to(root)) for path in cleanup_errors)
            raise ManifestError(
                f"manifest failed and generated evidence could not be removed: {paths}"
            ) from original_error
        _write_incomplete_marker(root, created, original_error)
        raise
def _write_incomplete_marker(root: Path, created: Iterable[Path], error: Exception) -> None:
    """Persist an explicitly non-certified outcome after removing generated evidence."""
    directory = root / "backtests" / "incomplete"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{uuid.uuid4().hex}.json"
    temporary = destination.with_suffix(".tmp")
    payload = _canonical_bytes({
        "status": "incomplete_uncertified",
        "created_artifacts_removed": [path.relative_to(root).as_posix() for path in created if not path.exists()],
        "created_artifacts_remaining": [path.relative_to(root).as_posix() for path in created if path.exists()],
        "failure_type": type(error).__name__,
        "failure_message": str(error)[:500],
    }) + b"\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except OSError as marker_error:
        temporary.unlink(missing_ok=True)
        raise ManifestError("manifest failed and incomplete marker could not be written") from marker_error
def external_context_requirements(strategy: str, config: dict[str, Any]) -> dict[str, bool]:
    """Declare external data dependencies for one resolved strategy configuration."""
    disabled = bool(config.get("disable_external_filters", False))
    swing = strategy == "swing_allocator"
    swing_funding_source = str(config.get("funding_overlay_source", "bybit")).lower()
    swing_uses_funding = swing and bool(config.get("use_funding_overlay"))
    requirements = {
        "macro": (strategy == "pro_trend" and not disabled)
        or (strategy == "scalp_momentum" and bool(config.get("use_macro_filter")))
        or (swing and bool(config.get("use_mvrv"))),
        "market": (strategy == "pro_trend" and not disabled)
        or (strategy == "scalp_momentum" and bool(config.get("use_market_filter")))
        or (swing and bool(config.get("use_vix") or config.get("use_dxy"))),
        "flow": swing and bool(config.get("use_flow_vol_overlay")),
        "okx_funding": (strategy == "pro_trend" and not disabled)
        or (swing_uses_funding and swing_funding_source == "okx"),
        "bybit_funding": strategy in {"basis_carry", "funding_extreme"}
        or (strategy == "prop_swing" and bool(config.get("model_funding")))
        or (swing_uses_funding and swing_funding_source == "bybit"),
    }
    if swing and str(config.get("phase_symbol", "")).upper() == "BTC-USDT":
        requirements["btc_phase"] = True
    return requirements
def capture_external_contexts(
    *, requirements: dict[str, bool], resolved_strategy: str, symbol: str, effective_from: datetime,
    effective_to: datetime, config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Read only the already-loaded, effective context slices after simulation."""
    records: list[dict[str, Any]] = []
    asset = symbol.split("-")[0].upper()
    if requirements.get("btc_phase"):
        from strategies.macro_context import btc_phase_signal
        observations = [
            (effective_from.isoformat(), btc_phase_signal(effective_from)["halving_phase"]),
            (effective_to.isoformat(), btc_phase_signal(effective_to)["halving_phase"]),
        ]
        records.append(_context_spec(
            "btc_phase", "BTC halving calendar", "BTC-USDT", effective_from, effective_to,
            observations, "strategies/macro_context.py", "btc_phase_signal.v1",
            loaded=True, consumed=True, coverage="covered", freshness="not_applicable",
        ))
    if requirements.get("macro"):
        from strategies import macro_context as macro
        context = macro._INSTANCES.get(asset)
        accessed_from, accessed_to, consumed = _access_window(
            macro._MANIFEST_ACCESSES, effective_from, effective_to, days_before=7
        )
        start = accessed_from.date()
        rows = [] if context is None else [
            (day.isoformat(), context._mvrv.get(day), context._realized.get(day))
            for day in sorted(set(context._mvrv) | set(context._realized))
            if start <= day <= accessed_to.date()
        ]
        records.append(_context_spec(
            "macro", "CoinMetrics Community API", asset, accessed_from, accessed_to, rows,
            "strategies/macro_context.py", "macro_context/MacroContext.v1",
            loaded=bool(context and context._loaded), consumed=consumed,
            coverage=_slice_coverage(rows, accessed_from, accessed_to, max_gap_days=7),
        ))
    if requirements.get("market"):
        from strategies import market_context as market
        accessed_from, accessed_to, consumed = _access_window(
            market._MANIFEST_ACCESSES, effective_from, effective_to,
            days_before=int(config.get("market_filter_lookback", 10)) + 5,
        )
        start, end = accessed_from.date().isoformat(), accessed_to.date().isoformat()
        for market_name, values in (("DXY", market._DXY_PRICES), ("NDX", market._NDX_PRICES), ("VIX", market._VIX_PRICES)):
            rows = [(day, values[day]) for day in sorted(values) if start <= day <= end]
            records.append(_context_spec(
                "market", "Yahoo Finance", market_name, accessed_from, accessed_to, rows,
                "strategies/market_context.py", "market_context/Yahoo.v1",
                loaded=market._LOADED_TO is not None, consumed=consumed,
                coverage=_slice_coverage(rows, accessed_from, accessed_to, max_gap_days=5),
            ))
    if requirements.get("flow"):
        from strategies import onchain_flow as flow
        key = symbol.upper()
        accessed_from, accessed_to, consumed = _access_window(
            flow._MANIFEST_ACCESSES.get(key, []), effective_from, effective_to
        )
        rows = [row for row in flow._ROWS.get(key, []) if int(accessed_from.timestamp() * 1000) <= row[0] <= int(accessed_to.timestamp() * 1000)]
        records.append(_context_spec(
            "flow", "CoinMetrics Community API", asset, accessed_from, accessed_to, rows,
            "strategies/onchain_flow.py", "onchain_flow/overlay.v1",
            loaded=key in flow._LOADED_RANGE, consumed=consumed,
            coverage=_slice_coverage(rows, accessed_from, accessed_to, max_gap_days=1),
        ))
    if requirements.get("okx_funding") and resolved_strategy != "swing_allocator":
        from strategies import funding_context as funding
        inst_id = funding._instrument_id(symbol)
        accessed_from, accessed_to, consumed = _access_window(
            funding._MANIFEST_ACCESSES.get(inst_id, []), effective_from, effective_to, days_before=5
        )
        snapshot = next((item for item in funding._SNAPSHOTS.get(inst_id, ()) if item.contains(accessed_from, accessed_to)), None)
        coverage_evidence = None if snapshot is None else funding.funding_coverage_manifest(snapshot, accessed_from)
        coverage_status = "missing" if coverage_evidence is None else coverage_evidence["coverage_status"]
        coverage = {"complete_covered_period": "covered", "proven_pre_listing": "pre_listing"}.get(coverage_status, "partial")
        records.append(_context_spec(
            "okx_funding", "OKX public funding-rate-history", inst_id, accessed_from, accessed_to,
            [] if snapshot is None else [(day, rate) for day, rate in sorted(snapshot.rates.items()) if accessed_from.date().isoformat() <= day <= accessed_to.date().isoformat()],
            "strategies/funding_context.py", "funding_context/snapshot.v1",
            loaded=snapshot is not None, consumed=consumed,
            coverage=coverage, freshness="fresh" if coverage in {"covered", "pre_listing"} else coverage,
            coverage_evidence=coverage_evidence,
        ))
    if (
        requirements.get("bybit_funding")
        or (requirements.get("okx_funding") and resolved_strategy == "swing_allocator")
        or resolved_strategy == "prop_swing"
    ):
        if resolved_strategy in {"basis_carry", "funding_extreme", "prop_swing"}:
            from strategies import funding_extreme as bybit
            path = bybit._ROOT / "data" / "cache" / f"funding_bybit_{symbol.replace('-', '').upper()}.json"
            markers = bybit._MANIFEST_CONSUMED.get(symbol.upper(), [])
            consumed = bool(markers)
            if -1 in markers:
                window = int(config.get("pctile_window", config.get("funding_window", 90))) * 8
                accessed_from, accessed_to = effective_from - timedelta(hours=window), effective_to
            elif markers:
                points = [datetime.fromtimestamp(item / 1000, tz=timezone.utc) for item in markers]
                accessed_from, accessed_to = min(points), max(points)
            else:
                accessed_from, accessed_to = effective_from, effective_to
            start_ms, end_ms = (int(value.timestamp() * 1000) for value in (accessed_from, accessed_to))
            rows = [row for row in bybit._MANIFEST_LOADS.get(symbol.upper(), []) if start_ms <= row[0] <= end_ms]
            loader_path, loader_version = "strategies/funding_extreme.py", "funding_extreme/load_funding.v1"
        else:
            from strategies import swing_funding_overlay as overlay
            source = str(config.get("funding_overlay_source", "bybit")).lower()
            path = overlay.funding_cache_path(symbol, source)
            accessed_from, accessed_to, consumed = _access_window(
                overlay.manifest_accesses(symbol, source), effective_from, effective_to,
                days_before=(int(config.get("funding_overlay_lookback_settlements", 90)) + 2) // 3,
            )
            try:
                rows = [
                    row for row in overlay.load_funding_rows(symbol, source)
                    if int(accessed_from.timestamp() * 1000) <= row[0] <= int(accessed_to.timestamp() * 1000)
                ]
            except Exception:
                rows = []
            loader_path = "strategies/swing_funding_overlay.py"
            loader_version = f"swing_funding_overlay/{source}.v2"
        end_ms = int(accessed_to.timestamp() * 1000)
        coverage_evidence = (
            overlay.manifest_coverage(symbol, source)
            if resolved_strategy == "swing_allocator" else getattr(bybit, "_MANIFEST_COVERAGE", {}).get(symbol.upper())
        )
        if coverage_evidence and coverage_evidence.get("coverage_status") == "proven_pre_listing":
            coverage, freshness, loaded = "pre_listing", "fresh", True
        elif not rows and path.exists() and not consumed:
            coverage, freshness, loaded = "covered", "not_applicable", True
        elif not rows:
            coverage, freshness, loaded = "missing", "missing", False
        elif _slice_coverage(rows, accessed_from, accessed_to, max_gap_days=1) == "partial":
            coverage, freshness, loaded = "partial", "partial", True
        elif end_ms - rows[-1][0] > 26 * 60 * 60 * 1000:
            coverage, freshness, loaded = "stale", "stale", True
        else:
            coverage, freshness, loaded = "covered", "fresh", True
        context_type = "okx_funding" if resolved_strategy == "swing_allocator" and source == "okx" else "bybit_funding"
        provider = f"{source.upper()} funding snapshot" if resolved_strategy == "swing_allocator" else "Bybit funding snapshot"
        market = overlay.funding_market(symbol, source) if resolved_strategy == "swing_allocator" else symbol
        records.append(_context_spec(
            context_type, provider, market, accessed_from, accessed_to, rows,
            loader_path, loader_version, loaded=loaded,
            consumed=consumed, configured=bool(requirements.get(context_type)),
            coverage=coverage, freshness=freshness, source_path=path,
            coverage_evidence=coverage_evidence,
        ))
    return records
def _context_spec(
    context_type: str, provider: str, market: str, effective_from: datetime, effective_to: datetime,
    observations: list[Any], loader_path: str, loader_version: str, *, loaded: bool,
    coverage: str, freshness: str = "not_applicable", source_path: Path | None = None,
    consumed: bool = True, configured: bool = True,
    coverage_evidence: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "context_type": context_type, "provider": provider, "market": market,
        "configured": configured, "loaded": loaded, "consumed": consumed,
        "effective_from": effective_from, "effective_to": effective_to,
        "observations": observations, "loader_path": loader_path,
        "loader_version": loader_version, "coverage": coverage,
        "freshness": freshness, "source_path": source_path,
        "coverage_evidence": coverage_evidence,
    }
def _access_window(
    accesses: Iterable[datetime | date], default_from: datetime, default_to: datetime, *, days_before: int = 0
) -> tuple[datetime, datetime, bool]:
    values = [
        value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        for value in accesses
    ]
    if not values:
        return default_from, default_to, False
    return min(values) - timedelta(days=days_before), max(values), True
def _slice_coverage(
    rows: Iterable[Any], effective_from: datetime, effective_to: datetime, *, max_gap_days: int
) -> str:
    values = list(rows)
    if not values:
        return "missing"
    timestamps: list[datetime] = []
    for row in values:
        value = row[0] if isinstance(row, (list, tuple)) else row
        if isinstance(value, int):
            timestamps.append(datetime.fromtimestamp(value / 1000, tz=timezone.utc))
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                timestamps.append(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc))
            except ValueError:
                return "invalid"
    allowed = timedelta(days=max_gap_days)
    ordered = sorted(timestamps)
    if ordered[0] > effective_from + allowed or ordered[-1] < effective_to - allowed:
        return "partial"
    return "covered" if all(right - left <= allowed for left, right in zip(ordered, ordered[1:])) else "partial"
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
    first_timestamp = int(bars[0].timestamp) if bars else None
    last_timestamp = int(bars[-1].timestamp) if bars else None
    return {
        "sha256": digest.hexdigest(),
        "input_bars": len(bars),
        "tested_bars": bars_tested,
        "first_timestamp_ms": first_timestamp,
        "last_timestamp_ms": last_timestamp,
        "coverage": {
            "first_utc": _timestamp_iso(first_timestamp),
            "last_utc": _timestamp_iso(last_timestamp),
        },
    }
def _result_metrics(result: Any) -> dict[str, Any]:
    excluded = {"trades", "equity_curve"}
    if not is_dataclass(result):
        raise ManifestError("backtest result must be a dataclass")
    metrics = {
        field.name: getattr(result, field.name)
        for field in fields(result)
        if field.name not in excluded
    }
    for name in (
        "final_asset_qty", "bnh_initial_asset", "asset_vs_bnh_ratio",
        "final_btc_qty", "bnh_initial_btc", "btc_vs_bnh_ratio",
    ):
        if hasattr(result, name):
            metrics[name] = getattr(result, name)
    return metrics
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
def _external_context_record(spec: dict[str, Any], root: Path) -> dict[str, Any]:
    required = {
        "context_type", "provider", "market", "configured", "loaded", "consumed",
        "effective_from", "effective_to", "observations", "loader_path", "loader_version",
        "coverage", "freshness",
    }
    if required - set(spec) or not isinstance(spec.get("observations"), list):
        raise ManifestError("external context provenance is incomplete")
    loader = (root / str(spec["loader_path"])).resolve()
    if not loader.is_relative_to(root) or not loader.is_file():
        raise ManifestError(f"external context loader is not a repository file: {spec['loader_path']}")
    source_file = spec.get("source_path")
    source_path: Path | None = None
    if source_file is not None:
        source_path = Path(source_file).resolve()
        if not source_path.is_relative_to(root) or not source_path.is_file():
            source_path = None
    observations = spec["observations"]
    coverage_evidence = spec.get("coverage_evidence")
    configured, loaded, consumed = (bool(spec[key]) for key in ("configured", "loaded", "consumed"))
    coverage, freshness = str(spec["coverage"]), str(spec["freshness"])
    if not configured and loaded and not consumed:
        status = "loaded_not_consumed"
    elif not configured:
        status = "not_configured"
    elif not loaded:
        status = coverage if coverage in {"missing", "stale", "invalid", "partial"} else "configured_not_loaded"
    elif not consumed:
        status = "loaded_not_consumed"
    elif coverage in {"missing", "stale", "invalid", "partial"}:
        status = coverage
    else:
        status = "consumed"
    ordered_hash = _sequence_hash(observations)
    bounds = [_observation_boundary(row) for row in observations]
    identity = {
        "context_type": spec["context_type"], "provider": spec["provider"],
        "market": spec["market"], "effective_from": spec["effective_from"],
        "effective_to": spec["effective_to"], "ordered_content_sha256": ordered_hash,
        "loader_source_sha256": _file_sha256(loader), "loader_version": spec["loader_version"],
        "coverage_evidence": coverage_evidence,
    }
    return {
        "context_type": str(spec["context_type"]), "provider": str(spec["provider"]),
        "market": str(spec["market"]), "status": status, "configured": configured,
        "loaded": loaded, "consumed": consumed,
        "affected_strategy_decisions": consumed and status == "consumed",
        "effective_window": {"from_utc": _utc_iso(spec["effective_from"]), "to_utc": _utc_iso(spec["effective_to"])},
        "earliest_observation": bounds[0] if bounds else None,
        "latest_observation": bounds[-1] if bounds else None,
        "record_count": len(observations), "ordered_content_sha256": ordered_hash,
        "snapshot_identity": _sha256_json(identity), "coverage": coverage,
        "freshness": freshness, "loader_version": str(spec["loader_version"]),
        "loader_source_file": loader.relative_to(root).as_posix(),
        "loader_source_sha256": _file_sha256(loader),
        "source_file": source_path.relative_to(root).as_posix() if source_path else None,
        "source_file_sha256": _file_sha256(source_path) if source_path else None,
        "coverage_evidence": coverage_evidence,
    }
def _observation_boundary(row: Any) -> Any:
    value = row[0] if isinstance(row, (tuple, list)) and row else row
    return _normalize(value) if isinstance(value, (datetime, date, Decimal, float, int, str)) else str(value)
def _validate_consumed_contexts(records: Iterable[dict[str, Any]]) -> None:
    for record in records:
        if record["consumed"] and record["status"] != "consumed":
            raise ManifestError(
                f"consumed external context is not certifiable: {record['context_type']} ({record['status']})"
            )
        if record["coverage"] == "pre_listing":
            from strategies.funding_coverage import CoverageEvidenceError, validate_manifest_coverage_record
            evidence = record.get("coverage_evidence") or {}
            required = {"source", "instrument", "venue", "funding_series_start_utc", "snapshot_identity", "content_sha256", "generated_at_utc", "validity_rule"}
            if evidence.get("coverage_status") != "proven_pre_listing" or not all(evidence.get(key) for key in required):
                raise ManifestError(f"pre-listing coverage lacks immutable evidence: {record['context_type']}")
            try:
                validate_manifest_coverage_record(evidence)
            except CoverageEvidenceError as exc:
                raise ManifestError(f"pre-listing coverage is invalid: {record['context_type']}") from exc
        if record["status"] == "consumed" and (
            record["coverage"] not in {"covered", "pre_listing"}
            or not record["ordered_content_sha256"]
            or not record["snapshot_identity"]
            or not record["loader_source_sha256"]
        ):
            raise ManifestError(f"consumed external context lacks identity evidence: {record['context_type']}")
def _context_statuses(
    requirements: dict[str, bool], records: list[dict[str, Any]]
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for context_type, required in sorted(requirements.items()):
        matching = [record["status"] for record in records if record["context_type"] == context_type]
        if not required:
            statuses[context_type] = "not_configured"
        elif not matching:
            raise ManifestError(f"required external context was not recorded: {context_type}")
        elif any(status in {"invalid", "stale", "missing", "partial", "configured_not_loaded"} for status in matching):
            statuses[context_type] = next(
                status for status in ("invalid", "stale", "missing", "partial", "configured_not_loaded") if status in matching
            )
        elif all(status == "loaded_not_consumed" for status in matching):
            statuses[context_type] = "loaded_not_consumed"
        elif all(status == "consumed" for status in matching):
            statuses[context_type] = "consumed"
        else:
            statuses[context_type] = "configured_not_loaded"
    return statuses
def _external_input_record(value: str | Path, root: Path) -> dict[str, Any]:
    supplied = Path(value)
    absolute = supplied.resolve() if supplied.is_absolute() else (root / supplied).resolve()
    if not absolute.is_relative_to(root):
        raise ManifestError(f"external input is outside repository: {value}")
    relative = absolute.relative_to(root).as_posix()
    kind = "funding" if absolute.name.startswith("funding_bybit_") else "file"
    if not absolute.exists():
        return {
            "kind": kind,
            "path": relative,
            "exists": False,
            "sha256": None,
            "size_bytes": 0,
            "coverage": None,
        }
    if not absolute.is_file():
        raise ManifestError(f"external input is not a file: {value}")
    return {
        "kind": kind,
        "path": relative,
        "exists": True,
        "sha256": _file_sha256(absolute),
        "size_bytes": absolute.stat().st_size,
        "coverage": _funding_coverage(absolute) if kind == "funding" else None,
    }
def _funding_coverage(path: Path) -> dict[str, Any]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ManifestError(f"funding input is unreadable: {path}") from exc
    if not isinstance(rows, list) or not rows:
        raise ManifestError(f"funding input is empty: {path}")
    timestamps: list[int] = []
    for row in rows:
        try:
            timestamp_ms, rate = int(row[0]), float(row[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise ManifestError(f"funding input has an invalid row: {path}") from exc
        if timestamp_ms <= 0 or not math.isfinite(rate):
            raise ManifestError(f"funding input has an invalid value: {path}")
        timestamps.append(timestamp_ms)
    first_timestamp = min(timestamps)
    last_timestamp = max(timestamps)
    return {
        "settlement_count": len(timestamps),
        "first_settlement_ms": first_timestamp,
        "last_settlement_ms": last_timestamp,
        "first_settlement_utc": _timestamp_iso(first_timestamp),
        "last_settlement_utc": _timestamp_iso(last_timestamp),
    }
def _funding_slice(
    external_records: Iterable[dict[str, Any]], from_dt: datetime, to_dt: datetime
) -> list[dict[str, Any]]:
    return [
        {
            "path": record["path"],
            "requested_from_utc": _utc_iso(from_dt),
            "requested_to_utc": _utc_iso(to_dt),
            "coverage": record["coverage"],
            "availability": "point_in_time_settlements_only",
        }
        for record in external_records
        if record["kind"] == "funding"
    ]
def _created_artifact_paths(
    values: Iterable[str | Path], root: Path
) -> tuple[Path, ...]:
    paths: list[Path] = []
    evidence_root = (root / "backtests").resolve()
    manifest_root = (root / MANIFEST_DIR).resolve()
    for value in values:
        supplied = Path(value)
        absolute = supplied.resolve() if supplied.is_absolute() else (root / supplied).resolve()
        if (
            not absolute.is_relative_to(evidence_root)
            or absolute.is_relative_to(manifest_root)
            or not absolute.is_file()
        ):
            raise ManifestError(f"created artifact is not removable generated evidence: {value}")
        paths.append(absolute)
    return tuple(dict.fromkeys(paths))
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
def _timestamp_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
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
