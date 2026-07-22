from __future__ import annotations

import json

from reporting.swing_journal import write_swing_journal


def test_non_btc_journal_uses_generic_inventory_fields_only(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = write_swing_journal(
        rebalance_log=[{
            "direction": "INIT",
            "price": 2000.0,
            "btc_pct_after": 0.5,
        }],
        strategy_name="Swing Allocator",
        symbol="ETH-USDT",
        timeframe="1H",
        from_date="2021-07-01",
        to_date="2026-01-01",
        cost_mode="realistic",
        config_overrides={},
        initial_balance=10000.0,
        final_balance=12000.0,
        final_btc_qty=0.0,
        asset_name="ETH",
        final_asset_qty=4.0,
    )

    stats = json.loads((tmp_path / path).read_text(encoding="utf-8"))["statistics"]

    assert stats["asset"] == "ETH"
    assert stats["final_asset_qty"] == 4.0
    assert stats["bnh_initial_asset"] == 5.0
    assert stats["asset_vs_bnh_ratio"] == 0.8
    assert stats["final_btc_qty"] == 0.0
    assert stats["bnh_initial_btc"] == 0.0
    assert stats["btc_vs_bnh_ratio"] == 0.0
