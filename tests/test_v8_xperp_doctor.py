import json
from datetime import UTC, datetime, timedelta

from execution.v8_xperp.doctor import inspect_runtime
from execution.v8_xperp.schedule import ScheduleConfig, SYNTHETIC_DEMO_CYCLE


ANCHOR = "2026-08-04T07:02:00Z"
NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


def config() -> ScheduleConfig:
    return ScheduleConfig(
        mode=SYNTHETIC_DEMO_CYCLE,
        synthetic_enabled=True,
        synthetic_anchor_utc=ANCHOR,
    )


def persist_schedule(root, anchor: str = "2026-08-04T07:02:00+00:00") -> None:
    (root / "schedule_mode.json").write_text(json.dumps({
        "mode": SYNTHETIC_DEMO_CYCLE,
        "synthetic_anchor_utc": anchor,
        "updated_at": "2026-08-04T06:47:34+00:00",
        "operator_acknowledgement": "test",
    }), encoding="utf-8")


def test_doctor_normalizes_equivalent_anchors_and_detects_stale_health(tmp_path) -> None:
    persist_schedule(tmp_path)
    runtime = tmp_path / SYNTHETIC_DEMO_CYCLE
    runtime.mkdir()
    (runtime / "health.json").write_text(json.dumps({
        "status": "HEALTHY", "checked_at": (NOW - timedelta(seconds=121)).isoformat(),
    }), encoding="utf-8")

    report = inspect_runtime(tmp_path, config(), now=NOW)

    assert report.anchors_match is True
    assert report.status == "STALE"
    assert report.health_age_seconds == 121
    assert "V8 health record is stale" in report.findings


def test_doctor_blocks_real_anchor_disagreement(tmp_path) -> None:
    persist_schedule(tmp_path, "2026-08-04T07:03:00+00:00")

    report = inspect_runtime(tmp_path, config(), now=NOW)

    assert report.status == "BLOCKED"
    assert report.anchors_match is False
    assert report.reason == "configured and persisted synthetic anchors disagree"


def test_doctor_reports_running_fresh_runtime(tmp_path) -> None:
    persist_schedule(tmp_path)
    runtime = tmp_path / SYNTHETIC_DEMO_CYCLE
    runtime.mkdir()
    (runtime / "health.json").write_text(json.dumps({
        "status": "HEALTHY", "checked_at": NOW.isoformat(),
    }), encoding="utf-8")
    (runtime / "canary_state.json").write_text(json.dumps({"status": "RUNNING"}), encoding="utf-8")

    report = inspect_runtime(tmp_path, config(), now=NOW)

    assert report.status == "HEALTHY"
    assert report.health_fresh is True
