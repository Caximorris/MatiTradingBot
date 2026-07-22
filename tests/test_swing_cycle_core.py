from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd

from core.exchange import OrderResult
from strategies.cycle_phase_clock import CyclePhaseClock
from strategies.swing_cycle_core import CycleState, SwingCycleCoreBot, SwingCycleCoreConfig


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

    def place_order(self, symbol, side, order_type, size, price=None, strategy=""):
        self.orders.append((side, size))
        if side == "buy":
            self.balances["BTC"] += size
            self.balances["USDT"] -= size * self.price
        else:
            self.balances["BTC"] -= size
            self.balances["USDT"] += size * self.price
        return OrderResult("core-1", symbol, side, order_type, size, price, self.price, size,
                           Decimal("0"), "USDT", "filled", True, strategy, self.now)


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
    bot = SwingCycleCoreBot(client, SwingCycleCoreConfig())
    bot.run()
    client.now += timedelta(hours=4)
    client.bar_time = client.now
    bot.run()
    assert client.orders == [("sell", Decimal("10.000000"))]
    assert bot._state["state"] == CycleState.EXIT_ORDER_SUBMITTED
