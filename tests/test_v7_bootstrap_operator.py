from tools.v7_robustness_suite import BLOCKS, REPLICATIONS, bootstrap_status, completion_summary


def _state(count: int) -> dict:
    return {"bootstrap": {f"{family}_{block}h": {"replications": {"completed": {str(i): {} for i in range(count)}, "failed": {}, "invalid": {}}}
                          for family in ("moving", "stationary") for block in BLOCKS}}


def test_bootstrap_status_counts_terminal_and_pending_without_legacy_rows():
    rows = bootstrap_status(_state(3))
    assert len(rows) == 8
    assert rows[0] == {"family": "moving", "block_hours": 24, "completed": 3, "failed": 0,
                       "invalid": 0, "pending": REPLICATIONS - 3, "total": REPLICATIONS}


def test_completion_requires_exactly_all_primary_cases_terminal():
    assert not completion_summary(_state(REPLICATIONS - 1))["complete"]
    assert completion_summary(_state(REPLICATIONS))["complete"]
