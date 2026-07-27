import pytest

from core.frozen_candidate import FrozenCandidateError, load_frozen_candidate


def test_v7_frozen_candidate_has_required_contract_and_stable_hash():
    candidate = load_frozen_candidate()
    assert candidate.bear_onset == 540
    assert candidate.accumulation == 900
    assert len(candidate.configuration_hash) == 64
    assert candidate.payload["fill_contract"].startswith("completed-bar")


@pytest.mark.parametrize("overrides", [
    {"phase_bear_start": 480}, {"phase_accumulation_start": 960},
    {"bear_onset": 600}, {"accumulation": 840},
])
def test_experiment_cannot_override_540_900_while_claiming_frozen_candidate(overrides):
    with pytest.raises(FrozenCandidateError, match="override rejected"):
        load_frozen_candidate().verify_overrides(overrides)
