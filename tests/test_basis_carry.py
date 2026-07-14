from __future__ import annotations

from strategies.basis_carry import (
    BasisCarryConfig, build_avg_funding_series, gate_is_open,
)

H8 = 8 * 3_600_000


def _rows(rates):
    return [(i * H8, r) for i, r in enumerate(rates)]


def test_avg_series_empty_below_window():
    assert build_avg_funding_series(_rows([0.0001] * 10), window=20) == []


def test_avg_series_tracks_simple_moving_average():
    rates = [0.0002] * 30
    series = build_avg_funding_series(_rows(rates), window=20)
    assert len(series) == 30 - 20 + 1
    assert all(abs(v - 0.0002) < 1e-12 for _, v in series)


def test_avg_series_reflects_regime_shift():
    rates = [0.0005] * 20 + [-0.0005] * 20
    series = build_avg_funding_series(_rows(rates), window=20)
    # primer valor (ts=19*H8): ventana [0..19] toda positiva -> avg > 0
    assert series[0][1] > 0
    # ultimo valor (ts=39*H8): ventana [20..39] toda negativa -> avg < 0
    assert series[-1][1] < 0


def test_gate_open_above_threshold():
    assert gate_is_open(avg_rate=0.0001, min_avg=0.0)
    assert not gate_is_open(avg_rate=-0.0001, min_avg=0.0)
    assert not gate_is_open(avg_rate=0.0001, min_avg=0.0002)


def test_from_dict_to_dict_roundtrip():
    overrides = {
        "symbol": "ETH-USDT", "notional_pct": 0.5, "funding_window": 60,
        "funding_min_avg": 0.0001, "model_funding": False,
    }
    cfg = BasisCarryConfig.from_dict(overrides)
    for k, v in overrides.items():
        assert getattr(cfg, k) == v
    assert cfg.to_dict()["funding_window"] == 60
    assert cfg.to_dict()["model_funding"] is False


def test_from_dict_ignores_unknown_keys():
    cfg = BasisCarryConfig.from_dict({"not_a_field": 123})
    assert not hasattr(cfg, "not_a_field")
