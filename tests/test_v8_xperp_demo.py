import asyncio
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("v8_xperp_demo", ROOT / "tools" / "v8_xperp_demo.py")
assert SPEC and SPEC.loader
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


class FakeAdapter:
    def __init__(self):
        self.instrument = SimpleNamespace(inst_id="BTC-XPERP")
        self.preflight_report = SimpleNamespace(instrument=self.instrument, marker="stale")
        self.operational_report_value = SimpleNamespace(instrument=self.instrument, marker="fresh")
        self.operational_report_calls = 0

    @contextmanager
    def locked(self):
        yield

    def preflight(self):
        return self.preflight_report

    def startup_recovery(self, _instrument):
        return {}

    def _credentials(self):
        return "key", "secret", "passphrase"

    def operational_report(self, instrument):
        assert instrument is self.instrument
        self.operational_report_calls += 1
        return self.operational_report_value

    def margin_tiers(self, _report):
        return (object(),)

    def selected_leverage(self, _report):
        return demo.Decimal("2")

    def _position(self, _instrument):
        return demo.Decimal("0")


class FakeStream:
    state = SimpleNamespace(connected=False)

    def __init__(self, **_kwargs):
        pass

    async def run(self, _stop):
        await asyncio.sleep(3600)

    async def force_disconnect(self):
        pass


class FakeService:
    started_report = None

    def __init__(self, **_kwargs):
        self.state = SimpleNamespace(status="STOPPED", maximum_notional_observed="0")

    def start(self, *, report, **_kwargs):
        type(self).started_report = report
        self.state.status = "RUNNING"

    def stop(self):
        self.state.status = "STOPPED"


def test_canary_refreshes_market_report_after_stream_is_healthy(monkeypatch):
    adapter = FakeAdapter()
    monkeypatch.setattr(demo, "CanaryConfig", SimpleNamespace(from_env=lambda: SimpleNamespace(enabled=True)))
    monkeypatch.setattr(demo, "V8XPerpDemoAdapter", lambda: adapter)
    monkeypatch.setattr(demo, "PrivateStreamSupervisor", FakeStream)
    monkeypatch.setattr(demo, "V8XPerpCanaryService", FakeService)
    monkeypatch.setattr(demo, "_wait_stream", lambda _stream: asyncio.sleep(0))

    result = asyncio.run(demo._run_canary(one_shot=True))

    assert result["status"] == "STOPPED"
    assert adapter.operational_report_calls == 1
    assert FakeService.started_report is adapter.operational_report_value


def test_failure_health_preserves_last_verified_operational_context(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "_runtime_root", lambda: tmp_path)
    (tmp_path / "health.json").write_text(
        json.dumps(
            {
                "status": "HEALTHY",
                "monitoring": {"instrument": "BTC-XPERP", "position_contracts": "0.01"},
                "phase": {"current_phase": "long_phase"},
                "funding": {"status": "REAL_PARITY_OBSERVED"},
            }
        ),
        encoding="utf-8",
    )

    demo._write_failure_health("market-data freshness gate failed")

    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["status"] == "BLOCKED"
    assert health["reason"] == "market-data freshness gate failed"
    assert health["monitoring"]["instrument"] == "BTC-XPERP"
    assert health["phase"]["current_phase"] == "long_phase"
    assert health["funding"]["status"] == "REAL_PARITY_OBSERVED"
