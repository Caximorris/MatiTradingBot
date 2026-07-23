"""Research-only frozen-v6 decision adapter with causal next-open execution.

This module is deliberately not registered as a strategy.  It reads v6's
private decision code through inheritance but owns every order lifecycle, so it
cannot alter a v6 bot, its state key, defaults, or any exchange client.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import json
from pathlib import Path
from typing import Any

from core.exchange import OrderResult
from strategies.swing_allocator import SwingAllocatorBot, SwingAllocatorConfig


class CausalIntegrityError(RuntimeError):
    """A causal comparator must fail closed rather than silently retry."""


@dataclass(frozen=True)
class CausalDecision:
    timestamp: datetime
    target: Decimal
    current: Decimal
    signals: tuple[str, ...]


@dataclass
class PendingCausalOrder:
    order_id: str
    side: str
    requested_qty: Decimal
    decision: CausalDecision


class CompletedBarClient:
    """Expose only the bar completed before the executor's current bar."""

    def __init__(self, executor: Any) -> None:
        self._executor = executor

    def current_time(self):
        return self._executor.current_time()

    def get_ticker(self, symbol: str) -> Decimal:
        if self._executor._idx <= 0:
            raise CausalIntegrityError("no completed bar available")
        return self._executor._bars[self._executor._idx - 1].close

    def get_ohlcv(self, symbol: str, timeframe: str = "1H", limit: int = 100, bar: str = "1H"):
        frame = self._executor.get_ohlcv(symbol, timeframe, limit + 1, bar)
        return frame.iloc[:-1].tail(limit)

    def get_balance(self):
        return self._executor.get_balance()


