import pytest

from core.certification_gate import CertificationGateError, manifest_fingerprint, validate_manifest


def _valid_manifest():
    document = {
        "status": "VALID", "manifest_complete": True,
        "execution_integrity_passed": True, "required_robustness_completed": True,
        "execution_contract": {}, "dataset": {}, "strategy_source_sha256": "x",
        "resolved_config_sha256": "x", "code_commit": "x", "working_tree_fingerprint": "x",
        "cases": {name: {"status": "PASS"} for name in (
            "integrity", "determinism", "adapter_parity", "buy_and_hold", "frozen_reference",
            "simplified_control", "sensitivity", "cost_stress", "delay_stress", "rolling_starts",
            "pseudo_oos", "block_bootstrap", "manifest_validation", "report_validation")},
    }
    document["manifest_sha256"] = manifest_fingerprint(document)
    document["record_id"] = document["manifest_sha256"]
    return document


def test_manifest_rejects_missing_required_case():
    document = _valid_manifest()
    document["cases"] = {}
    document["manifest_sha256"] = manifest_fingerprint(document)
    document["record_id"] = document["manifest_sha256"]
    with pytest.raises(CertificationGateError, match="required certification case incomplete"):
        validate_manifest(document)


@pytest.mark.parametrize("field", ["code_commit", "strategy_source_sha256"])
def test_manifest_rejects_tampering(field):
    document = _valid_manifest()
    document[field] = "tampered"
    with pytest.raises(CertificationGateError, match="fingerprint mismatch"):
        validate_manifest(document)
