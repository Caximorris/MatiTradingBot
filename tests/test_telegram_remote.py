from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tools.telegram_remote import (
    format_report,
    format_status,
    handle_command,
    prop_bot_rows,
    set_prop_active,
    set_swing_active,
    swing_bot_rows,
)


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.database import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_bot(session, name, symbol="BTC-USDT", active=True):
    from core.database import BotState
    session.add(BotState(
        strategy_name=name, symbol=symbol, is_active=active,
        config_json="{}", created_at=datetime.now(timezone.utc),
    ))
    session.flush()


def test_set_swing_active_ignores_internal_state_row(db_session):
    _add_bot(db_session, "swing_allocator_btc_usdt", active=True)
    _add_bot(db_session, "swing_allocator", active=False)   # fila de estado interno
    _add_bot(db_session, "swing_allocator_v6", active=False)  # estado de instancia
    _add_bot(db_session, "pro_trend_btc_usdt", active=True)  # otra estrategia: no tocar

    names = set_swing_active(db_session, False)

    assert names == ["swing_allocator_btc_usdt"]
    rows = {r.strategy_name: r.is_active for r in swing_bot_rows(db_session)}
    assert rows["swing_allocator_btc_usdt"] is False
    assert "swing_allocator_v6" not in rows


def test_pause_and_resume_commands_flip_is_active(db_session):
    _add_bot(db_session, "swing_allocator_btc_usdt", active=True)

    @contextmanager
    def get_session():
        yield db_session

    assert "PAUSADO" in handle_command("/pause", get_session)
    assert swing_bot_rows(db_session)[0].is_active is False
    assert "REANUDADO" in handle_command("/resume", get_session)
    assert swing_bot_rows(db_session)[0].is_active is True


def test_prop_pause_and_resume_only_touch_prop(db_session):
    _add_bot(db_session, "prop_swing_btc_usdt", active=True)
    _add_bot(db_session, "prop_swing", active=False)
    _add_bot(db_session, "swing_allocator_btc_usdt", active=True)

    @contextmanager
    def get_session():
        yield db_session

    assert set_prop_active(db_session, False) == ["prop_swing_btc_usdt"]
    assert prop_bot_rows(db_session)[0].is_active is False
    assert swing_bot_rows(db_session)[0].is_active is True
    assert "PROP REANUDADO" in handle_command("/prop_resume", get_session)
    assert prop_bot_rows(db_session)[0].is_active is True


def test_unknown_command_returns_help(db_session):
    @contextmanager
    def get_session():
        yield db_session

    assert "/status" in handle_command("/loquesea", get_session)


def test_menu_labels_and_shortcuts_expand_without_manual_arguments(monkeypatch, db_session):
    from decimal import Decimal
    import tools.telegram_remote as tr
    snaps = [_snap_full("v6"), _snap_full("demo")]
    monkeypatch.setattr(tr, "_load_snapshots", lambda gs: snaps)
    monkeypatch.setattr(tr, "fetch_price", lambda *a, **k: Decimal("50000"))

    @contextmanager
    def get_session():
        yield db_session

    assert "SWING v6" in tr.handle_command("🟢 V6 sim", get_session)
    assert "SWING demo" in tr.handle_command("/status_demo", get_session)
    assert "REPORT [v6]" in tr.handle_command("📋 Report v6", get_session)
    assert "Panel listo" in tr.handle_command("/menu", get_session)


def test_main_menu_markup_is_persistent_and_read_only():
    import json
    from tools.tg_menu import main_menu_markup

    menu = json.loads(main_menu_markup())
    labels = {label for row in menu["keyboard"] for label in row}
    assert menu["is_persistent"] is True
    assert {"📊 Resumen", "🟢 V6 sim", "🟠 OKX demo", "🏁 Prop firm"} <= labels
    assert not any("Pausar" in label or "Reiniciar" in label for label in labels)


def test_split_bot_num_is_order_independent_and_clamps():
    from tools.telegram_remote import _split_bot_num
    assert _split_bot_num(["/report"], 10, 1, 100) == (None, 10)
    assert _split_bot_num(["/report", "v6"], 10, 1, 100) == ("v6", 10)
    assert _split_bot_num(["/report", "25"], 10, 1, 100) == (None, 25)
    assert _split_bot_num(["/report", "v6", "25"], 10, 1, 100) == ("v6", 25)
    assert _split_bot_num(["/report", "25", "v6"], 10, 1, 100) == ("v6", 25)  # orden libre
    assert _split_bot_num(["/report", "500"], 10, 1, 100) == (None, 100)      # clamp alto


