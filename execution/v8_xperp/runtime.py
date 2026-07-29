"""Unattended V8 operational target controller.

The surrounding process owns the account lock and private stream.  One call to
``cycle`` performs fresh reconciliation and may emit at most one target identity.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .adapter import PreflightReport, SafetyError, V8XPerpDemoAdapter, _decimal
from .bootstrap import (
    BootstrapConfig,
    BootstrapDecision,
    BootstrapDecisionLedger,
    calculate_bootstrap,
    operational_phase,
)
from .canary import CanaryConfig, CappedTarget, cap_leverage_target
from .funding import (
    FundingLedger,
    make_expectation,
    reconcile_funding,
    source_hash,
)
from .index_source import OKXIndexPriceSource
from .intents import IntentLedger, TERMINAL
from .operator import OperatorControlStore
from .rollover import expiry_status
from .service import V8XPerpCanaryService
from .schedule import (
    REAL_CYCLE,
    SYNTHETIC_DEMO_CYCLE,
    ScheduleConfig,
    ScheduleEventLedger,
    synthetic_events_between,
    synthetic_preview,
)
from .target_transport import (
    OperationalTarget,
    OperationalTargetLedger,
    TransportState,
    TransportStateStore,
    decide_transport,
    scheduled_target,
    target_from_bootstrap,
)

FEE_RESERVE_RATE = Decimal("0.001")
FUNDING_RESERVE_RATE = Decimal("0.002")
SLIPPAGE_RESERVE_RATE = Decimal("0.0015")
OPERATOR_FLAT_REQUEST = "operator_flat.request"


def eligible_equity(
    available_usdc: Decimal,
    *,
    maximum_notional: Decimal,
    bootstrap_config: BootstrapConfig,
) -> Decimal:
    variable = maximum_notional * (
        FEE_RESERVE_RATE + FUNDING_RESERVE_RATE + SLIPPAGE_RESERVE_RATE
    )
    value = available_usdc - variable - bootstrap_config.operational_reserve_usd
    if value <= 0:
        raise SafetyError("eligible bootstrap equity is nonpositive after reserves")
    return value


def request_operator_flat(runtime_root: Path) -> dict[str, str]:
    """Atomically signal the owning process; never contend for its account lock."""
    path = runtime_root / OPERATOR_FLAT_REQUEST
    payload = {
        "requested_at": datetime.now(UTC).isoformat(),
        "action": "flat",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return payload


class V8OperationalController:
    def __init__(
        self,
        *,
        adapter: V8XPerpDemoAdapter,
        service: V8XPerpCanaryService,
        index_source: OKXIndexPriceSource,
        canary_config: CanaryConfig,
        bootstrap_config: BootstrapConfig,
        schedule_config: ScheduleConfig | None = None,
        runtime_root: Path | None = None,
    ) -> None:
        self.adapter = adapter
        self.service = service
        self.index_source = index_source
        self.canary_config = canary_config
        self.bootstrap_config = bootstrap_config
        self.schedule_config = schedule_config or ScheduleConfig()
        self.schedule_config.validate()
        root = runtime_root or adapter.runtime_root
        self.bootstrap_ledger = BootstrapDecisionLedger(root / "bootstrap_decisions.json")
        self.target_ledger = OperationalTargetLedger(root / "operational_targets.json")
        self.state_store = TransportStateStore(root / "target_transport_state.json")
        self.funding_ledger = FundingLedger(root / "funding.json")
        self.health_path = root / "health.json"
        self.operator_flat_path = root / OPERATOR_FLAT_REQUEST
        self.schedule_ledger = ScheduleEventLedger(root / "schedule_events.json")
        self.transition_report_dir = root / "reports" / "transitions"
        self.operator_control = OperatorControlStore(root)
        self.emergency_flatten_path = root / "emergency_flatten.request"
        self.reconcile_request_path = root / "reconcile.request"

    @staticmethod
    def _previous(state: TransportState) -> datetime | None:
        if state.last_observed_at is None:
            return None
        try:
            value = datetime.fromisoformat(state.last_observed_at)
        except ValueError as exc:
            raise SafetyError("transport last-observed timestamp is invalid") from exc
        if value.tzinfo is None:
            raise SafetyError("transport last-observed timestamp is not UTC-aware")
        return value.astimezone(UTC)

    def _bootstrap_for(
        self,
        *,
        report: PreflightReport,
        server_time: datetime,
        selected_leverage: Decimal,
        persist: bool,
    ) -> tuple[BootstrapDecision, CappedTarget]:
        phase = operational_phase(server_time)
        existing = next(
            (
                item for item in reversed(self.bootstrap_ledger.load())
                if item.instrument_id == report.instrument.inst_id
                and item.last_transition_at == phase.last_transition_at.isoformat()
                and item.state in {"PLANNED", "EXECUTED", "FLAT"}
            ),
            None,
        )
        if existing is None:
            reference = self.index_source.reference_after(
                phase.last_transition_at, retrieved_at=server_time
            )
            current = self.index_source.current(
                verified_server_time=server_time,
                maximum_age_seconds=self.canary_config.maximum_market_age_seconds,
            )
            equity = eligible_equity(
                report.available_usdc,
                maximum_notional=self.canary_config.max_notional_usd,
                bootstrap_config=self.bootstrap_config,
            )
            bound = min(selected_leverage, Decimal("2"))
            decision = calculate_bootstrap(
                environment=report.environment,
                account_hash=self.adapter.account_hash,
                instrument_id=report.instrument.inst_id,
                phase=phase,
                reference=reference,
                current=current,
                eligible_equity=equity,
                margin_safe_leverage=bound,
                liquidation_safe_leverage=bound,
                account_safe_leverage=bound,
                config=self.bootstrap_config,
            )
            capped = cap_leverage_target(
                target=f"bootstrap:{decision.transition_id}",
                direction=decision.direction if decision.enter else "flat",
                leverage=Decimal(decision.calculated_leverage),
                eligible_equity=equity,
                adverse_price=max(report.market.ask, report.market.last),
                contract_value=report.instrument.ct_val,
                lot_size=report.instrument.lot_sz,
                margin_safe_notional=self.canary_config.max_notional_usd,
                config=self.canary_config,
            )
            decision = replace(
                decision,
                final_contracts=str(abs(capped.signed_contracts)),
                final_notional=str(capped.allowed_notional),
                actual_leverage=str(capped.actual_leverage),
                state="PLANNED" if decision.enter else "FLAT",
            )
            if persist:
                self.bootstrap_ledger.create(decision)
            return decision, capped
        capped = cap_leverage_target(
            target=f"bootstrap:{existing.transition_id}",
            direction=existing.direction if existing.enter else "flat",
            leverage=Decimal(existing.calculated_leverage),
            eligible_equity=Decimal(existing.eligible_equity),
            adverse_price=max(report.market.ask, report.market.last),
            contract_value=report.instrument.ct_val,
            lot_size=report.instrument.lot_sz,
            margin_safe_notional=self.canary_config.max_notional_usd,
            config=self.canary_config,
        )
        if (
            str(abs(capped.signed_contracts)) != existing.final_contracts
            or str(capped.actual_leverage) != existing.actual_leverage
        ):
            # A frozen decision must never be resized from a new market price.
            capped = CappedTarget(
                requested_target=f"bootstrap:{existing.transition_id}",
                requested_notional=(
                    Decimal(existing.eligible_equity)
                    * Decimal(existing.calculated_leverage)
                    * (Decimal("1") if existing.direction == "long" else Decimal("-1"))
                ),
                allowed_notional=Decimal(existing.final_notional),
                signed_contracts=(
                    Decimal(existing.final_contracts)
                    if existing.direction == "long"
                    else -Decimal(existing.final_contracts)
                ),
                cap_reduced=True,
                strategy_leverage=Decimal(existing.calculated_leverage),
                actual_leverage=Decimal(existing.actual_leverage),
            )
        return existing, capped

    def _scheduled_cap(
        self,
        target: OperationalTarget,
        *,
        report: PreflightReport,
    ) -> tuple[OperationalTarget, CappedTarget, Decimal]:
        equity = eligible_equity(
            report.available_usdc,
            maximum_notional=self.canary_config.max_notional_usd,
            bootstrap_config=self.bootstrap_config,
        )
        capped = cap_leverage_target(
            target=f"scheduled:{target.transition_id}",
            direction=target.direction,
            leverage=Decimal("2"),
            eligible_equity=equity,
            adverse_price=max(report.market.ask, report.market.last),
            contract_value=report.instrument.ct_val,
            lot_size=report.instrument.lot_sz,
            margin_safe_notional=self.canary_config.max_notional_usd,
            config=self.canary_config,
        )
        return replace(
            target,
            final_contracts=str(abs(capped.signed_contracts)),
            final_notional=str(capped.allowed_notional),
            actual_leverage=str(capped.actual_leverage),
        ), capped, equity

    def cycle(
        self,
        *,
        report: PreflightReport,
        server_time: datetime,
        clock_drift_seconds: Decimal,
        execute: bool,
    ) -> dict[str, Any]:
        selected_leverage = self.adapter.selected_leverage(report)
        tiers = self.adapter.margin_tiers(report)
        self.service.refresh(
            report=report,
            tiers=tiers,
            authenticated_leverage=selected_leverage,
            reconciled_at=report.checked_at,
            clock_drift_seconds=clock_drift_seconds,
        )
        control = self.operator_control.load()
        if control.manual_stop:
            raise SafetyError("Telegram manual stop is latched")
        if execute and self.emergency_flatten_path.exists():
            self.service.manual_emergency_stop()
            self.emergency_flatten_path.unlink()
            raise SafetyError("Telegram emergency flatten completed; manual recovery required")
        if self.reconcile_request_path.exists():
            # The fresh report, stream gate, service refresh and intent checks above
            # are the authoritative reconciliation requested by Telegram.
            if execute:
                self.reconcile_request_path.unlink()
        state = self.state_store.load()
        previous = self._previous(state)
        position = self.adapter._position(report.instrument)
        active = self.target_ledger.active()
        due = scheduled_target(
            at=server_time,
            previous_observed_at=previous,
            schedule_config=self.schedule_config,
        )
        bootstrap_decision: BootstrapDecision | None = None
        bootstrap_target: OperationalTarget | None = None
        bootstrap_cap: CappedTarget | None = None
        if (
            self.schedule_config.mode == REAL_CYCLE
            and due is None
            and position == 0
            and active is None
        ):
            bootstrap_decision, bootstrap_cap = self._bootstrap_for(
                report=report,
                server_time=server_time,
                selected_leverage=selected_leverage,
                persist=execute,
            )
            bootstrap_target = target_from_bootstrap(bootstrap_decision)
        decision = decide_transport(
            now=server_time,
            previous_observed_at=previous,
            current_position=position,
            active_target=active,
            bootstrap_target=bootstrap_target,
            explicit_flat_requested=(
                state.explicit_flat_requested or self.operator_flat_path.exists()
            ),
            schedule_config=self.schedule_config,
        )
        paused_deferred = control.paused and decision.action in {"EXECUTE", "RESTORE"}
        if paused_deferred:
            decision = replace(
                decision,
                action="NOOP",
                target=None,
                reason="operator pause blocks new exposure",
            )
        capped: CappedTarget | None = bootstrap_cap
        equity = (
            Decimal(bootstrap_decision.eligible_equity)
            if bootstrap_decision is not None
            else eligible_equity(
                report.available_usdc,
                maximum_notional=self.canary_config.max_notional_usd,
                bootstrap_config=self.bootstrap_config,
            )
        )
        planned = decision.target
        if (
            planned is not None
            and decision.action == "EXECUTE"
            and (
                planned.kind == "scheduled_540_900"
                or self.schedule_config.mode == SYNTHETIC_DEMO_CYCLE
            )
        ):
            planned, capped, equity = self._scheduled_cap(planned, report=report)
            decision = replace(decision, target=planned)
        elif planned is not None and planned.kind == "operational_bootstrap" and capped is None:
            bootstrap_decision, capped = self._bootstrap_for(
                report=report,
                server_time=server_time,
                selected_leverage=selected_leverage,
                persist=False,
            )
        elif planned is not None and planned.kind == "operator_flat":
            capped = cap_leverage_target(
                target=planned.transition_id,
                direction="flat",
                leverage=Decimal("0"),
                eligible_equity=equity,
                adverse_price=report.market.last,
                contract_value=report.instrument.ct_val,
                lot_size=report.instrument.lot_sz,
                margin_safe_notional=self.canary_config.max_notional_usd,
                existing_notional=abs(position) * report.instrument.ct_val * report.market.last,
                config=self.canary_config,
            )
        elif planned is not None and decision.action == "RESTORE":
            signed = planned.signed_contracts
            capped = CappedTarget(
                requested_target=planned.transition_id,
                requested_notional=Decimal(planned.final_notional),
                allowed_notional=Decimal(planned.final_notional),
                signed_contracts=signed,
                cap_reduced=True,
                strategy_leverage=Decimal(planned.strategy_leverage),
                actual_leverage=Decimal(planned.actual_leverage),
            )
        schedule_events = (
            synthetic_events_between(
                self.schedule_config,
                previous_observed_at=previous,
                now=server_time,
            )
            if self.schedule_config.mode == SYNTHETIC_DEMO_CYCLE
            else []
        )
        phase = (
            asdict(
                synthetic_preview(
                    self.schedule_config,
                    now=server_time,
                    previous_observed_at=previous,
                )
            )
            if self.schedule_config.mode == SYNTHETIC_DEMO_CYCLE
            else asdict(operational_phase(server_time))
        )
        result: dict[str, Any] = {
            "server_time": server_time.isoformat(),
            "schedule_mode": self.schedule_config.mode,
            "phase": phase,
            "schedule_events": [asdict(item) for item in schedule_events],
            "position_before": str(position),
            "decision": asdict(decision),
            "bootstrap": asdict(bootstrap_decision) if bootstrap_decision else None,
            "capped": asdict(capped) if capped else None,
            "execute": execute,
            "operator_control": asdict(control),
        }
        if not execute:
            return result
        if paused_deferred:
            result["monitoring"] = self._monitoring(report, active, equity)
            self._write_health(result)
            return result
        for event in schedule_events:
            self.schedule_ledger.append(event)
        if decision.action in {"EXECUTE", "RESTORE"}:
            if planned is None or capped is None:
                raise SafetyError("executable transport decision lacks a capped target")
            if decision.action == "RESTORE":
                self.target_ledger.update(planned.transition_id, "PLANNED")
            else:
                self.target_ledger.create(planned)
            self.service.execute_capped_target(
                capped,
                transition_id=planned.transition_id,
                eligible_equity=equity,
            )
            active = self.target_ledger.update(planned.transition_id, "EXECUTED")
            if bootstrap_decision is not None and bootstrap_decision.enter:
                self.bootstrap_ledger.update_state(
                    bootstrap_decision.transition_id, "EXECUTED"
                )
        elif decision.action == "ADOPT" and planned is not None:
            active = self.target_ledger.update(planned.transition_id, "ADOPTED")
        self.state_store.write(TransportState(
            last_observed_at=server_time.astimezone(UTC).isoformat(),
            active_transition_id=active.transition_id if active else None,
            explicit_flat_requested=False if decision.action == "EXECUTE" else state.explicit_flat_requested,
        ))
        if self.operator_flat_path.exists() and self.adapter._position(report.instrument) == 0:
            self.operator_flat_path.unlink()
        result["position_after"] = str(self.adapter._position(report.instrument))
        result["funding"] = self.persist_next_funding(
            report, active, now_ms=int(server_time.timestamp() * 1000)
        )
        result["monitoring"] = self._monitoring(report, active, equity)
        for event in schedule_events:
            self._write_transition_report(result, event.transition_id)
        self._write_health(result)
        return result

    def persist_next_funding(
        self,
        report: PreflightReport,
        active: OperationalTarget | None,
        *,
        now_ms: int,
    ) -> dict[str, Any]:
        records = self.funding_ledger.load()
        if records:
            history = self.adapter._ok(
                self.adapter.public.funding_rate_history(
                    report.instrument.inst_id, limit="100"
                ),
                "operational funding history",
            )
            bills = self.adapter._ok(
                self.adapter.account.get_account_bills(
                    instType="FUTURES", mgnMode="isolated", limit="100"
                ),
                "operational funding bills",
            )
            for record in records:
                if record.state != "RECONCILED":
                    reconciled = reconcile_funding(
                        ledger=self.funding_ledger,
                        record=record,
                        official_history=history,
                        bills=bills,
                        now_ms=now_ms,
                    )
                    if reconciled.state in {
                        "SIGN_MISMATCH", "AMOUNT_MISMATCH",
                        "TIMESTAMP_MISMATCH", "CONFLICT", "MISSING",
                    }:
                        raise SafetyError(
                            f"funding reconciliation failed closed: {reconciled.state}"
                        )
        position_rows = self.adapter._ok(
            self.adapter.account.get_positions(
                instType="FUTURES", instId=report.instrument.inst_id
            ),
            "operational funding position",
        )
        positions = [row for row in position_rows if _decimal(row.get("pos")) != 0]
        if not positions or active is None:
            observed = any(
                item.state == "RECONCILED" for item in self.funding_ledger.load()
            )
            return {
                "status": "REAL_PARITY_OBSERVED" if observed else "NOT_APPLICABLE"
            }
        if len(positions) != 1:
            raise SafetyError("funding expectation position is ambiguous")
        rates = self.adapter._ok(
            self.adapter.public.get_funding_rate(report.instrument.inst_id),
            "operational funding rate",
        )
        if len(rates) != 1:
            raise SafetyError("operational funding rate is ambiguous")
        position, rate = positions[0], rates[0]
        settlement = int(rate["fundingTime"])
        signed_rate = _decimal(rate["fundingRate"])
        contracts = abs(_decimal(position["pos"]))
        notional = abs(_decimal(position["notionalUsd"]))
        expectation = make_expectation(
            environment=report.environment,
            account_hash=self.adapter.account_hash,
            instrument_id=report.instrument.inst_id,
            settlement_ms=settlement,
            side="long" if _decimal(position["pos"]) > 0 else "short",
            contracts=contracts,
            position_notional=notional,
            signed_rate=signed_rate,
            metadata_hash=report.instrument.metadata_hash,
            rate_source_hash=source_hash(rate),
            position_source_hash=source_hash(position),
            mark_source_hash=source_hash({"markPx": position.get("markPx")}),
        )
        existing = next(
            (
                item for item in self.funding_ledger.load()
                if item.identity == expectation.identity
            ),
            None,
        )
        if existing is None:
            self.funding_ledger.create(expectation)
        else:
            expectation = existing
        observed = any(
            item.state == "RECONCILED" for item in self.funding_ledger.load()
        )
        return {
            "status": (
                "REAL_PARITY_OBSERVED" if observed else "PENDING_REAL_PARITY"
            ),
            "settlement_ms": settlement,
            "expected_amount": expectation.expected_amount,
            "transition_id": active.transition_id,
        }

    def request_operator_flat(self) -> TransportState:
        request_operator_flat(self.operator_flat_path.parent)
        return self.state_store.load()

    def _monitoring(
        self,
        report: PreflightReport,
        active: OperationalTarget | None,
        eligible: Decimal,
    ) -> dict[str, Any]:
        position = self.adapter._position(report.instrument)
        notional = abs(position) * report.instrument.ct_val * report.market.last
        liquidation_distance: Decimal | None = None
        position_rows = self.adapter._ok(
            self.adapter.account.get_positions(
                instType="FUTURES", instId=report.instrument.inst_id
            ),
            "operational position-risk monitoring",
        )
        owned = [
            row for row in position_rows
            if row.get("instId", report.instrument.inst_id) == report.instrument.inst_id
            and _decimal(row.get("pos")) != 0
        ]
        if len(owned) > 1:
            raise SafetyError("multiple V8 position-risk rows are ambiguous")
        if owned:
            mark = _decimal(owned[0].get("markPx"))
            liquidation = _decimal(owned[0].get("liqPx"))
            if mark > 0 and liquidation > 0:
                liquidation_distance = abs(mark - liquidation) / mark * Decimal("100")
        orders = self.adapter._ok(
            self.adapter.trade.get_order_list(instType="FUTURES", state="live"),
            "operational open-order monitoring",
        )
        if orders:
            raise SafetyError("unresolved FUTURES open order blocks operational health")
        intents = IntentLedger(self.adapter.intent_path).load()
        stream_state = getattr(self.service.stream, "state", None)
        canary_state = self.service.state
        return {
            "environment": report.environment,
            "instrument": report.instrument.inst_id,
            "active_target": asdict(active) if active else None,
            "position_contracts": str(position),
            "position_notional_usd": str(notional),
            "actual_leverage": str(notional / eligible),
            "liquidation_distance_pct": (
                str(liquidation_distance)
                if liquidation_distance is not None
                else None
            ),
            "minimum_liquidation_distance_pct": str(
                self.canary_config.minimum_liquidation_distance_pct
            ),
            "available_usdc": str(report.available_usdc),
            "market_timestamp": report.market.timestamp.isoformat(),
            "rest_checked_at": report.checked_at.isoformat(),
            "websocket": asdict(stream_state) if stream_state else None,
            "open_futures_orders": 0,
            "non_terminal_intents": len(
                [item for item in intents if item.state not in TERMINAL]
            ),
            "margin_tier_count": len(self.service.tiers),
            "authenticated_leverage": str(self.service.leverage),
            "expiry": asdict(expiry_status(report.instrument)),
            "api_failures": canary_state.consecutive_api_failures,
            "daily_loss_usd": canary_state.daily_loss,
            "total_loss_usd": canary_state.total_loss,
            "manual_stop": canary_state.manual_stop,
        }

    def _write_health(self, result: dict[str, Any]) -> None:
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.health_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(result, handle, sort_keys=True, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.health_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _write_transition_report(
        self, result: dict[str, Any], transition_id: str
    ) -> None:
        self.transition_report_dir.mkdir(parents=True, exist_ok=True)
        path = self.transition_report_dir / f"{transition_id}.json"
        if path.exists():
            return
        fd, temporary = tempfile.mkstemp(dir=self.transition_report_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(result, handle, sort_keys=True, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
