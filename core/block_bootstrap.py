"""Fixed-seed dependence-preserving OHLCV block bootstrap."""
from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from data.market_data import OHLCVBar


@dataclass(frozen=True)
class BootstrapSummary:
    method: str
    seed: int
    block_hours: int
    simulations: int
    final_capitals: tuple[Decimal, ...]
    losing_capital_frequency: Decimal
    underperform_baseline_frequency: Decimal


def sample_blocks(bars: list[OHLCVBar], *, block_hours: int, seed: int,
                  stationary: bool = False) -> list[OHLCVBar]:
    """Resample contiguous candle blocks; individual rows are never shuffled."""
    if block_hours < 1 or not bars:
        raise ValueError("positive block size and bars required")
    rng = random.Random(seed)
    result: list[OHLCVBar] = []
    while len(result) < len(bars):
        start = rng.randrange(len(bars))
        length = block_hours if not stationary else max(1, int(rng.expovariate(1 / block_hours)))
        for offset in range(length):
            result.append(bars[(start + offset) % len(bars)])
            if len(result) == len(bars):
                break
    return result


def run_bootstrap(bars: list[OHLCVBar], evaluate: Callable[[list[OHLCVBar]], Decimal],
                  baseline: Decimal, *, seed: int = 20260723, simulations: int = 8,
                  block_hours: int = 168, stationary: bool = False) -> BootstrapSummary:
    values = tuple(evaluate(sample_blocks(bars, block_hours=block_hours, seed=seed + i,
                                          stationary=stationary)) for i in range(simulations))
    return BootstrapSummary("stationary" if stationary else "moving", seed, block_hours, simulations,
                            values, Decimal(sum(value < Decimal("10000") for value in values)) / simulations,
                            Decimal(sum(value < baseline for value in values)) / simulations)