def _snap_full(label, active=True):
    from decimal import Decimal
    return {
        "label": label, "name": f"swing_allocator_{label}_btc_usdt", "symbol": "BTC-USDT",
        "is_active": active, "last_run": None, "portfolio_id": f"swing_{label}",
        "balances": {"BTC": Decimal("0.1"), "USDT": Decimal("100")},
        "rebalances": [{"strategy": f"swing_allocator_{label}_btc_usdt", "direction": "INIT",
                        "timestamp": "2026-07-04T08:00:00+00:00", "btc_pct_after": 0.6,
                        "price": 50000.0, "portfolio_usdt": 5100.0}],
    }


def test_status_and_bots_route_to_summary_detail_and_error(monkeypatch, db_session):
    from decimal import Decimal
    import tools.telegram_remote as tr
    snaps = [_snap_full("v5"), _snap_full("v6")]
    monkeypatch.setattr(tr, "_load_snapshots", lambda gs: snaps)
    monkeypatch.setattr(tr, "fetch_price", lambda *a, **k: Decimal("50000"))

    @contextmanager
    def get_session():
        yield db_session

    summary = tr.handle_command("/status", get_session)
    assert "SWING — PAPER" in summary and "v5" in summary and "v6" in summary

    detail = tr.handle_command("/status v6", get_session)
    assert "SWING v6 — PAPER" in detail

    assert "no encontrado" in tr.handle_command("/status zzz", get_session)

    bots = tr.handle_command("/bots", get_session)
    assert "paper_state_swing_v6.json" in bots and "legacy" not in bots


def test_demo_status_labels_usdc_suppresses_fake_performance_and_flags_journal_gap(
    monkeypatch, db_session,
):
    from decimal import Decimal
    import tools.telegram_remote as tr

    demo = _snap_full("demo")
    demo.update({
        "execution": "okx_demo",
        "execution_quote": "USDC",
        "balances": {"BTC": Decimal("0.032895"), "USDT": Decimal("8691.55")},
        "rebalances": [{
            "strategy": "swing_allocator_demo_btc_usdt", "direction": "SELL",
            "timestamp": "2026-07-13T14:38:00+00:00", "btc_pct_after": 0.58,
            "btc_pct_before": 0.58, "price": 62502.0, "portfolio_usdt": 10277.0,
        }],
    })
    monkeypatch.setattr(tr, "_load_snapshots", lambda gs: [demo])
    monkeypatch.setattr(tr, "fetch_price", lambda *a, **k: Decimal("62786"))

    @contextmanager
    def get_session():
        yield db_session

    summary = tr.handle_command("/status", get_session)
    detail = tr.handle_command("/status demo", get_session)
    report = tr.handle_command("/report demo", get_session)
    equity = tr.handle_command("/equity demo", get_session)

    assert "valoracion hibrida" in summary and "bot/B&amp;H" not in summary
    assert "USDC" in detail and "Rendimiento Demo no comparable" in detail
    assert "Journal y cartera no coinciden" in detail
    assert "journal no incluye ajustes fuera del bot" in report
    assert "Equity Demo no comparable" in equity


def test_report_requires_bot_when_multiple(monkeypatch, db_session):
    import tools.telegram_remote as tr
    monkeypatch.setattr(tr, "_load_snapshots", lambda gs: [_snap_full("v5"), _snap_full("v6")])

    @contextmanager
    def get_session():
        yield db_session

    ambiguous = tr.handle_command("/report", get_session)
    assert "Indica el bot" in ambiguous and "v5" in ambiguous
    ok = tr.handle_command("/report v6", get_session)
    assert "REPORT [v6]" in ok


def _row(active=True, last_run=None):
    return SimpleNamespace(
        strategy_name="swing_allocator_btc_usdt", symbol="BTC-USDT",
        is_active=active, last_run=last_run,
    )


