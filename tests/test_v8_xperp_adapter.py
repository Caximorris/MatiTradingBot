from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from execution.v8_xperp.adapter import (
    Instrument,
    Market,
    PreflightReport,
    SafetyError,
    V8XPerpDemoAdapter,
    _ProcessLock,
)
from execution.v8_xperp.private_stream import DEMO_PRIVATE_WS, LIVE_PRIVATE_WS, PrivateStreamSupervisor
from execution.v8_xperp.intents import Intent, IntentLedger


def _report() -> PreflightReport:
    instrument = Instrument("BTC-USD_UM_XPERP-test", "BTC-USD_UM_XPERP", "BTC-USD", "USDC", "linear",
                            Decimal("1"), "BTC", Decimal("0.0001"), Decimal("0.0001"), Decimal("0.1"),
                            Decimal("10"), datetime(2031, 3, 28, tzinfo=UTC), "metadata")
    market = Market(Decimal("100"), Decimal("101"), Decimal("100"), datetime.now(UTC), Decimal("99.5"), Decimal("49.75"))
    return PreflightReport("okx_demo", "https://eea.okx.com", instrument, Decimal("100000"), True, "2", "net_mode", market, datetime.now(UTC))


def test_client_id_is_deterministic_for_one_persisted_transition() -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    report = _report()
    first = adapter._client_id(instrument=report.instrument, action="buy-open", transition_at="2026-01-01T00:00:00+00:00")
    second = adapter._client_id(instrument=report.instrument, action="buy-open", transition_at="2026-01-01T00:00:00+00:00")
    assert first == second
    assert first.startswith("v8xp") and len(first) <= 32


def test_target_quantizes_down_and_never_exceeds_requested_leverage() -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    result = adapter.calculate_target(_report(), "long 2x")
    assert result.quantized_contract_qty == Decimal("1900.0000")
    assert result.actual_leverage <= Decimal("2")
    assert result.remaining_available_margin > 0


def test_unknown_target_is_rejected() -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    with pytest.raises(ValueError, match="target must"):
        adapter.calculate_target(_report(), "long 3x")


def test_reduce_only_refuses_flat_position() -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    adapter._position = lambda _instrument: Decimal("0")
    with pytest.raises(SafetyError, match="while flat"):
        adapter.place_minimum(_report(), side="sell", reduce_only=True)


def test_private_stream_deduplicates_updates_and_stales_on_malformed_event() -> None:
    seen: list[dict] = []
    stream = PrivateStreamSupervisor(api_key="key", secret="secret", passphrase="pass", instrument_id="inst",
                                     reconcile=lambda: None, on_event=seen.append)
    for index, subscription in enumerate(stream.subscriptions()):
        accepted = stream.accept({"event": "subscribe", "arg": subscription})
        assert accepted is (index == len(stream.subscriptions()) - 1)
    assert stream.accept({"event": "channel-conn-count", "channel-conn-count": "1"})
    event = {"arg": {"channel": "orders"}, "data": [{"ordId": "1", "uTime": "2"}]}
    assert stream.accept(event)
    assert stream.accept(event)
    assert len(seen) == 1
    assert not stream.accept({"bad": "event"})
    with pytest.raises(SafetyError, match="stale"):
        stream.assert_healthy()


def test_private_stream_server_heartbeat_preserves_reconciled_health() -> None:
    stream = PrivateStreamSupervisor(
        api_key="key", secret="secret", passphrase="pass", instrument_id="inst",
        reconcile=lambda: None,
    )
    for subscription in stream.subscriptions():
        stream.accept({"event": "subscribe", "arg": subscription})
    stream.accept_heartbeat()
    stream.assert_healthy()
    assert stream.state.last_event_at is not None


def test_private_stream_rejects_cross_environment_or_manual_endpoint() -> None:
    args = dict(api_key="key", secret="secret", passphrase="pass", instrument_id="inst", reconcile=lambda: None)
    assert PrivateStreamSupervisor(**args).url == DEMO_PRIVATE_WS
    with pytest.raises(SafetyError, match="allowlist"):
        PrivateStreamSupervisor(**args, url=LIVE_PRIVATE_WS)
    with pytest.raises(SafetyError, match="live private"):
        PrivateStreamSupervisor(**args, environment="okx_live")


