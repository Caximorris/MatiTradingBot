from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from execution.v8_xperp.adapter import Instrument, SafetyError
from execution.v8_xperp.intents import Intent, IntentLedger
from execution.v8_xperp.recovery import IntentExecution, StartupRecovery


CLIENT_ID = "v8xp012345678901234567890123456"
INSTRUMENT = "BTC-USD_UM_XPERP-test"


class Exchange:
    def __init__(self) -> None:
        self.order: dict[str, Any] | None = None
        self.fills: list[dict[str, Any]] = []
        self.position = Decimal("0")
        self.submit_calls = 0
        self.cancel_calls = 0
        self.query_calls = {"order": 0, "open": 0, "history": 0, "fills": 0, "position": 0}
        self.submit_behaviors: list[str] = []
        self.cancel_behavior = "ack"
        self.hidden_snapshots = 0
        self.completed_snapshots = 0

    def place_order(self) -> dict[str, Any]:
        self.submit_calls += 1
        behavior = self.submit_behaviors.pop(0)
        if behavior == "timeout_before":
            raise TimeoutError("before acceptance")
        self.order = {
            "clOrdId": CLIENT_ID,
            "ordId": "remote-1",
            "state": "partially_filled" if behavior == "partial_timeout" else "filled",
            "accFillSz": "0.4" if behavior == "partial_timeout" else "1",
        }
        fill_size = self.order["accFillSz"]
        self.fills = [{"clOrdId": CLIENT_ID, "fillId": "fill-1", "fillSz": fill_size}]
        self.position = Decimal(fill_size)
        if behavior == "delayed_timeout":
            self.hidden_snapshots = 2
            raise TimeoutError("accepted but temporarily invisible")
        if behavior in {"timeout_after", "partial_timeout"}:
            raise TimeoutError("after acceptance")
        return {"code": "0", "data": [{"sCode": "0", "ordId": "remote-1"}]}

    def get_order(self, _inst: str, **_kwargs: Any) -> dict[str, Any]:
        self.query_calls["order"] += 1
        if self.completed_snapshots < self.hidden_snapshots:
            return {"code": "51603", "msg": "Order does not exist", "data": []}
        return (
            {"code": "0", "data": [self.order]}
            if self.order
            else {"code": "51603", "msg": "Order does not exist", "data": []}
        )

    def get_order_list(self, **_kwargs: Any) -> dict[str, Any]:
        self.query_calls["open"] += 1
        if self.completed_snapshots < self.hidden_snapshots:
            return {"code": "0", "data": []}
        rows = [self.order] if self.order and self.order["state"] in {"live", "partially_filled"} else []
        return {"code": "0", "data": rows}

    def get_orders_history(self, **_kwargs: Any) -> dict[str, Any]:
        self.query_calls["history"] += 1
        if self.completed_snapshots < self.hidden_snapshots:
            return {"code": "0", "data": []}
        rows = [self.order] if self.order and self.order["state"] not in {"live"} else []
        return {"code": "0", "data": rows}

    def get_fills(self, **_kwargs: Any) -> dict[str, Any]:
        self.query_calls["fills"] += 1
        if self.completed_snapshots < self.hidden_snapshots:
            return {"code": "0", "data": []}
        return {"code": "0", "data": list(self.fills)}

    def get_positions(self, **_kwargs: Any) -> dict[str, Any]:
        self.query_calls["position"] += 1
        if self.completed_snapshots < self.hidden_snapshots:
            self.completed_snapshots += 1
            return {"code": "0", "data": []}
        rows = [{"instId": INSTRUMENT, "pos": str(self.position)}] if self.position else []
        return {"code": "0", "data": rows}

    def cancel_order(self, _inst: str, **_kwargs: Any) -> dict[str, Any]:
        self.cancel_calls += 1
        if self.cancel_behavior == "fill":
            self.order = {
                "clOrdId": CLIENT_ID,
                "ordId": "remote-1",
                "state": "filled",
                "accFillSz": "1",
            }
            self.fills = [{"clOrdId": CLIENT_ID, "fillId": "fill-1", "fillSz": "1"}]
            self.position = Decimal("1")
            raise TimeoutError("fill won cancel race")
        assert self.order is not None
        self.order = {**self.order, "state": "canceled", "accFillSz": "0"}
        if self.cancel_behavior == "timeout":
            raise TimeoutError("cancellation acknowledgement lost")
        return {"code": "0", "data": [{"sCode": "0", "ordId": "remote-1"}]}


