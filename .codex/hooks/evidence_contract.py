"""Read-only provenance checks used by the research-integrity hook.

These checks intentionally never open raw journals.  A journal hash declared in a
manifest is treated as a reference; journal summaries remain the supported reader.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _inside(root: Path, value: Path) -> bool:
    try:
        value.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256.fullmatch(value))


def validate_manifest(root: Path, path: Path) -> tuple[bool, str]:
    """Validate an immutable manifest without reading its journal artifacts."""
    try:
        if not _inside(root, path) or not path.is_file():
            return False, "manifest path escapes repository or does not exist"
        document = json.loads(path.read_text(encoding="utf-8"))
        identity = document["identity"]
        result = document["result"]
        if document.get("schema_version") != 1 or not _is_hash(document.get("run_id")):
            return False, "manifest lacks a supported schema or run_id"
        if document["run_id"] != _canonical_sha256(identity):
            return False, "manifest run_id does not match its canonical identity"
        result_payload = {
            "metrics": result["metrics"],
            "trades_sha256": result["trades_sha256"],
            "equity_curve_sha256": result["equity_curve_sha256"],
        }
        if not all(_is_hash(result_payload[key]) for key in ("trades_sha256", "equity_curve_sha256")):
            return False, "manifest lacks result sequence hashes"
        if result.get("sha256") != _canonical_sha256(result_payload):
            return False, "manifest result hash does not match its payload"
        repository = identity["repository"]
        dataset = identity["dataset"]
        environment = identity["environment"]
        if not _is_hash(repository.get("worktree_sha256")) or not _is_hash(dataset.get("sha256")):
            return False, "manifest lacks repository or dataset identity"
        if not str(environment.get("python", "")).startswith(("3.12.", "3.13.")):
            return False, "manifest was not produced by a supported research interpreter"
        dependencies = environment.get("dependencies", {})
        if not isinstance(dependencies, dict) or any(value == "NOT_INSTALLED" for value in dependencies.values()):
            return False, "manifest has unresolved dependency identity"
        externals = identity.get("external_inputs", [])
        if not isinstance(externals, list):
            return False, "manifest external_inputs is malformed"
        for external in externals:
            if not isinstance(external, dict) or not isinstance(external.get("path"), str):
                return False, "manifest has malformed external input"
            if external.get("exists") and not _is_hash(external.get("sha256")):
                return False, "manifest has unhashed external input"
        strategy = identity.get("strategy", {})
        config = strategy.get("resolved_config", {})
        if strategy.get("resolved_name") == "swing_allocator":
            metrics = result_payload["metrics"]
            required_metrics = {"final_btc_qty", "bnh_initial_btc", "btc_vs_bnh_ratio"}
            if not required_metrics.issubset(metrics):
                return False, "Swing manifest lacks BTC-holder comparison metrics"
            if config.get("use_funding_overlay") and not any(
                item.get("exists") and "funding_bybit_" in item.get("path", "") for item in externals
            ):
                return False, "Swing funding overlay lacks a hashed Bybit input"
        artifacts = document.get("artifacts", [])
        if not isinstance(artifacts, list):
            return False, "manifest artifacts is malformed"
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not _is_hash(artifact.get("sha256")):
                return False, "manifest has malformed artifact hash"
            artifact_path = root / str(artifact.get("path", ""))
            if not _inside(root, artifact_path):
                return False, "manifest artifact escapes repository"
            if artifact.get("kind") != "journal" and not artifact_path.is_file():
                return False, "manifest references a missing non-journal artifact"
        return True, str(document["run_id"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"invalid manifest ({type(exc).__name__})"


def validate_report_provenance(
    root: Path, report: Path, manifest_paths: Iterable[Path]
) -> tuple[bool, str]:
    """Require a small report to cite both its source run id and result hash."""
    try:
        if not _inside(root, report) or not report.is_file() or report.stat().st_size > 1_000_000:
            return False, "report path is unsafe, missing, or too large for hook inspection"
        text = report.read_text(encoding="utf-8", errors="replace")
        sources: list[tuple[str, str]] = []
        for manifest_path in manifest_paths:
            valid, detail = validate_manifest(root, manifest_path)
            if not valid:
                return False, f"report source is invalid: {detail}"
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            sources.append((detail, document["result"]["sha256"]))
        if not sources:
            return False, "report has no validated source manifest"
        if not any(run_id in text and result_hash in text for run_id, result_hash in sources):
            return False, "report omits its source-manifest run_id or result hash"
        return True, "report provenance linked"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"invalid report provenance ({type(exc).__name__})"
