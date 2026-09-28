"""
Evidence manifest generation for SAT-SA.

A manifest is the machine-readable registration record of an evidence
submission. It answers the question an auditor asks first: *what exactly was
received?*

The manifest is deliberately dataset-agnostic. It records file identity
(name, size, digest, timestamps) and nothing about SOC semantics. It never
names an entity, a sector, a dataset type or an assessment period unless the
submitter supplied that information elsewhere (see ``provenance.py``).

Nothing in this module interprets submitted content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from framework.evidence.integrity import (
    HASH_ALGORITHM,
    EvidenceValidationError,
    IntegrityResult,
    IntegrityStatus,
    verify_sha256,
)

__all__ = [
    "EVIDENCE_ID_PREFIX",
    "LOCATION_ORIGINALS",
    "LOCATION_WORKING",
    "MANIFEST_SCHEMA_VERSION",
    "MANIFEST_SUFFIX",
    "ManifestFile",
    "EvidenceManifest",
    "build_manifest",
    "classify_file",
    "file_mtime_iso",
    "generate_evidence_id",
    "load_manifest",
    "path_safe_name",
    "resolve_within",
    "save_manifest",
    "utc_now",
    "utc_now_iso",
]


EVIDENCE_ID_PREFIX = "SATSA-EV"

MANIFEST_SCHEMA_VERSION = "1.0"

MANIFEST_SUFFIX = ".manifest.json"

MAX_STORED_NAME_LENGTH = 120

_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]")

_SNIFF_BYTES = 4096

_EXTENSION_TYPES = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".zip": "zip",
}

_ROLE_ORIGINAL = "original"
_ROLE_EXTRACTED = "extracted"

# Where a registered file physically lives, relative to the evidence workspace.
# "originals" is the preserved, write-protected copy; "working" is the controlled
# analysis area (analysis copy plus validated extracted package members).
LOCATION_ORIGINALS = "originals"
LOCATION_WORKING = "working"


# ---------------------------------------------------------------------------
# Time helpers (UTC only, ISO-8601, for machine readability)
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""

    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string, e.g. ``2026-09-27T09:15:00Z``."""

    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def generate_evidence_id(
    sha256: Optional[str] = None,
    created_at: Optional[datetime] = None,
    prefix: str = EVIDENCE_ID_PREFIX,
) -> str:
    """Build a unique, human-readable evidence identifier.

    The identifier is derived from the content digest and the registration
    moment only. It deliberately contains no entity name, sector, dataset type
    or filename, so it stays meaningful for any kind of submission.

    Format::

        SATSA-EV-<YYYYMMDDTHHMMSSZ>-<first 12 hex of SHA-256>

    The same file registered in the same second yields the same identifier,
    which is what allows ``EvidenceIntake`` to detect an attempt to register a
    duplicate submission instead of silently replacing it.
    """

    moment = created_at or utc_now()

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    fingerprint = (sha256 or "").strip().lower()[:12]

    if not fingerprint:
        fingerprint = uuid.uuid4().hex[:12]

    return f"{prefix}-{stamp}-{fingerprint}"


def path_safe_name(name: Union[str, Path]) -> str:
    """Return a filename that is safe to create inside the evidence workspace.

    Directory components and traversal segments are discarded, unsafe
    characters are replaced, and an unreadable or colliding form is disambiguated
    with a short digest of the original name. The result is never empty, never
    ``.`` or ``..``, and never longer than ``MAX_STORED_NAME_LENGTH``.
    """

    raw = str(name).replace("\\", "/").strip()

    raw = raw.rsplit("/", 1)[-1]

    if not raw or raw in (".", ".."):
        return "evidence_file"

    safe = _UNSAFE_CHARACTERS.sub("_", raw)

    if safe in ("", ".", ".."):
        safe = "evidence_file"

    if len(safe) > MAX_STORED_NAME_LENGTH:
        safe = safe[: MAX_STORED_NAME_LENGTH - 9]

    if safe != raw or len(safe) > MAX_STORED_NAME_LENGTH:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        safe = f"{safe}_{digest}"

    return safe


