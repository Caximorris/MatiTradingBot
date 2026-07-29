"""Hard risk envelope and kill-switch policy for the V8 continuous Demo canary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Mapping

from .adapter import SafetyError

HARD_NOTIONAL_USD = Decimal("1000")
HARD_DAILY_LOSS_USD = Decimal("25")
HARD_TOTAL_LOSS_USD = Decimal("100")
HARD_LEVERAGE = Decimal("2")
HARD_MIN_LIQ_DISTANCE_PCT = Decimal("35")
HARD_MAX_SPREAD_BPS = Decimal("20")
HARD_MAX_SLIPPAGE_BPS = Decimal("15")
HARD_MARKET_AGE_SECONDS = Decimal("5")
HARD_STREAM_AGE_SECONDS = Decimal("15")
HARD_CLOCK_DRIFT_SECONDS = Decimal("2")
HARD_API_FAILURES = 3
HARD_RECONCILIATION_SECONDS = Decimal("30")
EXPIRY_WARNING_DAYS = Decimal("30")
EXPIRY_NEW_STOP_DAYS = Decimal("14")
EXPIRY_MANDATORY_FLAT_DAYS = Decimal("7")


def _env_decimal(source: Mapping[str, str], name: str, default: str) -> Decimal:
    try:
        return Decimal(source.get(name, default))
    except Exception as exc:
        raise SafetyError(f"invalid canary configuration: {name}") from exc


@dataclass(frozen=True)
class CanaryConfig:
    enabled: bool
    max_notional_usd: Decimal
    daily_loss_usd: Decimal
    total_loss_usd: Decimal
    minimum_liquidation_distance_pct: Decimal
    maximum_spread_bps: Decimal
    maximum_slippage_bps: Decimal
    maximum_market_age_seconds: Decimal
    maximum_stream_age_seconds: Decimal
    maximum_clock_drift_seconds: Decimal
    maximum_api_failures: int
    maximum_reconciliation_seconds: Decimal

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> "CanaryConfig":
        values = source or os.environ
        enabled = values.get("V8_XPERP_CONTINUOUS_DEMO_ENABLED", "").lower() == "true"
        config = cls(
            enabled,
            _env_decimal(values, "V8_XPERP_MAX_NOTIONAL_USD", "1000"),
            _env_decimal(values, "V8_XPERP_DAILY_LOSS_USD", "25"),
            _env_decimal(values, "V8_XPERP_TOTAL_LOSS_USD", "100"),
            _env_decimal(values, "V8_XPERP_MIN_LIQ_DISTANCE_PCT", "35"),
            _env_decimal(values, "V8_XPERP_MAX_SPREAD_BPS", "20"),
            _env_decimal(values, "V8_XPERP_MAX_SLIPPAGE_BPS", "15"),
            _env_decimal(values, "V8_XPERP_MAX_MARKET_AGE_SECONDS", "5"),
            _env_decimal(values, "V8_XPERP_MAX_STREAM_AGE_SECONDS", "15"),
            _env_decimal(values, "V8_XPERP_MAX_CLOCK_DRIFT_SECONDS", "2"),
            int(values.get("V8_XPERP_MAX_API_FAILURES", "3")),
            _env_decimal(values, "V8_XPERP_MAX_RECONCILIATION_SECONDS", "30"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        ceilings = (
            ("notional", self.max_notional_usd, HARD_NOTIONAL_USD),
            ("daily loss", self.daily_loss_usd, HARD_DAILY_LOSS_USD),
            ("total loss", self.total_loss_usd, HARD_TOTAL_LOSS_USD),
            ("spread", self.maximum_spread_bps, HARD_MAX_SPREAD_BPS),
            ("slippage", self.maximum_slippage_bps, HARD_MAX_SLIPPAGE_BPS),
            ("market age", self.maximum_market_age_seconds, HARD_MARKET_AGE_SECONDS),
            ("stream age", self.maximum_stream_age_seconds, HARD_STREAM_AGE_SECONDS),
            ("clock drift", self.maximum_clock_drift_seconds, HARD_CLOCK_DRIFT_SECONDS),
            ("reconciliation duration", self.maximum_reconciliation_seconds, HARD_RECONCILIATION_SECONDS),
        )
        if any(value <= 0 or value > ceiling for _, value, ceiling in ceilings):
            raise SafetyError("canary configuration exceeds a hard safety ceiling")
        if self.minimum_liquidation_distance_pct < HARD_MIN_LIQ_DISTANCE_PCT:
            raise SafetyError("canary liquidation threshold is below the hard safety floor")
        if self.maximum_api_failures < 1 or self.maximum_api_failures > HARD_API_FAILURES:
            raise SafetyError("canary API-failure limit exceeds the hard safety ceiling")
        if self.daily_loss_usd > self.total_loss_usd:
            raise SafetyError("daily canary loss limit exceeds total loss limit")


@dataclass(frozen=True)
class CappedTarget:
    requested_target: str
    requested_notional: Decimal
    allowed_notional: Decimal
    signed_contracts: Decimal
    cap_reduced: bool


TARGET_MULTIPLIER = {
    "flat": Decimal("0"),
    "long 1x": Decimal("1"),
    "long 2x": Decimal("2"),
    "short 2x": Decimal("-2"),
}


def cap_target(
    *,
    target: str,
    equity_usdc: Decimal,
    adverse_price: Decimal,
    contract_value: Decimal,
    lot_size: Decimal,
    margin_safe_notional: Decimal,
    existing_notional: Decimal = Decimal("0"),
    pending_open_notional: Decimal = Decimal("0"),
    config: CanaryConfig,
) -> CappedTarget:
    if target not in TARGET_MULTIPLIER:
        raise SafetyError("unsupported V8 canary target")
    if min(equity_usdc, adverse_price, contract_value, lot_size) <= 0:
        raise SafetyError("invalid canary target inputs")
    requested = equity_usdc * TARGET_MULTIPLIER[target]
    if requested == 0:
        return CappedTarget(target, requested, Decimal("0"), Decimal("0"), existing_notional != 0)
    price_safe_cap = min(
        config.max_notional_usd,
        margin_safe_notional,
    ) / (Decimal("1") + config.maximum_slippage_bps / Decimal("10000"))
    available_cap = price_safe_cap - max(Decimal("0"), pending_open_notional)
    if available_cap <= 0:
        raise SafetyError("pending exposure exhausts the canary cap")
    allowed = min(abs(requested), available_cap)
    if existing_notional > allowed:
        raise SafetyError("existing position is larger than the capped target")
    raw_contracts = allowed / (adverse_price * contract_value)
    contracts = (raw_contracts / lot_size).to_integral_value(rounding=ROUND_DOWN) * lot_size
    actual = contracts * adverse_price * contract_value
    if contracts <= 0 or actual > config.max_notional_usd:
        raise SafetyError("capped canary target cannot produce a safe executable lot")
    signed = contracts if requested > 0 else -contracts
    return CappedTarget(target, requested, actual, signed, actual < abs(requested))


class KillAction(str, Enum):
    BLOCK_STOP_MANUAL = "block_stop_manual"
    BLOCK_NO_MUTATION_MANUAL = "block_no_mutation_manual"
    BLOCK_CANCEL_KNOWN = "block_cancel_known"
    CANCEL_FLATTEN_STOP_MANUAL = "cancel_flatten_stop_manual"


KILL_SWITCH_ACTIONS: dict[str, KillAction] = {
    "environment_mismatch": KillAction.BLOCK_STOP_MANUAL,
    "live_credential_detection": KillAction.BLOCK_STOP_MANUAL,
    "process_lock_conflict": KillAction.BLOCK_STOP_MANUAL,
    "corrupt_journal": KillAction.BLOCK_STOP_MANUAL,
    "startup_recovery_failure": KillAction.BLOCK_STOP_MANUAL,
    "unknown_position": KillAction.BLOCK_NO_MUTATION_MANUAL,
    "unknown_order": KillAction.BLOCK_NO_MUTATION_MANUAL,
    "multiple_positions": KillAction.BLOCK_NO_MUTATION_MANUAL,
    "multiple_instruments": KillAction.BLOCK_NO_MUTATION_MANUAL,
    "rest_ws_disagreement": KillAction.BLOCK_CANCEL_KNOWN,
    "stale_market": KillAction.BLOCK_CANCEL_KNOWN,
    "stale_private_stream": KillAction.BLOCK_CANCEL_KNOWN,
    "excessive_spread": KillAction.BLOCK_CANCEL_KNOWN,
    "excessive_slippage": KillAction.BLOCK_CANCEL_KNOWN,
    "clock_drift": KillAction.BLOCK_CANCEL_KNOWN,
    "api_failures": KillAction.BLOCK_STOP_MANUAL,
    "reconciliation_timeout": KillAction.BLOCK_STOP_MANUAL,
    "margin_tier_failure": KillAction.BLOCK_STOP_MANUAL,
    "liquidation_distance": KillAction.CANCEL_FLATTEN_STOP_MANUAL,
    "position_above_cap": KillAction.CANCEL_FLATTEN_STOP_MANUAL,
    "daily_loss": KillAction.CANCEL_FLATTEN_STOP_MANUAL,
    "total_loss": KillAction.CANCEL_FLATTEN_STOP_MANUAL,
    "expiry_mandatory_flat": KillAction.CANCEL_FLATTEN_STOP_MANUAL,
    "manual_emergency_stop": KillAction.CANCEL_FLATTEN_STOP_MANUAL,
}


def kill_action(reason: str) -> KillAction:
    try:
        return KILL_SWITCH_ACTIONS[reason]
    except KeyError as exc:
        raise SafetyError("unknown canary kill-switch reason") from exc
