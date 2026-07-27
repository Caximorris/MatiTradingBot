"""Fail-closed, causal execution contract for candidate certification.

This module is deliberately separate from the historical ``BacktestClient``.
Legacy runners remain archival only; a candidate can publish evidence only after
it has run through ``CertifiedEngine``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

from data.market_data import OHLCVBar


CONTRACT_VERSION = "certified-execution/v1"


class CertificationError(RuntimeError):
    """Raised when a candidate violates the non-causal execution contract."""


class OrderState(str, Enum):
    DECIDED = "decided"
    SUBMITTED = "submitted"
    OPEN = "open"
    FILLED = "filled"
    RECONCILED = "reconciled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SnapshotBar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class StrategySnapshot:
    """The only market view supplied to a certified strategy.

    ``bars`` ends at the completed decision bar.  There is intentionally no
    client, dataframe, mutable mapping, next bar, or external observation with
    a publication time after ``decision_at``.
    """

    decision_at: datetime
    bars: tuple[SnapshotBar, ...]
    external: Mapping[str, object]
    cash: Decimal
    base_qty: Decimal

    @property
    def latest(self) -> SnapshotBar:
        return self.bars[-1]


@dataclass(frozen=True)
class TargetIntent:
    client_order_id: str
    target_base_qty: Decimal | None = None
    target_base_pct: Decimal | None = None


@dataclass(frozen=True)
class CertifiedOrder:
    client_order_id: str
    state: OrderState
    submitted_at: datetime
    fill_at: datetime | None = None
    fill_price: Decimal | None = None
    quantity: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")


class CertifiedStrategy(Protocol):
    def decide(self, snapshot: StrategySnapshot) -> TargetIntent | None: ...


def contract_hash() -> str:
    return hashlib.sha256(CONTRACT_VERSION.encode()).hexdigest()


def _utc_bar(bar: OHLCVBar) -> SnapshotBar:
    return SnapshotBar(
        timestamp=datetime.fromtimestamp(bar.timestamp / 1000, tz=timezone.utc),
        open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
    )


class CertifiedEngine:
    """Completed-bar decisions, next-open fills, and pre-trade fee reserves."""

    def __init__(self, bars: Iterable[OHLCVBar], *, initial_cash: Decimal,
                 fee_rate: Decimal, slippage_bps: Decimal,
                 external_events: Iterable[tuple[str, datetime, object]] = ()) -> None:
        # The protected canonical cache intentionally retains known identical
        # duplicate observations.  A row-count cadence would make a 4H decision
        # schedule depend on those storage duplicates.  Collapse *only* exact
        # duplicates and reject conflicting or non-monotonic timestamps.
        self._bars = self._normalize_bars(bars)
        if len(self._bars) < 2:
            raise CertificationError("at least two bars are required for causal fills")
        self._raw_hash = self._hash_bars(self._bars)
        self.cash = initial_cash
        self.base_qty = Decimal("0")
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.orders: dict[str, CertifiedOrder] = {}
        self._external = tuple(external_events)

    @staticmethod
    def _normalize_bars(bars: Iterable[OHLCVBar]) -> tuple[OHLCVBar, ...]:
        normalized: list[OHLCVBar] = []
        for bar in bars:
            if normalized and bar.timestamp == normalized[-1].timestamp:
                if bar != normalized[-1]:
                    raise CertificationError("conflicting duplicate candle")
                continue
            if normalized and bar.timestamp < normalized[-1].timestamp:
                raise CertificationError("non-monotonic candle timestamp")
            normalized.append(bar)
        return tuple(normalized)

    @staticmethod
    def _hash_bars(bars: Iterable[OHLCVBar]) -> str:
        rows = [(b.timestamp, str(b.open), str(b.high), str(b.low), str(b.close), str(b.volume)) for b in bars]
        return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()

    def run(self, strategy: CertifiedStrategy, *, warmup_bars: int = 0) -> tuple[CertifiedOrder, ...]:
        seen: set[str] = set()
        for index in range(max(0, warmup_bars), len(self._bars) - 1):
            interval = max(1, int(getattr(strategy, "decision_interval_bars", 1)))
            if (index - warmup_bars) % interval:
                continue
            next_index = index + 1
            while next_index < len(self._bars) and self._bars[next_index].timestamp <= self._bars[index].timestamp:
                next_index += 1
            if next_index >= len(self._bars):
                continue
            decision_bar = self._bars[index]
            decision_at = datetime.fromtimestamp(decision_bar.timestamp / 1000, tz=timezone.utc)
            external = {
                name: value for name, published_at, value in self._external
                if published_at <= decision_at
            }
            history_limit = int(getattr(strategy, "history_limit", index + 1))
            start = max(0, index + 1 - history_limit)
            snapshot = StrategySnapshot(
                decision_at=decision_at,
                bars=tuple(_utc_bar(item) for item in self._bars[start : index + 1]),
                external=MappingProxyType(external),
                cash=self.cash, base_qty=self.base_qty,
            )
            intent = strategy.decide(snapshot)
            if intent is None:
                continue
            if not isinstance(intent, TargetIntent):
                raise CertificationError("strategy may return TargetIntent only")
            if intent.client_order_id in seen or intent.client_order_id in self.orders:
                raise CertificationError("duplicate order intent")
            seen.add(intent.client_order_id)
            self._submit_and_fill(intent, decision_at, self._bars[next_index])
        if self._hash_bars(self._bars) != self._raw_hash:
            raise CertificationError("dataset mutation detected")
        if any(order.state not in {OrderState.RECONCILED, OrderState.REJECTED} for order in self.orders.values()):
            raise CertificationError("unreconciled order")
        if self.cash < 0:
            raise CertificationError("negative cash")
        return tuple(self.orders.values())

    def _submit_and_fill(self, intent: TargetIntent, decision_at: datetime, next_bar: OHLCVBar) -> None:
        if (intent.target_base_qty is None) == (intent.target_base_pct is None):
            raise CertificationError("intent must contain exactly one target form")
        if intent.target_base_pct is not None:
            if not Decimal("0") <= intent.target_base_pct <= Decimal("1"):
                raise CertificationError("target base percentage outside [0, 1]")
            # The engine chooses quantity using the causally available next-open
            # price, never the strategy.  Fees/slippage are reserved first.
            next_open = next_bar.open
            total = self.cash + self.base_qty * next_open
            # A 100% target must reserve fee/slippage before sizing.  Otherwise
            # it is deterministically rejected for insufficient quote cash.
            buy_unit_cost = next_open * (Decimal("1") + self.slippage_bps / Decimal("10000")) * (Decimal("1") + self.fee_rate)
            affordable_qty = self.cash / buy_unit_cost
            requested_qty = total * intent.target_base_pct / next_open
            target_qty = min(requested_qty, self.base_qty + affordable_qty).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        else:
            target_qty = intent.target_base_qty
            if target_qty is None or target_qty < 0:
                raise CertificationError("invalid target quantity")
        delta = target_qty - self.base_qty
        order = CertifiedOrder(intent.client_order_id, OrderState.DECIDED, decision_at)
        self.orders[intent.client_order_id] = order
        if delta == 0:
            self.orders[intent.client_order_id] = CertifiedOrder(intent.client_order_id, OrderState.REJECTED, decision_at)
            return
        fill_at = datetime.fromtimestamp(next_bar.timestamp / 1000, tz=timezone.utc)
        if fill_at <= decision_at:
            raise CertificationError("same-bar decision and fill")
        direction = Decimal("1") if delta > 0 else Decimal("-1")
        price = next_bar.open * (Decimal("1") + direction * self.slippage_bps / Decimal("10000"))
        qty = abs(delta)
        fee = (qty * price * self.fee_rate).quantize(Decimal("0.00000001"))
        # Reserve the maximum required quote before a buy is sized/finalized.
        if delta > 0 and qty * price + fee > self.cash:
            qty = ((self.cash / (price * (Decimal("1") + self.fee_rate)))
                   .quantize(Decimal("0.00000001"), rounding=ROUND_DOWN))
            fee = (qty * price * self.fee_rate).quantize(Decimal("0.00000001"))
            delta = qty
        if delta > 0 and self.cash < qty * price + fee:
            self.orders[intent.client_order_id] = CertifiedOrder(intent.client_order_id, OrderState.REJECTED, decision_at)
            return
        if delta < 0 and self.base_qty < qty:
            self.orders[intent.client_order_id] = CertifiedOrder(intent.client_order_id, OrderState.REJECTED, decision_at)
            return
        if delta > 0:
            self.cash -= qty * price + fee
        else:
            self.cash += qty * price - fee
        self.base_qty += delta
        self.orders[intent.client_order_id] = CertifiedOrder(intent.client_order_id, OrderState.RECONCILED, decision_at, fill_at, price, qty, fee)