def resolve_within(root: Union[str, Path], relative: Union[str, Path]) -> Path:
    """Resolve ``relative`` under ``root``, refusing to escape ``root``.

    Manifests and archives both contain attacker-influenceable path strings.
    Every such string is funnelled through this helper so a tampered record
    cannot redirect reads or writes outside the evidence workspace.
    """

    base = Path(root).expanduser().resolve()
    candidate = (base / str(relative)).resolve()

    if candidate != base and base not in candidate.parents:
        raise EvidenceValidationError(
            f"Refusing to use a path outside the evidence workspace: {relative}"
        )

    return candidate


def classify_file(path: Union[str, Path], sample: Optional[bytes] = None) -> str:
    """Classify evidence content by extension, then by content sniffing.

    Purely a descriptive label used by the manifest; it is not a parser and it
    does not constrain what the analysis layer may later attempt.
    """

    suffix = Path(str(path)).suffix.lower()

    if suffix in _EXTENSION_TYPES:
        return _EXTENSION_TYPES[suffix]

    if sample is None:
        try:
            with Path(path).expanduser().open("rb") as handle:
                sample = handle.read(_SNIFF_BYTES)
        except OSError:
            return "unknown"

    if sample.startswith(b"PK\x03\x04") or sample.startswith(b"PK\x05\x06"):
        return "zip"

    if not sample:
        return "empty"

    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"

    return "text"


# ---------------------------------------------------------------------------
# Manifest records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestFile:
    """One registered file inside an evidence submission."""

    name: str
    stored_name: str
    relative_path: str
    size: int
    sha256: str
    modified_at: Optional[str] = None
    content_type: str = "unknown"
    role: str = _ROLE_ORIGINAL
    location: str = LOCATION_ORIGINALS

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "stored_name": self.stored_name,
            "relative_path": self.relative_path,
            "size": self.size,
            "sha256": self.sha256,
            "modified_at": self.modified_at,
            "content_type": self.content_type,
            "role": self.role,
            "location": self.location,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ManifestFile":
        return cls(
            name=str(payload.get("name", "")),
            stored_name=str(payload.get("stored_name", "")),
            relative_path=str(payload.get("relative_path", "")),
            size=int(payload.get("size", 0)),
            sha256=str(payload.get("sha256", "")),
            modified_at=payload.get("modified_at"),
            content_type=str(payload.get("content_type", "unknown")),
            role=str(payload.get("role", _ROLE_ORIGINAL)),
            location=str(payload.get("location", LOCATION_ORIGINALS)),
        )


