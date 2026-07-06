from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from tools import forward_report as fr


def test_forward_only_drops_pre_start_records():
    start = datetime(2026, 7, 4, tzinfo=timezone.utc)
    reb = [
        {"timestamp": "2026-01-01T00:00:00+00:00", "direction": "INIT"},   # pre-start: fuera
        {"timestamp": "2026-07-05T00:00:00+00:00", "direction": "BUY"},    # dentro
        {"timestamp": "no-es-fecha", "direction": "SELL"},                 # sin ts: fuera
    ]
    kept, dropped = fr._forward_only(reb, start)
    assert [r["direction"] for r in kept] == ["BUY"]
    assert dropped == 2


def test_drawdown_from_series():
    assert fr._drawdown_from_series([100, 120, 60, 90]) == -50.0
    assert fr._drawdown_from_series([100]) == 0.0


def test_bot_forward_metrics_excludes_history():
    start = datetime(2026, 7, 4, tzinfo=timezone.utc)
    snap = {
        "label": "v5", "name": "swing_allocator_v5_btc_usdt", "is_active": True,
        "wallet_exists": True, "equity_usd": Decimal("12000"), "btc_pct": 55.0,
        "bnh_ratio": 0.9, "stale": False, "last_run_age_min": 3.0,
        "rebalances": [
            {"timestamp": "2026-06-01T00:00:00+00:00", "direction": "INIT",
             "portfolio_usdt": 9999, "btc_pct_after": 0.6},                 # pre-start
            {"timestamp": "2026-07-10T00:00:00+00:00", "direction": "BUY",
             "portfolio_usdt": 10000, "btc_pct_after": 0.7},
        ],
    }
    m = fr._bot_forward_metrics(snap, start)
    assert m["n_rebalances_forward"] == 1
    assert m["pre_start_dropped"] == 1
    assert m["buys"] == 1
    assert m["max_exposure_pct"] == 70.0


class _Q:
    def filter(self, *_a, **_k):
        return self

    def all(self):
        return []


class _Session:
    def query(self, *_a, **_k):
        return _Q()


def test_build_forward_report_no_bots_is_clean():
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rep = fr.build_forward_report(_Session(), price=Decimal("40000"), now=now)
    assert rep["bots"] == []
    assert rep["pre_start_records_dropped"] == 0
    assert rep["forward_start"].startswith("2026-07-04")
    md = fr.to_markdown(rep)
    assert "Forward-Test Report" in md
    assert "2026-07-04" in md


def test_forward_start_matches_contract_date():
    # Guardia: la constante-fuente-de-verdad debe seguir en 2026-07-04 (contrato seccion 1).
    assert fr.FORWARD_TEST_START == datetime(2026, 7, 4, tzinfo=timezone.utc)
