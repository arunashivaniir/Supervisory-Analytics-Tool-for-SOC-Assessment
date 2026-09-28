"""
SAT-SA Evidence Integrity Primitives.

This module is the lowest layer of the SAT-SA evidence trust chain. It answers
one question only: "is the file I am looking at byte-for-byte the file that was
registered?"

Design constraints:

* Standard library only (``hashlib``). No network, no cloud, no SaaS.
* Files are hashed in fixed-size chunks, so a multi-gigabyte evidence package
  never has to fit in memory.
* Files are always opened in binary mode. CSV, JSON, ZIP and arbitrary binary
  evidence are all handled identically; no text/encoding assumption is made.
* Nothing here executes, imports, or evaluates submitted content.
* Verification never fails open. If a comparison cannot be performed
  meaningfully, the result is ``UNAVAILABLE`` or ``MISSING`` -- never
  ``VERIFIED``.

The integrity guarantee provided here is *verifiability against a recorded
digest*, not mathematical immutability. See ``docs/evidence_integrity.md``.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "HASH_ALGORITHM",
    "EvidenceError",
    "EvidenceNotFoundError",
    "EvidenceValidationError",
    "EvidenceConflictError",
    "UnsafeArchiveError",
    "IntegrityStatus",
    "IntegrityResult",
    "calculate_sha256",
    "calculate_sha256_of_text",
    "copy_and_hash",
    "is_sha256",
    "normalise_sha256",
    "verify_sha256",
]


# 1 MiB read window. Large enough to keep syscall overhead negligible, small
# enough that memory use is constant regardless of evidence size.
DEFAULT_CHUNK_SIZE = 1024 * 1024

HASH_ALGORITHM = "sha256"

_SHA256_HEX = re.compile(r"\A[0-9a-f]{64}\Z")

_SHA256_LABELS = ("sha256", "sha-256", "sha 256")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EvidenceError(Exception):
    """Base class for every error raised by the SAT-SA evidence layer."""


class EvidenceNotFoundError(EvidenceError):
    """Raised when a supplied evidence path does not exist."""


class EvidenceValidationError(EvidenceError):
    """Raised when a path or record fails a structural safety check."""


class EvidenceConflictError(EvidenceError):
    """Raised when registering evidence would overwrite existing evidence."""


class UnsafeArchiveError(EvidenceValidationError):
    """Raised for archive members that are unsafe or unprocessable."""


# ---------------------------------------------------------------------------
# Status model
# ---------------------------------------------------------------------------


class IntegrityStatus(str, Enum):
    """Explicit verification outcomes.

    ``INTEGRITY_FAILED`` is never a fallback: it means the registered digest
    and the observed digest disagree, i.e. the evidence changed after
    registration.
    """

    VERIFIED = "VERIFIED"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class IntegrityResult:
    """Outcome of a single integrity comparison.

    Attributes are plain data so the result can be serialised straight into an
    audit record, a manifest, or a dashboard payload.
    """

    status: IntegrityStatus
    path: str
    expected_sha256: Optional[str] = None
    observed_sha256: Optional[str] = None
    detail: str = ""

    @property
    def verified(self) -> bool:
        return self.status is IntegrityStatus.VERIFIED

    @property
    def failed(self) -> bool:
        return self.status is IntegrityStatus.INTEGRITY_FAILED

    @property
    def status_label(self) -> str:
        return self.status.value

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "path": self.path,
            "expected_sha256": self.expected_sha256,
            "observed_sha256": self.observed_sha256,
            "detail": self.detail,
        }

    def describe(self) -> str:
        """Human/auditor readable multi-line description."""
        lines = [self.status.value]

        lines.append(f"  File: {self.path}")

        if self.expected_sha256:
            lines.append(f"  Expected SHA-256: {self.expected_sha256}")

        if self.observed_sha256:
            lines.append(f"  Observed SHA-256: {self.observed_sha256}")

        if self.detail:
            lines.append(f"  Detail: {self.detail}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------


def normalise_sha256(value: Union[str, bytes, None]) -> Optional[str]:
    """Return a lowercase hex digest string, or ``None`` if nothing was given.

    Accepts common decorations such as ``"SHA256:ab12..."`` so that digests
    copied out of third-party tooling can be compared without reformatting.
    """

    if value is None:
        return None

    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")

    text = str(value).strip().lower()

    if not text:
        return None

    if ":" in text:
        label, _, remainder = text.partition(":")

        if label.strip() in _SHA256_LABELS:
            text = remainder.strip()

    return text or None


def is_sha256(value: Union[str, bytes, None]) -> bool:
    """True only for a well-formed 64-character hexadecimal SHA-256 digest."""

    normalised = normalise_sha256(value)

    return bool(normalised and _SHA256_HEX.match(normalised))


def calculate_sha256(
    file_path: Union[str, Path],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> str:
    """Return the hexadecimal SHA-256 digest of a file.

    The file is streamed in binary chunks; it is never loaded into memory as a
    whole and never decoded as text.

    Raises:
        EvidenceNotFoundError: the path does not exist.
        EvidenceValidationError: the path is a directory or unreadable.
    """

    if chunk_size <= 0:
        raise EvidenceValidationError("chunk_size must be a positive integer")

    path = Path(file_path).expanduser()

    if not path.exists():
        raise EvidenceNotFoundError(f"Evidence file not found: {path}")

    if path.is_dir():
        raise EvidenceValidationError(
            f"Expected a regular evidence file, received a directory: {path}"
        )

    digest = hashlib.sha256()

    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceValidationError(
            f"Evidence file could not be read: {path} ({error})"
        ) from error

    return digest.hexdigest()


def calculate_sha256_of_text(text: str) -> str:
    """Return the hexadecimal SHA-256 digest of a string.

    The in-memory sibling of :func:`calculate_sha256`, added so that callers
    needing to digest a small serialised payload -- a feature-schema
    fingerprint, a manifest body -- do not have to open a second SHA-256
    implementation or write a temporary file just to hash it. Encoding is
    explicit and fixed to UTF-8 so the digest is reproducible across
    platforms.

    Raises:
        EvidenceValidationError: the value is not text.
    """

    if not isinstance(text, str):
        raise EvidenceValidationError(
            "calculate_sha256_of_text expects a string, received "
            f"{type(text).__name__}"
        )

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def copy_and_hash(
    source: Union[str, Path],
    destination: Union[str, Path],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> tuple:
    """Copy a file while hashing the bytes actually written.

    The destination is opened in exclusive-create mode, so an existing file is
    never overwritten. The returned digest is computed from the copied stream
    rather than from the source, which lets the caller prove the copy on disk
    matches the source.

    Returns:
        ``(bytes_written, sha256_hex)``

    Raises:
        FileExistsError: the destination already exists.
        EvidenceValidationError: source/destination are not usable files.
    """

    if chunk_size <= 0:
        raise EvidenceValidationError("chunk_size must be a positive integer")

    source_path = Path(source).expanduser()
    destination_path = Path(destination).expanduser()

    if not source_path.is_file():
        raise EvidenceValidationError(
            f"Evidence source is not a regular file: {source_path}"
        )

    digest = hashlib.sha256()
    written = 0

    destination_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with source_path.open("rb") as reader:
            # "xb" fails if the destination exists: evidence is never replaced.
            with destination_path.open("xb") as writer:
                for chunk in iter(lambda: reader.read(chunk_size), b""):
                    writer.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)

                writer.flush()

                os.fsync(writer.fileno())
    except FileExistsError as error:
        raise EvidenceConflictError(
            f"Refusing to overwrite existing evidence: {destination_path}"
        ) from error
    except OSError as error:
        raise EvidenceValidationError(
            f"Evidence copy failed: {source_path} -> {destination_path} "
            f"({error})"
        ) from error

    return written, digest.hexdigest()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_sha256(
    file_path: Union[str, Path],
    expected_hash: Union[str, bytes, None],
) -> IntegrityResult:
    """Compare a file against a previously registered SHA-256 digest.

    Verification is explicit and never fails open:

    * digest missing or malformed -> ``UNAVAILABLE``
    * file absent                     -> ``MISSING``
    * file unreadable                 -> ``UNAVAILABLE``
    * digests disagree                 -> ``INTEGRITY_FAILED``
    * digests agree                    -> ``VERIFIED``
    """

    path = Path(file_path).expanduser()
    display_path = str(path)

    expected = normalise_sha256(expected_hash)

    if expected is None:
        return IntegrityResult(
            status=IntegrityStatus.UNAVAILABLE,
            path=display_path,
            detail="No registered SHA-256 digest is available for comparison",
        )

    if not is_sha256(expected):
        return IntegrityResult(
            status=IntegrityStatus.UNAVAILABLE,
            path=display_path,
            expected_sha256=expected,
            detail="Registered value is not a well-formed SHA-256 digest",
        )

    if not path.exists():
        return IntegrityResult(
            status=IntegrityStatus.MISSING,
            path=display_path,
            expected_sha256=expected,
            detail="Registered evidence file is no longer present",
        )

    if path.is_dir():
        return IntegrityResult(
            status=IntegrityStatus.UNAVAILABLE,
            path=display_path,
            expected_sha256=expected,
            detail="Registered evidence path is a directory, not a file",
        )

    try:
        observed = calculate_sha256(path)
    except EvidenceError as error:
        return IntegrityResult(
            status=IntegrityStatus.UNAVAILABLE,
            path=display_path,
            expected_sha256=expected,
            detail=str(error),
        )

    if observed == expected:
        return IntegrityResult(
            status=IntegrityStatus.VERIFIED,
            path=display_path,
            expected_sha256=expected,
            observed_sha256=observed,
            detail="Digest matches the registered value",
        )

    return IntegrityResult(
        status=IntegrityStatus.INTEGRITY_FAILED,
        path=display_path,
        expected_sha256=expected,
        observed_sha256=observed,
        detail="Evidence digest differs from the registered value; "
        "the file changed after registration",
    )
