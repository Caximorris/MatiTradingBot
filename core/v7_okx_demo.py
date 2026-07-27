"""Dedicated, demo-only execution adapter around the frozen V7 certified core.

No simulated fill is ever written here: all order, fill, fee, and balance fields
come from :class:`OKXDemoClient`.  The pure certified module remains network-free.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from core.demo_account_lease import DemoAccountLease, DemoLeaseError
from core.okx_demo_client import OKXDemoClient
from core.v7_certified_paper import CertifiedPaperAdapter, CertifiedPaperConfig, PaperSafetyError


class V7OKXDemoRunner:
    """One-intent-at-a-time adapter with durable actual-fill reconciliation."""

    def __init__(self, config: CertifiedPaperConfig, client: OKXDemoClient, lease: DemoAccountLease,
                 account_fingerprint: str) -> None:
        config.validate()
        if not isinstance(client, OKXDemoClient) or not client.is_paper:
            raise PaperSafetyError("V7 runner accepts only the dedicated OKX Demo client")
        if not account_fingerprint:
            raise PaperSafetyError("non-secret OKX Demo account fingerprint is required")
        self.config, self.client, self.lease, self.account_fingerprint = config, client, lease, account_fingerprint
        self.core = CertifiedPaperAdapter(config)

    def _require_owner(self) -> None:
        current = self.lease.current()
        if current is None or current.get("owner_instance_id") != self.config.instance_id:
            self.core.fail_closed("paper_client_unavailable")
            raise DemoLeaseError("V7 runner does not own the OKX Demo account lease")

    def adopt_account(self, *, target_btc: Decimal, now: datetime) -> dict[str, Any]:
        """Persist the inherited account baseline; never place an adoption order."""
        self._require_owner()
        balances = self.client.get_balance()
        if not balances or set(balances) - {"USDT", "BTC"}:
            self.core.fail_closed("wallet_reconciliation_mismatch", now)
            raise PaperSafetyError("unsupported or unavailable OKX Demo balances")
        if self.client.get_open_orders("BTC-USDT") or self.client.get_positions():
            self.core.fail_closed("wallet_reconciliation_mismatch", now)
            raise PaperSafetyError("open order or unsupported position prevents V7 takeover")
        state = self.core.load_state()
        baseline = {"cash": str(balances.get("USDT", Decimal("0"))), "btc": str(balances.get("BTC", Decimal("0"))),
                    "target_btc": str(target_btc), "adopted_at": now.astimezone(timezone.utc).isoformat()}
        if state.get("activation_baseline") and state["activation_baseline"] != baseline:
            raise PaperSafetyError("activation baseline is immutable")
        state.update(cash=baseline["cash"], btc=baseline["btc"], activation_baseline=baseline)
        self.core.append(state, {"event": "activation_baseline", **baseline})
        self.core.save_state(state)
        return {"status": "adopted" if Decimal(baseline["btc"]) == target_btc else "transition_required", **baseline}

    def submit_transition(self, *, intent_id: str, target_btc: Decimal, decision_at: datetime,
                          execution_at: datetime) -> dict[str, Any]:
        """Submit exactly one actual market order after a completed decision candle."""
        self._require_owner()
        if decision_at.tzinfo is None or execution_at.tzinfo is None or execution_at <= decision_at:
            raise PaperSafetyError("transition must execute strictly after its decision")
        if decision_at.astimezone(timezone.utc).hour % 4:
            raise PaperSafetyError("V7 decisions require UTC four-hour boundaries")
        state = self.core.load_state()
        if state.get("locked") or state.get("pending"):
            raise PaperSafetyError("V7 is locked or has an unresolved pending intent")
        if intent_id in state["seen_intents"]:
            return {"status": "duplicate_intent", "intent_id": intent_id}
        current_btc = Decimal(state["btc"])
        delta = target_btc - current_btc
        if delta == 0:
            return {"status": "already_at_target", "intent_id": intent_id}
        state["seen_intents"].append(intent_id)
        state["pending"] = {"intent_id": intent_id, "target_btc": str(target_btc), "decision_at": decision_at.isoformat(),
                            "eligible_execution_at": execution_at.isoformat()}
        self.core.append(state, {"event": "actual_intent", **state["pending"]})
        self.core.save_state(state)
        result = self.client.place_order("BTC-USDT", "buy" if delta > 0 else "sell", "market", abs(delta), strategy=self.config.strategy_id)
        if result.status != "filled" or result.filled_qty != abs(delta) or result.filled_price is None:
            self.core.fail_closed("pending_order_expired", execution_at)
            raise PaperSafetyError("partial, rejected, or ambiguous OKX Demo fill")
        fill_id = str(result.order_id)
        if fill_id in state["seen_fills"]:
            self.core.fail_closed("duplicate_fill", execution_at)
            raise PaperSafetyError("duplicate actual fill")
        balances = self.client.get_balance()
        actual_btc, actual_cash = Decimal(balances.get("BTC", "-1")), Decimal(balances.get("USDT", "-1"))
        if actual_btc != target_btc or actual_cash < 0:
            self.core.fail_closed("wallet_reconciliation_mismatch", execution_at)
            raise PaperSafetyError("actual OKX Demo balance does not reconcile after fill")
        state.update(cash=str(actual_cash), btc=str(actual_btc), pending=None)
        state["seen_fills"].append(fill_id)
        self.core.append(state, {"event": "actual_fill", "intent_id": intent_id, "order_id": fill_id,
                                 "fill_price": str(result.filled_price), "quantity": str(result.filled_qty),
                                 "fee": str(result.fee), "fee_currency": result.fee_currency,
                                 "actual_cash": str(actual_cash), "actual_btc": str(actual_btc),
                                 "model_execution": None})
        self.core.save_state(state)
        return {"status": "reconciled", "intent_id": intent_id, "order_id": fill_id,
                "actual_price": str(result.filled_price), "actual_fee": str(result.fee)}
