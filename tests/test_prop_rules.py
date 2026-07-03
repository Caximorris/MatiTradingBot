"""Tests de core/prop_rules.py con curvas de equity sinteticas (HYROTRADER_PLAN P1)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.prop_rules import (
    BREACH_DAILY, BREACH_TOTAL, DATA_END, PASSED, TIMEOUT, TRADE_LOSS,
    ONE_STEP, TWO_STEP_P1, TWO_STEP_P2, PropRulesConfig,
    evaluate_challenge, evaluate_two_step, simulate_challenges,
)

T0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)


def curve(values: list[float], start: datetime = T0, step_hours: int = 1):
    """Curva horaria de equity en float a partir de una lista de valores."""
    return [(start + timedelta(hours=i * step_hours), v) for i, v in enumerate(values)]


def flat_days(n_days: int, value: float = 1.0, start: datetime = T0):
    return curve([value] * (24 * n_days), start=start)


def drift_days(n_days: int, per_day: float, start: datetime = T0):
    """n_days dias, cada uno con subida lineal intradia de per_day (sin retrocesos)."""
    vals, level = [], 1.0
    for _ in range(n_days):
        for h in range(24):
            vals.append(level + per_day * (h + 1) / 24)
        level += per_day
    return curve(vals, start=start)


# ---------------------------------------------------------------------------
# Daily drawdown: trailing vs swing (estatico)
# ---------------------------------------------------------------------------

class TestDailyDrawdown:
    def _retrace_curve(self):
        # Dia 1: sube a 1.06 y retrocede a 1.005 (caida desde pico = 0.055).
        # El dia cierra POSITIVO (+0.5%) — el trailing standard debe breachear igual.
        vals = [1.0, 1.02, 1.04, 1.06, 1.03, 1.005] + [1.005] * 18
        return curve(vals)

    def test_trailing_breaches_on_retrace_from_intraday_peak(self):
        r = evaluate_challenge(self._retrace_curve(), 0, TWO_STEP_P1)  # daily 5%
        assert r.status == BREACH_DAILY

    def test_swing_upgrade_survives_same_retrace(self):
        cfg = TWO_STEP_P1.with_(swing_upgrade=True)
        # suelo estatico = 1.0 - 0.05 = 0.95; el minimo 1.005 nunca lo toca
        r = evaluate_challenge(self._retrace_curve(), 0, cfg)
        assert r.status != BREACH_DAILY

    def test_one_step_daily_is_tighter(self):
        # caida desde pico de 4.5%: breachea one-step (4%) pero no two-step (5%)
        vals = [1.0, 1.03, 1.06, 1.015] + [1.015] * 20
        assert evaluate_challenge(curve(vals), 0, ONE_STEP).status == BREACH_DAILY
        assert evaluate_challenge(curve(vals), 0, TWO_STEP_P1).status != BREACH_DAILY

    def test_day_reset_utc_clears_peak(self):
        # Dia 1 acaba en 1.04 (pico 1.04). Dia 2 cae a 1.0: caida 4% desde pico del DIA 1,
        # pero el pico se resetea a medianoche → dia 2 cae solo 4% desde SU pico 1.04...
        # construimos: dia 2 arranca 1.04, cae a 0.995 = -4.5% intradia → breach two-step NO
        # (limite 5%), one-step SI.
        d1 = [1.0 + 0.04 * (h + 1) / 24 for h in range(24)]
        d2 = [1.04 - 0.045 * (h + 1) / 24 for h in range(24)]
        c = curve(d1 + d2)
        assert evaluate_challenge(c, 0, TWO_STEP_P1).status != BREACH_DAILY
        assert evaluate_challenge(c, 0, ONE_STEP).status == BREACH_DAILY

    def test_intrabar_buffer_tightens_limit(self):
        # caida 4.2% desde pico: two-step (5%) sobrevive sin buffer, breachea con buffer 0.2
        vals = [1.0, 1.05, 1.008] + [1.008] * 21
        assert evaluate_challenge(curve(vals), 0, TWO_STEP_P1).status != BREACH_DAILY
        cfg = TWO_STEP_P1.with_(intrabar_buffer=0.2)  # limite efectivo 4%
        assert evaluate_challenge(curve(vals), 0, cfg).status == BREACH_DAILY


# ---------------------------------------------------------------------------
# Max loss total / por trade
# ---------------------------------------------------------------------------

class TestMaxLoss:
    def test_total_breach_static_from_initial(self):
        # deriva lenta (-0.5%/dia, sin breach diario) hasta perder 10.5%
        vals, level = [], 1.0
        for _ in range(21):
            for h in range(24):
                vals.append(level - 0.005 * (h + 1) / 24)
            level -= 0.005
        r = evaluate_challenge(curve(vals), 0, TWO_STEP_P1)
        assert r.status == BREACH_TOTAL

    def test_trade_loss_violation(self):
        c = flat_days(3)
        trades = [(T0 + timedelta(hours=30), -0.04)]  # -4% realizado > 3%
        r = evaluate_challenge(c, 0, TWO_STEP_P1, trade_pnls=trades)
        assert r.status == TRADE_LOSS
        assert r.worst_trade == pytest.approx(-0.04)

    def test_trade_loss_under_limit_ok(self):
        c = flat_days(3)
        trades = [(T0 + timedelta(hours=30), -0.02)]
        r = evaluate_challenge(c, 0, TWO_STEP_P1, trade_pnls=trades)
        assert r.status != TRADE_LOSS


# ---------------------------------------------------------------------------
# Target, dias minimos y Profit Distribution
# ---------------------------------------------------------------------------

class TestPassPath:
    def test_steady_gains_pass_two_step_p1(self):
        # +1%/dia x 12 dias: target 10% + 10 dias minimos + distribucion ok (max dia ~9%)
        r = evaluate_challenge(drift_days(13, 0.01), 0, TWO_STEP_P1)
        assert r.status == PASSED
        assert r.trading_days >= TWO_STEP_P1.min_trading_days
        assert r.max_day_share <= TWO_STEP_P1.profit_distribution_pct + 1e-9

    def test_min_trading_days_delays_pass(self):
        # +3%/dia: target 10% en 4 dias, pero min 10 dias → no puede pasar antes del dia 10
        r = evaluate_challenge(drift_days(14, 0.03), 0, TWO_STEP_P1)
        assert r.status == PASSED
        assert r.days_elapsed >= 10

    def test_profit_distribution_blocks_until_diluted(self):
        # Dia 1: +8%. Dias 2+: +0.5%/dia. Target 10% se alcanza el dia ~5, pero
        # 8%/10% = 80% > 40% → bloqueado hasta que total >= 8%/0.4 = 20% (dia ~25).
        d1 = [1.0 + 0.08 * (h + 1) / 24 for h in range(24)]
        vals, level = d1, 1.08
        for _ in range(40):
            for h in range(24):
                vals.append(level + 0.005 * (h + 1) / 24)
            level += 0.005
        r = evaluate_challenge(curve(vals), 0, TWO_STEP_P1)
        assert r.status == PASSED
        assert r.dist_blocked_days > 0
        assert r.final_return_pct >= 0.19   # tuvo que diluir hasta ~20%
        assert r.max_day_share <= 0.40 + 1e-9

    def test_timeout_on_flat_curve(self):
        cfg = TWO_STEP_P1.with_(max_days=30)
        r = evaluate_challenge(flat_days(40), 0, cfg)
        assert r.status == TIMEOUT

    def test_trading_days_counted_from_trades(self):
        # Con trade_pnls dados, solo cuentan dias con trades: 2 trades en 13 dias → sin pasar
        c = drift_days(13, 0.01)
        trades = [(T0 + timedelta(days=1, hours=5), 0.01),
                  (T0 + timedelta(days=2, hours=5), 0.01)]
        cfg = TWO_STEP_P1.with_(max_days=15)
        r = evaluate_challenge(c, 0, cfg, trade_pnls=trades)
        assert r.status in (TIMEOUT, DATA_END)   # target si, dias de trading no


# ---------------------------------------------------------------------------
# Two-Step encadenado y simulacion agregada
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_two_step_chained_pass(self):
        # +1%/dia x 40 dias: P1 pasa (~dia 12) y P2 (5% + 5 dias) pasa despues
        r = evaluate_two_step(drift_days(40, 0.01), 0)
        assert r.status == PASSED
        assert r.days_elapsed > 12

    def test_simulate_challenges_counts_and_rates(self):
        eq = [(ts, Decimal(str(v))) for ts, v in drift_days(120, 0.01)]
        stats = simulate_challenges(eq, TWO_STEP_P1, start_every_days=14)
        assert stats.windows > 0
        assert stats.pass_rate == 1.0
        assert stats.breach_rate == 0.0
        assert stats.median_days_pass >= 10

    def test_simulate_all_breach(self):
        # sierra diaria: pico +6% y desplome -6% cada dia → todo breachea
        day = [1.0 + 0.06 * (h + 1) / 12 for h in range(12)] + \
              [1.06 - 0.12 * (h + 1) / 12 for h in range(12)]
        vals = []
        for _ in range(30):
            vals.extend(day)
        eq = [(T0 + timedelta(hours=i), Decimal(str(v))) for i, v in enumerate(vals)]
        stats = simulate_challenges(eq, TWO_STEP_P1, start_every_days=3)
        assert stats.windows > 0
        assert stats.breach_rate == 1.0

    def test_data_end_excluded_from_rates(self):
        eq = [(ts, Decimal(str(v))) for ts, v in flat_days(3)]
        cfg = TWO_STEP_P1.with_(max_days=365)
        stats = simulate_challenges(eq, cfg, start_every_days=1)
        assert stats.windows == 0   # nada se resuelve en 3 dias planos
