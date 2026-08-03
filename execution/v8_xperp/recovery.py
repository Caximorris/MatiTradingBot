"""Durable query-before-retry execution and startup recovery for V8 X-Perp."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from .adapter import CLIENT_PREFIX, Instrument, SafetyError, _decimal
from .intents import TERMINAL, Intent, IntentLedger


@dataclass(frozen=True)
class ExchangeSnapshot:
    order: dict[str, Any] | None
    open_orders: tuple[dict[str, Any], ...]
    history: tuple[dict[str, Any], ...]
    fills: tuple[dict[str, Any], ...]
    position: Decimal


@dataclass(frozen=True)
class RecoveryResult:
    intent: Intent
    order: dict[str, Any] | None
    fill_count: int
    filled_contracts: Decimal
    position: Decimal
    retried: bool = False


class IntentExecution:
    """The only adapter-owned path to OKX order and cancellation endpoints."""

    def __init__(self, *, adapter: Any, ledger: IntentLedger) -> None:
        self.adapter = adapter
        self.ledger = ledger

    def _record(self, intent: Intent, state: str, **changes: object) -> Intent:
        updated = self.ledger.transition(intent.client_order_id, state, **changes)
        self.adapter._append(
            "intent_transition",
            {
                "client_id_hash": self.adapter.client_id_hash(intent.client_order_id),
                "transition_id": intent.transition_id,
                "state": state,
                **changes,
            },
        )
        return updated

    def snapshot(self, intent: Intent) -> ExchangeSnapshot:
        trade, account = self.adapter.trade, self.adapter.account
        order_payload = trade.get_order(
            intent.instrument_id,
            clOrdId=intent.client_order_id,
        )
        if (
            order_payload.get("code") == "51603"
            and order_payload.get("data") == []
        ):
            order_rows: list[dict[str, Any]] = []
        else:
            order_rows = self.adapter._ok(
                order_payload,
                "order query by client ID",
            )
        if len(order_rows) > 1:
            raise SafetyError("multiple exchange orders share one V8 client-order ID")
        open_rows = self.adapter._ok(
            trade.get_order_list(instType="FUTURES", state="live"),
            "open-order reconciliation",
        )
        history_rows = self.adapter._ok(
            trade.get_orders_history(instType="FUTURES", instId=intent.instrument_id),
            "order-history reconciliation",
        )
        fill_rows = self.adapter._ok(
            trade.get_fills(instType="FUTURES", instId=intent.instrument_id),
            "fill reconciliation",
        )
        positions = self.adapter._ok(
            account.get_positions(instType="FUTURES", instId=intent.instrument_id),
            "position reconciliation",
        )
        if len(positions) > 1:
            raise SafetyError("multiple unexpected FUTURES positions")
        own_open = tuple(row for row in open_rows if row.get("clOrdId") == intent.client_order_id)
        own_history = tuple(row for row in history_rows if row.get("clOrdId") == intent.client_order_id)
        own_fills = tuple(row for row in fill_rows if row.get("clOrdId") == intent.client_order_id)
        candidates = tuple(order_rows) + own_open + own_history
        order = candidates[0] if candidates else None
        if any(
            str(row.get("ordId", "")) != str(order.get("ordId", ""))
            for row in candidates[1:]
        ):
            raise SafetyError("conflicting exchange state for V8 client-order ID")
        position = _decimal(positions[0].get("pos")) if positions else Decimal("0")
        return ExchangeSnapshot(order, own_open, own_history, own_fills, position)

    @staticmethod
    def _filled(snapshot: ExchangeSnapshot) -> Decimal:
        order_filled = _decimal(snapshot.order.get("accFillSz")) if snapshot.order else Decimal("0")
        fill_total = sum((_decimal(row.get("fillSz")) for row in snapshot.fills), Decimal("0"))
        return max(order_filled, fill_total)

    def reconcile(
        self,
        intent: Intent,
        *,
        before_position: Decimal,
        permit_absent: bool,
        defer_absent: bool = False,
    ) -> RecoveryResult | None:
        snapshot = self.snapshot(intent)
        filled = self._filled(snapshot)
        requested = _decimal(intent.contracts)
        state = str(snapshot.order.get("state", "")) if snapshot.order else ""
        order_id = str(snapshot.order.get("ordId")) if snapshot.order and snapshot.order.get("ordId") else None
        changes = {
            "exchange_order_id": order_id,
            "filled_contracts": str(filled),
            "last_result": state or ("fill_seen" if filled else "not_found"),
        }
        if filled > 0 and (filled < requested or state in {"partially_filled", "live"}):
            current = self._record(intent, "PARTIALLY_FILLED", **changes)
            return RecoveryResult(current, snapshot.order, len(snapshot.fills), filled, snapshot.position)
        if filled >= requested or state == "filled":
            current = self._record(intent, "FILLED", **changes)
            direction = Decimal("1") if intent.side == "buy" else Decimal("-1")
            expected_position = (
                Decimal("0")
                if intent.reduce_only and intent.target == "flat"
                else before_position + direction * filled
            )
            if snapshot.position != expected_position:
                return RecoveryResult(
                    current,
                    snapshot.order,
                    len(snapshot.fills),
                    filled,
                    snapshot.position,
                )
            current = self._record(current, "RECONCILED", **changes)
            return RecoveryResult(current, snapshot.order, len(snapshot.fills), filled, snapshot.position)
        if state in {"canceled", "mmp_canceled"}:
            current = self._record(intent, "CANCELED", **changes)
            current = self._record(current, "RECONCILED", **changes)
            return RecoveryResult(current, snapshot.order, len(snapshot.fills), filled, snapshot.position)
        if state == "live" or snapshot.open_orders:
            current = self._record(intent, "OPEN", **changes)
            return RecoveryResult(current, snapshot.order, len(snapshot.fills), filled, snapshot.position)
        if not snapshot.order and not snapshot.fills and snapshot.position == before_position:
            if permit_absent:
                return None
            if defer_absent:
                return None
            self._record(intent, "UNKNOWN", **changes)
            raise SafetyError("unresolved ambiguous submission; exchange absence is not retry-authorized")
        self._record(intent, "UNKNOWN", **changes)
        raise SafetyError("journal and exchange state disagree; automatic modification blocked")

    @staticmethod
    def _ack(payload: dict[str, Any]) -> tuple[bool, str | None]:
        if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
            return False, None
        rows = payload["data"]
        if len(rows) != 1 or str(rows[0].get("sCode")) != "0":
            return False, str(rows[0].get("ordId")) if rows else None
        return True, str(rows[0].get("ordId")) if rows[0].get("ordId") else None

    def submit(
        self,
        intent: Intent,
        *,
        before_position: Decimal,
        submit_call: Callable[[], dict[str, Any]],
        allow_one_retry: bool = True,
    ) -> RecoveryResult:
        current = self._record(intent, "SUBMITTING", last_result="submission_started")
        ambiguous = False
        try:
            payload = submit_call()
            acknowledged, order_id = self._ack(payload)
            if acknowledged:
                current = self._record(
                    current,
                    "ACKNOWLEDGED",
                    exchange_order_id=order_id,
                    last_result="accepted",
                )
            else:
                ambiguous = True
                current = self._record(current, "UNKNOWN", last_result="malformed_or_ambiguous_ack")
        except Exception as exc:
            ambiguous = True
            current = self._record(
                current,
                "UNKNOWN",
                last_result=f"{type(exc).__name__}: submission acknowledgement lost",
            )
        result = self._poll_reconcile(
            current,
            before_position=before_position,
            permit_absent=ambiguous and allow_one_retry,
        )
        if result is not None:
            return result
        current = self._record(current, "SUBMITTING", last_result="proven_absent_controlled_retry")
        try:
            payload = submit_call()
        except Exception as exc:
            self._record(current, "UNKNOWN", last_result=f"{type(exc).__name__}: retry ambiguous")
            raise SafetyError("controlled retry acknowledgement is ambiguous; no further retry") from exc
        acknowledged, order_id = self._ack(payload)
        if not acknowledged:
            self._record(current, "UNKNOWN", last_result="controlled retry malformed")
            raise SafetyError("controlled retry acknowledgement is ambiguous; no further retry")
        current = self._record(
            current,
            "ACKNOWLEDGED",
            exchange_order_id=order_id,
            last_result="retry_accepted",
        )
        result = self._poll_reconcile(current, before_position=before_position, permit_absent=False)
        if result is None:
            raise SafetyError("controlled retry could not be reconciled")
        return RecoveryResult(
            result.intent,
            result.order,
            result.fill_count,
            result.filled_contracts,
            result.position,
            True,
        )

    def submit_order(
        self,
        intent: Intent,
        *,
        before_position: Decimal,
        after_response: Callable[[dict[str, Any]], None] | None = None,
    ) -> RecoveryResult:
        def call() -> dict[str, Any]:
            kwargs = {
                "clOrdId": intent.client_order_id,
                "reduceOnly": "true" if intent.reduce_only else "false",
            }
            if intent.price is not None:
                kwargs["px"] = intent.price
            response = self.adapter.trade.place_order(
                intent.instrument_id,
                "isolated",
                intent.side,
                intent.order_type,
                intent.contracts,
                **kwargs,
            )
            if after_response is not None:
                after_response(response)
            return response

        return self.submit(
            intent,
            before_position=before_position,
            submit_call=call,
        )

    def _poll_reconcile(
        self,
        intent: Intent,
        *,
        before_position: Decimal,
        permit_absent: bool,
        timeout: float = 12.0,
    ) -> RecoveryResult | None:
        deadline = time.monotonic() + timeout
        absence_started: float | None = None
        absence_confirmations = 0
        while True:
            result = self.reconcile(
                intent,
                before_position=before_position,
                permit_absent=permit_absent,
                defer_absent=not permit_absent,
            )
            if result is None and permit_absent:
                now = time.monotonic()
                absence_started = absence_started or now
                absence_confirmations += 1
                if absence_confirmations >= 5 and now - absence_started >= 2:
                    return None
                if now >= deadline:
                    self._record(intent, "UNKNOWN", last_result="absence_confirmation_timeout")
                    raise SafetyError("exchange absence could not be confirmed safely")
                time.sleep(0.5)
                continue
            if result is not None and result.intent.state in {"RECONCILED", "PARTIALLY_FILLED"}:
                return result
            if result is not None and result.intent.state == "OPEN" and intent.order_type == "limit":
                return result
            if time.monotonic() >= deadline:
                self._record(intent, "UNKNOWN", last_result="reconciliation_timeout")
                raise SafetyError("order state did not reconcile before timeout")
            time.sleep(0.25)

    def cancel(
        self,
        cancellation: Intent,
        *,
        original_client_id: str,
        cancel_call: Callable[[], dict[str, Any]],
    ) -> RecoveryResult:
        current = self._record(cancellation, "SUBMITTING", last_result="cancellation_started")
        try:
            payload = cancel_call()
            acknowledged, order_id = self._ack(payload)
            current = self._record(
                current,
                "CANCEL_PENDING" if acknowledged else "UNKNOWN",
                exchange_order_id=order_id,
                last_result="cancel_accepted" if acknowledged else "cancel_ack_ambiguous",
            )
        except Exception as exc:
            current = self._record(
                current,
                "UNKNOWN",
                last_result=f"{type(exc).__name__}: cancellation acknowledgement lost",
            )
        original = next(
            (row for row in self.ledger.load() if row.client_order_id == original_client_id),
            None,
        )
        if original is None:
            raise SafetyError("cancellation references an unknown local V8 order")
        deadline = time.monotonic() + 12
        while True:
            snapshot = self.snapshot(original)
            filled = self._filled(snapshot)
            state = str(snapshot.order.get("state", "")) if snapshot.order else ""
            if state in {"canceled", "mmp_canceled", "filled"}:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        if state not in {"canceled", "mmp_canceled", "filled"}:
            self._record(current, "UNKNOWN", last_result="cancel_result_unresolved")
            raise SafetyError("cancellation result remains ambiguous")
        terminal_state = "FILLED" if state == "filled" else "CANCELED"
        original = self._record(
            original,
            terminal_state,
            filled_contracts=str(filled),
            last_result=state,
        )
        self._record(
            original,
            "RECONCILED",
            filled_contracts=str(filled),
            last_result=state,
        )
        current = self._record(
            current,
            terminal_state,
            filled_contracts=str(filled),
            last_result=state,
        )
        current = self._record(
            current,
            "RECONCILED",
            filled_contracts=str(filled),
            last_result=state,
        )
        return RecoveryResult(current, snapshot.order, len(snapshot.fills), filled, snapshot.position)

    def cancel_order(
        self,
        cancellation: Intent,
        *,
        original_client_id: str,
    ) -> RecoveryResult:
        return self.cancel(
            cancellation,
            original_client_id=original_client_id,
            cancel_call=lambda: self.adapter.trade.cancel_order(
                cancellation.instrument_id,
                clOrdId=original_client_id,
            ),
        )


class StartupRecovery:
    def __init__(self, *, adapter: Any, ledger: IntentLedger) -> None:
        self.adapter = adapter
        self.ledger = ledger
        self.execution = IntentExecution(adapter=adapter, ledger=ledger)

    def run(self, instrument: Instrument) -> dict[str, Any]:
        intents = self.ledger.load()
        # RECONCILED is the only startup-complete state.  FILLED/CANCELED are
        # exchange observations that still require local/exchange agreement.
        active = [item for item in intents if item.state != "RECONCILED"]
        if any(item.metadata_hash and item.metadata_hash != instrument.metadata_hash for item in active):
            raise SafetyError("instrument metadata changed after intent creation")
        results: list[RecoveryResult] = []
        for intent in active:
            result = self.execution.reconcile(
                intent,
                before_position=Decimal("0"),
                permit_absent=False,
            )
            if result is not None:
                results.append(result)
        intents = self.ledger.load()
        open_rows = self.adapter._ok(
            self.adapter.trade.get_order_list(instType="FUTURES", state="live"),
            "startup open-order reconciliation",
        )
        unknown_orders = [
            row for row in open_rows
            if not str(row.get("clOrdId", "")).startswith(CLIENT_PREFIX)
            or not any(item.client_order_id == row.get("clOrdId") for item in intents)
        ]
        if unknown_orders:
            raise SafetyError("unknown exchange order; startup recovery blocked")
        fills = self.adapter._ok(
            self.adapter.trade.get_fills(instType="FUTURES", instId=instrument.inst_id),
            "startup fill reconciliation",
        )
        history = self.adapter._ok(
            self.adapter.trade.get_orders_history(
                instType="FUTURES", instId=instrument.inst_id
            ),
            "startup order-history reconciliation",
        )
        positions = self.adapter._ok(
            self.adapter.account.get_positions(instType="FUTURES"),
            "startup FUTURES position reconciliation",
        )
        nonzero = [row for row in positions if _decimal(row.get("pos")) != 0]
        if len(nonzero) > 1:
            raise SafetyError("multiple unexpected FUTURES positions")
        if nonzero and str(nonzero[0].get("instId")) != instrument.inst_id:
            raise SafetyError("unknown exchange position; startup recovery blocked")
        position = _decimal(nonzero[0].get("pos")) if nonzero else Decimal("0")
        position_intents = sorted(
            (item for item in intents if item.order_type != "cancel"),
            key=lambda item: (item.created_at, item.client_order_id),
        )
        if position != 0 and not position_intents:
            raise SafetyError("exchange position ownership is not proven by V8 fills or terminal order history")
        if position != 0 and position_intents[-1].target == "flat":
            raise SafetyError("journal says flat but exchange has a known V8 position")
        if position != 0:
            latest = position_intents[-1]
            if latest.metadata_hash != instrument.metadata_hash:
                raise SafetyError("current V8 position metadata differs from its opening intent")
            signed_local = (
                _decimal(latest.filled_contracts)
                if latest.side == "buy"
                else -_decimal(latest.filled_contracts)
            )
            if signed_local != position:
                raise SafetyError("V8 intent lineage does not reconcile to the current position")
            own_fills = [
                row for row in fills
                if row.get("clOrdId") == latest.client_order_id
            ]
            terminal_history = [
                row for row in history
                if row.get("clOrdId") == latest.client_order_id
                and row.get("state") == "filled"
                and _decimal(row.get("accFillSz")) == abs(position)
            ]
            if not own_fills and not terminal_history:
                raise SafetyError(
                    "exchange position ownership is not proven by V8 fills or terminal order history"
                )
            try:
                opened_ms = int(datetime.fromisoformat(latest.created_at).timestamp() * 1000)
            except Exception as exc:
                raise SafetyError("V8 position intent timestamp is invalid") from exc
            recent_unknown = [
                row for row in fills
                if int(row.get("fillTime") or row.get("ts") or opened_ms) >= opened_ms
                and row.get("clOrdId") != latest.client_order_id
            ]
            if recent_unknown:
                raise SafetyError("unknown fill exists in the current V8 position lineage window")
        else:
            own_fills = []
            terminal_history = []
        report = {
            "active_intents": len(active),
            "recovered": len(results),
            "position": str(position),
            "open_v8_orders": len(open_rows),
            "recent_v8_fills": len(own_fills),
            "terminal_history_proofs": len(terminal_history),
            "status": "reconciled",
        }
        self.adapter._append("startup_recovery_pass", report)
        return report


def sanitized_status(path: Path, ledger: IntentLedger) -> dict[str, Any]:
    intents = ledger.load()
    return {
        "journal": str(path),
        "integrity": "pass",
        "intent_count": len(intents),
        "non_terminal": [
            {
                "client_id_suffix": item.client_order_id[-8:],
                "transition_id": item.transition_id,
                "action": item.action,
                "state": item.state,
                "filled_contracts": item.filled_contracts,
                "updated_at": item.updated_at,
            }
            for item in intents
            if item.state not in TERMINAL
        ],
    }


def archive_reconciled(ledger: IntentLedger, destination: Path) -> int:
    rows = ledger.load()
    archived = [item for item in rows if item.state == "RECONCILED"]
    retained = [item for item in rows if item.state != "RECONCILED"]
    if archived:
        if destination.exists():
            raise SafetyError("refusing to overwrite an existing V8 intent archive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps([asdict(item) for item in archived], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        ledger._write(retained)
    return len(archived)
