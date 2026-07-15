from collections import Counter

from tools.ruff_ratchet import regressions


def test_ratchet_allows_debt_reduction() -> None:
    assert regressions(Counter({"a.py|F401": 1}), {"a.py|F401": 2}) == {}


def test_ratchet_rejects_new_or_increased_fingerprints() -> None:
    current = Counter({"a.py|F401": 3, "new.py|E701": 1})
    assert regressions(current, {"a.py|F401": 2}) == {
        "a.py|F401": (3, 2),
        "new.py|E701": (1, 0),
    }