@dataclass
class EvidenceManifest:
    """Registration record of a single evidence submission.

    The manifest is the reference point for integrity verification: it holds the
    SHA-256 digest each file is compared against. It is a plain local JSON file
    and is not signed, so it is the *weakest* link in the chain, not the
    strongest -- see limitation 1 in ``docs/evidence_integrity.md``.
    """

    evidence_id: str
    created_at: str
    files: list = field(default_factory=list)
    schema_version: str = MANIFEST_SCHEMA_VERSION
    hash_algorithm: str = HASH_ALGORITHM
    # Records only that the owner write bit was cleared on the preserved
    # originals at registration time. It is a handling control, not a security
    # boundary: nothing prevents the same account or a privileged user from
    # changing the file. Change detection comes from ``files[].sha256``.
    originals_read_only: bool = False
    notes: dict = field(default_factory=dict)

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.files)

    @property
    def file_count(self) -> int:
        return len(self.files)

    def by_name(self, name: str) -> Optional[ManifestFile]:
        for entry in self.files:
            if entry.name == name or entry.stored_name == name:
                return entry

        return None

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "created_at": self.created_at,
            "hash_algorithm": self.hash_algorithm,
            "originals_read_only": self.originals_read_only,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "files": [entry.to_dict() for entry in self.files],
            "notes": dict(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "EvidenceManifest":
        return cls(
            evidence_id=str(payload.get("evidence_id", "")),
            created_at=str(payload.get("created_at", "")),
            files=[
                ManifestFile.from_dict(item) for item in payload.get("files", [])
            ],
            schema_version=str(
                payload.get("schema_version", MANIFEST_SCHEMA_VERSION)
            ),
            hash_algorithm=str(payload.get("hash_algorithm", HASH_ALGORITHM)),
            originals_read_only=bool(
                payload.get("originals_read_only", False)
            ),
            notes=dict(payload.get("notes", {}) or {}),
        )

    def save(self, path: Union[str, Path]) -> Path:
        return save_manifest(self, path)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "EvidenceManifest":
        return load_manifest(path)

    def verify(self, roots=None) -> list:
        """Re-verify every registered file against its recorded digest.

        ``roots`` is either a single base directory (used for every entry) or a
        mapping of manifest location to base directory, e.g.::

            {"originals": originals_dir, "working": working_dir}

        Returns one :class:`IntegrityResult` per manifest entry. The manifest
        is the reference point for this call, so a digest edited *inside the
        manifest* would not be detected by it -- see
        ``docs/evidence_integrity.md`` for that stated limitation.
        """

        results: list = []

        for entry in self.files:
            try:
                base = _base_for_location(roots, entry)
                target = resolve_within(base, entry.relative_path)
            except EvidenceValidationError as error:
                results.append(
                    IntegrityResult(
                        status=IntegrityStatus.UNAVAILABLE,
                        path=str(entry.relative_path),
                        expected_sha256=entry.sha256,
                        detail=str(error),
                    )
                )
                continue

            results.append(verify_sha256(target, entry.sha256))

        return results


def _base_for_location(roots, entry: ManifestFile) -> Path:
    """Resolve the base directory a manifest entry should be read from."""

    if roots is None:
        raise EvidenceValidationError(
            "A base directory or location mapping is required to verify "
            "manifest entries"
        )

    if isinstance(roots, (str, Path)):
        return Path(roots)

    base = roots.get(entry.location)

    if base is None:
        raise EvidenceValidationError(
            f"Manifest entry location {entry.location!r} has no base "
            "directory configured"
        )

    return Path(base)


def build_manifest(
    evidence_id: str,
    files: Sequence,
    created_at: Optional[str] = None,
    originals_read_only: bool = False,
    notes: Optional[dict] = None,
) -> EvidenceManifest:
    """Assemble an :class:`EvidenceManifest` from registered file entries.

    ``files`` accepts :class:`ManifestFile` objects or equivalent dicts.
    """

    entries: list = []

    for item in files:
        if isinstance(item, ManifestFile):
            entries.append(item)
        elif isinstance(item, dict):
            entries.append(ManifestFile.from_dict(item))
        else:
            raise EvidenceValidationError(
                f"Unsupported manifest entry type: {type(item).__name__}"
            )

    return EvidenceManifest(
        evidence_id=evidence_id,
        created_at=created_at or utc_now_iso(),
        files=entries,
        originals_read_only=originals_read_only,
        notes=dict(notes or {}),
    )


def save_manifest(
    manifest: EvidenceManifest,
    path: Union[str, Path],
) -> Path:
    """Write a manifest as UTF-8 JSON, creating parent directories."""

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    return target


def load_manifest(path: Union[str, Path]) -> EvidenceManifest:
    """Read a manifest written by :func:`save_manifest`."""

    source = Path(path).expanduser()

    if not source.is_file():
        raise EvidenceValidationError(f"Manifest not found: {source}")

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceValidationError(
            f"Manifest could not be read: {source} ({error})"
        ) from error

    if not isinstance(payload, dict):
        raise EvidenceValidationError(
            f"Manifest is not a JSON object: {source}"
        )

    return EvidenceManifest.from_dict(payload)


def file_mtime_iso(path: Union[str, Path]) -> Optional[str]:
    """UTC ISO-8601 modification time of a file, or ``None`` if unavailable."""

    try:
        stamp = datetime.fromtimestamp(
            os.stat(path).st_mtime,
            tz=timezone.utc,
        )
    except OSError:
        return None

    return stamp.isoformat(timespec="seconds").replace("+00:00", "Z")