def test_format_status_reports_alive_paused_and_stale():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    from decimal import Decimal
    balances = {"BTC": Decimal("0.5"), "USDT": Decimal("1000")}

    alive = format_status([_row(True, now - timedelta(minutes=2))], balances, Decimal("100000"), [], now)
    assert "VIVO" in alive
    assert "Portfolio: $51,000.00" in alive   # total = 0.5*100k+1000, no la pata BTC ($50k)

    paused = format_status([_row(False)], balances, None, [], now)
    assert "PAUSADO" in paused

    stale = format_status([_row(True, now - timedelta(hours=3))], balances, None, [], now)
    assert "SIN TICK" in stale


def test_format_report_truncates_and_counts():
    rebalances = [
        {"timestamp": f"2026-07-{d:02d}T12:00:00+00:00", "direction": "BUY",
         "btc_pct_before": 0.6, "btc_pct_after": 0.8, "price": 100000.0,
         "portfolio_usdt": 12000.0, "signals": ["regime_bull"]}
        for d in range(1, 16)
    ]
    out = format_report(rebalances, n=10)
    assert "15 rebalanceo(s)" in out
    assert "5 anteriores omitidos" in out
    assert out.count("regime_bull") == 10


def test_reconcile_is_reported_as_audit_not_strategy_rebalance():
    from tools.tg_views import format_rebalance_alert

    events = [
        {"strategy": "swing_allocator_demo_btc_usdt",
         "timestamp": "2026-07-13T14:00:00+00:00", "direction": "INIT",
         "btc_pct_before": 0.0, "btc_pct_after": 0.6, "price": 60000.0,
         "portfolio_usdt": 10000.0, "signals": ["init"]},
        {"strategy": "swing_allocator_demo_btc_usdt",
         "timestamp": "2026-07-14T09:00:00+00:00", "direction": "RECONCILE",
         "btc_pct_before": 0.58, "btc_pct_after": 0.192, "price": 62557.0,
         "portfolio_usdt": 10749.0, "signals": ["manual_wallet_reconcile"],
         "reconciliation": {"reason": "ajuste manual"}},
    ]

    report = format_report(events)
    alert = format_rebalance_alert(events[-1])

    assert "1 rebalanceo(s), 1 evento(s) de auditoria" in report
    assert "RECONCILIACION DE AUDITORIA [demo]" in alert
    assert "motivo: ajuste manual" in alert


def test_parse_daily_checks_and_streak():
    from tools.telegram_remote import format_parity, parse_daily_checks, parity_streak
    log = (
        "===== daily_checks 2026-07-05T12:10:00Z =====\n"
        "timestamp,2026-07-05T12:00:00+00:00\n"
        "live_target,0.2000\n"
        "live_signals,regime_bear;halving_bear_onset\n"
        "PARITY_OK\n"
        "no_data\n"
        "===== daily_checks 2026-07-06T12:10:00Z =====\n"
        "live_target,0.2000\n"
        "PARITY_FAIL\n"
        "===== daily_checks 2026-07-07T12:10:00Z =====\n"
        "live_target,0.2000\n"
        "PARITY_OK\n"
    )
    blocks = parse_daily_checks(log)
    assert [b["parity"] for b in blocks] == [True, False, True]
    assert blocks[0]["target"] == "0.2000"
    assert parity_streak(blocks) == 1          # el FAIL corta la racha
    out = format_parity(blocks)
    assert "1/30" in out and "OK" in out
    assert "PARIDAD" in format_parity([])


def test_format_parity_flags_stale_check():
    """Regresion 2026-07-11: el cron perdio +x 5 dias; /parity mostraba 'OK' en verde sin
    avisar porque no comparaba la antiguedad del ultimo check contra `now`."""
    from datetime import datetime, timezone

    from tools.telegram_remote import format_parity, parse_daily_checks
    log = "===== daily_checks 2026-07-06T12:10:01Z =====\nlive_target,0.2000\nPARITY_OK\n"
    blocks = parse_daily_checks(log)
    fresh_now = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)
    stale_now = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)
    assert "VIEJO" not in format_parity(blocks, now=fresh_now)
    assert "VIEJO" in format_parity(blocks, now=stale_now)
    # sin `now` (comportamiento anterior) no debe romper ni marcar viejo
    assert "VIEJO" not in format_parity(blocks)


