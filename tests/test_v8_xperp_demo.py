import asyncio
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from execution.v8_xperp.evidence import EvidenceStore
from execution.v8_xperp.funding import FundingLedger, make_expectation


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


def test_funding_failure_health_overrides_historical_parity(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "_runtime_root", lambda: tmp_path)
    ledger = FundingLedger(tmp_path / "funding.json")
    record = ledger.create(make_expectation(
        environment="okx_demo",
        account_hash="account",
        instrument_id="BTC-XPERP",
        settlement_ms=1_800_000_000_000,
        side="long",
        contracts=demo.Decimal("0.01"),
        position_notional=demo.Decimal("1000"),
        signed_rate=demo.Decimal("0.0001"),
        metadata_hash="metadata",
        rate_source_hash="rate",
        position_source_hash="position",
        mark_source_hash="mark",
    ))
    ledger.update(
        record.identity,
        state="AMOUNT_MISMATCH",
        actual_amount="-0.2",
        bill_id="bill-1",
    )

    demo._write_failure_health("funding reconciliation failed closed: AMOUNT_MISMATCH")

    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["funding"] == {
        "status": "FAILED_AMOUNT_MISMATCH",
        "settlement_ms": 1_800_000_000_000,
        "expected_amount": "-0.1000",
        "actual_amount": "-0.2",
        "bill_id": "bill-1",
    }


def test_evidence_delivery_records_receipt_only_after_telegram_ack(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    report_path = store.cycles_dir / "cycle-0000.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
        "report_id": "v8-cycle-cycle-0000",
        "kind": "cycle",
        "key": "cycle-0000",
        "window": {"start": "2026-07-29T00:00:00+00:00", "end": "2026-08-02T00:00:00+00:00"},
        "counts": {"observations": 1, "transitions": 3, "incidents": 0},
        "current": {"monitoring": {"position_notional_usd": "1000", "position_contracts": "0.0156"}, "funding": {"status": "PASS"}},
    }), encoding="utf-8")
    monkeypatch.setattr(demo.TelegramConfig, "from_env", lambda: SimpleNamespace(
        enabled=True, token="test-token", allowed_chat_ids=frozenset({42}),
    ))
    sent = []

    class Response:
        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(demo.urllib.request, "urlopen", lambda request, timeout: sent.append((request, timeout)) or Response())

    demo._deliver_evidence_reports(store)

    assert len(sent) == 1
    assert store.pending_reports() == []
