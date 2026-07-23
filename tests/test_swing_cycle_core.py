from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from core.exchange import OrderResult
from core.backtest import BacktestClient
from data.market_data import OHLCVBar
from strategies.cycle_phase_clock import CyclePhaseClock
from strategies.swing_cycle_core import CycleState, SwingCycleCoreBot, SwingCycleCoreConfig
from core.v7_operations import TransitionJournal


class CycleClient:
    def __init__(self, now: datetime, btc: str = "0", usdt: str = "1000") -> None:
        self.now = now
        self.price = Decimal("100")
        self.balances = {"BTC": Decimal(btc), "USDT": Decimal(usdt)}
        self.orders: list[tuple[str, Decimal]] = []
        self.bar_time = now

    def current_time(self):
        return self.now

    def get_ticker(self, symbol):
        return self.price

    def get_balance(self):
        return self.balances.copy()

    def get_ohlcv(self, symbol, limit=2):
        return pd.DataFrame({"timestamp": [int(self.bar_time.timestamp() * 1000)]})

    def place_order(self, symbol, side, order_type, size, price=None, strategy="", **_kwargs):
        self.orders.append((side, size))
        if side == "buy":
            self.balances["BTC"] += size
            self.balances["USDT"] -= size * self.price
        else:
            self.balances["BTC"] -= size
            self.balances["USDT"] += size * self.price
        return OrderResult("core-1", symbol, side, order_type, size, price, self.price, size,
                           Decimal("0"), "USDT", "filled", True, strategy, self.now)

    def get_open_orders(self, symbol):
        return []


def _at(days: int) -> datetime:
    return datetime(2024, 4, 20, tzinfo=timezone.utc) + timedelta(days=days, hours=12)


def test_frozen_clock_target_policy_and_conservative_variant():
    bot = SwingCycleCoreBot(CycleClient(_at(200)), SwingCycleCoreConfig())
    assert bot.target_for_phase("post_halving") == Decimal("1")
    assert bot.target_for_phase("bull_peak") == Decimal("1")
    assert bot.target_for_phase("bear_onset") == Decimal("0")
    assert bot.target_for_phase("accumulation") == Decimal("1")
    conservative = SwingCycleCoreBot(CycleClient(_at(600)), SwingCycleCoreConfig.from_dict({"bear_onset_btc_pct": "0.2"}))
    assert conservative.target_for_phase("bear_onset") == Decimal("0.2")


def test_clock_is_immutable_and_has_no_macro_global_contamination():
    first = CyclePhaseClock(bear_onset_start=540)
    second = CyclePhaseClock(bear_onset_start=600)
    assert first.phase_at(_at(550))[1] == "bear_onset"
    assert second.phase_at(_at(550))[1] == "bull_peak"
    assert first.phase_at(_at(550))[1] == "bear_onset"


def test_exact_halving_timestamp_never_activates_at_midnight():
    event = CyclePhaseClock().halving_timestamps[-1]
    assert CyclePhaseClock().phase_at(event - timedelta(seconds=1))[1] == "accumulation"
    assert CyclePhaseClock().phase_at(event)[1] == "post_halving"


def test_causal_price_uses_previous_completed_backtest_bar():
    first = OHLCVBar(int(datetime(2024, 4, 20, tzinfo=timezone.utc).timestamp() * 1000),
                     Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("1"))
    second = OHLCVBar(int((datetime(2024, 4, 20, 1, tzinfo=timezone.utc)).timestamp() * 1000),
                      Decimal("200"), Decimal("200"), Decimal("200"), Decimal("200"), Decimal("1"))
    client = BacktestClient("BTC-USDT", [first, second], fill_next_open=True)
    client.advance(1)
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig())
    assert bot._safe_price() == Decimal("100")


def test_bear_transition_exits_once_and_stable_block_is_idempotent():
    client = CycleClient(_at(600), btc="10", usdt="0")
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig())
    bot.run()
    assert client.orders == [("sell", Decimal("10.000000"))]
    assert bot._state["state"] == CycleState.BEAR_CASH
    client.now += timedelta(hours=4)
    client.bar_time = client.now
    bot.run()
    assert len(client.orders) == 1


def test_same_target_phase_crossing_is_descriptive_not_a_transition_or_order(tmp_path: Path):
    client = CycleClient(_at(179), btc="10", usdt="0")
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig(
        transition_journal_path=str(tmp_path / "transitions.jsonl")
    ))
    bot.run()  # post_halving, target 1
    client.now = _at(180)
    client.bar_time = client.now
    bot.run()  # bull_peak, still target 1

    assert client.orders == []
    assert [event["event_type"] for event in bot._event_log] == ["decision", "decision"]
    journal = TransitionJournal(tmp_path / "transitions.jsonl").validate()
    assert [(row["previous_phase"], row["new_phase"], row["previous_target"], row["new_target"])
            for row in journal] == [
                ("unknown", "post_halving", "unknown", "1"),
                ("post_halving", "bull_peak", "1", "1"),
            ]


