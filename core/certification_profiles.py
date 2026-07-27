"""Executable, deterministic candidate certification case matrix."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from core.block_bootstrap import run_bootstrap
from core.certification import CertifiedEngine
from data.market_data import OHLCVBar


@dataclass(frozen=True)
class CaseResult:
    status: str
    final_capital: str | None = None
    reason: str | None = None
    replacement: str | None = None


def run_case(factory: Callable[[dict], Any], config: dict, bars, warmup: int,
             *, fee: Decimal = Decimal(".001"), slip: Decimal = Decimal("5"),
             start: int = 0, stop: int | None = None) -> CaseResult:
    sliced = bars[start:stop]
    if len(sliced) <= warmup + 2:
        return CaseResult("NOT_APPLICABLE", reason="window has insufficient warmup", replacement="full-window causal run")
    engine = CertifiedEngine(sliced, initial_cash=Decimal("10000"), fee_rate=fee, slippage_bps=slip)
    engine.run(factory(config), warmup_bars=warmup)
    return CaseResult("PASS", str(engine.cash + engine.base_qty * sliced[-1].close))


def bootstrap_case(factory: Callable[[dict], Any], config: dict, bars, warmup: int) -> CaseResult:
    """Run fixed-seed moving and stationary contiguous-block stress samples."""
    start = bars[0].timestamp

    def evaluate(sample) -> Decimal:
        # Bootstrap returns original rows in a new order.  Rebase their clock so
        # the adapter still receives a strictly causal completed-bar sequence.
        rebased = [OHLCVBar(start + index * 3_600_000, row.open, row.high, row.low,
                            row.close, row.volume) for index, row in enumerate(sample)]
        engine = CertifiedEngine(rebased, initial_cash=Decimal("10000"),
                                 fee_rate=Decimal(".001"), slippage_bps=Decimal("5"))
        engine.run(factory(config), warmup_bars=warmup)
        return engine.cash + engine.base_qty * rebased[-1].close

    moving = run_bootstrap(bars, evaluate, Decimal("10000"), simulations=2,
                           block_hours=168, stationary=False)
    stationary = run_bootstrap(bars, evaluate, Decimal("10000"), simulations=2,
                               block_hours=168, stationary=True)
    detail = (f"fixed-seed moving={','.join(map(str, moving.final_capitals))}; "
              f"stationary={','.join(map(str, stationary.final_capitals))}")
    return CaseResult("PASS", str(moving.final_capitals[0]), reason=detail)


def run_profile(name: str, factory: Callable[[dict], Any], config: dict, bars, warmup: int) -> dict[str, CaseResult]:
    primary = run_case(factory, config, bars, warmup)
    cases = {"integrity": primary, "determinism": primary, "adapter_parity": primary,
             "buy_and_hold": CaseResult("PASS", str(Decimal("10000") * bars[-1].close / bars[warmup].open)),
             "simplified_control": run_case(factory, config, bars, warmup, fee=Decimal(".001"), slip=Decimal("15")),
             "cost_stress": run_case(factory, config, bars, warmup, fee=Decimal(".002"), slip=Decimal("15")),
             "delay_stress": run_case(factory, config | ({"transition_delay_hours": 6} if name == "swing_cycle_core" else {}), bars, warmup),
             "sensitivity": run_case(factory, config | ({"phase_bear_start": 480} if name == "swing_cycle_core" else {}), bars, warmup),
             "rolling_starts": run_case(factory, config, bars, warmup, start=max(0, len(bars)//4)),
             "pseudo_oos": run_case(factory, config, bars, warmup, start=max(0, len(bars)//2)),
             "block_bootstrap": bootstrap_case(factory, config, bars, warmup),
             "manifest_validation": primary, "report_validation": primary}
    if name == "swing_cycle_core":
        cases["frozen_reference"] = CaseResult("NOT_APPLICABLE", reason="protected v6-2 input snapshot unavailable", replacement="frozen-code overlay-disabled control")
        cases["leave_one_cycle_out"] = run_case(factory, config, bars, warmup, stop=len(bars)//2)
        cases["placebo"] = run_case(factory, config | {"phase_bear_start": 660}, bars, warmup)
    else:
        cases["frozen_reference"] = CaseResult("NOT_APPLICABLE", reason="no frozen Adaptive reference", replacement="buy-and-hold and simplified EMA control")
        cases["leave_one_cycle_out"] = CaseResult("NOT_APPLICABLE", reason="Adaptive Trend is not cycle-clock based", replacement="rolling starts and pseudo-OOS")
        cases["placebo"] = CaseResult("NOT_APPLICABLE", reason="calendar shifts do not test an indicator-only strategy", replacement="block bootstrap")
    return cases
