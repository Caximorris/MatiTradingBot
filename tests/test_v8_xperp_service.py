from datetime import UTC, datetime
from decimal import Decimal

import pytest

from execution.v8_xperp.adapter import Instrument, Market, PreflightReport, SafetyError
from execution.v8_xperp.canary import CanaryConfig
from execution.v8_xperp.intents import IntentLedger
from execution.v8_xperp.margins import parse_margin_tiers
from execution.v8_xperp.service import CanaryStateStore, V8XPerpCanaryService


def config(enabled: bool = True) -> CanaryConfig:
    return CanaryConfig.from_env({
        "V8_XPERP_CONTINUOUS_DEMO_ENABLED": str(enabled).lower(),
    })


def report() -> PreflightReport:
    inst = Instrument(
        "BTC-XPERP", "BTC-XPERP-FAMILY", "BTC-USD", "USDC", "linear",
        Decimal("1"), "BTC", Decimal("0.0001"), Decimal("0.0001"),
        Decimal("0.1"), Decimal("10"), datetime(2031, 1, 1, tzinfo=UTC), "hash",
    )
    market = Market(
        Decimal("64999.9"), Decimal("65000"), Decimal("65000"),
        datetime.now(UTC), Decimal("0.015"), Decimal("0.01"),
    )
    return PreflightReport(
        "okx_demo", "https://eea.okx.com", inst, Decimal("100000"),
        True, "2", "net_mode", market, datetime.now(UTC),
    )


def tiers():
    return parse_margin_tiers([{
        "tier": "1", "instFamily": "BTC-XPERP-FAMILY", "uly": "BTC-USD",
        "minSz": "0", "maxSz": "4000", "maxLever": "10",
        "imr": "0.1", "mmr": "0.004",
    }], instrument=report().instrument)


class Stream:
    healthy = True

    def assert_healthy(self):
        if not self.healthy:
            raise SafetyError("stream stale")


class Adapter:
    def __init__(self, tmp_path):
        self.runtime_root = tmp_path
        self.intent_path = tmp_path / "intents.json"
        self._lock_depth = 1
        self._startup_recovered = True
        self.position = Decimal("0")
        self.calls = []

    def _assert_lock_held(self):
        if self._lock_depth != 1:
            raise SafetyError("lock")

    def _assert_recovered(self):
        if not self._startup_recovered:
            raise SafetyError("recovery")

    def _position(self, _instrument):
        return self.position

    def place_market(self, _report, *, side, contracts, reduce_only, target):
        self.calls.append((side, contracts, reduce_only, target))
        self.position += contracts if side == "buy" else -contracts
        return "id", {"state": "filled"}

    def emergency_flatten(self, _report):
        self.position = Decimal("0")

    def cancel_known_pending(self, _report):
        self.calls.append(("cancel", Decimal("0"), True, "known"))
        return 0


def service(tmp_path, *, enabled=True):
    adapter = Adapter(tmp_path)
    state = CanaryStateStore(tmp_path / "state.json")
    svc = V8XPerpCanaryService(adapter=adapter, config=config(enabled), state_store=state)
    return svc, adapter


def test_disabled_or_stale_service_cannot_start(tmp_path) -> None:
    svc, _ = service(tmp_path, enabled=False)
    with pytest.raises(SafetyError, match="disabled"):
        svc.start(report=report(), tiers=tiers(), authenticated_leverage=Decimal("2"), stream=Stream())
    svc, _ = service(tmp_path / "stale")
    stream = Stream()
    stream.healthy = False
    with pytest.raises(SafetyError, match="stale"):
        svc.start(report=report(), tiers=tiers(), authenticated_leverage=Decimal("2"), stream=stream)


def test_lifecycle_caps_long_two_x_and_closes_reduce_only(tmp_path) -> None:
    svc, adapter = service(tmp_path)
    svc.start(report=report(), tiers=tiers(), authenticated_leverage=Decimal("2"), stream=Stream())
    opened = svc.execute_target("long 2x")
    assert opened.allowed_notional <= Decimal("1000")
    assert adapter.position == Decimal("0.0153")
    closed = svc.execute_target("flat")
    assert closed.signed_contracts == 0
    assert adapter.position == 0
    assert adapter.calls == [
        ("buy", Decimal("0.0153"), False, "long 2x"),
        ("sell", Decimal("0.0153"), True, "flat"),
    ]
    svc.stop()
    assert CanaryStateStore(tmp_path / "state.json").load().status == "STOPPED"


def test_loss_events_are_exact_once_and_limits_latch(tmp_path) -> None:
    svc, _ = service(tmp_path)
    svc.record_loss(event_id="bill-1", amount=Decimal("-10"))
    svc.record_loss(event_id="bill-1", amount=Decimal("-10"))
    assert svc.state.daily_loss == "10"
    with pytest.raises(SafetyError, match="loss"):
        svc.record_loss(event_id="bill-2", amount=Decimal("-15"))
    restarted = V8XPerpCanaryService(
        adapter=Adapter(tmp_path),
        config=config(),
        state_store=CanaryStateStore(tmp_path / "state.json"),
    )
    assert restarted.state.daily_loss == "25"
    assert len(restarted.state.loss_event_ids) == 2


def test_nonterminal_intent_and_leverage_above_two_block_start(tmp_path) -> None:
    svc, adapter = service(tmp_path)
    from execution.v8_xperp.intents import Intent

    IntentLedger(adapter.intent_path).create(Intent(
        "t", "v8xp123", report().instrument.inst_id, "long", "buy-open",
        "buy", "0.0001", False, "market",
    ))
    with pytest.raises(SafetyError, match="non-terminal"):
        svc.start(report=report(), tiers=tiers(), authenticated_leverage=Decimal("2"), stream=Stream())
    svc, _ = service(tmp_path / "lever")
    with pytest.raises(SafetyError, match="leverage"):
        svc.start(report=report(), tiers=tiers(), authenticated_leverage=Decimal("3"), stream=Stream())


def test_kill_switch_actions_mutate_only_known_state(tmp_path) -> None:
    svc, adapter = service(tmp_path)
    svc.start(report=report(), tiers=tiers(), authenticated_leverage=Decimal("2"), stream=Stream())
    assert svc.apply_kill_switch("stale_market").value == "block_cancel_known"
    assert adapter.calls[-1][0] == "cancel"

    svc, adapter = service(tmp_path / "unknown")
    svc.start(report=report(), tiers=tiers(), authenticated_leverage=Decimal("2"), stream=Stream())
    adapter.position = Decimal("1")
    assert svc.apply_kill_switch("unknown_position").value == "block_no_mutation_manual"
    assert adapter.position == 1
