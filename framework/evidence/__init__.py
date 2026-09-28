"""
SAT-SA Evidence Trust Layer.

An evidence integrity and provenance layer that sits *in front of* the existing
SAT-SA analytics framework. It answers the supervisory question "can this
evidence be trusted, and can we prove it was not altered?" before any analysis
is performed.

    Submitted evidence
        -> EvidenceIntake (validate, hash, register)
        -> manifest + provenance + preserved original
        -> controlled working copy
        -> existing SAT-SA framework
        -> supervisory findings
        -> human auditor / examiner review

Scope of this package:

* SHA-256 integrity calculation and explicit verification
* Evidence manifest and provenance registration records
* Separation of preserved originals from controlled analysis copies
* Safe handling of submitted ZIP evidence packages

This package deliberately contains **no SOC analytics**. It does not know what
alerts, investigations, assets or escalations are, and it holds no second
analytical engine. Integrity decisions are dataset-agnostic; semantic
interpretation remains entirely with the existing SAT-SA framework.

Public names are resolved lazily (PEP 562) so that importing
``framework.evidence`` does not import the intake CLI module, which keeps
``python -m framework.evidence.intake`` free of ``runpy`` re-execution
warnings.
"""

from typing import Any

__all__ = [
    # integrity
    "DEFAULT_CHUNK_SIZE",
    "HASH_ALGORITHM",
    "IntegrityResult",
    "IntegrityStatus",
    "calculate_sha256",
    "calculate_sha256_of_text",
    "copy_and_hash",
    "is_sha256",
    "normalise_sha256",
    "verify_sha256",
    # errors
    "EvidenceConflictError",
    "EvidenceError",
    "EvidenceNotFoundError",
    "EvidenceValidationError",
    "UnsafeArchiveError",
    # manifest
    "EVIDENCE_ID_PREFIX",
    "LOCATION_ORIGINALS",
    "LOCATION_WORKING",
    "MANIFEST_SCHEMA_VERSION",
    "EvidenceManifest",
    "ManifestFile",
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
    # provenance
    "PROVENANCE_SCHEMA_VERSION",
    "STATUS_REGISTERED",
    "STATUS_UNDER_REVIEW",
    "ProvenanceRecord",
    "build_provenance",
    "load_provenance",
    "save_provenance",
    # intake
    "DEFAULT_WORKSPACE_ROOT",
    "EvidenceIntake",
    "EvidenceIntegrityError",
    "EvidenceRecord",
    "EvidenceResolutionError",
    "EvidenceWorkspace",
    "ResolvedEvidence",
    "intake_file",
    "safe_member_name",
    "unlock_preserved_original",
    "validate_evidence_id",
    "validate_package",
]


_EXPORTS = {
    # integrity
    "DEFAULT_CHUNK_SIZE": "integrity",
    "HASH_ALGORITHM": "integrity",
    "IntegrityResult": "integrity",
    "IntegrityStatus": "integrity",
    "calculate_sha256": "integrity",
    "calculate_sha256_of_text": "integrity",
    "copy_and_hash": "integrity",
    "is_sha256": "integrity",
    "normalise_sha256": "integrity",
    "verify_sha256": "integrity",
    # errors
    "EvidenceConflictError": "integrity",
    "EvidenceError": "integrity",
    "EvidenceNotFoundError": "integrity",
    "EvidenceValidationError": "integrity",
    "UnsafeArchiveError": "integrity",
    # manifest
    "EVIDENCE_ID_PREFIX": "manifest",
    "LOCATION_ORIGINALS": "manifest",
    "LOCATION_WORKING": "manifest",
    "MANIFEST_SCHEMA_VERSION": "manifest",
    "EvidenceManifest": "manifest",
    "ManifestFile": "manifest",
    "build_manifest": "manifest",
    "classify_file": "manifest",
    "file_mtime_iso": "manifest",
    "generate_evidence_id": "manifest",
    "load_manifest": "manifest",
    "path_safe_name": "manifest",
    "resolve_within": "manifest",
    "save_manifest": "manifest",
    "utc_now": "manifest",
    "utc_now_iso": "manifest",
    # provenance
    "PROVENANCE_SCHEMA_VERSION": "provenance",
    "STATUS_REGISTERED": "provenance",
    "STATUS_UNDER_REVIEW": "provenance",
    "ProvenanceRecord": "provenance",
    "build_provenance": "provenance",
    "load_provenance": "provenance",
    "save_provenance": "provenance",
    # intake
    "DEFAULT_WORKSPACE_ROOT": "intake",
    "EvidenceIntake": "intake",
    "EvidenceIntegrityError": "intake",
    "EvidenceRecord": "intake",
    "EvidenceResolutionError": "intake",
    "EvidenceWorkspace": "intake",
    "ResolvedEvidence": "intake",
    "intake_file": "intake",
    "safe_member_name": "intake",
    "unlock_preserved_original": "intake",
    "validate_evidence_id": "intake",
    "validate_package": "intake",
}


def __getattr__(name: str) -> Any:
    """Resolve a public name from its submodule on first access."""

    module_name = _EXPORTS.get(name)

    if module_name is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    from importlib import import_module

    module = import_module(f"{__name__}.{module_name}")

    value = getattr(module, name)

    globals()[name] = value

    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(_EXPORTS))
