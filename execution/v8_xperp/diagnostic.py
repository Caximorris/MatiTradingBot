"""Frozen, non-optimizing comparisons for historical V8 cold starts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Callable

from .bootstrap import (
    BootstrapConfig,
    IndexPriceSample,
    calculate_bootstrap,
    operational_phase,
)


def compare_cold_start(
    at: datetime,
    *,
    sample_after: Callable[[datetime, datetime], IndexPriceSample],
    config: BootstrapConfig | None = None,
) -> dict[str, object]:
    """Compare frozen leverage policies at one preregistered timestamp."""
    policy = config or BootstrapConfig()
    phase = operational_phase(at)
    reference = sample_after(phase.last_transition_at, at)
    current = sample_after(at, at)
    decision = calculate_bootstrap(
        environment="okx_demo",
        account_hash="diagnostic",
        instrument_id="BTC-XPERP-DIAGNOSTIC",
        phase=phase,
        reference=reference,
        current=current,
        eligible_equity=Decimal("1000"),
        margin_safe_leverage=Decimal("2"),
        liquidation_safe_leverage=Decimal("2"),
        account_safe_leverage=Decimal("2"),
        config=policy,
    )
    adverse = Decimal(decision.adverse_move_to_reference)
    leverages = {
        "flat_until_transition": Decimal("0"),
        "fixed_1x": Decimal("1"),
        "immediate_2x": Decimal("2"),
        "dynamic": Decimal(decision.calculated_leverage),
    }
    return {
        "cold_start_at": at.isoformat(),
        "phase": asdict(phase),
        "reference": asdict(reference),
        "current": asdict(current),
        "adverse_move_to_reference": str(adverse),
        "policies": {
            name: {
                "leverage": str(leverage),
                "reference_loss_fraction": str(adverse * leverage),
            }
            for name, leverage in leverages.items()
        },
        "dynamic_enter": decision.enter,
        "dynamic_reason": decision.reason,
    }
