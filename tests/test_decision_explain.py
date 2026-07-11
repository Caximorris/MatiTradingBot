from tools.decision_explain import explain_rebalance, explain_signal, find_rebalance


def test_explain_signal_prefers_longest_match():
    """Mismo bug de fondo que registry.resolve() (2026-07-11): un prefijo corto no debe
    ganarle a una variante mas especifica que lo contiene."""
    generic = explain_signal("regime_bull")
    suppressed = explain_signal("regime_bull_suppressed_bear_onset")
    assert "SUPRIMIDO" in suppressed
    assert "SUPRIMIDO" not in generic


def test_explain_signal_handles_dynamic_suffix():
    assert "MVRV" in explain_signal("mvrv_3.20")
    assert "RSI" in explain_signal("rsi_ob_78")


def test_explain_signal_unknown_code_is_labeled_not_silently_ignored():
    out = explain_signal("totally_unknown_signal")
    assert "no reconocida" in out


def test_find_rebalance_filters_by_strategy_and_date():
    rebalances = [
        {"strategy": "swing_allocator_btc_usdt", "timestamp": "2026-07-04T08:59:00+00:00",
         "direction": "INIT"},
        {"strategy": "swing_allocator_v6_btc_usdt", "timestamp": "2026-07-06T14:20:00+00:00",
         "direction": "INIT"},
        {"strategy": "swing_allocator_btc_usdt", "timestamp": "2026-07-06T12:00:00+00:00",
         "direction": "SELL"},
    ]
    latest_v5 = find_rebalance(rebalances, strategy="swing_allocator_btc_usdt")
    assert latest_v5["timestamp"] == "2026-07-06T12:00:00+00:00"

    by_date = find_rebalance(rebalances, date="2026-07-04")
    assert by_date["direction"] == "INIT"
    assert by_date["timestamp"].startswith("2026-07-04")

    assert find_rebalance(rebalances, strategy="nonexistent") is None
    assert find_rebalance([]) is None


def test_explain_rebalance_renders_readable_block():
    entry = {
        "strategy": "swing_allocator_btc_usdt", "symbol": "BTC-USDT",
        "timestamp": "2026-07-04T08:59:00+00:00", "direction": "SELL",
        "btc_pct_before": 0.60, "btc_pct_target": 0.20, "btc_pct_after": 0.20,
        "price": 62573.0, "qty": 0.05, "portfolio_usdt": 9994.0,
        "signals": ["regime_bear", "halving_bear_onset"],
    }
    out = explain_rebalance(entry)
    assert "60%" in out and "20%" in out
    assert "regime_bear" in out
    assert "Regimen bajista" in out
    assert "cooldown" in out.lower()  # gap conocido, siempre visible


def test_explain_rebalance_no_signals():
    entry = {"strategy": "x", "symbol": "BTC-USDT", "timestamp": "t", "direction": "INIT"}
    out = explain_rebalance(entry)
    assert "ninguna registrada" in out
