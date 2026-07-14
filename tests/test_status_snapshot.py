from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from tools.status_snapshot import (
    build_bot_records,
    build_paper_portfolios,
    format_iso_madrid,
    format_madrid,
)


class _State(SimpleNamespace):
    def get_config(self):
        return self.config


def _state(name: str, config: dict, *, active: bool = True):
    return _State(
        strategy_name=name,
        symbol="BTC-USDT",
        is_active=active,
        last_run=datetime(2026, 7, 14, 8, 39, tzinfo=timezone.utc),
        total_pnl=Decimal("0"),
        config=config,
    )


def _wallet(path, btc: str, cash: str):
    path.write_text(json.dumps({"balances": {"BTC": btc, "USDT": cash}}), encoding="utf-8")


def test_records_hide_internal_rows_and_show_real_demo_execution_pair():
    rows = build_bot_records([
        _state("swing_allocator_v6_btc_usdt", {
            "instance_id": "v6", "paper_portfolio_id": "swing_v6",
        }),
        _state("swing_allocator_demo_btc_usdt", {
            "instance_id": "demo", "paper_portfolio_id": "okx_demo",
            "execution": "okx_demo", "execution_quote": "USDC",
        }),
        _state("prop_swing_btc_usdt", {"paper_portfolio_id": "prop_cft"}),
        _state("swing_allocator_demo", {"instance_id": "demo"}, active=False),
        _state("prop_swing", {}, active=False),
    ])

    assert [r["label"] for r in rows] == ["v6", "demo", "prop"]
    demo = rows[1]
    assert demo["signal_symbol"] == "BTC-USDT"
    assert demo["execution_symbol"] == "BTC-USDC"
    assert demo["execution_venue"] == "OKX Demo"


def test_portfolios_are_isolated_and_reverse_demo_quote_alias_for_display(tmp_path):
    records = build_bot_records([
        _state("swing_allocator_v6_btc_usdt", {
            "instance_id": "v6", "paper_portfolio_id": "swing_v6",
        }),
        _state("swing_allocator_demo_btc_usdt", {
            "instance_id": "demo", "paper_portfolio_id": "okx_demo",
            "execution": "okx_demo", "execution_quote": "USDC",
        }),
    ])
    _wallet(tmp_path / "paper_state_swing_v6.json", "0.03", "8000")
    _wallet(tmp_path / "paper_state_okx_demo.json", "0.04", "8700")

    portfolios = build_paper_portfolios(records, tmp_path)

    assert portfolios[0]["quote_currency"] == "USDT"
    assert portfolios[0]["quote_balance"] == Decimal("8000")
    assert portfolios[1]["quote_currency"] == "USDC"
    assert portfolios[1]["quote_balance"] == Decimal("8700")
    assert portfolios[1]["quote_is_alias"] is True
    assert portfolios[1]["wallet_path"].name == "paper_state_okx_demo.json"


def test_missing_wallet_is_explicit_and_madrid_time_is_rendered(tmp_path):
    records = build_bot_records([
        _state("prop_swing_btc_usdt", {"paper_portfolio_id": "prop_cft"}),
    ])
    portfolio = build_paper_portfolios(records, tmp_path)[0]

    assert portfolio["wallet_exists"] is False
    assert portfolio["quote_balance"] == Decimal("0")
    assert format_madrid(records[0]["last_run"]) == "14/07 10:39 CEST"
    assert format_iso_madrid("2026-07-14T08:00:00+00:00") == "14/07 10:00 CEST"
    assert format_madrid(None) == "—"
