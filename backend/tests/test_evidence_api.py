"""Tests for the evidence integrity the adapter transports.

These tests are about one thing: whether the adapter reports the evidence trust
layer's verification faithfully. They deliberately do not test the trust layer
itself, which has its own suite, and they contain no digest logic of their own.
Every assertion is on a value the trust layer produced.

The store used here is a temporary one, registered through the framework's own
``intake``, so a submission is preserved, given a working copy, and recorded in a
manifest exactly as a real one is. Tampering is done by unlocking the preserved
original with the framework's own named maintenance action and appending a byte,
which is the situation the recorded digest exists to detect. No file in the
repository's evidence store is read or written by these tests.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from framework.evidence.integrity import (
    EvidenceNotFoundError,
    EvidenceValidationError,
    IntegrityStatus,
)
from framework.evidence.intake import (
    EvidenceIntake,
    intake_file,
    unlock_preserved_original,
)

from backend import evidence_store
from backend.app import _evidence_error, app
from backend.datasets import repository_root


# --------------------------------------------------------------------- fixtures


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A temporary evidence store, and the ID of one registered submission."""

    root = tmp_path / "evidence"
    monkeypatch.setattr(evidence_store, "EVIDENCE_ROOT", str(root))

    source = tmp_path / "submission.csv"
    source.write_text("event_id,timestamp\n1,2026-01-01T00:00:00Z\n")

    record = intake_file(source, root=root, source_identifier="TEST-001")

    return {"root": str(root), "evidence_id": record.evidence_id, "source": source}


def tamper(path) -> None:
    """Modify a file the way a modification would really happen."""

    unlock_preserved_original(path)

    with open(path, "ab") as handle:
        handle.write(b"2,2026-01-02T00:00:00Z\n")


# ------------------------------------------------------------------- reporting


def test_verified_submission_reports_both_copies(store):
    described = evidence_store.describe(store["evidence_id"])

    assert described["overall_status"] == IntegrityStatus.VERIFIED.value
    assert described["original"]["status"] == IntegrityStatus.VERIFIED.value
    assert described["working"]["status"] == IntegrityStatus.VERIFIED.value
    assert described["analysis"]["permitted"] is True
    assert described["analysis"]["blocked_reason"] is None


def test_expected_and_observed_digests_are_the_manifest_and_the_file(store):
    described = evidence_store.describe(store["evidence_id"])

    registered = described["registered_sha256"]

    # The expected value is the digest recorded at registration, and it is the
    # same value both copies are compared against.
    assert registered
    assert described["original"]["expected_sha256"] == registered
    assert described["working"]["expected_sha256"] == registered

    # A verified comparison reports the same digest on both sides. The interface
    # shows these, so neither may be missing.
    assert described["original"]["observed_sha256"] == registered
    assert described["working"]["observed_sha256"] == registered


def test_provenance_is_carried_with_its_unavailable_fields(store):
    described = evidence_store.describe(store["evidence_id"])

    provenance = described["provenance"]

    assert provenance is not None
    assert provenance["source_identifier"] == "TEST-001"

    # Fields that were not supplied are listed rather than filled in.
    assert "submitted_by" in provenance["unavailable_fields"]


def test_subject_paths_are_repository_relative(store):
    described = evidence_store.describe(store["evidence_id"])

    for subject in ("original", "working"):
        path = described[subject]["path"]

        assert path is not None
        assert not os.path.isabs(path)


# ------------------------------------------------------------------ verification


def test_verify_reruns_the_comparison_rather_than_reporting_a_stored_status(store):
    intake = EvidenceIntake(store["root"])
    working = intake.workspace.working_copy_path(
        store["evidence_id"], "submission.csv"
    )

    assert evidence_store.verify(store["evidence_id"])["overall_status"] == "VERIFIED"

    tamper(working)

    assert evidence_store.verify(store["evidence_id"])["overall_status"] == "INTEGRITY_FAILED"


def test_tampered_working_copy_blocks_analysis_and_reports_both_digests(store):
    intake = EvidenceIntake(store["root"])
    working = intake.workspace.working_copy_path(
        store["evidence_id"], "submission.csv"
    )

    registered = evidence_store.describe(store["evidence_id"])["registered_sha256"]

    tamper(working)

    described = evidence_store.verify(store["evidence_id"])

    assert described["overall_status"] == IntegrityStatus.INTEGRITY_FAILED.value
    assert described["working"]["status"] == IntegrityStatus.INTEGRITY_FAILED.value
    assert described["working"]["expected_sha256"] == registered
    assert described["working"]["observed_sha256"] not in (None, registered)

    # The original was verified before the working copy was reached, so it is
    # reported as verified and the gate is still closed.
    assert described["original"]["status"] == IntegrityStatus.VERIFIED.value
    assert described["analysis"]["permitted"] is False
    assert described["analysis"]["blocked_reason"]


def test_tampered_original_is_reported_and_the_working_copy_is_not_claimed_verified(store):
    intake = EvidenceIntake(store["root"])
    original = next(
        entry
        for entry in intake.load_manifest(store["evidence_id"]).files
        if entry.role == "original"
    )
    preserved = intake.workspace.evidence_dir(store["evidence_id"]) / original.relative_path

    tamper(preserved)

    described = evidence_store.verify(store["evidence_id"])

    assert described["overall_status"] == IntegrityStatus.INTEGRITY_FAILED.value
    assert described["original"]["status"] == IntegrityStatus.INTEGRITY_FAILED.value
    assert described["original"]["observed_sha256"] not in (None, described["registered_sha256"])
    assert described["analysis"]["permitted"] is False

    # Verification stops at the first subject that fails, so the working copy is
    # reported as not checked. It must never be shown as verified.
    assert described["working"]["status"] == IntegrityStatus.UNAVAILABLE.value
    assert described["working"]["observed_sha256"] is None


