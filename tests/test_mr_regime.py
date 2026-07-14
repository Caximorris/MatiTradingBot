from __future__ import annotations

from strategies.mr_regime import MrRegimeConfig, dip_entry_signal, regime_is_bullish


def test_regime_bullish_all_conditions_met():
    assert regime_is_bullish(ema50=110, ema200=100, close=115, adx_val=20, adx_min=15.0)


def test_regime_not_bullish_golden_cross_missing():
    assert not regime_is_bullish(ema50=95, ema200=100, close=115, adx_val=20, adx_min=15.0)


def test_regime_not_bullish_price_below_ema200():
    assert not regime_is_bullish(ema50=110, ema200=100, close=95, adx_val=20, adx_min=15.0)


def test_regime_not_bullish_adx_too_low():
    assert not regime_is_bullish(ema50=110, ema200=100, close=115, adx_val=10, adx_min=15.0)


def test_dip_entry_fires_below_threshold():
    # sma20=100, atr14=2, entry_mult=2.0 -> umbral 96
    assert dip_entry_signal(close=95.9, sma20=100, atr14=2, entry_mult=2.0)


def test_dip_entry_does_not_fire_above_threshold():
    assert not dip_entry_signal(close=97, sma20=100, atr14=2, entry_mult=2.0)


def test_from_dict_to_dict_roundtrip():
    overrides = {
        "symbol": "ETH-USDT", "adx_min": 18.0, "sma_period": 25, "atr_period": 10,
        "entry_mult": 1.5, "cooldown_hours": 48, "time_stop_hours": 48,
        "stop_mult": 2.5, "risk_per_trade": 0.02,
    }
    cfg = MrRegimeConfig.from_dict(overrides)
    for k, v in overrides.items():
        assert getattr(cfg, k) == v
    assert cfg.to_dict()["adx_min"] == 18.0
    assert cfg.to_dict()["cooldown_hours"] == 48


def test_from_dict_ignores_unknown_keys():
    cfg = MrRegimeConfig.from_dict({"not_a_field": 123})
    assert not hasattr(cfg, "not_a_field")
