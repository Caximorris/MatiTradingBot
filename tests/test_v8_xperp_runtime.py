from datetime import UTC, datetime, timedelta
from decimal import Decimal

from execution.v8_xperp.adapter import Instrument, Market, PreflightReport
from execution.v8_xperp.bootstrap import BootstrapConfig, IndexPriceSample
from execution.v8_xperp.canary import CanaryConfig
from execution.v8_xperp.private_stream import StreamState
from execution.v8_xperp.service import CanaryRuntimeState
from execution.v8_xperp.runtime import V8OperationalController, request_operator_flat


SERVER = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
TRANSITION = datetime(2024, 4, 20, 0, 9, 27, tzinfo=UTC) + timedelta(days=540)


def report() -> PreflightReport:
    instrument = Instrument(
        "BTC-XPERP", "BTC-FAMILY", "BTC-USD", "USDC", "linear",
        Decimal("1"), "BTC", Decimal("0.0001"), Decimal("0.0001"),
        Decimal("0.1"), Decimal("10"), datetime(2031, 1, 1, tzinfo=UTC), "meta",
    )
    market = Market(
        Decimal("64999"), Decimal("65000"), Decimal("65000"),
        SERVER - timedelta(seconds=1), Decimal("0.15"), Decimal("0.075"),
    )
    return PreflightReport(
        "okx_demo", "https://eea.okx.com", instrument, Decimal("100000"),
        True, "2", "net_mode", market, SERVER - timedelta(seconds=1),
    )


class Account:
    def __init__(self, adapter):
        self.adapter = adapter

    def get_positions(self, **_kwargs):
        if self.adapter.position == 0:
            return {"code": "0", "data": []}
        return {"code": "0", "data": [{
            "pos": str(self.adapter.position),
            "notionalUsd": str(abs(self.adapter.position) * Decimal("65000")),
            "markPx": "65000",
        }]}

    @staticmethod
    def get_account_bills(**_kwargs):
        return {"code": "0", "data": []}


class Public:
    @staticmethod
    def get_funding_rate(_instrument):
        return {"code": "0", "data": [{
            "fundingTime": str(int((SERVER + timedelta(hours=4)).timestamp() * 1000)),
            "fundingRate": "0.0001",
        }]}

    @staticmethod
    def funding_rate_history(_instrument, *, limit):
        assert limit == "100"
        return {"code": "0", "data": []}


class Trade:
    @staticmethod
    def get_order_list(**_kwargs):
        return {"code": "0", "data": []}


class Adapter:
    def __init__(self, tmp_path):
        self.runtime_root = tmp_path
        self.intent_path = tmp_path / "intents.json"
        self.account_hash = "account"
        self.position = Decimal("0")
        self.account = Account(self)
        self.public = Public()
        self.trade = Trade()

    @staticmethod
    def selected_leverage(_report):
        return Decimal("2")

    @staticmethod
    def margin_tiers(_report):
        return (object(),)

    def _position(self, _instrument):
        return self.position

    @staticmethod
    def _ok(payload, _label):
        return payload["data"]


class Service:
    def __init__(self, adapter):
        self.adapter = adapter
        self.executions = []
        self.tiers = (object(),)
        self.leverage = Decimal("2")
        self.stream = type("Stream", (), {"state": StreamState(
            connected=True, subscribed=True, stale=False, reconnects=0,
            last_event_at=SERVER,
        )})()
        self.state = CanaryRuntimeState(status="RUNNING")

    def refresh(self, **_kwargs):
        return None

    def execute_capped_target(self, capped, *, transition_id, eligible_equity):
        self.executions.append((transition_id, capped, eligible_equity))
        self.adapter.position = capped.signed_contracts


class Source:
    def __init__(self):
        self.calls = 0

    def reference_after(self, transition_at, *, retrieved_at):
        self.calls += 1
        assert transition_at == TRANSITION
        return IndexPriceSample(
            "okx_eea_btc_usd_index", "BTC-USD",
            TRANSITION + timedelta(minutes=51), Decimal("109765.4"),
            retrieved_at, "a" * 64,
        )

    def current(self, *, verified_server_time, maximum_age_seconds):
        self.calls += 1
        return IndexPriceSample(
            "okx_eea_btc_usd_index", "BTC-USD",
            verified_server_time - timedelta(seconds=1), Decimal("65000"),
            verified_server_time, "b" * 64,
        )