def test_restoring_the_file_returns_the_submission_to_verified(store):
    intake = EvidenceIntake(store["root"])
    working = intake.workspace.working_copy_path(
        store["evidence_id"], "submission.csv"
    )

    original_bytes = open(working, "rb").read()

    tamper(working)
    assert evidence_store.verify(store["evidence_id"])["overall_status"] == "INTEGRITY_FAILED"

    open(working, "wb").write(original_bytes)

    described = evidence_store.verify(store["evidence_id"])

    assert described["overall_status"] == IntegrityStatus.VERIFIED.value
    assert described["analysis"]["permitted"] is True


# ------------------------------------------------------------------- inventory


def test_inventory_lists_the_submission(store):
    items = evidence_store.inventory()

    assert [item["evidence_id"] for item in items] == [store["evidence_id"]]


def test_inventory_reports_an_unreadable_registration_rather_than_hiding_it(store):
    intake = EvidenceIntake(store["root"])

    # A manifest that cannot be parsed: the submission is registered, so it has
    # to stay visible. Hiding it would make the store look as though it held one
    # submission rather than two.
    broken = "SATSA-EV-20260101T000000Z-000000000000"
    (intake.workspace.manifests_dir / f"{broken}.manifest.json").write_text("{ not json")

    items = evidence_store.inventory()

    unreadable = [item for item in items if item["evidence_id"] == broken]

    assert len(unreadable) == 1
    assert unreadable[0]["overall_status"] == IntegrityStatus.UNAVAILABLE.value
    assert unreadable[0]["registered_sha256"] is None
    assert unreadable[0]["analysis"]["permitted"] is False
    assert unreadable[0]["analysis"]["blocked_reason"]

    # The readable submission beside it is still reported normally.
    assert [item["evidence_id"] for item in items if item["overall_status"] == "VERIFIED"] == [
        store["evidence_id"]
    ]


# ---------------------------------------------------------------------- errors


def test_unknown_identifier_is_not_found(store):
    with pytest.raises(EvidenceNotFoundError):
        evidence_store.describe("SATSA-EV-20260101T000000Z-000000000000")


def test_malformed_identifier_is_rejected(store):
    with pytest.raises(EvidenceValidationError):
        evidence_store.describe("not an evidence id")


def test_unknown_identifier_maps_to_404_and_a_malformed_one_to_400():
    assert _evidence_error(EvidenceNotFoundError("nope")).status_code == 404
    assert _evidence_error(EvidenceValidationError("nope")).status_code == 400


# ---------------------------------------------------------------------- routes


def test_the_evidence_routes_are_registered():
    routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/api/evidence", "GET") in routes
    assert ("/api/evidence/{evidence_id}", "GET") in routes
    assert ("/api/evidence/{evidence_id}/verify", "POST") in routes


# ------------------------------------------------------------------- the gate


def in_store(*parts: str) -> str:
    """A path inside the store, as the adapter would receive it.

    The adapter compares repository-relative paths, so a test that moved the
    store to a temporary directory has to describe its paths the same way.
    """

    absolute = os.path.join(evidence_store.EVIDENCE_ROOT, *parts)

    return os.path.relpath(absolute, repository_root()).replace(os.sep, "/")


def test_an_ordinary_dataset_is_not_gated(store):
    assert evidence_store.gate_dataset("data/demo/incident_event_log.csv") is None


def test_a_verified_working_copy_is_permitted(store):
    target = evidence_store.gate_dataset(
        in_store("working", store["evidence_id"], "dataset", "submission.csv")
    )

    assert target is not None
    assert target["evidence_id"] == store["evidence_id"]
    assert target["original_integrity"]["status"] == "VERIFIED"
    assert target["working_integrity"]["status"] == "VERIFIED"


def test_a_tampered_working_copy_cannot_be_analysed(store):
    intake = EvidenceIntake(store["root"])
    working = intake.workspace.working_copy_path(store["evidence_id"], "submission.csv")

    tamper(working)

    with pytest.raises(evidence_store.EvidenceAnalysisBlocked) as blocked:
        evidence_store.gate_dataset(
            in_store("working", store["evidence_id"], "dataset", "submission.csv")
        )

    # The refusal carries the trust layer's comparison, so the reason a run was
    # refused can be reported without hashing anything again.
    assert blocked.value.comparison is not None
    assert blocked.value.comparison.status is IntegrityStatus.INTEGRITY_FAILED
    assert blocked.value.comparison.expected_sha256
    assert blocked.value.comparison.observed_sha256


def test_a_preserved_original_is_never_an_analysis_target(store):
    with pytest.raises(evidence_store.EvidenceAnalysisBlocked) as blocked:
        evidence_store.gate_dataset(
            in_store("originals", store["evidence_id"], "submission.csv")
        )

    assert "preserved original" in str(blocked.value)


def test_a_register_manifest_is_not_an_analysis_target(store):
    with pytest.raises(evidence_store.EvidenceAnalysisBlocked):
        evidence_store.gate_dataset(
            in_store("manifests", f"{store['evidence_id']}.manifest.json")
        )


def test_an_unregistered_working_copy_cannot_be_analysed(store):
    with pytest.raises(evidence_store.EvidenceAnalysisBlocked):
        evidence_store.gate_dataset(
            in_store("working", "SATSA-EV-20260101T000000Z-000000000000", "dataset", "x.csv")
        )
