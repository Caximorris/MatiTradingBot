from __future__ import annotations

from pathlib import Path

from tools.paper_bots import (
    bot_label,
    count_strategy_events,
    filter_rebalances,
    is_operable_bot_name,
    paper_state_path,
    resolve_bot,
    safe_state_name,
)

RUNTIME = Path("data") / "runtime"


def test_bot_label_prefers_instance_id_then_name_then_legacy():
    assert bot_label("swing_allocator_v6_btc_usdt", {"instance_id": "v6"}) == "v6"
    assert bot_label("swing_allocator_v5_btc_usdt", {}) == "v5"          # del nombre
    assert bot_label("swing_allocator_btc_usdt", None) == "legacy"       # sin version
    assert bot_label("swing_allocator_demo_btc_usdt", None) == "demo"
    assert bot_label("prop_swing_btc_usdt", None) == "prop"


def test_count_strategy_events_excludes_reconciliation_rows():
    events = [
        {"direction": "INIT"}, {"direction": "SELL"}, {"direction": "RECONCILE"},
    ]
    assert count_strategy_events(events) == 2


def test_paper_state_path_isolated_vs_legacy():
    assert paper_state_path("swing_v6", RUNTIME) == RUNTIME / "paper_state_swing_v6.json"
    assert paper_state_path(None, RUNTIME) == RUNTIME / "paper_state.json"
    # mismo saneado que core/exchange.OKXClient._safe_state_name
    assert paper_state_path("Prop/CFT", RUNTIME).name == "paper_state_prop_cft.json"


def test_safe_state_name_matches_exchange_rules():
    assert safe_state_name("swing_V6") == "swing_v6"
    assert safe_state_name("a/b c") == "a_b_c"
    assert safe_state_name("___") == "default"


def test_operable_bot_name_excludes_internal_state_rows():
    assert is_operable_bot_name("swing_allocator_v6_btc_usdt", "BTC-USDT") is True
    assert is_operable_bot_name("swing_allocator_demo_btc_usdt", "BTC-USDT") is True
    assert is_operable_bot_name("prop_swing_btc_usdt", "BTC-USDT") is True
    assert is_operable_bot_name("swing_allocator_v6", "BTC-USDT") is False
    assert is_operable_bot_name("swing_allocator_demo", "BTC-USDT") is False
    assert is_operable_bot_name("prop_swing", "BTC-USDT") is False


def _bots():
    return [
        {"label": "v5", "name": "swing_allocator_v5_btc_usdt"},
        {"label": "v6", "name": "swing_allocator_v6_btc_usdt"},
        {"label": "legacy", "name": "swing_allocator_btc_usdt"},
    ]


def test_resolve_bot_by_label_and_substring_and_ambiguity():
    bots = _bots()
    assert resolve_bot("v6", bots)["name"] == "swing_allocator_v6_btc_usdt"
    assert resolve_bot("V6", bots)["label"] == "v6"                 # case-insensitive
    assert resolve_bot("nope", bots) is None
    # 'swing_allocator' es subcadena de los tres -> ambiguo -> None (evita elegir mal)
    assert resolve_bot("swing_allocator", bots) is None
    # subcadena unica del strategy_name resuelve
    assert resolve_bot("v5_btc", bots)["label"] == "v5"


def test_filter_rebalances_by_strategy():
    rebs = [
        {"strategy": "swing_allocator_v5_btc_usdt", "num": 1},
        {"strategy": "swing_allocator_v6_btc_usdt", "num": 2},
        {"strategy": "swing_allocator_v5_btc_usdt", "num": 3},
    ]
    v5 = filter_rebalances(rebs, "swing_allocator_v5_btc_usdt")
    assert [r["num"] for r in v5] == [1, 3]
    assert filter_rebalances(rebs, None) == rebs          # None = todos (legacy)
    assert filter_rebalances(rebs, "desconocido") == []
