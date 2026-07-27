import pytest

from core.certification_gate import CertificationGateError, manifest_fingerprint, require_paper_or_live_candidate, validate_manifest


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


def test_missing_v6_blocks_only_comparator_dependent_claims(tmp_path):
    document = _valid_manifest() | {"strategy": "swing_cycle_core", "comparator_integrity": "BLOCKED_UNAVAILABLE_EVIDENCE"}
    document["cases"]["frozen_reference"] = {"status": "UNAVAILABLE", "reason": "protected frozen-V6 funding snapshot unavailable"}
    document["manifest_sha256"] = manifest_fingerprint(document)
    document["record_id"] = document["manifest_sha256"]
    validate_manifest(document)  # execution/replication self-certification remains evaluable
    path = tmp_path / f"{document['record_id']}.json"
    path.write_text(__import__("json").dumps(document), encoding="utf-8")
    with pytest.raises(CertificationGateError, match="paper/live readiness blocked"):
        require_paper_or_live_candidate(path)


def test_unavailable_v6_cannot_be_relabeled_as_passing_statistics():
    document = _valid_manifest() | {"strategy": "swing_cycle_core", "comparator_integrity": "BLOCKED_UNAVAILABLE_EVIDENCE", "underperformance_vs_v6": "0.1"}
    document["cases"]["frozen_reference"] = {"status": "UNAVAILABLE", "reason": "protected frozen-V6 funding snapshot unavailable"}
    document["manifest_sha256"] = manifest_fingerprint(document)
    document["record_id"] = document["manifest_sha256"]
    with pytest.raises(CertificationGateError, match="V6-relative statistic"):
        validate_manifest(document)
