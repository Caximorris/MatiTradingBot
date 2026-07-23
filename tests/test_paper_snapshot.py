from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tools import paper_snapshot as ps
from core.v7_operations import canonical_hash
from tools.v7_paper_setup import SHADOW_NAME, config_for


# --- Fakes minimos para simular BotState + session sin DB real ----------------

class _FakeBot:
    def __init__(self, name, symbol, is_active, last_run, config):
        self.strategy_name = name
        self.symbol = symbol
        self.is_active = is_active
        self.last_run = last_run
        self._config = config

    def get_config(self):
        return self._config


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_a, **_k):
        return _FakeQuery(self._rows)


def _write_wallet(path, btc, usdt):
    path.write_text(json.dumps({"balances": {"BTC": btc, "USDT": usdt}}), encoding="utf-8")


def _write_v7_promotion_report(path):
    report = {
        "promotion_eligible": False,
        "state": {
            "checks": {
                "transition_journal_valid": True,
                "shadow_state_valid": True,
                "configuration_evidence_valid": True,
            },
            "counters": {
                "duplicate_transitions": 0,
                "unexplained_error_locks": 0,
                "fail_open_events": 0,
                "unreconciled_position_events": 0,
                "v6_regressions": 0,
                "production_live_orders": 0,
            },
        },
    }
    report["report_hash"] = canonical_hash(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding="utf-8")


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def test_read_paper_balances_missing_file_is_empty(tmp_path):
    assert ps.read_paper_balances(tmp_path / "nope.json") == {}


def test_read_paper_balances_parses_decimals(tmp_path):
    p = tmp_path / "w.json"
    _write_wallet(p, "0.5", "1000")
    bals = ps.read_paper_balances(p)
    assert bals == {"BTC": Decimal("0.5"), "USDT": Decimal("1000")}


def test_perf_ratio_below_one_when_worse_than_bnh():
    # INIT: 10000 USDT @ 20000. Ahora precio 40000 (x2). B&H valdria 20000.
    # El bot tiene 0.25 BTC + 0 USDT = 10000 -> bot/B&H = 0.5
    balances = {"BTC": Decimal("0.25"), "USDT": Decimal("0")}
    reb = [{"direction": "INIT", "portfolio_usdt": 10000, "price": 20000}]
    equity, ratio = ps.perf_ratio(balances, reb, Decimal("40000"))
    assert equity == Decimal("10000")
    assert abs(ratio - 0.5) < 1e-9


def test_perf_ratio_none_without_price_or_rebalances():
    assert ps.perf_ratio({"BTC": Decimal("1")}, [], Decimal("100")) == (None, None)
    assert ps.perf_ratio({"BTC": Decimal("1")}, [{"x": 1}], None) == (None, None)


def test_next_4h_eval_rounds_to_block():
    nxt, mins = ps.next_4h_eval(datetime(2026, 7, 20, 9, 15, tzinfo=timezone.utc))
    assert nxt == datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    assert mins == 165


def test_discover_bots_includes_prop_and_excludes_other_strategies():
    rows = [
        _FakeBot("swing_allocator_v6_btc_usdt", "BTC-USDT", True, NOW,
                 {"instance_id": "v6", "paper_portfolio_id": "swing_v6"}),
        _FakeBot("prop_swing_btc_usdt", "BTC-USDT", True, NOW,
                 {"instance_id": "prop", "paper_portfolio_id": "prop_cft"}),
        _FakeBot("pro_trend_btc_usdt", "BTC-USDT", False, NOW, {}),
        _FakeBot("prop_swing", "BTC-USDT", False, NOW, {}),
    ]

    bots = ps.discover_bots(_FakeSession(rows))

    assert [b["name"] for b in bots] == [
        "swing_allocator_v6_btc_usdt", "prop_swing_btc_usdt",
    ]


def test_build_snapshots_includes_v7_runtime_health(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "RUNTIME", tmp_path)
    config = config_for("shadow")
    journal = tmp_path / "v7_btc_usdt_shadow" / "transitions.jsonl"
    journal.parent.mkdir()
    journal.write_text("evidence\n", encoding="utf-8")
    config["transition_journal_path"] = str(journal)
    _write_v7_promotion_report(tmp_path / "v7" / "promotion_report.json")
    _write_wallet(tmp_path / "paper_state_swing_cycle_core_v7_btc_usdt_shadow.json", "0", "1000")

    snaps = ps.build_snapshots(
        _FakeSession([_FakeBot(SHADOW_NAME, "BTC-USDT", True, NOW, config)]),
        price=Decimal("40000"), now=NOW, rebalances_path=tmp_path / "empty.jsonl",
    )

    assert len(snaps) == 1
    health = snaps[0]["v7_health"]
    assert snaps[0]["is_v7"] is True
    assert health["service_managed"] is True
    assert health["execution_valid"] is True
    assert health["journal_exists"] is True
    assert health["promotion_report_valid"] is True
    assert health["promotion_report_failures"] == []


def test_v7_health_fails_closed_when_configuration_evidence_is_invalid(tmp_path):
    report_path = tmp_path / "v7" / "promotion_report.json"
    _write_v7_promotion_report(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["state"]["checks"]["configuration_evidence_valid"] = False
    report["report_hash"] = canonical_hash({key: value for key, value in report.items() if key != "report_hash"})
    report_path.write_text(json.dumps(report), encoding="utf-8")

    health = ps.v7_health({}, runtime_dir=tmp_path)

    assert health["promotion_report_valid"] is True
    assert health["promotion_report_failures"] == ["configuration_evidence_valid"]


def test_build_snapshots_marks_stale_and_computes_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "RUNTIME", tmp_path)
    reb_path = tmp_path / "reb.jsonl"
    reb_path.write_text(json.dumps({
        "strategy": "swing_allocator_v5_btc_usdt", "direction": "INIT",
        "portfolio_usdt": 10000, "price": 20000, "timestamp": "2026-07-04T00:00:00+00:00",
        "btc_pct_after": 0.6,
    }) + "\n", encoding="utf-8")
    _write_wallet(tmp_path / "paper_state_v5.json", "0.3", "4000")

    rows = [
        _FakeBot("swing_allocator_v5_btc_usdt", "BTC-USDT", True,
                 NOW - timedelta(minutes=30), {"paper_portfolio_id": "v5", "instance_id": "v5"}),
        _FakeBot("swing_allocator", "BTC-USDT", True, NOW, {}),   # fila de estado -> excluida
        _FakeBot("swing_allocator_v5", "BTC-USDT", False, NOW,
                 {"initialized": True}),   # estado de instancia -> excluido
    ]
    snaps = ps.build_snapshots(_FakeSession(rows), price=Decimal("40000"), now=NOW,
                               rebalances_path=reb_path)
    assert len(snaps) == 1
    s = snaps[0]
    assert s["label"] == "v5"
    assert s["stale"] is True          # ultimo tick hace 30 min > 10
    assert s["n_rebalances"] == 1
    assert s["equity_usd"] == Decimal("0.3") * Decimal("40000") + Decimal("4000")
    assert s["btc_pct"] is not None
