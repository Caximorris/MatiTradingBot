"""Manifest, reporting, and promotion gates for certified candidates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_CASES = (
    "integrity", "determinism", "adapter_parity", "buy_and_hold",
    "frozen_reference", "simplified_control", "sensitivity", "cost_stress",
    "delay_stress", "rolling_starts", "pseudo_oos", "block_bootstrap",
    "manifest_validation", "report_validation",
)


class CertificationGateError(RuntimeError):
    pass


def manifest_fingerprint(document: dict[str, Any]) -> str:
    canonical = {key: value for key, value in document.items()
                 if key not in {"manifest_sha256", "record_id"}}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def validate_manifest(document: dict[str, Any]) -> None:
    required = {"status", "manifest_complete", "execution_integrity_passed",
                "required_robustness_completed", "execution_contract", "dataset",
                "strategy_source_sha256", "resolved_config_sha256", "code_commit",
                "working_tree_fingerprint", "cases", "manifest_sha256", "record_id"}
    missing = sorted(required - set(document))
    if missing:
        raise CertificationGateError(f"certification manifest missing: {', '.join(missing)}")
    if document["status"] != "VALID" or not all(document[key] for key in (
        "manifest_complete", "execution_integrity_passed", "required_robustness_completed"
    )):
        raise CertificationGateError("candidate certification is not valid")
    fingerprint = manifest_fingerprint(document)
    if document["manifest_sha256"] != fingerprint or document["record_id"] != fingerprint:
        raise CertificationGateError("certification manifest fingerprint mismatch")
    cases = document["cases"]
    for name in REQUIRED_CASES:
        value = cases.get(name)
        if not isinstance(value, dict) or value.get("status") not in {"PASS", "NOT_APPLICABLE"}:
            raise CertificationGateError(f"required certification case incomplete: {name}")
        if value["status"] == "NOT_APPLICABLE" and not value.get("reason"):
            raise CertificationGateError(f"inapplicable case lacks reason: {name}")


def load_valid_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CertificationGateError("certification manifest unreadable") from exc
    validate_manifest(document)
    if path.stem != document["record_id"]:
        raise CertificationGateError("certification manifest filename identity mismatch")
    return document


def require_certified_candidate(path: Path) -> dict[str, Any]:
    """Common gate for reports, shadow, paper, and live dry-run registration."""
    return load_valid_manifest(path)
