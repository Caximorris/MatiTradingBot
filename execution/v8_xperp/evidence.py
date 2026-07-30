"""Durable V8 forward-test evidence, cycle reports, and weekly reports."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .adapter import SafetyError
from .schedule import SYNTHETIC_DEMO_CYCLE

SCHEMA = 1
OBSERVATION_SECONDS = 300


@dataclass(frozen=True)
class EvidenceReport:
    report_id: str
    path: Path
    payload: dict[str, Any]

    def telegram_text(self) -> str:
        current = self.payload["current"]
        monitoring = current.get("monitoring") or {}
        funding = current.get("funding") or {}
        try:
            notional = f"${float(monitoring.get('position_notional_usd', 0)):,.2f}"
        except (TypeError, ValueError):
            notional = "unknown"
        title = "🔁 V8 completed cycle" if self.payload["kind"] == "cycle" else "📅 V8 weekly evidence"
        return "\n".join((
            f"<b>{title} · {self.payload['key']}</b>",
            f"Window: <code>{self.payload['window']['start']} → {self.payload['window']['end']}</code>",
            f"Position: <b>{notional}</b> · "
            f"{monitoring.get('position_contracts', 'unknown')} contracts",
            f"Funding: <b>{funding.get('status', 'unknown')}</b>",
            f"Evidence: {self.payload['counts']['observations']} observations · "
            f"{self.payload['counts']['transitions']} transitions · "
            f"{self.payload['counts']['incidents']} incidents",
            f"Saved: <code>{self.path.name}</code>",
        ))


class EvidenceStore:
    """Append-only operational evidence with idempotent report artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root / "evidence"
        self.events_path = self.root / "events.jsonl"
        self.observation_path = self.root / "observation_state.json"
        self.delivery_path = self.root / "delivery.json"
        self.cycles_dir = self.root / "reports" / "cycles"
        self.weeks_dir = self.root / "reports" / "weeks"

    def record_incident(self, *, message: str, category: str, now: datetime | None = None) -> None:
        observed = (now or datetime.now(UTC)).astimezone(UTC)
        self._append("incident", {
            "at": observed.isoformat(),
            "category": category,
            "message": message[:500],
        })

    def observe(self, result: dict[str, Any], *, now: datetime) -> None:
        observed = now.astimezone(UTC)
        bucket = int(observed.timestamp()) // OBSERVATION_SECONDS
        previous = self._load_json(self.observation_path, default={})
        if previous.get("bucket") == bucket:
            return
        self._append("observation", {
            "at": observed.isoformat(),
            "status": "HEALTHY",
            "monitoring": _monitoring_summary(result),
            "funding_status": (result.get("funding") or {}).get("status"),
            "phase": (result.get("phase") or {}).get("current_phase"),
        })
        _atomic_json(self.observation_path, {"bucket": bucket, "at": observed.isoformat()})

    def due_reports(self, result: dict[str, Any], *, now: datetime) -> list[EvidenceReport]:
        observed = now.astimezone(UTC)
        self.observe(result, now=observed)
        for event in result.get("schedule_events", []):
            if isinstance(event, dict):
                self._append("transition", {"at": observed.isoformat(), "event": event})
        reports: list[EvidenceReport] = []
        for event in result.get("schedule_events", []):
            if not isinstance(event, dict):
                continue
            if (
                result.get("schedule_mode") == SYNTHETIC_DEMO_CYCLE
                and event.get("event_type") == "synthetic_halving"
                and int(event.get("cycle_number", 0)) > 0
            ):
                cycle = int(event["cycle_number"]) - 1
                end = datetime.fromisoformat(str(event["effective_at"])).astimezone(UTC)
                report = self._write_report(
                    kind="cycle",
                    key=f"cycle-{cycle:04d}",
                    destination=self.cycles_dir / f"cycle-{cycle:04d}.json",
                    start=end - timedelta(days=4),
                    end=end,
                    result=result,
                )
                if report is not None:
                    reports.append(report)
        week_end = observed.date() - timedelta(days=observed.weekday())
        week_start = week_end - timedelta(days=7)
        if self._events_between(
            datetime.combine(week_start, datetime.min.time(), UTC),
            datetime.combine(week_end, datetime.min.time(), UTC),
        ):
            key = f"{week_start.isocalendar().year}-W{week_start.isocalendar().week:02d}"
            report = self._write_report(
                kind="week",
                key=key,
                destination=self.weeks_dir / f"{key}.json",
                start=datetime.combine(week_start, datetime.min.time(), UTC),
                end=datetime.combine(week_end, datetime.min.time(), UTC),
                result=result,
            )
            if report is not None:
                reports.append(report)
        return reports

    def pending_reports(self) -> list[EvidenceReport]:
        delivered = self._load_json(self.delivery_path, default={})
        reports: list[EvidenceReport] = []
        for directory in (self.cycles_dir, self.weeks_dir):
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                payload = self._load_json(path, default=None)
                if not isinstance(payload, dict):
                    raise SafetyError("corrupt V8 evidence report")
                report_id = str(payload.get("report_id", ""))
                if not report_id:
                    raise SafetyError("V8 evidence report has no identity")
                if report_id not in delivered:
                    reports.append(EvidenceReport(report_id, path, payload))
        return reports

    def mark_delivered(self, report_id: str, *, now: datetime) -> None:
        delivered = self._load_json(self.delivery_path, default={})
        delivered[report_id] = now.astimezone(UTC).isoformat()
        _atomic_json(self.delivery_path, delivered)

    def _write_report(
        self,
        *,
        kind: str,
        key: str,
        destination: Path,
        start: datetime,
        end: datetime,
        result: dict[str, Any],
    ) -> EvidenceReport | None:
        if destination.exists():
            return None
        events = self._events_between(start, end)
        counts = {
            "observations": sum(item["event"] == "observation" for item in events),
            "transitions": sum(item["event"] == "transition" for item in events),
            "incidents": sum(item["event"] == "incident" for item in events),
        }
        payload = {
            "schema": SCHEMA,
            "report_id": f"v8-{kind}-{key}",
            "kind": kind,
            "key": key,
            "generated_at": datetime.now(UTC).isoformat(),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "counts": counts,
            "events": events,
            "current": _result_summary(result),
        }
        _atomic_json(destination, payload)
        self._append("report_created", {
            "at": datetime.now(UTC).isoformat(),
            "report_id": payload["report_id"],
            "path": str(destination.relative_to(self.root)),
        })
        return EvidenceReport(str(payload["report_id"]), destination, payload)

    def _events_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                at = datetime.fromisoformat(str(item["payload"]["at"])).astimezone(UTC)
            except Exception as exc:
                raise SafetyError("corrupt V8 evidence event ledger") from exc
            if start <= at < end:
                events.append(item)
        return events

    def _append(self, event: str, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record = {"schema": SCHEMA, "event": event, "payload": payload}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _load_json(path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SafetyError("corrupt V8 evidence state") from exc


def _monitoring_summary(result: dict[str, Any]) -> dict[str, Any]:
    monitoring = result.get("monitoring") or {}
    return {
        key: monitoring.get(key)
        for key in (
            "instrument", "position_contracts", "position_notional_usd",
            "actual_leverage", "liquidation_distance_pct", "open_futures_orders",
            "non_terminal_intents", "api_failures", "manual_stop",
        )
    }


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "server_time": result.get("server_time"),
        "schedule_mode": result.get("schedule_mode"),
        "phase": result.get("phase"),
        "decision": result.get("decision"),
        "funding": result.get("funding"),
        "monitoring": _monitoring_summary(result),
        "operator_control": result.get("operator_control"),
    }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
