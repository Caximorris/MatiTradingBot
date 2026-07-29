from datetime import UTC, datetime
from decimal import Decimal

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