def test_private_stream_blocks_until_all_subscriptions_and_rest_agree() -> None:
    def disagree() -> None:
        raise SafetyError("REST and WebSocket disagree")

    stream = PrivateStreamSupervisor(
        api_key="key",
        secret="secret",
        passphrase="pass",
        instrument_id="inst",
        reconcile=disagree,
    )
    for subscription in stream.subscriptions():
        stream.accept({"event": "subscribe", "arg": subscription})
    with pytest.raises(SafetyError, match="stale"):
        stream.assert_healthy()


def test_process_lock_rejects_second_owner_and_releases(tmp_path) -> None:
    path = tmp_path / "executor.lock"
    with _ProcessLock(path):
        with pytest.raises(SafetyError, match="owns the process lock"):
            with _ProcessLock(path):
                pass
    with _ProcessLock(path):
        pass


def test_reversal_closes_then_opens_opposite_with_separate_order_calls() -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    report = _report()
    positions = iter([report.instrument.min_sz, Decimal("0"), -report.instrument.min_sz])
    adapter._position = lambda _instrument: next(positions)
    calls: list[tuple[str, bool]] = []

    def place(_report, *, side: str, reduce_only: bool):
        calls.append((side, reduce_only))
        return f"id-{len(calls)}", {"state": "filled"}

    adapter.place_minimum = place
    result = adapter.reverse_minimum(report)

    assert calls == [("sell", True), ("sell", False)]
    assert result["position"] == str(-report.instrument.min_sz)


def test_emergency_flatten_cancels_known_order_even_when_position_is_flat(tmp_path) -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    adapter._lock_depth = 1
    adapter._startup_recovered = True
    adapter._discover = lambda: _report().instrument
    adapter.intent_path = tmp_path / "intents.json"
    client_id = "v8xpknown000000000000000000001"
    IntentLedger(adapter.intent_path).create(Intent(
        "transition", client_id, _report().instrument.inst_id, "long", "buy-open",
        "buy", "0.0001", False, "limit", metadata_hash="metadata",
    ))
    open_orders = [[{"clOrdId": client_id, "reduceOnly": "false"}], []]

    class Account:
        @staticmethod
        def get_positions(**_kwargs):
            return {"code": "0", "data": []}

    class Trade:
        @staticmethod
        def get_order_list(**_kwargs):
            return {"code": "0", "data": open_orders.pop(0)}

    adapter.account = Account()
    adapter.trade = Trade()
    adapter._position = lambda _instrument: Decimal("0")
    canceled: list[str] = []
    adapter.cancel_v8_order = lambda _report, value: canceled.append(value)
    events: list[str] = []
    adapter._append = lambda event, _payload: events.append(event)

    result = adapter.emergency_flatten(_report())

    assert canceled == [client_id]
    assert result == {"status": "already_flat", "canceled_orders": 1}
    assert events == ["incident_started", "incident_resolved"]


def test_emergency_flatten_never_mutates_unknown_order_or_multiple_positions(tmp_path) -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    adapter._lock_depth = 1
    adapter._startup_recovered = True
    adapter._discover = lambda: _report().instrument
    adapter.intent_path = tmp_path / "intents.json"
    adapter._append = lambda *_args: None
    mutations: list[str] = []
    adapter.cancel_v8_order = lambda *_args: mutations.append("cancel")

    class Trade:
        @staticmethod
        def get_order_list(**_kwargs):
            return {"code": "0", "data": [{"clOrdId": "external"}]}

    class Account:
        rows = [{"instId": _report().instrument.inst_id, "pos": "1"}]

        @classmethod
        def get_positions(cls, **_kwargs):
            return {"code": "0", "data": cls.rows}

    adapter.trade, adapter.account = Trade(), Account()
    with pytest.raises(SafetyError, match="unknown FUTURES order"):
        adapter.emergency_flatten(_report())
    assert mutations == []

    Account.rows = [
        {"instId": _report().instrument.inst_id, "pos": "1"},
        {"instId": "OTHER", "pos": "1"},
    ]
    with pytest.raises(SafetyError, match="multiple"):
        adapter.emergency_flatten(_report())
    assert mutations == []


