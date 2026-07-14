from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tools import paper_snapshot as ps


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
