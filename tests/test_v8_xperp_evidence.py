from datetime import UTC, datetime, timedelta

from execution.v8_xperp.evidence import EvidenceStore


def result(*, events=None):
    return {
        "server_time": "2026-08-02T00:00:00+00:00",
        "schedule_mode": "synthetic_demo_cycle",
        "phase": {"current_phase": "long_phase"},
        "decision": {"action": "ADOPT"},
        "funding": {"status": "REAL_PARITY_OBSERVED"},
        "monitoring": {
            "instrument": "BTC-XPERP",
            "position_contracts": "0.0156",
            "position_notional_usd": "1000.25",
            "actual_leverage": "0.01",
            "liquidation_distance_pct": "47",
            "open_futures_orders": 0,
            "non_terminal_intents": 0,
            "api_failures": 0,
            "manual_stop": False,
        },
        "operator_control": {"paused": False},
        "schedule_events": events or [],
    }


def test_completed_synthetic_cycle_creates_one_durable_report(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    end = datetime(2026, 8, 2, tzinfo=UTC)
    for offset, name in ((timedelta(days=4), "synthetic_halving"), (timedelta(days=2), "bear_transition"), (timedelta(days=1), "accumulation_transition")):
        at = end - offset
        store._append("transition", {"at": at.isoformat(), "event": {"event_type": name}})
    reports = store.due_reports(result(events=[{
        "event_type": "synthetic_halving",
        "cycle_number": 1,
        "effective_at": end.isoformat(),
    }]), now=end)

    assert len(reports) == 1
    report = reports[0]
    assert report.report_id == "v8-cycle-cycle-0000"
    assert report.path.is_file()
    assert report.payload["counts"]["transitions"] == 3
    assert "V8 completed cycle" in report.telegram_text()
    assert store.due_reports(result(), now=end + timedelta(minutes=5)) == []


def test_completed_week_and_delivery_outbox_are_idempotent(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    observed = datetime(2026, 8, 3, 1, tzinfo=UTC)
    store.record_incident(
        message="market freshness gate failed",
        category="safety_error",
        now=observed - timedelta(days=2),
    )

    reports = store.due_reports(result(), now=observed)

    assert len(reports) == 1
    report = reports[0]
    assert report.report_id == "v8-week-2026-W31"
    assert report.payload["counts"]["incidents"] == 1
    assert store.pending_reports() == [report]
    store.mark_delivered(report.report_id, now=observed)
    assert store.pending_reports() == []
    assert store.due_reports(result(), now=observed + timedelta(minutes=5)) == []
