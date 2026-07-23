"""Phase policy profiles for Swing Allocator v6 research.

The first profile, v5_equiv, must reproduce the current v5 regime+halving
allocation before any new candidate is measured.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhasePolicy:
    neutral_target: float
    bull_target: float
    bear_target: float
    suppress_bull: bool = False


PHASE_POLICY_PROFILES: dict[str, dict[str, PhasePolicy]] = {
    "v5_equiv": {
        "post_halving": PhasePolicy(neutral_target=0.80, bull_target=1.00, bear_target=0.60),
        "bull_peak": PhasePolicy(neutral_target=0.80, bull_target=1.00, bear_target=0.60),
        "bear_onset": PhasePolicy(
            neutral_target=0.30,
            bull_target=0.30,
            bear_target=0.20,
            suppress_bull=True,
        ),
        "accumulation": PhasePolicy(neutral_target=0.60, bull_target=0.80, bear_target=0.40),
    },
    # Research-only ablation: retain v5-equivalent bear/accumulation behavior while
    # making both bullish phases a constant 100% BTC target.  It is never a default.
    "bull_phase_hold_research": {
        "post_halving": PhasePolicy(neutral_target=1.00, bull_target=1.00, bear_target=1.00),
        "bull_peak": PhasePolicy(neutral_target=1.00, bull_target=1.00, bear_target=1.00),
        "bear_onset": PhasePolicy(
            neutral_target=0.30, bull_target=0.30, bear_target=0.20, suppress_bull=True,
        ),
        "accumulation": PhasePolicy(neutral_target=0.60, bull_target=0.80, bear_target=0.40),
    },
}


def regime_state(ind: dict | None, price: float, adx_min_trend: float, use_regime: bool) -> str:
    if not use_regime or not ind:
        return "neutral"
    ema50 = ind.get("ema50d", 0.0)
    ema200 = ind.get("ema200d", 0.0)
    adx_v = ind.get("adx", 0.0)
    if ema50 > ema200 and price > ema200 and adx_v > adx_min_trend:
        return "bull"
    if ema50 < ema200:
        return "bear"
    return "neutral"


def phase_policy_target(profile: str, phase: str, regime: str) -> tuple[float, list[str]] | None:
    policies = PHASE_POLICY_PROFILES.get(profile)
    if not policies:
        raise ValueError(f"unknown phase_policy_profile: {profile}")
    policy = policies.get(phase)
    if policy is None:
        return None

    active: list[str] = []
    if regime == "bull":
        target = policy.bull_target
        if policy.suppress_bull:
            active.append("regime_bull_suppressed_bear_onset")
        else:
            active.append("regime_bull")
    elif regime == "bear":
        target = policy.bear_target
        active.append("regime_bear")
    else:
        target = policy.neutral_target

    if phase in ("post_halving", "bull_peak"):
        active.append(f"halving_{phase}")
    elif phase == "bear_onset":
        active.append("halving_bear_onset")

    return target, active