class BelowMinimumSource(Source):
    def current(self, *, verified_server_time, maximum_age_seconds):
        self.calls += 1
        return IndexPriceSample(
            "okx_eea_btc_usd_index", "BTC-USD",
            verified_server_time - timedelta(seconds=1), Decimal("58000"),
            verified_server_time, "c" * 64,
        )


def canary_config():
    return CanaryConfig.from_env({"V8_XPERP_CONTINUOUS_DEMO_ENABLED": "true"})


def test_execute_bootstrap_once_then_restart_adopts_without_recalculation(tmp_path) -> None:
    adapter = Adapter(tmp_path)
    service = Service(adapter)
    source = Source()
    controller = V8OperationalController(
        adapter=adapter, service=service, index_source=source,
        canary_config=canary_config(), bootstrap_config=BootstrapConfig(),
    )
    first = controller.cycle(
        report=report(), server_time=SERVER,
        clock_drift_seconds=Decimal("0"), execute=True,
    )
    assert first["decision"]["action"] == "EXECUTE"
    assert len(service.executions) == 1
    assert abs(adapter.position) * Decimal("65000") <= 1000
    assert first["funding"]["status"] == "PENDING_REAL_PARITY"

    class NoRecalculate(Source):
        def reference_after(self, *_args, **_kwargs):
            raise AssertionError("restart recalculated bootstrap")

        def current(self, **_kwargs):
            raise AssertionError("restart recalculated bootstrap")

    restarted = V8OperationalController(
        adapter=adapter, service=service, index_source=NoRecalculate(),
        canary_config=canary_config(), bootstrap_config=BootstrapConfig(),
    )
    second = restarted.cycle(
        report=report(), server_time=SERVER + timedelta(minutes=1),
        clock_drift_seconds=Decimal("0"), execute=True,
    )
    assert second["decision"]["action"] == "ADOPT"
    assert len(service.executions) == 1


def test_preactivation_calculation_does_not_persist_or_submit(tmp_path) -> None:
    adapter = Adapter(tmp_path)
    service = Service(adapter)
    controller = V8OperationalController(
        adapter=adapter, service=service, index_source=Source(),
        canary_config=canary_config(), bootstrap_config=BootstrapConfig(),
    )
    result = controller.cycle(
        report=report(), server_time=SERVER,
        clock_drift_seconds=Decimal("0"), execute=False,
    )
    assert result["phase"]["direction"] == "short"
    assert Decimal(result["bootstrap"]["calculated_leverage"]) < 2
    assert Decimal(result["capped"]["allowed_notional"]) <= 1000
    assert service.executions == []
    assert controller.bootstrap_ledger.load() == []
    assert controller.target_ledger.load() == []


def test_operator_flat_request_is_consumed_only_after_flat_execution(tmp_path) -> None:
    adapter = Adapter(tmp_path)
    adapter.position = Decimal("-0.01")
    service = Service(adapter)
    controller = V8OperationalController(
        adapter=adapter, service=service, index_source=Source(),
        canary_config=canary_config(), bootstrap_config=BootstrapConfig(),
    )
    request_operator_flat(tmp_path)
    assert controller.operator_flat_path.exists()
    result = controller.cycle(
        report=report(), server_time=SERVER,
        clock_drift_seconds=Decimal("0"), execute=True,
    )
    assert result["decision"]["reason"] == "explicit operator flat"
    assert adapter.position == 0
    assert not controller.operator_flat_path.exists()


def test_below_minimum_bootstrap_persists_flat_without_target_order(tmp_path) -> None:
    adapter = Adapter(tmp_path)
    service = Service(adapter)
    controller = V8OperationalController(
        adapter=adapter, service=service, index_source=BelowMinimumSource(),
        canary_config=canary_config(), bootstrap_config=BootstrapConfig(),
    )
    result = controller.cycle(
        report=report(), server_time=SERVER,
        clock_drift_seconds=Decimal("0"), execute=True,
    )
    assert result["bootstrap"]["enter"] is False
    assert result["decision"]["action"] == "NOOP"
    assert result["decision"]["target"]["state"] == "FLAT"
    assert controller.bootstrap_ledger.load()[0].state == "FLAT"
    assert controller.target_ledger.load() == []
    assert service.executions == []
