"""Disabled-by-default bounded lifecycle for the V8 OKX Demo canary."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .adapter import ENVIRONMENT, PreflightReport, SafetyError, V8XPerpDemoAdapter, _decimal, _utc_now
from .canary import (
    CanaryConfig,
    CappedTarget,
    HARD_LEVERAGE,
    KillAction,
    cap_target,
    kill_action,
)
from .intents import IntentLedger
from .margins import MarginTier, assess_margin
from .rollover import expiry_status


@dataclass(frozen=True)
class CanaryRuntimeState:
    status: str = "STOPPED"
    started_at: str | None = None
    stopped_at: str | None = None
    last_target: str = "flat"
    maximum_notional_observed: str = "0"
    consecutive_api_failures: int = 0
    manual_stop: bool = False
    daily_loss: str = "0"
    total_loss: str = "0"
    loss_event_ids: tuple[str, ...] = ()


class CanaryStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> CanaryRuntimeState:
        if not self.path.exists():
            return CanaryRuntimeState()
        try:
            return CanaryRuntimeState(**json.loads(self.path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise SafetyError("corrupt V8 canary runtime state") from exc

    def write(self, state: CanaryRuntimeState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(state), handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class V8XPerpCanaryService:
    def __init__(
        self,
        *,
        adapter: V8XPerpDemoAdapter,
        config: CanaryConfig,
        state_store: CanaryStateStore | None = None,
    ) -> None:
        self.adapter = adapter
        self.config = config
        self.state_store = state_store or CanaryStateStore(adapter.runtime_root / "canary_state.json")
        self.state = self.state_store.load()
        self.report: PreflightReport | None = None
        self.tiers: tuple[MarginTier, ...] = ()
        self.leverage = Decimal("0")
        self.stream: Any | None = None

    def start(
        self,
        *,
        report: PreflightReport,
        tiers: tuple[MarginTier, ...],
        authenticated_leverage: Decimal,
        stream: Any,
        clock_drift_seconds: Decimal = Decimal("0"),
        reconciled_at: datetime | None = None,
    ) -> None:
        if not self.config.enabled:
            raise SafetyError("continuous V8 Demo is disabled by configuration")
        if ENVIRONMENT != "okx_demo":
            raise SafetyError("canary environment mismatch")
        self.adapter._assert_lock_held()
        self.adapter._assert_recovered()
        stream.assert_healthy()
        if authenticated_leverage <= 0 or authenticated_leverage > HARD_LEVERAGE:
            raise SafetyError("authenticated isolated leverage exceeds the canary ceiling")
        active = [item for item in IntentLedger(self.adapter.intent_path).load() if item.state != "RECONCILED"]
        if active:
            raise SafetyError("a non-terminal V8 transition blocks canary startup")
        if report.market.spread_bps > self.config.maximum_spread_bps:
            raise SafetyError("canary spread gate failed")
        if report.market.estimated_slippage_bps > self.config.maximum_slippage_bps:
            raise SafetyError("canary slippage gate failed")
        age = Decimal(str((_utc_now() - report.market.timestamp).total_seconds()))
        if age < 0 or age > self.config.maximum_market_age_seconds:
            raise SafetyError("canary market-data freshness gate failed")
        if not tiers:
            raise SafetyError("canary margin tiers are unavailable")
        expiry = expiry_status(report.instrument)
        if expiry.block_new_exposure:
            raise SafetyError("X-Perp expiry blocks new canary exposure")
        if clock_drift_seconds < 0 or clock_drift_seconds > self.config.maximum_clock_drift_seconds:
            raise SafetyError("canary clock-drift gate failed")
        reconciled = reconciled_at or report.checked_at
        reconciliation_age = Decimal(str((_utc_now() - reconciled).total_seconds()))
        if reconciliation_age < 0 or reconciliation_age > self.config.maximum_reconciliation_seconds:
            raise SafetyError("canary reconciliation freshness gate failed")
        stream_state = getattr(stream, "state", None)
        last_event = getattr(stream_state, "last_event_at", None)
        if last_event is not None:
            stream_age = Decimal(str((_utc_now() - last_event).total_seconds()))
            if stream_age < 0 or stream_age > self.config.maximum_stream_age_seconds:
                raise SafetyError("canary private-stream freshness gate failed")
        if self.state.manual_stop:
            raise SafetyError("manual emergency stop is latched")
        if _decimal(self.state.daily_loss) >= self.config.daily_loss_usd:
            raise SafetyError("daily canary loss limit is latched")
        if _decimal(self.state.total_loss) >= self.config.total_loss_usd:
            raise SafetyError("total canary loss limit is latched")
        self.report, self.tiers, self.leverage, self.stream = report, tiers, authenticated_leverage, stream
        self.state = CanaryRuntimeState(
            status="RUNNING",
            started_at=datetime.now(UTC).isoformat(),
            last_target=self.state.last_target,
            maximum_notional_observed=self.state.maximum_notional_observed,
            daily_loss=self.state.daily_loss,
            total_loss=self.state.total_loss,
            loss_event_ids=self.state.loss_event_ids,
        )
        self.state_store.write(self.state)

    def execute_target(self, target: str) -> CappedTarget:
        if self.state.status != "RUNNING" or self.report is None or self.stream is None:
            raise SafetyError("V8 canary service is not running")
        self.stream.assert_healthy()
        self.adapter._assert_lock_held()
        current = self.adapter._position(self.report.instrument)
        if target == "flat":
            if current != 0:
                side = "sell" if current > 0 else "buy"
                self.adapter.place_market(
                    self.report, side=side, contracts=abs(current),
                    reduce_only=True, target="flat",
                )
            capped = cap_target(
                target="flat", equity_usdc=self.report.available_usdc,
                adverse_price=self.report.market.last,
                contract_value=self.report.instrument.ct_val,
                lot_size=self.report.instrument.lot_sz,
                margin_safe_notional=self.config.max_notional_usd,
                existing_notional=abs(current) * self.report.instrument.ct_val * self.report.market.last,
                config=self.config,
            )
            self._record_target(target, Decimal("0"))
            return capped
        if current != 0:
            raise SafetyError("canary exposure changes require a reconciled flat account")
        adverse_price = max(self.report.market.ask, self.report.market.last)
        capped = cap_target(
            target=target,
            equity_usdc=self.report.available_usdc,
            adverse_price=adverse_price,
            contract_value=self.report.instrument.ct_val,
            lot_size=self.report.instrument.lot_sz,
            margin_safe_notional=self.config.max_notional_usd,
            config=self.config,
        )
        side = "buy" if capped.signed_contracts > 0 else "sell"
        contracts = abs(capped.signed_contracts)
        reserve = capped.allowed_notional * Decimal("0.0045")
        assess_margin(
            instrument=self.report.instrument,
            tiers=self.tiers,
            contracts=contracts,
            side="long" if side == "buy" else "short",
            mark_price=self.report.market.last,
            entry_price=adverse_price,
            leverage=self.leverage,
            available_usdc=self.report.available_usdc,
            reserve_usdc=reserve,
            minimum_liquidation_distance_pct=self.config.minimum_liquidation_distance_pct,
        )
        self.adapter.place_market(
            self.report, side=side, contracts=contracts,
            reduce_only=False, target=target,
        )
        actual = abs(self.adapter._position(self.report.instrument)) * self.report.instrument.ct_val * self.report.market.last
        if actual > self.config.max_notional_usd:
            raise SafetyError("post-fill position exceeds the hard canary cap")
        self._record_target(target, actual)
        return capped

    def record_loss(self, *, event_id: str, amount: Decimal) -> None:
        if amount >= 0 or event_id in self.state.loss_event_ids:
            return
        loss = abs(amount)
        daily = _decimal(self.state.daily_loss) + loss
        total = _decimal(self.state.total_loss) + loss
        self.state = CanaryRuntimeState(
            **{
                **asdict(self.state),
                "daily_loss": str(daily),
                "total_loss": str(total),
                "loss_event_ids": (*self.state.loss_event_ids, event_id),
            }
        )
        self.state_store.write(self.state)
        if daily >= self.config.daily_loss_usd or total >= self.config.total_loss_usd:
            raise SafetyError("canary realized-loss limit breached")

    def manual_emergency_stop(self) -> None:
        if self.report and self.state.status == "RUNNING":
            self.adapter.emergency_flatten(self.report)
        self.state = CanaryRuntimeState(
            **{**asdict(self.state), "status": "STOPPED", "manual_stop": True, "stopped_at": _utc_now().isoformat()}
        )
        self.state_store.write(self.state)

    def apply_kill_switch(self, reason: str) -> KillAction:
        action = kill_action(reason)
        if self.report is None:
            self.state = CanaryRuntimeState(
                **{
                    **asdict(self.state),
                    "status": "STOPPED",
                    "manual_stop": True,
                    "stopped_at": _utc_now().isoformat(),
                }
            )
            self.state_store.write(self.state)
            return action
        if action == KillAction.BLOCK_CANCEL_KNOWN:
            self.adapter.cancel_known_pending(self.report)
        elif action == KillAction.CANCEL_FLATTEN_STOP_MANUAL:
            self.adapter.emergency_flatten(self.report)
        self.state = CanaryRuntimeState(
            **{
                **asdict(self.state),
                "status": "STOPPED",
                "manual_stop": action
                in {
                    KillAction.BLOCK_STOP_MANUAL,
                    KillAction.BLOCK_NO_MUTATION_MANUAL,
                    KillAction.CANCEL_FLATTEN_STOP_MANUAL,
                },
                "stopped_at": _utc_now().isoformat(),
            }
        )
        self.state_store.write(self.state)
        return action

    def stop(self) -> None:
        if self.report and self.adapter._position(self.report.instrument) != 0:
            raise SafetyError("refusing to stop the canary while a position remains")
        self.state = CanaryRuntimeState(
            **{**asdict(self.state), "status": "STOPPED", "stopped_at": _utc_now().isoformat()}
        )
        self.state_store.write(self.state)

    def _record_target(self, target: str, notional: Decimal) -> None:
        maximum = max(_decimal(self.state.maximum_notional_observed), notional)
        self.state = CanaryRuntimeState(
            **{
                **asdict(self.state),
                "last_target": target,
                "maximum_notional_observed": str(maximum),
            }
        )
        self.state_store.write(self.state)
