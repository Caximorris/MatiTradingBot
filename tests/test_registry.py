from strategies.registry import resolve


def test_resolve_prop_swing_not_shadowed_by_pro_alias():
    """Regresion 2026-07-11: 'prop_swing_btc_usdt' resolvia a pro_trend porque el
    alias corto 'pro' (pro_trend) es prefijo de 'prop_swing...' sin limite de palabra,
    y pro_trend se inserta antes que prop_swing en el registro. Causo que un bot
    registrado como PropSwing corriera en produccion como Pro Trend (congelado)
    con su config ignorada silenciosamente."""
    assert resolve("prop_swing_btc_usdt").name == "prop_swing"


def test_resolve_swing_allocator_variants():
    assert resolve("swing_allocator_btc_usdt").name == "swing_allocator"
    assert resolve("swing_allocator_v6_btc_usdt").name == "swing_allocator"


def test_resolve_pro_trend_still_resolves():
    assert resolve("pro_trend_btc_usdt").name == "pro_trend"


def test_resolve_exact_alias_match():
    assert resolve("prop").name == "prop_swing"
    assert resolve("pro").name == "pro_trend"


def test_resolve_unknown_returns_none():
    assert resolve("nonexistent_strategy_btc_usdt") is None
