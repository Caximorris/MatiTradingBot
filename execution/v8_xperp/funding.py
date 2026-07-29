"""Atomic exact-once funding expectations and OKX bill reconciliation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .adapter import SafetyError, _decimal

FUNDING_SCHEMA = 1
FUNDING_STATES = {
    "EXPECTED", "DUE", "DELAYED", "MATCHED", "RECONCILED", "MISSING",
    "SIGN_MISMATCH", "AMOUNT_MISMATCH", "TIMESTAMP_MISMATCH", "CONFLICT",
}
DELAY_AFTER_MS = 120_000
MISSING_AFTER_MS = 900_000
AMOUNT_ABS_TOLERANCE = Decimal("0.00000001")
AMOUNT_REL_TOLERANCE = Decimal("0.000001")
AMOUNT_MAX_TOLERANCE = Decimal("0.01")


def source_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FundingExpectation:
    environment: str
    account_hash: str
    instrument_id: str
    settlement_ms: int
    side: str
    contracts: str
    position_notional: str
    signed_rate: str
    expected_amount: str
    metadata_hash: str
    rate_source_hash: str
    position_source_hash: str
    mark_source_hash: str
    state: str = "EXPECTED"
    bill_id: str | None = None
    bill_hash: str | None = None
    actual_amount: str | None = None
    last_result: str | None = None
    schema: int = FUNDING_SCHEMA

    @property
    def identity(self) -> tuple[str, str, str, int]:
        return self.environment, self.account_hash, self.instrument_id, self.settlement_ms


def make_expectation(
    *,
    environment: str,
    account_hash: str,
    instrument_id: str,
    settlement_ms: int,
    side: str,
    contracts: Decimal,
    position_notional: Decimal,
    signed_rate: Decimal,
    metadata_hash: str,
    rate_source_hash: str,
    position_source_hash: str,
    mark_source_hash: str,
) -> FundingExpectation:
    if side not in {"long", "short"} or contracts <= 0 or position_notional <= 0:
        raise SafetyError("invalid funding expectation inputs")
    direction = Decimal("1") if side == "long" else Decimal("-1")
    expected = -direction * position_notional * signed_rate
    return FundingExpectation(
        environment, account_hash, instrument_id, settlement_ms, side,
        str(contracts), str(position_notional), str(signed_rate), str(expected),
        metadata_hash, rate_source_hash, position_source_hash, mark_source_hash,
    )


class FundingLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[FundingExpectation]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            records = [FundingExpectation(**row) for row in rows]
        except Exception as exc:
            raise SafetyError("corrupt V8 funding ledger") from exc
        if any(
            record.schema != FUNDING_SCHEMA or record.state not in FUNDING_STATES
            for record in records
        ):
            raise SafetyError("unsupported V8 funding ledger schema/state")
        identities = [record.identity for record in records]
        if len(identities) != len(set(identities)):
            raise SafetyError("duplicate V8 funding expectation identity")
        matched_ids = [record.bill_id for record in records if record.bill_id]
        if len(matched_ids) != len(set(matched_ids)):
            raise SafetyError("one funding bill is assigned to multiple expectations")
        return records

    def create(self, record: FundingExpectation) -> FundingExpectation:
        rows = self.load()
        existing = next((item for item in rows if item.identity == record.identity), None)
        if existing is not None:
            if existing != record:
                raise SafetyError("V8 funding expectation identity content changed")
            return existing
        if record.state != "EXPECTED":
            raise SafetyError("invalid V8 funding expectation")
        self._write([*rows, record])
        return record

    def update(self, identity: tuple[str, str, str, int], **changes: object) -> FundingExpectation:
        rows = self.load()
        found: FundingExpectation | None = None
        output: list[FundingExpectation] = []
        for item in rows:
            if item.identity == identity:
                found = replace(item, **changes)
                output.append(found)
            else:
                output.append(item)
        if found is None or found.state not in FUNDING_STATES:
            raise SafetyError("unknown or invalid V8 funding expectation update")
        self._write(output)
        return found

    def _write(self, rows: list[FundingExpectation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump([asdict(item) for item in rows], handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _amount_tolerance(expected: Decimal) -> Decimal:
    return min(
        AMOUNT_MAX_TOLERANCE,
        max(AMOUNT_ABS_TOLERANCE, abs(expected) * AMOUNT_REL_TOLERANCE),
    )


def reconcile_funding(
    *,
    ledger: FundingLedger,
    record: FundingExpectation,
    official_history: list[dict[str, Any]],
    bills: list[dict[str, Any]],
    now_ms: int,
) -> FundingExpectation:
    history = [
        row for row in official_history
        if row.get("instId") == record.instrument_id
        and int(row.get("fundingTime", -1)) == record.settlement_ms
    ]
    if len(history) > 1:
        return ledger.update(record.identity, state="CONFLICT", last_result="duplicate official funding rows")
    if not history:
        same_instrument = [
            row for row in official_history if row.get("instId") == record.instrument_id
        ]
        if len(same_instrument) == 1 and int(same_instrument[0].get("fundingTime", -1)) != record.settlement_ms:
            return ledger.update(
                record.identity,
                state="TIMESTAMP_MISMATCH",
                last_result="official settlement timestamp changed",
            )
        state = (
            "EXPECTED" if now_ms < record.settlement_ms
            else "DUE" if now_ms < record.settlement_ms + DELAY_AFTER_MS
            else "DELAYED" if now_ms < record.settlement_ms + MISSING_AFTER_MS
            else "MISSING"
        )
        return ledger.update(record.identity, state=state, last_result="official settlement not available")
    official_rate = _decimal(history[0].get("realizedRate") or history[0].get("fundingRate"))
    if official_rate != _decimal(record.signed_rate):
        return ledger.update(record.identity, state="CONFLICT", last_result="official funding rate changed")

    candidates = [
        bill for bill in bills
        if str(bill.get("type")) == "8"
        and str(bill.get("subType")) in {"173", "174"}
        and bill.get("instId") == record.instrument_id
        and bill.get("ccy") == "USDC"
        and record.settlement_ms <= int(bill.get("ts", -1)) <= record.settlement_ms + MISSING_AFTER_MS
    ]
    unique = {str(item.get("billId")): item for item in candidates if item.get("billId")}
    if len(unique) > 1:
        return ledger.update(record.identity, state="CONFLICT", last_result="multiple funding bills match one settlement")
    if not unique:
        wrong_time = [
            bill for bill in bills
            if str(bill.get("type")) == "8"
            and bill.get("instId") == record.instrument_id
            and bill.get("ccy") == "USDC"
        ]
        if wrong_time:
            return ledger.update(
                record.identity,
                state="TIMESTAMP_MISMATCH",
                last_result="funding bill posting timestamp is outside tolerance",
            )
        state = "DELAYED" if now_ms < record.settlement_ms + MISSING_AFTER_MS else "MISSING"
        return ledger.update(record.identity, state=state, last_result="funding bill not available")
    bill_id, bill = next(iter(unique.items()))
    existing = next(
        (item for item in ledger.load() if item.bill_id == bill_id and item.identity != record.identity),
        None,
    )
    if existing:
        return ledger.update(record.identity, state="CONFLICT", last_result="funding bill already consumed")
    bill_digest = source_hash(bill)
    if record.bill_id == bill_id:
        if record.bill_hash != bill_digest:
            return ledger.update(record.identity, state="CONFLICT", last_result="funding bill content changed")
        return record

    actual = _decimal(bill.get("pnl"))
    expected = _decimal(record.expected_amount)
    subtype = str(bill.get("subType"))
    if (subtype == "173" and actual >= 0) or (subtype == "174" and actual <= 0):
        return ledger.update(
            record.identity, state="SIGN_MISMATCH", bill_id=bill_id,
            bill_hash=bill_digest, actual_amount=str(actual), last_result="bill subtype/sign mismatch",
        )
    if (expected > 0) != (actual > 0):
        return ledger.update(
            record.identity, state="SIGN_MISMATCH", bill_id=bill_id,
            bill_hash=bill_digest, actual_amount=str(actual), last_result="expected/actual sign mismatch",
        )
    if abs(actual - expected) > _amount_tolerance(expected):
        return ledger.update(
            record.identity, state="AMOUNT_MISMATCH", bill_id=bill_id,
            bill_hash=bill_digest, actual_amount=str(actual), last_result="funding amount outside tolerance",
        )
    matched = ledger.update(
        record.identity, state="MATCHED", bill_id=bill_id,
        bill_hash=bill_digest, actual_amount=str(actual), last_result="exact funding bill matched",
    )
    return ledger.update(matched.identity, state="RECONCILED", last_result="exact-once funding reconciled")