def test_full_clock_range_has_only_two_target_transitions_per_completed_cycle():
    clock = CyclePhaseClock()
    bot = SwingCycleCoreBot(CycleClient(_at(1)), SwingCycleCoreConfig())
    for index, halving in enumerate(clock.halving_timestamps[:-1]):
        next_halving = clock.halving_timestamps[index + 1]
        # All four phase labels remain available across every confirmed cycle;
        # only entry to and exit from bear_onset changes exposure.
        phases = [clock.phase_at(halving + timedelta(days=days))[1]
                  for days in (1, 180, 540, 900)]
        targets = [bot.target_for_phase(phase) for phase in phases]
        assert phases == ["post_halving", "bull_peak", "bear_onset", "accumulation"]
        assert sum(a != b for a, b in zip(targets, targets[1:])) == 2
        assert halving < next_halving


def test_invalid_persisted_phase_or_order_state_is_rejected_before_use():
    bot = SwingCycleCoreBot(CycleClient(_at(600)), SwingCycleCoreConfig())
    invalid_phase = bot._fresh_state() | {"phase": "invented_phase"}
    invalid_order = bot._fresh_state() | {"state": CycleState.EXIT_ORDER_SUBMITTED}
    import pytest
    with pytest.raises(ValueError, match="phase"):
        bot._validate_persisted_state(invalid_phase)
    with pytest.raises(ValueError, match="durable order"):
        bot._validate_persisted_state(invalid_order)


def test_accumulation_transition_buys_and_bypasses_normal_threshold():
    client = CycleClient(_at(901), btc="0", usdt="1000")
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig(rebalance_threshold=Decimal("1")))
    bot.run()
    assert client.orders == [("buy", Decimal("9.950000"))]
    assert bot._state["state"] == CycleState.STABLE_RISK_ON


def test_stale_ticker_bar_and_unknown_pre_halving_fail_closed_without_order():
    client = CycleClient(_at(600), btc="10", usdt="0")
    client.bar_time = client.now - timedelta(hours=6)
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig())
    bot.run()
    assert client.orders == []
    client.now = datetime(2010, 1, 1, tzinfo=timezone.utc)
    client.bar_time = client.now
    bot.run()
    assert bot._state["state"] == CycleState.ERROR_LOCKED


def test_unavailable_ticker_fails_closed_without_consuming_transition():
    client = CycleClient(_at(600), btc="10", usdt="0")
    client.price = Decimal("0")
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig())
    bot.run()
    assert client.orders == []
    assert bot._state["last_block"] is None


def test_open_order_is_never_resubmitted_without_explicit_reconciliation():
    client = CycleClient(_at(600), btc="10", usdt="0")

    def open_order(*args, **kwargs):
        client.orders.append((args[1], args[3]))
        return OrderResult("pending-1", args[0], args[1], args[2], args[3], None, None,
                           Decimal("0"), Decimal("0"), "USDT", "open", True,
                           kwargs["strategy"], client.now)

    client.place_order = open_order
    client.get_open_orders = lambda _symbol: [{"order_id": "pending-1"}]
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig())
    bot.run()
    client.now += timedelta(hours=4)
    client.bar_time = client.now
    bot.run()
    assert client.orders == [("sell", Decimal("10.000000"))]
    assert bot._state["state"] == CycleState.EXIT_ORDER_SUBMITTED


def test_submitted_order_reconciles_once_when_adapter_reports_causal_fill():
    client = CycleClient(_at(600), btc="10", usdt="0")
    first = {"value": True}

    def deferred(*args, **kwargs):
        client.orders.append((args[1], args[3]))
        return OrderResult("deferred-1", args[0], args[1], args[2], args[3], None, None,
                           Decimal("0"), Decimal("0"), "USDT", "open", True,
                           kwargs["strategy"], client.now)

    def observed(_symbol, _order_id):
        if first["value"]:
            first["value"] = False
            return OrderResult("deferred-1", "BTC-USDT", "sell", "market", Decimal("10"),
                               None, None, Decimal("0"), Decimal("0"), "USDT", "open", True,
                               "", client.now)
        client.balances = {"BTC": Decimal("0"), "USDT": Decimal("1000")}
        return OrderResult("deferred-1", "BTC-USDT", "sell", "market", Decimal("10"),
                           None, Decimal("100"), Decimal("10"), Decimal("0"), "USDT", "filled", True,
                           "", client.now)

    client.place_order = deferred
    client.get_order_status = observed
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig())
    bot.run()
    client.now += timedelta(hours=4)
    client.bar_time = client.now
    bot.run()
    assert bot._state["state"] == CycleState.EXIT_ORDER_SUBMITTED
    client.now += timedelta(hours=4)
    client.bar_time = client.now
    bot.run()
    assert bot._state["state"] == CycleState.BEAR_CASH
    assert bot._state["order_id"] is None
    assert len(client.orders) == 1
