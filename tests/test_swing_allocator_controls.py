from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig


class FakeClient:
    def __init__(self, price: Decimal = Decimal("100")):
        self.price = price

    def current_time(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc)

    def get_ticker(self, symbol: str):
        return self.price

    def get_ohlcv(self, symbol: str, limit: int = 2):
        return pd.DataFrame(
            {
                "timestamp": [1, 2],
                "open": [100.0, 100.0],
                "high": [101.0, 101.0],
                "low": [99.0, 99.0],
                "close": [100.0, 100.0],
                "volume": [1.0, 1.0],
            }
        )


class BlockingRisk:
    def check_daily_loss(self):
        return True, -123.45


def test_market_data_rejects_anomalous_price_jump():
    bot = SwingAllocatorBot(
        client=FakeClient(price=Decimal("140")),
        config=SwingAllocatorConfig(max_price_jump_pct=0.25),
    )
    assert bot._market_data_ok() is False


def test_risk_manager_blocks_swing_buys_on_daily_loss():
    bot = SwingAllocatorBot(
        client=FakeClient(),
        config=SwingAllocatorConfig(),
        risk_manager=BlockingRisk(),
    )
    assert bot._risk_allows_buy(Decimal("100")) is False


def test_live_rebalance_is_persisted_as_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bot = SwingAllocatorBot(
        client=FakeClient(),
        config=SwingAllocatorConfig(persist_live_rebalance_log=True),
    )

    bot._log_rebalance(
        pct_before=0.6,
        pct_target=0.8,
        pct_after=0.8,
        direction="BUY",
        price=100.0,
        qty=1.0,
        portfolio_usdt=1000.0,
        signals=["test"],
    )

    path = tmp_path / "data" / "runtime" / "swing_rebalances.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["strategy"] == "swing_allocator_btc_usdt"
    assert payload["direction"] == "BUY"
