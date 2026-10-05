"""Evidence integrity, read from the existing evidence trust layer.

This module is transport for ``framework.evidence``. It owns no hashing, no
digest comparison and no verdict of its own: every status it reports is the
return value of code that already exists in the trust layer.

    EvidenceIntake.verify()                 re-verify each registered file
    EvidenceIntake.load_provenance()        where the evidence came from
    EvidenceIntake.verify_analysis_target() the framework's own analysis gate

The last of those already answers the question a screen has to ask — may this
evidence be analysed, and if not, why — and it carries the full digest
comparison on the exception it raises. So this module calls it and reports what
came back rather than deriving an "integrity ok" flag of its own. A failed
verification is reported with the registered digest, the observed digest and the
subject that failed, taken from ``EvidenceIntegrityError``, and nothing is
re-hashed here.

What this module adds is a rollup. The trust layer reports one status per
subject: the preserved original and the controlled working copy. A screen needs
one status per submission, so :func:`_rollup` reduces the pair. That rollup is
presentation only. It never upgrades a status, it never reports a subject as
verified when it was not examined, and a submission that could not be verified is
reported as ``UNAVAILABLE`` rather than ``VERIFIED``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from framework.evidence.integrity import (
    EvidenceError,
    EvidenceNotFoundError,
    IntegrityResult,
    IntegrityStatus,
)
from framework.evidence.intake import (
    EvidenceIntake,
    EvidenceIntegrityError,
    EvidenceResolutionError,
)
from framework.evidence.manifest import EvidenceManifest, ManifestFile

from backend.datasets import repository_root

#: The evidence store inside the repository, which is also the framework's own
#: default workspace. Resolved against the repository root so the adapter does
#: not depend on the process working directory.
EVIDENCE_ROOT = os.path.join(repository_root(), "data", "evidence")

#: The subjects the trust layer verifies. These strings are the framework's
#: own subject names, so a status on screen is traceable to the audit record.
ORIGINAL_SUBJECT = "preserved original"
WORKING_SUBJECT = "controlled working copy"


def _intake() -> EvidenceIntake:
    """The trust layer's own entry point for this workspace."""

    return EvidenceIntake(EVIDENCE_ROOT)


def _relative(path: str) -> str:
    """A repository-relative path, or the absolute one if it is outside."""

    try:
        return os.path.relpath(path, repository_root()).replace(os.sep, "/")
    except ValueError:
        return path


def _rollup(
    original: Optional[IntegrityResult],
    working: Optional[IntegrityResult],
) -> str:
    """One status for a submission, from the statuses of its two subjects.

    A subject that was never reached is ``None``. The framework verifies the
    original before the working copy and stops at the first failure, so a
    working copy that was never examined has no status of its own and is
    reported as ``UNAVAILABLE`` — never as verified.
    """

    results = [result for result in (original, working) if result is not None]

    if results and all(result.verified for result in results):
        return IntegrityStatus.VERIFIED.value

    statuses = {result.status for result in results}

    # A digest disagreement is reported ahead of an absent file: it is a
    # statement about the evidence, where an absent file is a statement about
    # the filesystem.
    for status in (
        IntegrityStatus.INTEGRITY_FAILED,
        IntegrityStatus.MISSING,
        IntegrityStatus.UNAVAILABLE,
    ):
        if status in statuses:
            return status.value

    return IntegrityStatus.UNAVAILABLE.value


def _comparison(result: Optional[IntegrityResult], unreached: str) -> Dict[str, Any]:
    """One subject's integrity comparison, as the trust layer reported it."""

    if result is None:
        return {
            "status": IntegrityStatus.UNAVAILABLE.value,
            "path": None,
            "expected_sha256": None,
            "observed_sha256": None,
            "detail": unreached,
        }

    payload = result.to_dict()
    payload["path"] = _relative(str(result.path))

    return payload


def _manifest_entry(manifest: EvidenceManifest) -> Optional[ManifestFile]:
    """The manifest entry for the preserved original, if one is registered."""

    for entry in manifest.files:
        if entry.role == "original":
            return entry

    return None


