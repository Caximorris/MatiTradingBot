"""Immutable, versioned funding-series coverage declarations.

This module deliberately contains no network client.  Adding a declaration is a
reviewed source change; a backtest can only use the declarations already present
in its checkout.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Mapping


class CoverageEvidenceError(ValueError):
    """A coverage declaration is absent, malformed, or applies to another feed."""


@dataclass(frozen=True)
class FundingCoverageEvidence:
    source: str
    instrument: str
    venue: str
    series_start: datetime
    snapshot_identity: str
    content_sha256: str
    generated_at: datetime
    validity_rule: str

    def validate(self, instrument: str, venue: str) -> None:
        if self.instrument != instrument:
            raise CoverageEvidenceError(
                f"coverage evidence instrument mismatch: {self.instrument} != {instrument}"
            )
        if self.venue != venue:
            raise CoverageEvidenceError(
                f"coverage evidence venue mismatch: {self.venue} != {venue}"
            )
        if not all((self.source, self.snapshot_identity, self.validity_rule)):
            raise CoverageEvidenceError("coverage evidence has an empty required identity field")
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise CoverageEvidenceError("coverage evidence content hash is not SHA-256")
        for value, name in ((self.series_start, "series_start"), (self.generated_at, "generated_at")):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise CoverageEvidenceError(f"coverage evidence {name} must be UTC")
        if self.content_sha256 != coverage_fingerprint(self):
            raise CoverageEvidenceError("coverage evidence content hash does not match its declaration")

    def manifest_record(self) -> dict[str, str]:
        self.validate(self.instrument, self.venue)
        return {
            "source": self.source,
            "instrument": self.instrument,
            "venue": self.venue,
            "funding_series_start_utc": _utc_iso(self.series_start),
            "snapshot_identity": self.snapshot_identity,
            "content_sha256": self.content_sha256,
            "generated_at_utc": _utc_iso(self.generated_at),
            "validity_rule": self.validity_rule,
        }


def coverage_fingerprint(evidence: FundingCoverageEvidence) -> str:
    """Hash the immutable declaration fields, excluding its self-referential hash."""
    payload = {
        "source": evidence.source,
        "instrument": evidence.instrument,
        "venue": evidence.venue,
        "series_start": _utc_iso(evidence.series_start),
        "snapshot_identity": evidence.snapshot_identity,
        "generated_at": _utc_iso(evidence.generated_at),
        "validity_rule": evidence.validity_rule,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def make_coverage_evidence(
    *, source: str, instrument: str, venue: str, series_start: datetime,
    snapshot_identity: str, generated_at: datetime, validity_rule: str,
) -> FundingCoverageEvidence:
    provisional = FundingCoverageEvidence(
        source=source, instrument=instrument, venue=venue, series_start=series_start,
        snapshot_identity=snapshot_identity, content_sha256="", generated_at=generated_at,
        validity_rule=validity_rule,
    )
    return FundingCoverageEvidence(
        **{**provisional.__dict__, "content_sha256": coverage_fingerprint(provisional)}
    )


# Versioned metadata snapshot. It intentionally has no inferred declarations:
# the first settlement row is never elevated to listing evidence. Add only
# independently reviewed venue metadata with the immutable source above.
METADATA_SNAPSHOT_VERSION = "funding-coverage-metadata/v1"
_EVIDENCE: Mapping[tuple[str, str], FundingCoverageEvidence] = MappingProxyType({})


def coverage_evidence_for(instrument: str, venue: str) -> FundingCoverageEvidence | None:
    evidence = _EVIDENCE.get((venue, instrument))
    if evidence is not None:
        evidence.validate(instrument, venue)
    return evidence


def coverage_manifest_record(
    evidence: FundingCoverageEvidence | None, status: str, detail: str
) -> dict[str, str]:
    record = {
        "metadata_snapshot_version": METADATA_SNAPSHOT_VERSION,
        "coverage_status": status,
        "coverage_detail": detail,
    }
    if evidence is not None:
        record.update(evidence.manifest_record())
    return record


def validate_manifest_coverage_record(record: Mapping[str, str]) -> None:
    required = {
        "source", "instrument", "venue", "funding_series_start_utc", "snapshot_identity",
        "content_sha256", "generated_at_utc", "validity_rule",
    }
    if not all(record.get(key) for key in required):
        raise CoverageEvidenceError("coverage evidence has incomplete manifest fields")
    try:
        evidence = FundingCoverageEvidence(
            source=record["source"], instrument=record["instrument"], venue=record["venue"],
            series_start=_parse_utc(record["funding_series_start_utc"]),
            snapshot_identity=record["snapshot_identity"], content_sha256=record["content_sha256"],
            generated_at=_parse_utc(record["generated_at_utc"]), validity_rule=record["validity_rule"],
        )
    except (TypeError, ValueError) as exc:
        raise CoverageEvidenceError("coverage evidence has invalid UTC timestamps") from exc
    evidence.validate(evidence.instrument, evidence.venue)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return parsed