def test_format_anomalies_empty_and_populated():
    from tools.anomaly_check import Alert
    from tools.tg_views import format_anomalies

    assert "Sin anomalias" in format_anomalies([])

    alerts = [
        Alert("CRITICAL", "negative-balance", "USDT en -5", "Parar e investigar", bot="v5"),
        Alert("HIGH", "daily-check-stale", "hace 120h", "Revisar cron"),
    ]
    out = format_anomalies(alerts)
    assert "negative-balance" in out and "[v5]" in out
    assert "daily-check-stale" in out
    assert "2 hallazgo" in out


def test_build_equity_series_reconstructs_holdings():
    from tools.tg_charts import build_equity_series, equity_summary
    h = 3_600_000
    t0 = 1_751_600_000_000
    rebalances = [
        {"timestamp": "2026-07-04T08:00:00+00:00", "direction": "INIT",
         "btc_pct_after": 0.6, "price": 100.0, "portfolio_usdt": 1000.0},
        {"timestamp": "2026-07-04T10:00:00+00:00", "direction": "SELL",
         "btc_pct_after": 0.2, "price": 100.0, "portfolio_usdt": 1000.0},
    ]
    # timestamps de velas alineados con los de los rebalanceos
    import datetime as dt
    base = int(dt.datetime(2026, 7, 4, 8, tzinfo=dt.timezone.utc).timestamp() * 1000)
    candles = [(base + i * h, 100.0 + i * 10) for i in range(4)]  # 100,110,120,130

    s = build_equity_series(rebalances, candles)
    # INIT: 6 BTC + 400 USDT. Velas 0-1: 6*100+400=1000, 6*110+400=1060
    assert s["bot"][0] == 1000.0 and s["bot"][1] == 1060.0
    # SELL en vela 2 (10:00): 2 BTC + 800 USDT -> 2*120+800=1040, 2*130+800=1060
    assert s["bot"][2] == 1040.0 and s["bot"][3] == 1060.0
    # B&H: 10 BTC desde el INIT -> 1000,1100,1200,1300
    assert s["bnh"] == [1000.0, 1100.0, 1200.0, 1300.0]
    assert [e[2] for e in s["events"]] == ["INIT", "SELL"]
    assert build_equity_series([], candles)["ts"] == []
    summary = equity_summary(rebalances, s)
    assert summary is not None
    assert summary["bot_final"] == 1060.0
    assert summary["bot_return_pct"] == pytest.approx(6.0)
    assert summary["bnh_return_pct"] == pytest.approx(30.0)
    assert abs(summary["bot_bnh_ratio"] - (1.06 / 1.30)) < 1e-12


def _snap(label="v5", active=True, last_run=None, balances=None, rebalances=None):
    from decimal import Decimal
    return {
        "label": label, "name": f"swing_allocator_{label}_btc_usdt", "symbol": "BTC-USDT",
        "is_active": active, "last_run": last_run,
        "balances": balances or {"BTC": Decimal("0.02"), "USDT": Decimal("8000")},
        "rebalances": rebalances or [],
    }


def test_format_heartbeat_multi_summarizes_each_bot():
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone
    from tools.telegram_remote import format_heartbeat_multi
    now = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)
    rebs = [{"timestamp": "2026-07-04T08:59:00+00:00", "portfolio_usdt": 10000.0,
             "price": 62578.0}]
    snaps = [
        _snap("v5", True, now - timedelta(minutes=1), rebalances=rebs),
        _snap("v6", False),
    ]
    hb = format_heartbeat_multi(snaps, Decimal("62578"), [], now)
    # v5: total = 0.02*62578 + 8000 = 9251.56 ; ratio = 9251.56/10000 = 0.925
    assert "v5" in hb and "$9,252" in hb and "(0.925)" in hb
    assert "v6" in hb and "parity 0/30" in hb
    assert format_heartbeat_multi([], Decimal("62578"), [], now).startswith("\U0001F493")


def test_heartbeat_marks_demo_as_hybrid_instead_of_ratio():
    from decimal import Decimal
    from datetime import datetime, timezone
    from tools.telegram_remote import format_heartbeat_multi

    demo = _snap("demo", rebalances=[{
        "timestamp": "2026-07-04T08:59:00+00:00",
        "portfolio_usdt": 10000.0,
        "price": 62578.0,
    }])
    demo["execution"] = "okx_demo"
    out = format_heartbeat_multi(
        [demo], Decimal("62578"), [], datetime(2026, 7, 5, 8, tzinfo=timezone.utc),
    )

    assert "hibrido" in out
    assert "(0." not in out