def _registered_original(intake: EvidenceIntake, identifier: str) -> Optional[IntegrityResult]:
    """The trust layer's verification result for the preserved original.

    ``EvidenceIntake.verify`` returns one result per manifest entry, in manifest
    order, so the original's result is paired with the original's entry here
    rather than being matched on a path.
    """

    manifest = intake.load_manifest(identifier)

    for entry, result in zip(manifest.files, intake.verify(identifier)):
        if entry.role == "original":
            return result

    return None


def describe(evidence_id: str) -> Dict[str, Any]:
    """One registered submission, verified through the existing mechanism.

    Reports the registration, the provenance, the digest the manifest registered,
    and the integrity of both the preserved original and the controlled working
    copy, together with whether the framework's analysis gate permits analysis.
    """

    intake = _intake()

    identifier = intake.resolve_evidence_id(evidence_id)
    manifest = intake.load_manifest(identifier)
    entry = _manifest_entry(manifest)

    try:
        provenance: Optional[Dict[str, Any]] = intake.load_provenance(identifier).to_dict()
    except EvidenceError:
        provenance = None

    # The framework's own gate. It verifies the original, then the working copy,
    # and raises on the first subject that does not verify. The original's
    # result is taken from the trust layer's own verification, so a failure
    # carries the digests the framework produced rather than a new comparison.
    original_result = _registered_original(intake, identifier)
    working_result: Optional[IntegrityResult] = None
    analysis_permitted = False
    blocked_reason: Optional[str] = None
    target_path: Optional[str] = None

    try:
        resolved = intake.verify_analysis_target(identifier)

        original_result = resolved.original_integrity
        working_result = resolved.working_integrity
        analysis_permitted = resolved.verified
        target_path = _relative(str(resolved.working_path))

        if not analysis_permitted:
            blocked_reason = (
                "Verification did not succeed for both the preserved original "
                "and the controlled working copy"
            )
    except EvidenceIntegrityError as failure:
        analysis_permitted = False
        blocked_reason = failure.result.detail

        if failure.subject == WORKING_SUBJECT:
            working_result = failure.result
    except (EvidenceResolutionError, EvidenceNotFoundError) as failure:
        analysis_permitted = False
        blocked_reason = str(failure)

    return {
        "evidence_id": identifier,
        "registered_at": manifest.created_at,
        "hash_algorithm": manifest.hash_algorithm,
        "manifest_schema_version": manifest.schema_version,
        "originals_read_only": manifest.originals_read_only,
        "file_count": manifest.file_count,
        "total_size": manifest.total_size,
        "source": {
            "filename": entry.name if entry is not None else None,
            "stored_name": entry.stored_name if entry is not None else None,
            "size_bytes": entry.size if entry is not None else None,
            "content_type": entry.content_type if entry is not None else None,
            "modified_at": entry.modified_at if entry is not None else None,
        },
        # The digest the manifest registered. Every observed digest reported
        # below is compared against this value by the trust layer.
        "registered_sha256": entry.sha256 if entry is not None else None,
        "original": _comparison(
            original_result,
            "The preserved original was not examined",
        ),
        "working": _comparison(
            working_result,
            "The controlled working copy was not examined, because "
            "verification of the preserved original did not succeed",
        ),
        "overall_status": _rollup(original_result, working_result),
        "analysis": {
            "permitted": analysis_permitted,
            "blocked_reason": blocked_reason,
            "target_path": target_path,
        },
        "provenance": provenance,
        "files": [item.to_dict() for item in manifest.files],
    }


def _unreadable(evidence_id: str, reason: str) -> Dict[str, Any]:
    """A registration that could not be read, listed rather than hidden.

    An unreadable registration is a fact about the evidence store; reporting it
    as ``UNAVAILABLE`` keeps it visible instead of making the store look empty.
    """

    unavailable = IntegrityStatus.UNAVAILABLE.value

    return {
        "evidence_id": evidence_id,
        "registered_at": None,
        "hash_algorithm": None,
        "manifest_schema_version": None,
        "originals_read_only": None,
        "file_count": None,
        "total_size": None,
        "source": {
            "filename": None,
            "stored_name": None,
            "size_bytes": None,
            "content_type": None,
            "modified_at": None,
        },
        "registered_sha256": None,
        "original": _comparison(None, reason),
        "working": _comparison(None, reason),
        "overall_status": unavailable,
        "analysis": {
            "permitted": False,
            "blocked_reason": reason,
            "target_path": None,
        },
        "provenance": None,
        "files": [],
    }


