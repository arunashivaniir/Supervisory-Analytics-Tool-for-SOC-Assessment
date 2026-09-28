"""
Evidence provenance records for SAT-SA.

Provenance answers a different question to the manifest:

* manifest    -- what exactly arrived? (names, sizes, digests)
* provenance  -- who/what claims to have sent it, and when was it received?

Every descriptive field is optional. The module never invents an entity name,
CSE identifier, submitter name or assessment period. When the source does not
provide a value, the field stays ``None`` and is listed explicitly in
``unavailable_fields`` so that an auditor can see the gap instead of reading a
fabricated value.

The record is generic enough to serve both an NCIIPC supervisory assessment and
an independent security audit: nothing here is specific to a sector, an entity
register, or a dataset shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from framework.evidence.integrity import EvidenceValidationError
from framework.evidence.manifest import utc_now_iso

__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "PROVENANCE_SUFFIX",
    "STATUS_REGISTERED",
    "STATUS_UNDER_REVIEW",
    "ProvenanceRecord",
    "build_provenance",
    "load_provenance",
    "save_provenance",
]


PROVENANCE_SCHEMA_VERSION = "1.0"

PROVENANCE_SUFFIX = ".provenance.json"

STATUS_REGISTERED = "REGISTERED"

STATUS_UNDER_REVIEW = "UNDER_REVIEW"

# Fields that describe the submitting party or the reporting window. Any of
# these may legitimately be unknown at intake time.
OPTIONAL_SOURCE_FIELDS = (
    "source_identifier",
    "submitted_by",
    "assessment_period",
    "received_channel",
    "package_type",
)


@dataclass
class ProvenanceRecord:
    """Where a piece of evidence came from, and what is known about it."""

    evidence_id: str
    received_at: str
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    sha256: Optional[str] = None
    package_type: Optional[str] = None
    source_identifier: Optional[str] = None
    assessment_period: Optional[str] = None
    submitted_by: Optional[str] = None
    received_channel: Optional[str] = None
    status: str = STATUS_REGISTERED
    schema_version: str = PROVENANCE_SCHEMA_VERSION
    custody_events: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def unavailable_fields(self) -> list:
        """Optional descriptive fields the source did not supply."""

        return [
            name
            for name in OPTIONAL_SOURCE_FIELDS
            if getattr(self, name) in (None, "")
        ]

    def to_dict(self) -> dict:
        payload = {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "received_at": self.received_at,
            "status": self.status,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "sha256": self.sha256,
            "package_type": self.package_type,
            "source_identifier": self.source_identifier,
            "assessment_period": self.assessment_period,
            "submitted_by": self.submitted_by,
            "received_channel": self.received_channel,
            "unavailable_fields": self.unavailable_fields,
            "custody_events": list(self.custody_events),
            "metadata": dict(self.metadata),
        }

        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "ProvenanceRecord":
        return cls(
            evidence_id=str(payload.get("evidence_id", "")),
            received_at=str(payload.get("received_at", "")),
            original_filename=payload.get("original_filename"),
            file_size=(
                int(payload["file_size"])
                if payload.get("file_size") is not None
                else None
            ),
            sha256=payload.get("sha256"),
            package_type=payload.get("package_type"),
            source_identifier=payload.get("source_identifier"),
            assessment_period=payload.get("assessment_period"),
            submitted_by=payload.get("submitted_by"),
            received_channel=payload.get("received_channel"),
            status=str(payload.get("status", STATUS_REGISTERED)),
            schema_version=str(
                payload.get("schema_version", PROVENANCE_SCHEMA_VERSION)
            ),
            custody_events=list(payload.get("custody_events", []) or []),
            metadata=dict(payload.get("metadata", {}) or {}),
        )

    def add_custody_event(
        self,
        action: str,
        actor: Optional[str] = None,
        detail: Optional[str] = None,
        occurred_at: Optional[str] = None,
    ) -> dict:
        """Append a chain-of-custody event. Metadata only, never content."""

        event = {
            "action": str(action),
            "actor": actor,
            "detail": detail,
            "occurred_at": occurred_at or utc_now_iso(),
        }

        self.custody_events.append(event)

        return event

    def save(self, path: Union[str, Path]) -> Path:
        return save_provenance(self, path)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "ProvenanceRecord":
        return load_provenance(path)


def build_provenance(
    evidence_id: str,
    received_at: Optional[str] = None,
    original_filename: Optional[str] = None,
    file_size: Optional[int] = None,
    sha256: Optional[str] = None,
    package_type: Optional[str] = None,
    source_identifier: Optional[str] = None,
    assessment_period: Optional[str] = None,
    submitted_by: Optional[str] = None,
    received_channel: Optional[str] = None,
    status: str = STATUS_REGISTERED,
    metadata: Optional[dict] = None,
) -> ProvenanceRecord:
    """Create a provenance record, leaving unsupplied fields as ``None``."""

    return ProvenanceRecord(
        evidence_id=evidence_id,
        received_at=received_at or utc_now_iso(),
        original_filename=original_filename,
        file_size=file_size,
        sha256=sha256,
        package_type=package_type,
        source_identifier=source_identifier,
        assessment_period=assessment_period,
        submitted_by=submitted_by,
        received_channel=received_channel,
        status=status,
        metadata=dict(metadata or {}),
    )


def save_provenance(
    record: ProvenanceRecord,
    path: Union[str, Path],
) -> Path:
    """Write a provenance record as UTF-8 JSON."""

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(
        json.dumps(record.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    return target


def load_provenance(path: Union[str, Path]) -> ProvenanceRecord:
    """Read a provenance record written by :func:`save_provenance`."""

    source = Path(path).expanduser()

    if not source.is_file():
        raise EvidenceValidationError(f"Provenance record not found: {source}")

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceValidationError(
            f"Provenance record could not be read: {source} ({error})"
        ) from error

    if not isinstance(payload, dict):
        raise EvidenceValidationError(
            f"Provenance record is not a JSON object: {source}"
        )

    return ProvenanceRecord.from_dict(payload)