def test_emergency_flatten_uses_post_cancel_partial_position_and_records_incident(tmp_path) -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    adapter._lock_depth = 1
    adapter._startup_recovered = True
    adapter.intent_path = tmp_path / "intents.json"
    adapter._discover = lambda: _report().instrument
    adapter.cancel_known_pending = lambda _report: 1
    positions = iter([Decimal("0.4")])
    adapter._position = lambda _instrument: next(positions)
    events: list[str] = []
    adapter._append = lambda event, _payload: events.append(event)
    captured: dict[str, object] = {}

    class Account:
        calls = 0

        @classmethod
        def get_positions(cls, **_kwargs):
            cls.calls += 1
            return {
                "code": "0",
                "data": (
                    [{"instId": _report().instrument.inst_id, "pos": "0.4"}]
                    if cls.calls == 1
                    else []
                ),
            }

    class Trade:
        @staticmethod
        def get_order_list(**_kwargs):
            return {"code": "0", "data": []}

    def create_intent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(client_order_id="v8xppartial0000000000000000001")

    class Execution:
        @staticmethod
        def submit_order(_intent, *, before_position):
            assert before_position == Decimal("0.4")
            return SimpleNamespace(order={"state": "filled"}, position=Decimal("0"))

    adapter.account, adapter.trade = Account(), Trade()
    adapter._create_intent = create_intent
    adapter._intent_execution = lambda: Execution()

    result = adapter.emergency_flatten(_report())

    assert captured["contracts"] == Decimal("0.4")
    assert captured["reduce_only"] is True
    assert result["status"] == "flat"
    assert events == ["incident_started", "incident_order", "incident_resolved"]


def test_emergency_flatten_blocks_metadata_change_before_mutation(tmp_path) -> None:
    adapter = object.__new__(V8XPerpDemoAdapter)
    adapter._lock_depth = 1
    adapter._startup_recovered = True
    adapter.intent_path = tmp_path / "intents.json"
    changed = _report().instrument
    adapter._discover = lambda: type(changed)(
        changed.inst_id, changed.inst_family, changed.uly, changed.settle_ccy,
        changed.ct_type, changed.ct_val, changed.ct_val_ccy, changed.lot_sz,
        changed.min_sz, changed.tick_sz, changed.lever, changed.exp_time, "changed",
    )
    events: list[str] = []
    adapter._append = lambda event, _payload: events.append(event)
    with pytest.raises(SafetyError, match="metadata changed"):
        adapter.emergency_flatten(_report())
    assert events == ["incident_started", "incident_failed"]


def test_injected_rest_clients_require_explicit_test_gate(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OKX_XPERP_DEMO_API_KEY", "demo-key")
    monkeypatch.setenv("OKX_XPERP_DEMO_SECRET_KEY", "demo-secret")
    monkeypatch.setenv("OKX_XPERP_DEMO_PASSPHRASE", "demo-pass")
    with pytest.raises(SafetyError, match="test-only"):
        V8XPerpDemoAdapter(runtime_root=tmp_path, account=object())
    adapter = V8XPerpDemoAdapter(
        runtime_root=tmp_path,
        account=object(),
        allow_test_clients=True,
    )
    assert adapter.account is not None


def test_account_lock_identity_is_independent_of_runtime_root(monkeypatch, tmp_path) -> None:
    # CI deliberately has no Demo credentials.  This test exercises only the
    # account-derived lock identity, so use inert values rather than a local .env.
    monkeypatch.setenv("OKX_XPERP_DEMO_API_KEY", "lock-test-key")
    monkeypatch.setenv("OKX_XPERP_DEMO_SECRET_KEY", "lock-test-secret")
    monkeypatch.setenv("OKX_XPERP_DEMO_PASSPHRASE", "lock-test-pass")
    first = V8XPerpDemoAdapter(runtime_root=tmp_path / "one")
    second = V8XPerpDemoAdapter(runtime_root=tmp_path / "two")
    assert first._account_lock_path == second._account_lock_path
    with first.locked():
        with pytest.raises(SafetyError, match="owns the process lock"):
            with second.locked():
                pass