def inventory() -> List[Dict[str, Any]]:
    """Every registered submission, newest registration first.

    This is the ``Verify Integrity`` action's whole-store counterpart: it runs
    the framework's verification for each registered submission, so the statuses
    shown are the ones the trust layer reports.
    """

    intake = _intake()

    described: List[Dict[str, Any]] = []

    for evidence_id in intake.workspace.list_evidence_ids():
        try:
            described.append(describe(evidence_id))
        except EvidenceNotFoundError:
            continue
        except EvidenceError as error:
            described.append(_unreadable(evidence_id, f"{type(error).__name__}: {error}"))

    described.sort(key=lambda item: (item["registered_at"] or "", item["evidence_id"]), reverse=True)

    return described


def verify(evidence_id: str) -> Dict[str, Any]:
    """Re-verify one submission on demand, through the same mechanism.

    Recomputes nothing here: the digests reported are the ones the trust layer
    just produced while verifying.
    """

    return describe(evidence_id)


# ---------------------------------------------------------------------------
# The analysis gate, applied to a dataset path
# ---------------------------------------------------------------------------


class EvidenceAnalysisBlocked(Exception):
    """A requested dataset is registered evidence that may not be analysed.

    Carries the trust layer's own comparison, so the caller can report the
    registered and observed digests without recalculating either.
    """

    def __init__(self, reason: str, comparison: Optional[IntegrityResult] = None):
        self.reason = reason
        self.comparison = comparison

        super().__init__(reason)


def _evidence_store_relative(relative_path: str) -> Optional[str]:
    """A dataset path's location inside the evidence store, if it is in one.

    Returned as ``<evidence_id>/<path within the submission>``, so a dataset
    path can be attributed to the submission it belongs to without this module
    knowing anything about submissions.
    """

    store_prefix = os.path.relpath(EVIDENCE_ROOT, repository_root()).replace(os.sep, "/")

    if not relative_path.startswith(f"{store_prefix}/"):
        return None

    return relative_path[len(store_prefix) + 1 :]


def gate_dataset(relative_path: str) -> Optional[Dict[str, Any]]:
    """Whether the trust layer permits analysing this dataset path.

    Returns ``None`` when the path is not registered evidence, which is the
    ordinary case: an ordinary dataset is not gated by the evidence store, and
    the pipeline is left to run exactly as it did before.

    For a path that *is* registered evidence, the trust layer's own gate is
    applied and the resolved working copy is returned. A preserved original is
    refused outright, because the trust layer never hands one out for analysis
    and the adapter must not hand one to the pipeline either.

    Raises:
        EvidenceAnalysisBlocked: the submission did not verify, or the path is a
            preserved original, which is not an analysis target.
    """

    located = _evidence_store_relative(relative_path)

    if located is None:
        return None

    location, _, remainder = located.partition("/")
    evidence_id = remainder.split("/", 1)[0]

    if location == "originals":
        raise EvidenceAnalysisBlocked(
            f"{evidence_id} is a preserved original, which is not an analysis "
            f"target. Analyse its controlled working copy instead: "
            f"{'data/evidence/working/' + evidence_id}",
        )

    if location != "working":
        raise EvidenceAnalysisBlocked(
            f"{relative_path} is part of the evidence register rather than an "
            f"analysable dataset.",
        )

    intake = _intake()

    try:
        resolved = intake.verify_analysis_target(evidence_id)
    except EvidenceIntegrityError as failure:
        raise EvidenceAnalysisBlocked(failure.result.detail, failure.result) from None
    except EvidenceError as failure:
        raise EvidenceAnalysisBlocked(str(failure)) from None

    return {
        "evidence_id": resolved.evidence_id,
        "original_integrity": resolved.original_integrity.to_dict(),
        "working_integrity": resolved.working_integrity.to_dict(),
        "target_path": _relative(str(resolved.working_path)),
    }