class Adapter:
    def __init__(self, exchange: Exchange) -> None:
        self.trade = exchange
        self.account = exchange
        self.events: list[dict[str, Any]] = []

    @staticmethod
    def _ok(payload: dict[str, Any], _label: str) -> list[dict[str, Any]]:
        if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
            raise SafetyError("bad exchange response")
        return payload["data"]

    @staticmethod
    def client_id_hash(value: str) -> str:
        return value[-8:]

    def _append(self, event: str, payload: dict[str, Any]) -> None:
        self.events.append({"event": event, "payload": payload})


def _intent(**changes: Any) -> Intent:
    base = Intent(
        transition_id="transition-1",
        client_order_id=CLIENT_ID,
        instrument_id=INSTRUMENT,
        target="long",
        action="buy-open",
        side="buy",
        contracts="1",
        reduce_only=False,
        order_type="market",
        metadata_hash="metadata",
    )
    return replace(base, **changes)


def _instrument(metadata_hash: str = "metadata") -> Instrument:
    return Instrument(
        INSTRUMENT,
        "BTC-USD_UM_XPERP",
        "BTC-USD",
        "USDC",
        "linear",
        Decimal("1"),
        "BTC",
        Decimal("0.1"),
        Decimal("0.1"),
        Decimal("0.1"),
        Decimal("10"),
        datetime(2031, 1, 1, tzinfo=UTC),
        metadata_hash,
    )


def _engine(tmp_path: Path, exchange: Exchange, intent: Intent | None = None) -> tuple[IntentExecution, IntentLedger, Intent]:
    ledger = IntentLedger(tmp_path / "intents.json")
    requested = intent or _intent()
    created = ledger.create(replace(requested, state="CREATED"))
    if requested.state != "CREATED":
        created = ledger.transition(created.client_order_id, requested.state)
    return IntentExecution(adapter=Adapter(exchange), ledger=ledger), ledger, created