class V6FrozenDecisionsCausalExecutionControl(SwingAllocatorBot):
    """Frozen v6 signals + shared BacktestClient causal execution only."""

    name = "V6_FROZEN_DECISIONS_CAUSAL_EXECUTION_CONTROL"

    def __init__(self, executor: Any, config: SwingAllocatorConfig) -> None:
        self._executor = executor
        self._decision_client = CompletedBarClient(executor)
        super().__init__(self._decision_client, config, session=None, risk_manager=None)
        self._pending: PendingCausalOrder | None = None
        self.decisions: list[CausalDecision] = []
        self.execution_events: list[dict[str, str]] = []

    def _is_backtest_client(self) -> bool:
        return True

    def run(self) -> None:
        reconciled = self._reconcile_before_decision()
        if reconciled or self._pending is not None or self._executor._idx <= 0:
            return
        super().run()

    def _initialize(self) -> None:
        # Preserve v6's initial base target, but use the completed close to
        # calculate intent and the shared next-open executor to fill it.
        self._submit_target(Decimal(str(self._cfg.base_btc_pct)), ("init",))
        self._mark_initialized()

    def _rebalance(self, target: float, current: float, signals: list[str]) -> None:
        self._submit_target(Decimal(str(target)), tuple(signals))

    def _submit_target(self, target: Decimal, signals: tuple[str, ...]) -> None:
        balance = self._executor.get_balance()
        base = self._cfg.symbol.split("-")[0]
        decision_price = self._decision_client.get_ticker(self._cfg.symbol)
        total = balance.get("USDT", Decimal("0")) + balance.get(base, Decimal("0")) * decision_price
        current = Decimal("0") if total <= 0 else balance.get(base, Decimal("0")) * decision_price / total
        decision = CausalDecision(self._executor.current_time(), target, current, signals)
        self.decisions.append(decision)
        side = "buy" if target > current else "sell"
        desired = abs(target - current) * total
        if side == "buy":
            # Reserve twice-conservative costs before submitting.  Any next-open
            # gap beyond that is a recorded rejection, never a negative balance.
            desired = min(desired, balance.get("USDT", Decimal("0")) * Decimal("0.995"))
        else:
            desired = min(desired, balance.get(base, Decimal("0")) * decision_price)
        qty = (desired / decision_price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        if qty <= 0:
            return
        client_id = f"v6c{self._executor._idx:08d}"[-32:]
        result = self._executor.place_order(self._cfg.symbol, side, "market", qty,
                                            strategy=self.name, client_order_id=client_id)
        if result.status != "open":
            raise CausalIntegrityError(f"submission_not_open:{result.status}:{result.error}")
        self._pending = PendingCausalOrder(result.order_id, side, qty, decision)
        self.execution_events.append({"event": "submitted", "order_id": result.order_id,
                                      "side": side, "qty": str(qty), "timestamp": decision.timestamp.isoformat()})

    def _reconcile_before_decision(self) -> bool:
        if self._pending is None:
            return False
        result: OrderResult | None = self._executor.get_order_status(self._cfg.symbol, self._pending.order_id)
        if result is None or result.status == "open":
            return True
        if result.status == "rejected":
            # A next-open gap can make an otherwise valid completed-bar intent
            # unaffordable.  Preserve it for audit and wait for a later v6
            # evaluation; never retry inside the same decision block.
            self.execution_events.append({"event": "rejected", "order_id": self._pending.order_id,
                                          "qty": str(self._pending.requested_qty),
                                          "reason": result.error or "next_open_unaffordable"})
            self._pending = None
            return True
        if result.status != "filled" or result.filled_qty != self._pending.requested_qty:
            raise CausalIntegrityError(f"unresolved_or_partial_fill:{getattr(result, 'status', 'missing')}")
        self.execution_events.append({"event": "filled", "order_id": result.order_id,
                                      "qty": str(result.filled_qty), "price": str(result.filled_price),
                                      "fee": str(result.fee), "timestamp": result.timestamp.isoformat()})
        self._pending = None
        return True


def run_current_input_fallback(bars: list[Any], initial_balance: Decimal = Decimal("10000"),
                               cost_mode: str = "realistic") -> tuple[Any, V6FrozenDecisionsCausalExecutionControl]:
    """Run the funding-off frozen-v6 fallback under causal execution.

    This is intentionally not called v6-2 parity: the protected historical
    funding snapshot is unavailable.  It is the valid same-input comparator
    until that immutable snapshot is restored.
    """
    from core.backtest import BacktestClient, BacktestEngine
    cfg = SwingAllocatorConfig(
        instance_id="v6_causal_current_input_fallback",
        use_phase_policy_router=True,
        phase_policy_profile="v5_equiv",
        use_funding_overlay=False,
        funding_overlay_source="bybit",
    )
    client = BacktestClient("BTC-USDT", bars, initial_balance=initial_balance,
                            cost_mode=cost_mode, fill_next_open=True)
    # Match the v7 suite exactly: bars before 2015-01-01 are indicator warmup,
    # never an investable evaluation period.
    start_ms = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    warmup = sum(bar.timestamp < start_ms for bar in bars)
    engine = BacktestEngine(client, lambda _client, _session:
                            V6FrozenDecisionsCausalExecutionControl(client, cfg),
                            warmup_bars=max(20, warmup), timeframe="1H")
    result = engine.run()
    return result, engine.last_strategy


def main() -> None:
    """Direct local runner; no registry, database, paper, or exchange access."""
    from tools.swing_cycle_core_suite import load_bars
    bars, dataset = load_bars()
    result, control = run_current_input_fallback(bars)
    output = {
        "identity": "V6_FROZEN_DECISIONS_CAUSAL_EXECUTION_CONTROL_CURRENT_INPUT_FALLBACK",
        "execution_contract": "completed_bar_decision_next_open_fill",
        "funding_identity": "funding_off_current_input_fallback_not_archival_v6_2",
        "dataset": dataset,
        "final_capital": str(result.final_balance), "cagr": str(result.cagr),
        "max_drawdown_pct": str(result.max_drawdown_pct), "calmar": str(result.calmar),
        "sharpe": str(result.sharpe_ratio), "sortino": str(result.sortino),
        "decisions": len(control.decisions), "execution_events": control.execution_events,
    }
    Path("backtests/v6_causal_comparator_result.json").write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
