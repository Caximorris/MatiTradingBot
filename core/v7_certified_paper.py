"""V7 certified isolated paper candidate: local, durable, and paper-only.

This module intentionally imports neither exchange clients nor routing code.  It
accepts immutable :class:`StrategySnapshot` / :class:`TargetIntent` values and
persists only a candidate-owned wallet, state file, and append-only journal.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.certification import StrategySnapshot, TargetIntent, contract_hash


PAPER_CANDIDATE_ID = "v7-certified-isolated-paper-candidate"
_TERMINAL = frozenset({"filled", "reconciled"})
CIRCUIT_BREAKER_REASONS = frozenset({
    "unexpected_error_locked", "duplicate_intent", "duplicate_order", "duplicate_fill",
    "pending_order_expired", "wallet_reconciliation_mismatch", "negative_impossible_balance",
    "hash_mismatch", "configuration_mismatch", "stale_data", "conflicting_duplicate_candle",
    "out_of_order_candle", "missing_required_candle", "paper_client_unavailable",
    "repeated_unexpected_exception", "unexpected_v7_regime_transition", "non_causal_fill",
})


class PaperSafetyError(RuntimeError):
    """Fail-closed operational corruption or isolation violation."""


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_frozen_candidate(path: Path) -> tuple[dict[str, Any], str]:
    raw = _read_json(path, None)
    if not isinstance(raw, dict) or raw.get("schema_version") != "v7-frozen-candidate/v1":
        raise PaperSafetyError("missing or invalid frozen V7 candidate specification")
    if raw.get("phase_days", {}).get("bear_onset_start") != 540 or raw.get("phase_days", {}).get("accumulation_start") != 900:
        raise PaperSafetyError("frozen V7 phase contract mismatch")
    return raw, _hash(raw)


@dataclass(frozen=True)
class CertifiedPaperConfig:
    instance_id: str
    strategy_id: str
    wallet_id: str
    portfolio_id: str
    wallet_path: Path
    journal_path: Path
    evidence_path: Path
    report_path: Path
    frozen_spec_path: Path
    candidate_hash: str
    source_hash: str
    configuration_hash: str
    active: bool = False
    service_managed: bool = True
    allow_shorts: bool = False
    mode: str = "paper"
    promotion_allowed: bool = False

    def validate(self) -> None:
        if self.active or not self.service_managed or self.allow_shorts or self.mode != "paper" or self.promotion_allowed:
            raise PaperSafetyError("certified candidate must remain inactive, paper-only, and non-promotable")
        values = (self.instance_id, self.strategy_id, self.wallet_id, self.portfolio_id)
        if len(set(values)) != len(values) or not all("v7_certified" in value for value in values):
            raise PaperSafetyError("candidate identifiers are not isolated")
        spec, candidate_hash = load_frozen_candidate(self.frozen_spec_path)
        if candidate_hash != self.candidate_hash or spec.get("strategy_identifier") != "swing_cycle_core":
            raise PaperSafetyError("candidate hash mismatch")
        if self.source_hash != contract_hash():
            raise PaperSafetyError("certified execution contract hash mismatch")
        expected = _hash(self.as_dict(include_hashes=False))
        if expected != self.configuration_hash:
            raise PaperSafetyError("configuration hash mismatch")

    def as_dict(self, *, include_hashes: bool = True) -> dict[str, Any]:
        value = {"instance_id": self.instance_id, "strategy_id": self.strategy_id, "wallet_id": self.wallet_id,
                 "portfolio_id": self.portfolio_id, "wallet_path": str(self.wallet_path), "journal_path": str(self.journal_path),
                 "evidence_path": str(self.evidence_path), "report_path": str(self.report_path),
                 "frozen_spec_path": str(self.frozen_spec_path), "active": self.active,
                 "service_managed": self.service_managed, "allow_shorts": self.allow_shorts, "mode": self.mode,
                 "promotion_allowed": self.promotion_allowed}
        if include_hashes:
            value |= {"candidate_hash": self.candidate_hash, "source_hash": self.source_hash,
                      "configuration_hash": self.configuration_hash}
        return value


def make_config(root: Path, *, instance_id: str = "v7_certified_paper") -> CertifiedPaperConfig:
    spec_path = root / "docs" / "v7_frozen_candidate.json"
    _, candidate_hash = load_frozen_candidate(spec_path)
    runtime = root / "data" / "runtime" / "v7_certified" / instance_id
    base = {"instance_id": instance_id, "strategy_id": "v7_certified_strategy", "wallet_id": "v7_certified_wallet",
            "portfolio_id": "v7_certified_portfolio", "wallet_path": runtime / "wallet.json", "journal_path": runtime / "journal.jsonl",
            "evidence_path": runtime / "evidence", "report_path": runtime / "reports", "frozen_spec_path": spec_path,
            "active": False, "service_managed": True, "allow_shorts": False, "mode": "paper", "promotion_allowed": False}
    configuration_hash = _hash({key: str(value) if isinstance(value, Path) else value for key, value in base.items()})
    return CertifiedPaperConfig(**base, candidate_hash=candidate_hash, source_hash=contract_hash(), configuration_hash=configuration_hash)


class CertifiedPaperAdapter:
    """Append-only local paper adapter; it has no client construction surface."""

    def __init__(self, config: CertifiedPaperConfig) -> None:
        config.validate()
        self.config = config

    def decide(self, snapshot: StrategySnapshot, intent: TargetIntent | None) -> TargetIntent | None:
        if snapshot.decision_at.tzinfo is None or snapshot.decision_at.utcoffset().total_seconds() != 0:
            raise PaperSafetyError("decision timestamp must be UTC")
        if snapshot.decision_at.hour % 4 or not snapshot.bars or snapshot.latest.timestamp > snapshot.decision_at:
            raise PaperSafetyError("completed-bar UTC four-hour cadence required")
        if intent is not None and not isinstance(intent, TargetIntent):
            raise PaperSafetyError("only TargetIntent may reach certified paper")
        return intent

    def initial_state(self) -> dict[str, Any]:
        return {"candidate_id": PAPER_CANDIDATE_ID, "candidate_hash": self.config.candidate_hash,
                "configuration_hash": self.config.configuration_hash, "source_hash": self.config.source_hash,
                "locked": False, "lock_reason": None, "lock_timestamp": None, "seen_intents": [],
                "seen_fills": [], "pending": None, "cash": "10000", "btc": "0", "journal_sequence": 0}

    def load_state(self) -> dict[str, Any]:
        state = _read_json(self.config.wallet_path, self.initial_state())
        if not isinstance(state, dict):
            raise PaperSafetyError("candidate wallet state corrupt")
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        _write_json(self.config.wallet_path, state)

    def lock(self, state: dict[str, Any], reason: str, now: datetime) -> None:
        if reason not in CIRCUIT_BREAKER_REASONS:
            reason = "repeated_unexpected_exception"
        state.update(locked=True, lock_reason=reason, lock_timestamp=now.astimezone(timezone.utc).isoformat())
        self.save_state(state)

    def fail_closed(self, reason: str, now: datetime | None = None) -> None:
        """Persist an operational lock; human action is required for any future run."""
        state = self.load_state()
        self.lock(state, reason, now or datetime.now(timezone.utc))

    def validate_candle_batch(self, candles: list[dict[str, Any]], *, now: datetime,
                              max_age_hours: int = 5) -> None:
        """Validate paper feed order before a decision can be considered."""
        prior: datetime | None = None
        seen: dict[datetime, dict[str, Any]] = {}
        try:
            for candle in candles:
                stamp = datetime.fromisoformat(str(candle["timestamp"])).astimezone(timezone.utc)
                if prior is not None and stamp < prior:
                    raise PaperSafetyError("out_of_order_candle")
                if stamp in seen:
                    if candle != seen[stamp]:
                        raise PaperSafetyError("conflicting_duplicate_candle")
                    continue
                seen[stamp] = candle
                prior = stamp
            if not prior:
                raise PaperSafetyError("missing_required_candle")
            if (now.astimezone(timezone.utc) - prior).total_seconds() > max_age_hours * 3600:
                raise PaperSafetyError("stale_data")
        except PaperSafetyError as exc:
            self.fail_closed(str(exc), now)
            raise

    def append(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        self.config.journal_path.parent.mkdir(parents=True, exist_ok=True)
        sequence = state["journal_sequence"] + 1
        record = {"sequence": sequence, "candidate_id": PAPER_CANDIDATE_ID, **event}
        record["entry_hash"] = _hash(record)
        with self.config.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        state["journal_sequence"] = sequence

    def replay_operation(self, row: dict[str, str]) -> dict[str, Any]:
        """Apply one independently reconciled operation, exactly once, for parity replay."""
        state = self.load_state()
        timestamp = datetime.fromisoformat(row["decision_timestamp"])
        if state.get("locked"):
            raise PaperSafetyError("paper circuit breaker is locked")
        if state["candidate_hash"] != self.config.candidate_hash or state["configuration_hash"] != self.config.configuration_hash:
            self.lock(state, "hash_mismatch", timestamp)
            raise PaperSafetyError("hash mismatch")
        intent_id = f"v7-certified-{row['sequence']}"
        if intent_id in state["seen_intents"]:
            return {"status": "duplicate_intent", "sequence": row["sequence"]}
        if row["fill_timestamp"] <= row["decision_timestamp"]:
            self.lock(state, "non_causal_fill", timestamp)
            raise PaperSafetyError("paper fill is not next-open causal")
        cash_before, btc_before = Decimal(row["cash_before"]), Decimal(row["btc_before"])
        if Decimal(state["cash"]) != cash_before or Decimal(state["btc"]) != btc_before:
            self.lock(state, "wallet_reconciliation_mismatch", timestamp)
            raise PaperSafetyError("wallet reconciliation mismatch")
        fill_id = f"fill-{row['sequence']}"
        state["seen_intents"].append(intent_id)
        state["pending"] = {"intent_id": intent_id, "side": row["side"], "eligible_fill_timestamp": row["fill_timestamp"]}
        self.append(state, {"event": "intent", "intent_id": intent_id, "decision_timestamp": row["decision_timestamp"],
                            "information_cutoff": row["information_cutoff"], "target": row["new_target"], "side": row["side"]})
        if fill_id in state["seen_fills"]:
            self.lock(state, "duplicate_fill", timestamp)
            raise PaperSafetyError("duplicate fill")
        state["cash"], state["btc"] = row["cash_after"], row["btc_after"]
        state["seen_fills"].append(fill_id)
        state["pending"] = None
        self.append(state, {"event": "fill", "intent_id": intent_id, "fill_id": fill_id, "fill_timestamp": row["fill_timestamp"],
                            "fill_open": row["fill_open"], "fill_price": row["fill_price"], "quantity": row["quantity"],
                            "fee": row["fee"], "cash_before": row["cash_before"], "cash_after": row["cash_after"],
                            "btc_before": row["btc_before"], "btc_after": row["btc_after"], "equity_after": row["equity_after"]})
        self.save_state(state)
        return {"status": "reconciled", "sequence": row["sequence"], "state": state}


def replay_six_operation_ledger(config: CertifiedPaperConfig, ledger_path: Path) -> dict[str, Any]:
    adapter = CertifiedPaperAdapter(config)
    results: list[dict[str, Any]] = []
    with ledger_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 6:
        raise PaperSafetyError("certified ledger must contain exactly six operations")
    for row in rows:
        results.append(adapter.replay_operation(row))
    state = adapter.load_state()
    return {"PAPER_REPLAY_PARITY": "PASS", "intents": len(state["seen_intents"]), "fills": len(state["seen_fills"]),
            "final_cash": state["cash"], "final_btc": state["btc"], "results": results}
