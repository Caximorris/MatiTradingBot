"""Isolated v7 Cycle Core: BTC except for a precommitted bear-onset cash phase."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger

from core.v7_operations import canonical_hash
from strategies.cycle_phase_clock import CyclePhaseClock, PHASES


class CycleState(StrEnum):
    STABLE_RISK_ON = "STABLE_RISK_ON"
    EXIT_PENDING = "EXIT_PENDING"
    EXIT_ORDER_SUBMITTED = "EXIT_ORDER_SUBMITTED"
    BEAR_CASH = "BEAR_CASH"
    ENTRY_PENDING = "ENTRY_PENDING"
    ENTRY_ORDER_SUBMITTED = "ENTRY_ORDER_SUBMITTED"
    ERROR_LOCKED = "ERROR_LOCKED"


@dataclass
class SwingCycleCoreConfig:
    symbol: str = "BTC-USDT"
    instance_id: str = "v7_cycle_core"
    bear_onset_btc_pct: Decimal = Decimal("0")
    rebalance_threshold: Decimal = Decimal("0.01")
    max_data_age_hours: int = 5
    transition_delay_hours: int = 0
    phase_post_end: int = 180
    phase_bear_start: int = 540
    phase_accumulation_start: int = 900
    confirmed_halving_timestamps: tuple[datetime, ...] = CyclePhaseClock().halving_timestamps
    operational_mode: str = "research"
    transition_journal_path: str = ""
    max_strategic_orders_per_day: int = 4
    max_unresolved_orders: int = 1

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SwingCycleCoreConfig":
        values = dict(raw)
        for key in ("bear_onset_btc_pct", "rebalance_threshold"):
            if key in values:
                values[key] = Decimal(str(values[key]))
        if "confirmed_halving_dates" in values:
            raise ValueError("confirmed_halving_dates is unsafe; use exact UTC timestamps")
        if "confirmed_halving_timestamps" in values:
            parsed = []
            for item in values["confirmed_halving_timestamps"]:
                timestamp = datetime.fromisoformat(str(item).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("halving timestamps must be UTC-aware")
                parsed.append(timestamp.astimezone(timezone.utc))
            values["confirmed_halving_timestamps"] = tuple(parsed)
        cfg = cls(**{key: value for key, value in values.items() if key in cls.__dataclass_fields__})
        if cfg.symbol.upper() != "BTC-USDT":
            raise ValueError("Cycle Core is BTC-USDT only")
        if cfg.bear_onset_btc_pct not in (Decimal("0"), Decimal("0.2"), Decimal("1")):
            raise ValueError("bear_onset_btc_pct must be 0, 0.2, or 1 (buy-and-hold control)")
        if not Decimal("0") <= cfg.rebalance_threshold <= Decimal("1"):
            raise ValueError("rebalance_threshold must be in [0, 1]")
        if cfg.transition_delay_hours not in (0, 1, 6, 12, 24, 72):
            raise ValueError("transition_delay_hours must be a predefined delay")
        if cfg.operational_mode not in {"research", "shadow", "paper"}:
            raise ValueError("operational_mode must be research, shadow, or paper")
        if cfg.max_strategic_orders_per_day < 1 or cfg.max_unresolved_orders != 1:
            raise ValueError("v7 requires 1 unresolved order and a positive daily order cap")
        return cfg

    def to_dict(self) -> dict[str, Any]:
        output = asdict(self)
        output["bear_onset_btc_pct"] = str(self.bear_onset_btc_pct)
        output["rebalance_threshold"] = str(self.rebalance_threshold)
        output["confirmed_halving_timestamps"] = [item.isoformat().replace("+00:00", "Z")
                                                    for item in self.confirmed_halving_timestamps]
        return output


class SwingCycleCoreBot:
    """Client-agnostic, fail-closed strategic allocator with an isolated state key."""

    _STATE_VERSION = 2

    def __init__(self, client: Any, config: SwingCycleCoreConfig, session: Any = None,
                 risk_manager: Any = None) -> None:
        self._client, self._cfg, self._session = client, config, session
        self._risk_manager = risk_manager
        self._clock = CyclePhaseClock(
            halving_timestamps=config.confirmed_halving_timestamps,
            post_halving_end=config.phase_post_end,
            bear_onset_start=config.phase_bear_start,
            accumulation_start=config.phase_accumulation_start,
        )
        self._state = self._fresh_state()
        self._decision_log: list[dict[str, Any]] = []
        self._transition_log: list[dict[str, Any]] = []
        # Report-only operational timeline.  It is deliberately independent of
        # the optional durable journal so research reports cannot omit events.
        self._event_log: list[dict[str, Any]] = []
        self._load_state()

    @property
    def name(self) -> str:
        suffix = self._safe_id(self._cfg.instance_id)
        return f"swing_cycle_core_{suffix}_{self._cfg.symbol.lower().replace('-', '_')}"

    @property
    def _state_name(self) -> str:
        return f"swing_cycle_core_{self._safe_id(self._cfg.instance_id)}"

    @staticmethod
    def _safe_id(value: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.lower())
        return clean.strip("_") or "default"

    def should_enter(self) -> bool:
        return self._state["state"] == CycleState.ENTRY_PENDING

    def should_exit(self) -> bool:
        return self._state["state"] == CycleState.EXIT_PENDING

    def run(self) -> None:
        """Evaluate once per UTC 4-hour block; invalid inputs leave risk unchanged."""
        if self._state["state"] == CycleState.ERROR_LOCKED:
            return
        try:
            now = self._utc_now()
            block = self._clock.evaluation_block(now)
        except Exception as exc:
            self._lock(f"invalid_clock:{exc}")
            return
        if self._state.get("last_block") == block:
            return
        if not self._market_data_ok(now):
            return  # do not consume: a later tick in this block may be valid
        # A delay is a predeclared execution stress: it observes only a past UTC
        # timestamp, so it cannot turn a future phase into a present decision.
        days, phase = self._clock.phase_at(now - timedelta(hours=self._cfg.transition_delay_hours))
        if phase not in PHASES:
            self._lock(f"unknown_phase:{days}")
            return
        previous = self._state.get("phase")
        previous_target = self.target_for_phase(previous) if previous in PHASES else None
        target = self.target_for_phase(phase)
        current = self._current_btc_pct()
        self._decision_log.append({
            "timestamp": now.isoformat(), "block": block,
            "previous_phase": previous, "phase": phase,
            "previous_target": str(previous_target) if previous_target is not None else "unknown",
            "target": str(target), "current": str(current),
        })
        context = self._transition_context(previous, previous_target, phase, target)
        self._state["last_block"] = block
        self._state["phase"] = phase
        self._record_event("decision", target, current, "decision", "four_hour_evaluation", context)
        self._append_transition(target, "decision", Decimal("0"), None, "decision",
                                "four_hour_evaluation", context)
        if self._state["state"] in (CycleState.EXIT_ORDER_SUBMITTED, CycleState.ENTRY_ORDER_SUBMITTED):
            self._reconcile_transition(target, context)
            return
        desired_state = self._desired_state(target, current)

        # Labels can change inside one exposure regime (post_halving -> bull_peak
        # and accumulation -> post_halving).  They are descriptive, not strategic:
        # only a target change may bypass the reconciliation threshold.
        target_changed = previous_target is not None and previous_target != target
        if target_changed:
            self._record_event("transition", target, current, "transition", "target_changed", context)
        if target_changed or self._state["state"] in (
            CycleState.EXIT_PENDING, CycleState.ENTRY_PENDING,
            CycleState.EXIT_ORDER_SUBMITTED, CycleState.ENTRY_ORDER_SUBMITTED,
        ):
            self._state["state"] = desired_state
            if not self._save_state():
                return
            self._reconcile_transition(target, context)
            return

        # Stable reconciliation is allowed once per block, but no order is generated at target.
        if abs(target - current) >= self._cfg.rebalance_threshold:
            self._state["state"] = desired_state
            if not self._save_state():
                return
            self._reconcile_transition(target, context)
        else:
            self._state["state"] = CycleState.BEAR_CASH if target == 0 else CycleState.STABLE_RISK_ON
            self._save_state()

    def target_for_phase(self, phase: str) -> Decimal:
        if phase not in PHASES:
            raise ValueError(f"unknown cycle phase: {phase}")
        return self._cfg.bear_onset_btc_pct if phase == "bear_onset" else Decimal("1")

    def reconcile_error_lock(self) -> None:
        """Explicit operator action required after corrupt/ambiguous persisted state."""
        if self._state["state"] != CycleState.ERROR_LOCKED:
            return
        self._state = self._fresh_state()
        self._save_state()

    def _desired_state(self, target: Decimal, current: Decimal) -> CycleState:
        # Quantized fills and the bounded execution reserve can leave a small,
        # documented residual; it is not a tactical signal nor a retry trigger.
        if abs(target - current) <= Decimal("0.01"):
            return CycleState.BEAR_CASH if target == 0 else CycleState.STABLE_RISK_ON
        return CycleState.EXIT_PENDING if target < current else CycleState.ENTRY_PENDING

    def _reconcile_transition(self, target: Decimal, context: dict[str, Any] | None = None) -> None:
        state = CycleState(self._state["state"])
        if state in (CycleState.EXIT_ORDER_SUBMITTED, CycleState.ENTRY_ORDER_SUBMITTED):
            order_id = self._state.get("order_id")
            if not order_id:
                self._lock("submitted_order_missing_id")
                return
            try:
                observer = getattr(self._client, "get_order_status", None)
                observed = observer(self._cfg.symbol, order_id) if observer else None
            except Exception as exc:
                self._lock(f"order_status_unavailable:{exc}")
                return
            if observed is None:
                # Legacy adapters cannot certify a missing order as filled.  A
                # target reconciliation is the only safe fallback and a residual
                # becomes an explicit operator-visible lock, never a retry.
                try:
                    is_open = any((item.get("order_id") or item.get("ordId")) == order_id
                                  for item in self._client.get_open_orders(self._cfg.symbol))
                except Exception as exc:
                    self._lock(f"open_order_query_failed:{exc}")
                    return
                if is_open:
                    return
                current = self._current_btc_pct()
                desired = self._desired_state(target, current)
                if desired in (CycleState.BEAR_CASH, CycleState.STABLE_RISK_ON):
                    self._state.update(state=desired, order_id=None, pending_order=None)
                    self._record_event("fill", target, current, "filled_inferred",
                                       "legacy_target_reconciliation", context)
                    self._append_transition(target, "reconciled", Decimal("0"), None,
                                            "filled_inferred", "legacy_target_reconciliation", context)
                    self._save_state()
                else:
                    self._lock("submitted_order_status_unknown")
                return
            status = getattr(observed, "status", "unknown")
            if status in {"open", "live", "partially_filled"}:
                self._state["pending_order"] = self._order_observation(observed)
                self._save_state()
                return
            if status != "filled":
                self._lock(f"submitted_order_terminal:{status}")
                return
            current = self._current_btc_pct()
            desired = self._desired_state(target, current)
            if desired not in (CycleState.BEAR_CASH, CycleState.STABLE_RISK_ON):
                self._lock("filled_order_target_unreached")
                return
            self._state.update(state=desired, order_id=None, pending_order=None)
            self._record_event("fill", target, current, "filled", "causal_fill_reconciled", context,
                               observed)
            self._append_transition(target, "reconciled", Decimal("0"), observed,
                                    "filled", "causal_fill_reconciled", context)
            self._save_state()
            return
        if state not in (CycleState.EXIT_PENDING, CycleState.ENTRY_PENDING):
            return
        current = self._current_btc_pct()
        side = "sell" if target < current else "buy"
        qty = self._order_quantity(target, current, side)
        if qty <= 0:
            self._state["state"] = self._desired_state(target, current)
            self._save_state()
            return
        submitted = CycleState.EXIT_ORDER_SUBMITTED if side == "sell" else CycleState.ENTRY_ORDER_SUBMITTED
        client_order_id = self._client_order_id()
        self._state.update(state=submitted, order_id=client_order_id,
                           pending_order={"client_order_id": client_order_id, "side": side,
                                          "requested_qty": str(qty),
                                          "decision_timestamp": self._utc_now().isoformat(),
                                          "earliest_fill_timestamp": self._earliest_fill_timestamp().isoformat()})
        if not self._save_state():
            return  # Persist before any side effect; no durable state means no order.
        self._record_event("submission", target, current, "submitted", "order_submitted", context,
                           order_id=client_order_id, side=side, qty=qty)
        self._append_transition(target, side, qty, None, "submitted", "order_submitted", context)
        try:
            result = self._client.place_order(self._cfg.symbol, side, "market", qty,
                                              strategy=self.name, client_order_id=client_order_id)
        except Exception as exc:
            self._append_transition(target, side, qty, None, "exception", str(exc), context)
            self._lock(f"order_exception:{exc}")
            return
        self._state["order_id"] = getattr(result, "order_id", None) or client_order_id
        self._state["pending_order"] = self._order_observation(result)
        status = getattr(result, "status", "rejected")
        transition = {
            "timestamp": self._utc_now().isoformat(), "phase": self._state.get("phase"),
            "target": str(target), "side": side, "qty": str(qty),
            "order_id": self._state["order_id"], "status": status,
            "filled_qty": str(getattr(result, "filled_qty", Decimal("0"))),
            "fee": str(getattr(result, "fee", Decimal("0"))),
            "reason": "phase_transition_or_residual_reconciliation",
        }
        self._transition_log.append(transition)
        if status == "filled":
            self._record_event("fill", target, self._current_btc_pct(), status, transition["reason"], context,
                               result, side=side, qty=qty)
        self._append_transition(target, side, qty, result, status, transition["reason"], context)
        if status in {"open", "live", "partially_filled"}:
            self._save_state()
            return
        if status != "filled":
            self._state["state"] = CycleState.EXIT_PENDING if side == "sell" else CycleState.ENTRY_PENDING
            self._save_state()
            return
        current_after = self._current_btc_pct()
        self._state["order_id"] = None
        self._state["pending_order"] = None
        self._state["state"] = self._desired_state(target, current_after)
        self._save_state()

    def _order_quantity(self, target: Decimal, current: Decimal, side: str) -> Decimal:
        balance = self._client.get_balance()
        base = self._cfg.symbol.split("-")[0]
        price = self._safe_price()
        total = balance.get("USDT", Decimal("0")) + balance.get(base, Decimal("0")) * price
        if total <= 0:
            return Decimal("0")
        delta_value = abs(target - current) * total
        if side == "buy":
            # Keep 50 bps for the predefined worst 2x-conservative fee/slippage
            # stress.  This is execution reserve, never a strategic allocation.
            delta_value = min(delta_value, balance.get("USDT", Decimal("0")) * Decimal("0.995"))
        else:
            delta_value = min(delta_value, balance.get(base, Decimal("0")) * price)
        return (delta_value / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

    def _current_btc_pct(self) -> Decimal:
        balance = self._client.get_balance()
        base = self._cfg.symbol.split("-")[0]
        price = self._safe_price()
        btc_value = balance.get(base, Decimal("0")) * price
        total = btc_value + balance.get("USDT", Decimal("0"))
        return Decimal("0") if total <= 0 else btc_value / total

    def _safe_price(self) -> Decimal:
        completed = getattr(self._client, "get_completed_ticker", None)
        raw_price = completed(self._cfg.symbol) if completed is not None else self._client.get_ticker(self._cfg.symbol)
        price = Decimal(str(raw_price))
        if price <= 0:
            raise ValueError("ticker unavailable")
        return price

    def _market_data_ok(self, now: datetime) -> bool:
        try:
            self._safe_price()
            # The deterministic backtest client exposes the decision bar directly;
            # querying a pandas slice for every 4-hour decision is equivalent but
            # needlessly expensive.  Live/paper still prove freshness from OHLCV.
            if self._client.__class__.__name__ == "BacktestClient":
                return True
            bars = self._client.get_ohlcv(self._cfg.symbol, limit=2)
            if bars is None or len(bars) < 1:
                return False
            timestamp = bars.iloc[-1]["timestamp"] if hasattr(bars, "iloc") else bars[-1]["timestamp"]
            observed = datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc)
            age_hours = (now - observed).total_seconds() / 3600
            return 0 <= age_hours <= self._cfg.max_data_age_hours
        except Exception as exc:
            logger.warning("[{}] fail-closed market data: {}", self.name, exc)
            return False

    def _utc_now(self) -> datetime:
        now = self._client.current_time()
        if now.tzinfo is None:
            raise ValueError("client returned naive timestamp")
        return now.astimezone(timezone.utc)

    def _fresh_state(self) -> dict[str, Any]:
        return {"version": self._STATE_VERSION, "state": CycleState.STABLE_RISK_ON,
                "phase": None, "last_block": None, "order_id": None, "pending_order": None,
                "error": None}

    def _load_state(self) -> None:
        if self._session is None:
            return
        try:
            from core.database import get_or_create_bot_state
            row = get_or_create_bot_state(self._session, self._state_name, self._cfg.symbol)
            saved = row.get_config()
            if not saved:
                return
            required = {"version", "state", "phase", "last_block", "order_id", "pending_order", "error"}
            if not isinstance(saved, dict) or set(saved) != required or saved["version"] != self._STATE_VERSION:
                raise ValueError("invalid state schema")
            self._validate_persisted_state(saved)
            saved["state"] = CycleState(saved["state"])
            self._state = saved
        except Exception as exc:
            self._state = self._fresh_state()
            self._state.update(state=CycleState.ERROR_LOCKED, error=f"corrupt_state:{exc}")
            self._save_state()

    def _save_state(self) -> bool:
        if self._session is None:
            return True
        try:
            from core.database import get_or_create_bot_state
            row = get_or_create_bot_state(self._session, self._state_name, self._cfg.symbol)
            payload = dict(self._state)
            payload["state"] = str(payload["state"])
            row.set_config(payload)
            return True
        except Exception as exc:
            logger.warning("[{}] state persistence failed: {}", self.name, exc)
            self._state.update(state=CycleState.ERROR_LOCKED, error=f"state_persist:{exc}")
            return False

    def _lock(self, reason: str) -> None:
        self._state.update(state=CycleState.ERROR_LOCKED, error=reason)
        self._save_state()

    def _client_order_id(self) -> str:
        """Deterministic, short id persisted before the side effect."""
        block = self._clock.evaluation_block(self._utc_now()).replace("-", "").replace("T", "")
        return f"v7{block}{len(self._transition_log):02d}"[:32]

    def _earliest_fill_timestamp(self) -> datetime:
        # The simulator submits after a decision at this bar's availability and
        # fills at the following 1H open.  Live adapters retain this as a lower
        # bound, then report the venue's actual fill timestamp.
        return self._utc_now() + timedelta(hours=1)

    @staticmethod
    def _order_observation(result: Any) -> dict[str, str]:
        return {"order_id": str(getattr(result, "order_id", "")),
                "status": str(getattr(result, "status", "unknown")),
                "filled_qty": str(getattr(result, "filled_qty", Decimal("0"))),
                "filled_price": str(getattr(result, "filled_price", "")),
                "fee": str(getattr(result, "fee", Decimal("0"))),
                "fee_currency": str(getattr(result, "fee_currency", ""))}

    def _validate_persisted_state(self, saved: dict[str, Any]) -> None:
        state = CycleState(saved["state"])
        phase = saved["phase"]
        if phase is not None and phase not in PHASES:
            raise ValueError("invalid persisted phase")
        submitted = {CycleState.EXIT_ORDER_SUBMITTED, CycleState.ENTRY_ORDER_SUBMITTED}
        if state in submitted:
            if not isinstance(saved["order_id"], str) or not saved["order_id"] or not isinstance(saved["pending_order"], dict):
                raise ValueError("submitted state missing durable order")
        elif saved["order_id"] is not None or saved["pending_order"] is not None:
            raise ValueError("non-submitted state has pending order")

    def _transition_context(self, previous_phase: str | None, previous_target: Decimal | None,
                            new_phase: str, new_target: Decimal) -> dict[str, Any]:
        return {"previous_phase": previous_phase or "unknown",
                "new_phase": new_phase,
                "previous_target": str(previous_target) if previous_target is not None else "unknown",
                "new_target": str(new_target),
                "state_hash_before": canonical_hash(self._state),}

    def _record_event(self, event_type: str, target: Decimal, current: Decimal, status: str,
                      reason: str, context: dict[str, Any] | None, result: Any | None = None,
                      *, order_id: str = "", side: str = "", qty: Decimal = Decimal("0")) -> None:
        self._event_log.append({
            "timestamp": self._utc_now().isoformat(), "event_type": event_type,
            "previous_phase": (context or {}).get("previous_phase", self._state.get("phase") or "unknown"),
            "new_phase": (context or {}).get("new_phase", self._state.get("phase") or "unknown"),
            "previous_target": (context or {}).get("previous_target", str(target)),
            "new_target": (context or {}).get("new_target", str(target)),
            "target": str(target), "current": str(current), "status": status, "reason": reason,
            "order_id": order_id or str(getattr(result, "order_id", "") or self._state.get("order_id") or ""),
            "side": side, "qty": str(qty), "price": str(self._safe_price()),
        })

    def _append_transition(self, target: Decimal, side: str, qty: Decimal, result: Any | None,
                           status: str, reason: str, context: dict[str, Any] | None = None) -> None:
        """Write operational evidence only when the instance configured a journal path."""
        if not self._cfg.transition_journal_path:
            return
        try:
            from core.v7_operations import TransitionJournal
            now = self._utc_now()
            current = self._current_btc_pct()
            order_id = (getattr(result, "order_id", "") if result is not None else "") or self._state.get("order_id") or ""
            details = context or self._transition_context(self._state.get("phase"), target,
                                                           self._state.get("phase") or "unknown", target)
            TransitionJournal(Path(self._cfg.transition_journal_path)).append({
                "strategy_id": self.name,
                "instance_id": self._cfg.instance_id,
                "transition_id": f"{self._clock.evaluation_block(now)}:{status}:{side}:{order_id or 'none'}",
                "previous_phase": details["previous_phase"], "new_phase": details["new_phase"],
                "previous_target": details["previous_target"], "new_target": details["new_target"],
                "decision_timestamp": now.isoformat(), "market_data_timestamp": now.isoformat(),
                "expected_position": str(target), "actual_position": str(current),
                "order_id": order_id, "fill_ids": [order_id] if order_id else [],
                "fees": str(getattr(result, "fee", Decimal("0"))), "slippage": "unknown",
                "status": status, "retry_count": 0,
                "state_hash_before": details["state_hash_before"],
                "state_hash_after": canonical_hash(self._state), "reason": reason,
            })
        except Exception as exc:
            self._lock(f"transition_journal:{exc}")
