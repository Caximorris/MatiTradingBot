import pytest

from core.certification_gate import CertificationGateError, validate_manifest


def test_manifest_rejects_missing_required_case():
    with pytest.raises(CertificationGateError, match="required certification case incomplete"):
        validate_manifest({
            "status": "VALID", "manifest_complete": True,
            "execution_integrity_passed": True, "required_robustness_completed": True,
            "execution_contract": {}, "dataset": {}, "strategy_source_sha256": "x",
            "resolved_config_sha256": "x", "code_commit": "x", "working_tree_fingerprint": "x",
            "cases": {},
        })
