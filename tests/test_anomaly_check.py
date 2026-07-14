from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from tools import anomaly_check as ac

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def _snap(**kw):
    base = {
        "label": "v5", "name": "swing_allocator_v5_btc_usdt", "symbol": "BTC-USDT",
        "is_active": True, "wallet_exists": True, "stale": False,
        "last_run_age_min": 2.0, "balances": {"BTC": Decimal("0.3"), "USDT": Decimal("4000")},
        "btc_pct": 60.0, "n_rebalances": 1, "last_rebalance": {"btc_pct_after": 0.6},
    }
    base.update(kw)
    return base


def test_clean_snapshot_no_alerts():
    assert ac.check_anomalies([_snap()], price=Decimal("40000"), now=NOW) == []


def test_price_none_flags_okx():
    alerts = ac.check_anomalies([_snap()], price=None, now=NOW)
    assert any(a.code == "okx-price-unavailable" for a in alerts)


def test_stale_bot_flagged_high():
    alerts = ac.check_anomalies([_snap(stale=True, last_run_age_min=45.0)],
                                price=Decimal("40000"), now=NOW)
    a = next(a for a in alerts if a.code == "bot-stale-tick")
    assert a.severity == "HIGH"


def test_negative_balance_is_critical():
    alerts = ac.check_anomalies([_snap(balances={"USDT": Decimal("-5")})],
                                price=Decimal("40000"), now=NOW)
    assert any(a.code == "negative-balance" and a.severity == "CRITICAL" for a in alerts)


def test_impossible_allocation_is_critical():
    alerts = ac.check_anomalies([_snap(btc_pct=140.0)], price=Decimal("40000"), now=NOW)
    assert any(a.code == "impossible-allocation" for a in alerts)


def test_large_journal_vs_wallet_allocation_gap_is_high():
    alerts = ac.check_anomalies([
        _snap(label="demo", execution="okx_demo", btc_pct=19.2,
              last_rebalance={"btc_pct_after": 0.58}),
    ], price=Decimal("40000"), now=NOW)

    alert = next(a for a in alerts if a.code == "journal-allocation-gap")
    assert alert.severity == "HIGH"
    assert "38.8pp" in alert.message


def test_reconcile_event_clears_journal_allocation_gap():
    alerts = ac.check_anomalies([
        _snap(label="demo", execution="okx_demo", btc_pct=19.2,
              last_rebalance={"direction": "RECONCILE", "btc_pct_after": 0.192}),
    ], price=Decimal("40000"), now=NOW)

    assert not any(a.code == "journal-allocation-gap" for a in alerts)


def test_v6_early_divergence_flagged_before_date():
    v5 = _snap(label="v5", n_rebalances=1, last_rebalance={"btc_pct_after": 0.6})
    v6 = _snap(label="v6", n_rebalances=2, last_rebalance={"btc_pct_after": 0.8})
    alerts = ac.check_anomalies([v5, v6], price=Decimal("40000"), now=NOW)
    assert any(a.code == "v6-early-divergence" for a in alerts)


def test_v6_divergence_not_flagged_after_date():
    after = datetime(2026, 11, 1, tzinfo=timezone.utc)
    v5 = _snap(label="v5", n_rebalances=1, last_rebalance={"btc_pct_after": 0.6})
    v6 = _snap(label="v6", n_rebalances=2, last_rebalance={"btc_pct_after": 0.8})
    alerts = ac.check_anomalies([v5, v6], price=Decimal("40000"), now=after)
    assert not any(a.code == "v6-early-divergence" for a in alerts)


def test_alerts_sorted_by_severity():
    alerts = ac.check_anomalies([_snap(balances={"USDT": Decimal("-5")})],
                                price=None, now=NOW)
    sev = [a.severity for a in alerts]
    assert sev == sorted(sev, key=lambda s: ac._SEVERITY_ORDER[s])


def test_dedup_suppresses_repeat_within_ttl():
    a = ac.Alert("HIGH", "bot-stale-tick", "msg", "act", bot="v5")
    to_send, state = ac.filter_new_alerts([a], {}, now=NOW)
    assert to_send == [a]
    # mismo mensaje 1h despues (ttl 6h) -> no reenviar
    later = NOW.replace(hour=13)
    again, _ = ac.filter_new_alerts([a], state, now=later)
    assert again == []


def test_dedup_resends_when_message_changes():
    a1 = ac.Alert("HIGH", "bot-stale-tick", "msg-A", "act", bot="v5")
    _, state = ac.filter_new_alerts([a1], {}, now=NOW)
    a2 = ac.Alert("HIGH", "bot-stale-tick", "msg-B", "act", bot="v5")
    again, _ = ac.filter_new_alerts([a2], state, now=NOW)
    assert again == [a2]


def test_daily_check_stale_flagged():
    """Regresion 2026-07-11: el cron perdio +x 5 dias y /parity seguia mostrando 'OK' en verde
    porque solo miraba el resultado, nunca la antiguedad del ultimo check."""
    alerts = ac.check_anomalies([_snap()], price=Decimal("40000"), now=NOW,
                                daily_check_age_min=ac.DAILY_CHECK_STALE_MIN + 1)
    a = next(a for a in alerts if a.code == "daily-check-stale")
    assert a.severity == "HIGH"


def test_daily_check_fresh_not_flagged():
    alerts = ac.check_anomalies([_snap()], price=Decimal("40000"), now=NOW,
                                daily_check_age_min=60.0)
    assert not any(a.code == "daily-check-stale" for a in alerts)


def test_daily_check_none_not_flagged():
    """None = no evaluado (p.ej. dev sin cron) -> no debe fabricar una alerta falsa."""
    alerts = ac.check_anomalies([_snap()], price=Decimal("40000"), now=NOW,
                                daily_check_age_min=None)
    assert not any(a.code == "daily-check-stale" for a in alerts)


def test_daily_check_age_minutes_from_blocks():
    blocks = [
        {"ts": "2026-07-06T12:10:01+00:00", "parity": True, "target": "0.2000"},
    ]
    age = ac.daily_check_age_minutes(blocks, NOW)
    # NOW = 2026-07-20T12:00, ultimo check 2026-07-06T12:10 -> ~14 dias
    assert age > 60 * 24 * 13


def test_daily_check_age_minutes_empty_blocks():
    assert ac.daily_check_age_minutes([], NOW) is None


def test_daily_check_age_minutes_bad_timestamp():
    assert ac.daily_check_age_minutes([{"ts": "?"}], NOW) is None
