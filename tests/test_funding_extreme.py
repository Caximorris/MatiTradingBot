from __future__ import annotations

from strategies.funding_extreme import build_funding_signals

H8 = 8 * 3_600_000


def _rows(rates):
    return [(i * H8, r) for i, r in enumerate(rates)]


def test_no_signals_with_flat_funding():
    assert build_funding_signals(_rows([0.0001] * 60), window=20) == []


def test_hi_lo_and_dedup():
    rates = [0.0001] * 100
    rates[40] = 0.01     # hi
    rates[42] = 0.01     # 16h despues -> dedup (72h)
    rates[70] = -0.01    # lo, 240h despues -> pasa
    sig = build_funding_signals(_rows(rates), window=20, dedup_hours=72)
    assert sig == [(40 * H8, "hi"), (70 * H8, "lo")]


def test_threshold_is_trailing_shift1():
    # El propio spike NO se autoincluye en su umbral (shift(1)): un unico spike
    # tras historia plana SIEMPRE dispara
    rates = [0.0001] * 30 + [0.02]
    sig = build_funding_signals(_rows(rates), window=20)
    assert sig and sig[0][1] == "hi"


def test_use_flags():
    rates = [0.0001] * 100
    rates[50] = -0.01
    assert build_funding_signals(_rows(rates), window=20, use_lo=False) == []