def test_timeout_before_acceptance_allows_one_controlled_retry(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["timeout_before", "accepted"]
    engine, ledger, intent = _engine(tmp_path, exchange)

    result = engine.submit(intent, before_position=Decimal("0"), submit_call=exchange.place_order)

    assert result.retried is True
    assert exchange.submit_calls == 2
    assert len(exchange.fills) == 1
    assert exchange.position == 1
    assert result.fill_count == 1
    assert ledger.load()[0].state == "RECONCILED"
    assert all(count >= 2 for count in exchange.query_calls.values())


def test_timeout_after_acceptance_never_retries(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["timeout_after"]
    engine, _, intent = _engine(tmp_path, exchange)

    result = engine.submit(intent, before_position=Decimal("0"), submit_call=exchange.place_order)

    assert exchange.submit_calls == 1
    assert result.retried is False
    assert result.fill_count == 1
    assert exchange.position == 1


def test_timeout_after_acceptance_waits_through_exchange_visibility_lag(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["delayed_timeout"]
    engine, _, intent = _engine(tmp_path, exchange)

    result = engine.submit(intent, before_position=Decimal("0"), submit_call=exchange.place_order)

    assert exchange.submit_calls == 1
    assert result.retried is False
    assert result.fill_count == 1


def test_filled_without_local_acknowledgement_is_adopted(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["timeout_after"]
    with pytest.raises(TimeoutError):
        exchange.place_order()
    engine, ledger, intent = _engine(tmp_path, exchange, _intent(state="UNKNOWN"))

    result = engine.reconcile(intent, before_position=Decimal("0"), permit_absent=False)

    assert result is not None and result.filled_contracts == 1
    assert exchange.submit_calls == 1
    assert ledger.load()[0].state == "RECONCILED"


def test_partial_fill_disconnect_records_actual_and_does_not_resubmit(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["partial_timeout"]
    engine, ledger, intent = _engine(tmp_path, exchange)

    result = engine.submit(intent, before_position=Decimal("0"), submit_call=exchange.place_order)

    assert exchange.submit_calls == 1
    assert result.filled_contracts == Decimal("0.4")
    assert result.position == Decimal("0.4")
    assert ledger.load()[0].state == "PARTIALLY_FILLED"


def test_duplicate_client_id_adopts_exchange_and_cannot_create_second_intent(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["timeout_after"]
    with pytest.raises(TimeoutError):
        exchange.place_order()
    engine, ledger, intent = _engine(tmp_path, exchange, _intent(state="UNKNOWN"))

    with pytest.raises(SafetyError, match="duplicate"):
        ledger.create(_intent(transition_id="transition-2"))
    result = engine.reconcile(intent, before_position=Decimal("0"), permit_absent=False)

    assert result is not None
    assert exchange.submit_calls == 1
    assert len(ledger.load()) == 1
    assert exchange.position == 1


@pytest.mark.parametrize("behavior, terminal, position, fills", [
    ("timeout", "canceled", Decimal("0"), 0),
    ("fill", "filled", Decimal("1"), 1),
])
def test_cancellation_ack_lost_and_cancel_fill_race_are_adopted(
    tmp_path: Path,
    behavior: str,
    terminal: str,
    position: Decimal,
    fills: int,
) -> None:
    exchange = Exchange()
    exchange.order = {
        "clOrdId": CLIENT_ID,
        "ordId": "remote-1",
        "state": "live",
        "accFillSz": "0",
    }
    engine, ledger, original = _engine(tmp_path, exchange, _intent(state="OPEN", order_type="limit"))
    cancellation = ledger.create(
        _intent(
            transition_id="cancel-transition",
            client_order_id="v8xpcancel0123456789012345678",
            action="cancel",
            side="cancel",
            contracts="0",
            target=CLIENT_ID,
            order_type="cancel",
            reduce_only=True,
        )
    )
    exchange.cancel_behavior = behavior

    result = engine.cancel(
        cancellation,
        original_client_id=original.client_order_id,
        cancel_call=lambda: exchange.cancel_order(INSTRUMENT, clOrdId=CLIENT_ID),
    )

    assert exchange.cancel_calls == 1
    assert exchange.submit_calls == 0
    assert result.order is not None and result.order["state"] == terminal
    assert result.position == position
    assert result.fill_count == fills
    assert all(row.state == "RECONCILED" for row in ledger.load())


def test_process_restart_adopts_existing_position_without_submission(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["timeout_after"]
    with pytest.raises(TimeoutError):
        exchange.place_order()
    _, ledger, _ = _engine(tmp_path, exchange, _intent(state="UNKNOWN"))

    report = StartupRecovery(adapter=Adapter(exchange), ledger=ledger).run(_instrument())

    assert exchange.submit_calls == 1
    assert len(exchange.fills) == 1
    assert exchange.position == 1
    assert report["position"] == "1"
    assert report["recovered"] == 1
    assert ledger.load()[0].state == "RECONCILED"


def test_startup_blocks_changed_metadata_unknown_order_and_unknown_position(tmp_path: Path) -> None:
    exchange = Exchange()
    adapter = Adapter(exchange)
    _, ledger, _ = _engine(tmp_path, exchange)
    with pytest.raises(SafetyError, match="metadata changed"):
        StartupRecovery(adapter=adapter, ledger=ledger).run(_instrument("changed"))

    empty = IntentLedger(tmp_path / "empty.json")
    exchange.order = {
        "clOrdId": "external-order",
        "ordId": "external-1",
        "state": "live",
        "accFillSz": "0",
    }
    with pytest.raises(SafetyError, match="unknown exchange order"):
        StartupRecovery(adapter=adapter, ledger=empty).run(_instrument())

    exchange.order = None
    exchange.position = Decimal("1")
    with pytest.raises(SafetyError, match="ownership is not proven"):
        StartupRecovery(adapter=adapter, ledger=empty).run(_instrument())


def test_startup_blocks_journal_exchange_disagreements(tmp_path: Path) -> None:
    exchange = Exchange()
    adapter = Adapter(exchange)
    _, filled_ledger, _ = _engine(tmp_path, exchange, _intent(state="FILLED"))
    with pytest.raises(SafetyError, match="unresolved ambiguous"):
        StartupRecovery(adapter=adapter, ledger=filled_ledger).run(_instrument())

    flat_ledger = IntentLedger(tmp_path / "flat.json")
    flat = flat_ledger.create(_intent(target="flat", action="sell-close", side="sell", reduce_only=True))
    flat_ledger.transition(flat.client_order_id, "RECONCILED", filled_contracts="1", last_result="filled")
    exchange.order = {
        "clOrdId": CLIENT_ID,
        "ordId": "remote-1",
        "state": "filled",
        "accFillSz": "1",
    }
    exchange.fills = [{"clOrdId": CLIENT_ID, "fillId": "fill-1", "fillSz": "1"}]
    exchange.position = Decimal("1")
    with pytest.raises(SafetyError, match="journal says flat"):
        StartupRecovery(adapter=adapter, ledger=flat_ledger).run(_instrument())


def test_corrupt_and_unsupported_journals_fail_closed(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    with pytest.raises(SafetyError, match="corrupt"):
        IntentLedger(corrupt).load()

    unsupported = tmp_path / "unsupported.json"
    unsupported.write_text('[{"schema": 999}]', encoding="utf-8")
    with pytest.raises(SafetyError, match="unsupported"):
        IntentLedger(unsupported).load()


def test_duplicate_non_terminal_transition_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-transition.json"
    first = _intent()
    second = _intent(
        client_order_id="v8xpduplicate000000000000000001",
        action="sell-open",
        side="sell",
    )
    path.write_text(
        json.dumps([asdict(first), asdict(second)]),
        encoding="utf-8",
    )
    with pytest.raises(SafetyError, match="duplicate non-terminal"):
        IntentLedger(path).load()


def test_multiple_unexpected_positions_fail_closed(tmp_path: Path) -> None:
    exchange = Exchange()

    def positions(**_kwargs: Any) -> dict[str, Any]:
        return {
            "code": "0",
            "data": [
                {"instId": INSTRUMENT, "pos": "1"},
                {"instId": "OTHER-FUTURES", "pos": "1"},
            ],
        }

    exchange.get_positions = positions  # type: ignore[method-assign]
    with pytest.raises(SafetyError, match="multiple unexpected"):
        StartupRecovery(
            adapter=Adapter(exchange),
            ledger=IntentLedger(tmp_path / "empty.json"),
        ).run(_instrument())


def test_unresolved_ambiguous_submission_stops_after_one_retry(tmp_path: Path) -> None:
    exchange = Exchange()
    exchange.submit_behaviors = ["timeout_before", "timeout_before"]
    engine, ledger, intent = _engine(tmp_path, exchange)

    with pytest.raises(SafetyError, match="no further retry"):
        engine.submit(intent, before_position=Decimal("0"), submit_call=exchange.place_order)

    assert exchange.submit_calls == 2
    assert exchange.fills == []
    assert exchange.position == 0
    assert ledger.load()[0].state == "UNKNOWN"
