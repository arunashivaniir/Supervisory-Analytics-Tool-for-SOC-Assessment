"""
Integration tests: Evidence Trust Layer -> existing SAT-SA pipeline.

These tests cover the seam introduced in Phase 2 and nothing else. Integrity
primitives, manifests, provenance, ZIP safety and tamper semantics are already
covered by ``framework/tests/test_evidence.py`` and are not duplicated here.

The contract under test:

    Evidence ID -> resolve -> verify -> controlled working copy
                -> existing pipeline -> result linked to the evidence ID

Every test builds its own evidence in a pytest temporary directory. No project
dataset is read or written. Tests that reach the analytical engine are skipped
unless the SAT-SA pipeline configuration is reachable from the working
directory, because ``SATSAPipeline`` resolves its config with repository
relative paths (existing behaviour, deliberately unchanged).
"""

import os

import pytest

from framework.evidence.intake import (
    EvidenceError,
    EvidenceIntake,
    EvidenceIntegrityError,
    EvidenceNotFoundError,
    EvidenceResolutionError,
    EvidenceValidationError,
    unlock_preserved_original,
)
from framework.pipeline import (
    USAGE,
    main,
    parse_arguments,
    run_from_evidence,
)


REPOSITORY_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

PIPELINE_CONFIG = os.path.join(
    REPOSITORY_ROOT, "framework", "config", "semantic_patterns.json"
)

requires_pipeline = pytest.mark.skipif(
    not os.path.isfile(PIPELINE_CONFIG),
    reason="SAT-SA pipeline configuration is not reachable from this "
    "working directory",
)


SUMMARY_MARKER = "SAT-SA SUPERVISORY SUMMARY"

ANALYSIS_MARKERS = (
    "Running SAT-SA analysis",
    "Loading dataset",
    "Profiling dataset",
    "Running semantic inference",
    "Generating supervisory findings",
    "Generating entity assessment",
    SUMMARY_MARKER,
)


ANALYSIS_ABORTED = "[!] Analysis aborted"


