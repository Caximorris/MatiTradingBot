"""Pure, snapshot-only adapters for candidate certification.

These do not import or invoke the legacy order-capable strategy bots.  They
preserve the decision rules while moving sizing and all execution to the shared
certified engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from core.certification import StrategySnapshot, TargetIntent
from strategies.cycle_phase_clock import CyclePhaseClock
from strategies.swing_cycle_core import SwingCycleCoreConfig


@dataclass
class SwingCycleCoreCertifiedAdapter:
    config: SwingCycleCoreConfig
    _last_block: str | None = None
    _last_target: Decimal | None = None
    _sequence: int = 0
    history_limit = 1
    decision_interval_bars = 1

    def __post_init__(self) -> None:
        self._clock = CyclePhaseClock(
            halving_timestamps=self.config.confirmed_halving_timestamps,
            post_halving_end=self.config.phase_post_end,
            bear_onset_start=self.config.phase_bear_start,
            accumulation_start=self.config.phase_accumulation_start,
        )

    def should_evaluate(self, snapshot: StrategySnapshot) -> bool:
        """Use UTC decision windows, never row count, for V7's 4H cadence."""
        at = snapshot.decision_at
        return at.minute == 0 and at.second == 0 and at.microsecond == 0 and at.hour % 4 == 0

    def decide(self, snapshot: StrategySnapshot) -> TargetIntent | None:
        block = self._clock.evaluation_block(snapshot.decision_at)
        if block == self._last_block:
            return None
        self._last_block = block
        _, phase = self._clock.phase_at(snapshot.decision_at - timedelta(hours=self.config.transition_delay_hours))
        target = self.config.bear_onset_btc_pct if phase == "bear_onset" else Decimal("1")
        # Establish the starting exposure without manufacturing a no-op target
        # intent.  Only an executable target transition is an order intent.
        if self._last_target is None:
            self._last_target = target
            return None
        if self._last_target == target:
            return None
        self._last_target = target
        self._sequence += 1
        return TargetIntent(f"v7-certified-{self._sequence}", target_base_pct=target)


@dataclass
class AdaptiveTrendCertifiedAdapter:
    """A causal EMA crossover control; legacy indicators remain untouched."""
    fast: int = 50
    slow: int = 200
    _sequence: int = 0
    history_limit = 200
    decision_interval_bars = 24

    def decide(self, snapshot: StrategySnapshot) -> TargetIntent | None:
        closes = [bar.close for bar in snapshot.bars]
        if len(closes) < self.slow:
            return None
        fast = sum(closes[-self.fast:]) / self.fast
        slow = sum(closes[-self.slow:]) / self.slow
        self._sequence += 1
        return TargetIntent(f"adaptive-certified-{self._sequence}", target_base_pct=Decimal("1") if fast > slow else Decimal("0"))


def swing_cycle_core_factory(config: dict) -> SwingCycleCoreCertifiedAdapter:
    return SwingCycleCoreCertifiedAdapter(SwingCycleCoreConfig.from_dict(config))


def adaptive_trend_factory(config: dict) -> AdaptiveTrendCertifiedAdapter:
    return AdaptiveTrendCertifiedAdapter()
