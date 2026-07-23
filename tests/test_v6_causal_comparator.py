from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.backtest import BacktestClient
from data.market_data import OHLCVBar
from strategies.swing_allocator import SwingAllocatorConfig
from tools.v6_causal_comparator import V6FrozenDecisionsCausalExecutionControl


def _bar(hour: int, open_: str, close: str) -> OHLCVBar:
    return OHLCVBar(int((datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour)).timestamp() * 1000),
                    Decimal(open_), Decimal(open_), Decimal(open_), Decimal(close), Decimal("1"))


def test_frozen_v6_decision_uses_completed_bar_and_next_open_fill():
    client = BacktestClient("BTC-USDT", [_bar(0, "100", "100"), _bar(1, "120", "120"), _bar(2, "121", "121")],
                            initial_balance=Decimal("1000"), fill_next_open=True, cost_mode="realistic")
    config = SwingAllocatorConfig(instance_id="causal_control", use_funding_overlay=False)
    bot = V6FrozenDecisionsCausalExecutionControl(client, config)
    client.advance(0)
    bot.run()  # no completed bar: cannot decide
    assert not bot.decisions
    client.advance(1)
    bot.run()
    assert bot.decisions[0].timestamp == client.current_time()
    assert bot.execution_events[0]["event"] == "submitted"
    client.advance(2)
    bot.run()
    assert bot.execution_events[1]["event"] == "filled"
    assert len(client._executed) == 1
    assert client._executed[0].price == Decimal("121.06")  # next open + realistic slippage


def test_pending_order_suppresses_duplicate_v6_execution():
    client = BacktestClient("BTC-USDT", [_bar(i, "100", "100") for i in range(4)],
                            initial_balance=Decimal("1000"), fill_next_open=True)
    bot = V6FrozenDecisionsCausalExecutionControl(client, SwingAllocatorConfig(use_funding_overlay=False))
    client.advance(1)
    bot.run()
    bot.run()
    assert len(bot.execution_events) == 1