def write_csv(path, body="alert_id,priority,host,close_time\n"
                          "A-1,HIGH,WEB_01,120\nA-2,LOW,DB_02,45\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path):
    return tmp_path / "evidence_store"


@pytest.fixture
def registered(store, tmp_path):
    """A registered, verified CSV submission and its EvidenceRecord."""

    source = write_csv(tmp_path / "alerts.csv")
    record = EvidenceIntake(root=store).intake(source)

    return record


# ---------------------------------------------------------------------------
# Command line parsing
# ---------------------------------------------------------------------------


def test_direct_dataset_invocation_is_parsed_unchanged():
    assert parse_arguments(["dataset_noisy.csv"]) == (
        "dataset_noisy.csv",
        None,
        None,
    )


def test_evidence_invocation_is_parsed():
    dataset, evidence_id, root = parse_arguments(
        ["--from-evidence", "SATSA-EV-1", "--evidence-root", "store"]
    )

    assert (dataset, evidence_id, root) == (None, "SATSA-EV-1", "store")


def test_evidence_invocation_supports_equals_form():
    dataset, evidence_id, root = parse_arguments(
        ["--from-evidence=SATSA-EV-1", "--evidence-root=store"]
    )

    assert (dataset, evidence_id, root) == (None, "SATSA-EV-1", "store")


def test_unknown_option_is_a_usage_error():
    from framework.pipeline import PipelineUsageError

    with pytest.raises(PipelineUsageError):
        parse_arguments(["--not-a-real-option"])


def test_evidence_id_without_a_value_is_a_usage_error():
    from framework.pipeline import PipelineUsageError

    with pytest.raises(PipelineUsageError):
        parse_arguments(["--from-evidence"])


def test_no_arguments_prints_usage_and_does_not_analyse(capsys):
    assert main([]) == 1

    output = capsys.readouterr().out

    assert USAGE.splitlines()[0] in output
    assert SUMMARY_MARKER not in output


def test_dataset_and_evidence_together_are_refused(capsys, store, registered):
    assert main(
        [
            "some_dataset.csv",
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    ) == 2

    output = capsys.readouterr().out

    assert "not both" in output
    assert SUMMARY_MARKER not in output


# ---------------------------------------------------------------------------
# 1-3. Valid evidence: resolution, working copy, evidence_id in the result
# ---------------------------------------------------------------------------


@requires_pipeline
def test_from_evidence_analyses_the_verified_working_copy(
    capsys,
    store,
    registered,
):
    assert main(
        [
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    ) == 0

    output = capsys.readouterr().out

    assert "[+] Resolving evidence" in output
    assert f"[+] Evidence ID: {registered.evidence_id}" in output
    assert "[+] Verifying evidence integrity" in output
    assert "[+] Integrity status: VERIFIED" in output
    assert "[+] Loading controlled working copy" in output
    assert "[+] Running SAT-SA analysis" in output
    assert SUMMARY_MARKER in output


@requires_pipeline
def test_pipeline_is_never_handed_the_preserved_original(
    capsys,
    store,
    registered,
):
    main(
        [
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    )

    output = capsys.readouterr().out

    # The summary reports what was actually analysed.
    assert f"Dataset: {registered.working_path}" in output
    assert str(registered.original_path) not in output
    assert "dataset" in str(registered.working_path)
    assert "originals" not in str(registered.working_path)


@requires_pipeline
def test_result_carries_the_evidence_id(registered):
    from framework.pipeline import SATSAPipeline

    result = SATSAPipeline().run(
        str(registered.working_path),
        evidence_id=registered.evidence_id,
    )

    assert result["evidence_id"] == registered.evidence_id
    assert result["dataset"] == str(registered.working_path)


@requires_pipeline
def test_evidence_mode_result_keeps_the_existing_schema(
    capsys,
    store,
    registered,
    tmp_path,
):
    from framework.pipeline import SATSAPipeline

    direct = SATSAPipeline().run(str(registered.working_path))
    linked = SATSAPipeline().run(
        str(registered.working_path),
        evidence_id=registered.evidence_id,
    )

    assert set(linked) - set(direct) == {"evidence_id"}
    assert "evidence_id" not in direct

    for key in (
        "dataset",
        "profile",
        "semantic_mapping",
        "mapping_report",
        "dataset_context",
        "canonical_records",
        "feature_analysis",
        "supervisory_findings",
        "entity_assessment",
    ):
        assert key in linked
        assert key in direct

    assert linked["profile"] == direct["profile"]
    assert linked["supervisory_findings"] == direct["supervisory_findings"]


@requires_pipeline
def test_evidence_id_is_printed_in_the_summary(store, registered):
    from framework.pipeline import SATSAPipeline

    result = SATSAPipeline().run(
        str(registered.working_path),
        evidence_id=registered.evidence_id,
    )

    # print_summary only renders the field when present.
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()

    with redirect_stdout(buffer):
        from framework.pipeline import print_summary

        print_summary(result)

    assert f"Evidence ID: {registered.evidence_id}" in buffer.getvalue()


# ---------------------------------------------------------------------------
# 4. Tampered original blocks analysis
# ---------------------------------------------------------------------------


def test_tampered_original_blocks_analysis(capsys, store, registered):
    unlock_preserved_original(registered.original_path)
    registered.original_path.write_text(
        "alert_id,priority,host,close_time\nA-1,LOW,DB_02,45\n",
        encoding="utf-8",
    )

    assert main(
        [
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    ) == 3

    output = capsys.readouterr().out

    assert "[!] Evidence integrity verification failed" in output
    assert "[!] Status: INTEGRITY_FAILED" in output
    assert "[!] Subject: preserved original" in output
    assert "[!] Expected SHA-256: " in output
    assert "[!] Observed SHA-256: " in output
    assert ANALYSIS_ABORTED in output

    for marker in ANALYSIS_MARKERS:
        assert marker not in output


def test_tampered_original_reports_both_digests(capsys, store, registered):
    from framework.evidence import calculate_sha256

    expected = registered.manifest.files[0].sha256

    unlock_preserved_original(registered.original_path)
    registered.original_path.write_text("tampered\n", encoding="utf-8")

    main(
        [
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    )

    output = capsys.readouterr().out

    assert f"[!] Expected SHA-256: {expected}" in output
    assert (
        f"[!] Observed SHA-256: "
        f"{calculate_sha256(registered.original_path)}" in output
    )
    assert expected != calculate_sha256(registered.original_path)


def test_working_copy_tamper_blocks_analysis(capsys, store, registered):
    registered.working_path.write_text("substituted\n", encoding="utf-8")

    assert main(
        [
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    ) == 3

    output = capsys.readouterr().out

    assert "[!] Status: INTEGRITY_FAILED" in output
    assert "[!] Subject: controlled working copy" in output
    assert ANALYSIS_ABORTED in output

    for marker in ANALYSIS_MARKERS:
        assert marker not in output


# ---------------------------------------------------------------------------
# 5. Missing evidence ID blocks analysis
# ---------------------------------------------------------------------------


def test_unregistered_evidence_id_blocks_analysis(capsys, store, tmp_path):
    assert main(
        [
            "--from-evidence",
            "SATSA-EV-20260101T000000Z-000000000000",
            "--evidence-root",
            str(store),
        ]
    ) == 3

    output = capsys.readouterr().out

    assert "[!] EvidenceNotFoundError" in output
    assert "No evidence registration found" in output
    assert ANALYSIS_ABORTED in output

    for marker in ANALYSIS_MARKERS:
        assert marker not in output


@pytest.mark.parametrize(
    "evidence_id",
    [
        "../../../etc/passwd",
        "../../manifests/SATSA-EV-1.manifest.json",
        "/etc/passwd",
        "C:/windows/system32",
        "SATSA-EV-1/../SATSA-EV-2",
        "with space",
        "x" * 200,
    ],
)
def test_hostile_evidence_ids_are_refused_without_touching_disk(
    capsys,
    store,
    evidence_id,
):
    assert main(
        ["--from-evidence", evidence_id, "--evidence-root", str(store)]
    ) == 3

    output = capsys.readouterr().out

    assert ANALYSIS_ABORTED in output
    assert SUMMARY_MARKER not in output


@pytest.mark.parametrize("evidence_id", ["", "   "])
def test_empty_evidence_id_is_a_usage_error(capsys, store, evidence_id):
    assert main(
        ["--from-evidence", evidence_id, "--evidence-root", str(store)]
    ) == 2

    output = capsys.readouterr().out

    assert "requires an evidence ID" in output
    assert SUMMARY_MARKER not in output


def test_a_user_supplied_file_is_never_used_as_a_fallback(
    capsys,
    store,
    registered,
    tmp_path,
):
    """A decoy CSV must not be analysed when verification fails."""

    unlock_preserved_original(registered.original_path)
    registered.original_path.write_text("tampered\n", encoding="utf-8")

    decoy = write_csv(tmp_path / "decoy.csv")

    assert main(
        [
            str(decoy),
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    ) == 2

    assert SUMMARY_MARKER not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 6. Missing original blocks analysis
# ---------------------------------------------------------------------------


def test_missing_original_blocks_analysis(capsys, store, registered):
    unlock_preserved_original(registered.original_path)
    registered.original_path.unlink()

    assert main(
        [
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    ) == 3

    output = capsys.readouterr().out

    assert "[!] Evidence integrity verification failed" in output
    assert "[!] Status: MISSING" in output
    assert "[!] Expected SHA-256: " in output
    assert ANALYSIS_ABORTED in output

    for marker in ANALYSIS_MARKERS:
        assert marker not in output


def test_missing_working_copy_blocks_analysis(capsys, store, registered):
    registered.working_path.unlink()

    assert main(
        [
            "--from-evidence",
            registered.evidence_id,
            "--evidence-root",
            str(store),
        ]
    ) == 3

    output = capsys.readouterr().out

    assert "EvidenceResolutionError" in output
    assert ANALYSIS_ABORTED in output
    assert SUMMARY_MARKER not in output


# ---------------------------------------------------------------------------
# 7. Direct CSV mode remains compatible
# ---------------------------------------------------------------------------


@requires_pipeline
def test_direct_csv_invocation_remains_compatible(capsys, tmp_path):
    source = write_csv(tmp_path / "alerts.csv")

    assert main([str(source)]) == 0

    output = capsys.readouterr().out

    assert f"Dataset: {source}" in output
    assert "[+] Loading dataset" in output
    assert SUMMARY_MARKER in output
    assert "Evidence ID" not in output
    assert "Resolving evidence" not in output


@requires_pipeline
def test_direct_mode_needs_no_evidence_registration(capsys, tmp_path):
    """Normal local development must not depend on the evidence store."""

    source = write_csv(tmp_path / "standalone.csv")

    assert not (tmp_path / "evidence_store").exists()
    assert main([str(source)]) == 0
    assert SUMMARY_MARKER in capsys.readouterr().out


@requires_pipeline
def test_direct_mode_ignores_an_unrelated_evidence_root(
    capsys,
    tmp_path,
):
    source = write_csv(tmp_path / "standalone.csv")

    assert main([str(source), "--evidence-root", str(tmp_path / "absent")]) == 0
    assert SUMMARY_MARKER in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Resolution API behaviour
# ---------------------------------------------------------------------------


def test_resolve_evidence_id_confirms_a_registration(store, registered):
    intake = EvidenceIntake(root=store)

    assert intake.resolve_evidence_id(registered.evidence_id) == (
        registered.evidence_id
    )


def test_verify_analysis_target_returns_the_working_copy(store, registered):
    resolved = EvidenceIntake(root=store).verify_analysis_target(
        registered.evidence_id
    )

    assert resolved.evidence_id == registered.evidence_id
    assert resolved.working_path == registered.working_path
    assert resolved.original_path == registered.original_path
    assert resolved.verified is True
    assert resolved.original_integrity.verified is True
    assert resolved.working_integrity.verified is True


def test_verify_analysis_target_raises_on_tamper(store, registered):
    unlock_preserved_original(registered.original_path)
    registered.original_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(EvidenceIntegrityError) as error:
        EvidenceIntake(root=store).verify_analysis_target(
            registered.evidence_id
        )

    assert error.value.result.status.value == "INTEGRITY_FAILED"
    assert error.value.result.expected_sha256 is not None
    assert error.value.result.observed_sha256 is not None
    assert error.value.result.expected_sha256 != (
        error.value.result.observed_sha256
    )


def test_verify_analysis_target_raises_for_missing_original(store, registered):
    unlock_preserved_original(registered.original_path)
    registered.original_path.unlink()

    with pytest.raises(EvidenceIntegrityError) as error:
        EvidenceIntake(root=store).verify_analysis_target(
            registered.evidence_id
        )

    assert error.value.result.status.value == "MISSING"


def test_verify_analysis_target_raises_for_unknown_id(store):
    with pytest.raises(EvidenceNotFoundError):
        EvidenceIntake(root=store).verify_analysis_target(
            "SATSA-EV-20260101T000000Z-000000000000"
        )


def test_verify_analysis_target_rejects_a_hostile_id(store):
    with pytest.raises(EvidenceValidationError):
        EvidenceIntake(root=store).verify_analysis_target("../../etc/passwd")


def test_run_from_evidence_returns_none_when_unverified(store, registered):
    unlock_preserved_original(registered.original_path)
    registered.original_path.write_text("tampered\n", encoding="utf-8")

    assert run_from_evidence(registered.evidence_id, str(store)) is None


def test_resolution_errors_are_evidence_errors():
    assert issubclass(EvidenceIntegrityError, EvidenceError)
    assert issubclass(EvidenceResolutionError, EvidenceError)
    assert issubclass(EvidenceNotFoundError, EvidenceError)
    assert issubclass(EvidenceValidationError, EvidenceError)


@requires_pipeline
def test_evidence_mode_does_not_bypass_the_existing_engine(
    store,
    registered,
):
    """The analytical result must come from the unmodified pipeline."""

    from framework.pipeline import SATSAPipeline

    evidence_result = run_from_evidence(registered.evidence_id, str(store))
    direct_result = SATSAPipeline().run(str(registered.working_path))

    assert set(evidence_result) - set(direct_result) == {"evidence_id"}
    assert evidence_result["profile"] == direct_result["profile"]
    assert (
        evidence_result["canonical_records"]
        == direct_result["canonical_records"]
    )
    assert evidence_result["entity_assessment"] == direct_result[
        "entity_assessment"
    ]
