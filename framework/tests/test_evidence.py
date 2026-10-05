"""
Tests for the SAT-SA evidence integrity layer.

The evidence layer is deliberately dataset-agnostic, so these tests build their
own throwaway evidence in pytest temporary directories. They do not read, write
or depend on any of the project's datasets, and they never touch the real
``data/evidence`` workspace.

Run with::

    python -m pytest framework/tests/test_evidence.py -v
"""

import hashlib
import ast
import json
import os
import stat
import zipfile

import pytest

from framework.evidence.integrity import (
    EvidenceConflictError,
    EvidenceNotFoundError,
    EvidenceValidationError,
    IntegrityStatus,
    UnsafeArchiveError,
    calculate_sha256,
    is_sha256,
    normalise_sha256,
    verify_sha256,
)
from framework.evidence.intake import (
    EvidenceIntake,
    safe_member_name,
    unlock_preserved_original,
    validate_package,
)
from framework.evidence.manifest import (
    build_manifest,
    classify_file,
    generate_evidence_id,
    load_manifest,
    path_safe_name,
    resolve_within,
    save_manifest,
    utc_now,
)
from framework.evidence.provenance import (
    STATUS_REGISTERED,
    build_provenance,
    load_provenance,
    save_provenance,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def write_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def csv_evidence(path, body="alert_id,severity\nA-1,HIGH\nA-2,LOW\n"):
    return write_bytes(path, body.encode("utf-8"))


def json_evidence(path, body=None):
    if body is None:
        body = json.dumps({"alerts": [{"id": "A-1"}]})
    return write_bytes(path, body.encode("utf-8"))


def binary_evidence(path, size=4096, seed=7):
    return write_bytes(
        path,
        bytes((index * seed) % 256 for index in range(size)),
    )


def make_zip(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


@pytest.fixture
def workspace(tmp_path):
    return tmp_path / "evidence_store"


@pytest.fixture
def intake(workspace):
    return EvidenceIntake(root=workspace)


# ---------------------------------------------------------------------------
# 1-2. SHA-256 calculation, determinism
# ---------------------------------------------------------------------------


def test_calculate_sha256_matches_hashlib(tmp_path):
    sample = tmp_path / "evidence.bin"
    payload = os.urandom(2048)
    sample.write_bytes(payload)

    assert calculate_sha256(sample) == hashlib.sha256(payload).hexdigest()


def test_calculate_sha256_handles_csv_json_and_binary(tmp_path):
    csv_file = csv_evidence(tmp_path / "alerts.csv")
    json_file = json_evidence(tmp_path / "investigations.json")
    binary_file = binary_evidence(tmp_path / "capture.pcap")

    for path in (csv_file, json_file, binary_file):
        digest = calculate_sha256(path)

        assert is_sha256(digest)
        assert len(digest) == 64


def test_same_file_produces_same_hash(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")

    assert calculate_sha256(sample) == calculate_sha256(sample)


def test_identical_content_in_different_files_produces_same_hash(tmp_path):
    first = csv_evidence(tmp_path / "one.csv")
    second = csv_evidence(tmp_path / "two.csv")

    assert calculate_sha256(first) == calculate_sha256(second)


def test_chunked_reading_does_not_change_the_digest(tmp_path):
    sample = binary_evidence(tmp_path / "large.bin", size=70000)

    assert calculate_sha256(sample, chunk_size=1) == calculate_sha256(
        sample, chunk_size=65536
    )


def test_empty_file_has_the_well_known_digest(tmp_path):
    empty = write_bytes(tmp_path / "empty.csv", b"")

    assert (
        calculate_sha256(empty)
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


# ---------------------------------------------------------------------------
# 3. Modified file produces a different hash
# ---------------------------------------------------------------------------


def test_modified_file_produces_a_different_hash(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")
    before = calculate_sha256(sample)

    sample.write_text("alert_id,severity\nA-1,HIGH\nA-2,CRITICAL\n")

    assert calculate_sha256(sample) != before


def test_append_only_change_is_detected(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")
    before = calculate_sha256(sample)

    with sample.open("a", encoding="utf-8") as handle:
        handle.write("A-3,MEDIUM\n")

    assert calculate_sha256(sample) != before


# ---------------------------------------------------------------------------
# 4-5. verify_sha256 success and failure
# ---------------------------------------------------------------------------


def test_verify_sha256_returns_verified_for_untouched_file(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")
    registered = calculate_sha256(sample)

    result = verify_sha256(sample, registered)

    assert result.status is IntegrityStatus.VERIFIED
    assert result.verified is True
    assert result.failed is False
    assert result.expected_sha256 == registered
    assert result.observed_sha256 == registered
    assert result.status_label == "VERIFIED"


def test_verify_sha256_detects_modification(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")
    registered = calculate_sha256(sample)

    sample.write_text("alert_id,severity\nA-1,LOW\n")

    result = verify_sha256(sample, registered)

    assert result.status is IntegrityStatus.INTEGRITY_FAILED
    assert result.verified is False
    assert result.failed is True
    assert result.expected_sha256 == registered
    assert result.observed_sha256 == calculate_sha256(sample)
    assert result.expected_sha256 != result.observed_sha256
    assert "INTEGRITY_FAILED" in result.describe()


def test_verify_sha256_does_not_silently_accept_a_changed_file(tmp_path):
    sample = binary_evidence(tmp_path / "capture.pcap")
    registered = calculate_sha256(sample)

    payload = bytearray(sample.read_bytes())
    payload[0] ^= 0xFF
    sample.write_bytes(bytes(payload))

    result = verify_sha256(sample, registered)

    assert result.status is IntegrityStatus.INTEGRITY_FAILED
    assert "INTEGRITY_FAILED" in result.to_dict()["status"]


def test_verify_sha256_reports_missing_file(tmp_path):
    registered = "0" * 64

    result = verify_sha256(tmp_path / "absent.csv", registered)

    assert result.status is IntegrityStatus.MISSING
    assert result.verified is False


def test_verify_sha256_reports_unavailable_without_a_registered_hash(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")

    assert (
        verify_sha256(sample, None).status is IntegrityStatus.UNAVAILABLE
    )
    assert (
        verify_sha256(sample, "   ").status is IntegrityStatus.UNAVAILABLE
    )


def test_verify_sha256_refuses_a_malformed_digest(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")

    result = verify_sha256(sample, "not-a-digest")

    assert result.status is IntegrityStatus.UNAVAILABLE
    assert result.verified is False


def test_verify_sha256_accepts_labelled_digests(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")
    registered = calculate_sha256(sample)

    assert normalise_sha256(f"sha256:{registered}") == registered
    assert verify_sha256(sample, f"SHA256:{registered}").verified is True


def test_verify_sha256_rejects_a_directory(tmp_path):
    directory = tmp_path / "evidence_dir"
    directory.mkdir()

    result = verify_sha256(directory, "0" * 64)

    assert result.status is IntegrityStatus.UNAVAILABLE
    assert result.verified is False


# ---------------------------------------------------------------------------
# Missing / invalid paths
# ---------------------------------------------------------------------------


def test_calculate_sha256_raises_for_missing_file(tmp_path):
    with pytest.raises(EvidenceNotFoundError):
        calculate_sha256(tmp_path / "no_such_file.csv")


def test_calculate_sha256_raises_for_directory(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(EvidenceValidationError):
        calculate_sha256(directory)


def test_intake_reports_a_missing_source_cleanly(intake, tmp_path):
    with pytest.raises(EvidenceNotFoundError):
        intake.intake(tmp_path / "no_such_submission.csv")


def test_intake_rejects_a_directory_source(intake, tmp_path):
    directory = tmp_path / "submission_dir"
    directory.mkdir()

    with pytest.raises(EvidenceValidationError):
        intake.intake(directory)


# ---------------------------------------------------------------------------
# 6-7. Manifest content and evidence ID
# ---------------------------------------------------------------------------


def test_manifest_records_filename_size_and_sha256(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv", "alert_id,severity\nA-1,HIGH\n")

    record = intake.intake(source)
    manifest = intake.load_manifest(record.evidence_id)

    assert manifest.evidence_id == record.evidence_id
    assert manifest.hash_algorithm == "sha256"
    assert manifest.file_count == 1

    entry = manifest.files[0]

    assert entry.name == "alerts.csv"
    assert entry.stored_name == "alerts.csv"
    assert entry.size == source.stat().st_size
    assert entry.sha256 == calculate_sha256(source)
    assert is_sha256(entry.sha256)
    assert manifest.total_size == entry.size


def test_manifest_is_written_as_json_with_a_utc_timestamp(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)
    payload = json.loads(intake.manifest_path(record.evidence_id).read_text())

    assert payload["evidence_id"] == record.evidence_id
    assert payload["created_at"].endswith("Z")
    assert payload["files"][0]["sha256"] == calculate_sha256(source)
    assert payload["file_count"] == 1
    assert payload["total_size"] == source.stat().st_size


def test_manifest_round_trips_through_disk(intake, tmp_path):
    source = json_evidence(tmp_path / "investigations.json")

    record = intake.intake(source)
    reloaded = load_manifest(intake.manifest_path(record.evidence_id))

    assert reloaded.to_dict() == record.manifest.to_dict()


def test_manifest_works_for_arbitrary_file_types(intake, tmp_path):
    binary = binary_evidence(tmp_path / "network_capture.pcap")
    archive = make_zip(tmp_path / "package.zip", {"a.csv": "x\n"})

    for source in (binary, archive):
        entry = intake.intake(source).manifest.files[0]

        assert entry.size == source.stat().st_size
        assert entry.sha256 == calculate_sha256(source)


def test_evidence_id_is_generated_and_prefixed(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)

    assert record.evidence_id.startswith("SATSA-EV-")
    assert len(record.evidence_id) > len("SATSA-EV-")

    assert record.evidence_id in intake.workspace.list_evidence_ids()


def test_evidence_id_contains_no_entity_or_dataset_specific_text(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    evidence_id = intake.intake(source).evidence_id

    for forbidden in ("alerts", "csv", "cse", "entity", "sector"):
        assert forbidden not in evidence_id.lower()


def test_generate_evidence_id_is_stable_for_the_same_input():
    digest = "a" * 64
    moment = utc_now()

    first = generate_evidence_id(digest, moment)
    second = generate_evidence_id(digest, moment)

    assert first == second
    assert digest[:12] in first
    assert first.startswith("SATSA-EV-")


def test_generate_evidence_id_differs_for_different_content():
    moment = utc_now()

    assert generate_evidence_id("a" * 64, moment) != generate_evidence_id(
        "b" * 64, moment
    )


def test_generate_evidence_id_falls_back_to_a_unique_suffix():
    assert generate_evidence_id().startswith("SATSA-EV-")


# ---------------------------------------------------------------------------
# 8. Provenance
# ---------------------------------------------------------------------------


def test_provenance_is_generated_from_supplied_context(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(
        source,
        source_identifier="CSE-EXAMPLE-001",
        assessment_period="2026-Q1",
        submitted_by="Examination Cell",
    )

    provenance = intake.load_provenance(record.evidence_id)

    assert provenance.evidence_id == record.evidence_id
    assert provenance.original_filename == "alerts.csv"
    assert provenance.file_size == source.stat().st_size
    assert provenance.sha256 == calculate_sha256(source)
    assert provenance.received_at.endswith("Z")
    assert provenance.status == STATUS_REGISTERED


def test_provenance_leaves_unsupplied_fields_explicitly_unavailable(
    intake,
    tmp_path,
):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)
    provenance = intake.load_provenance(record.evidence_id)

    assert provenance.source_identifier is None
    assert provenance.submitted_by is None
    assert provenance.assessment_period is None

    assert "source_identifier" in provenance.unavailable_fields
    assert "submitted_by" in provenance.unavailable_fields
    assert "assessment_period" in provenance.unavailable_fields

    payload = provenance.to_dict()

    assert payload["source_identifier"] is None
    assert payload["unavailable_fields"]


def test_provenance_never_invents_submitter_details(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)
    payload = intake.load_provenance(record.evidence_id).to_dict()

    assert payload["submitted_by"] is None
    assert payload["assessment_period"] is None


def test_provenance_records_a_chain_of_custody(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)

    actions = [
        event["action"]
        for event in record.provenance.custody_events
    ]

    assert "EVIDENCE_RECEIVED" in actions
    assert "ORIGINAL_PRESERVED" in actions
    assert "ANALYSIS_COPY_CREATED" in actions


def test_provenance_round_trips_through_disk(tmp_path):
    record = build_provenance(
        evidence_id="SATSA-EV-TEST-0001",
        original_filename="alerts.csv",
        file_size=12,
        sha256="b" * 64,
        source_identifier="SRC-1",
    )

    target = save_provenance(record, tmp_path / "p.json")

    assert load_provenance(target).to_dict() == record.to_dict()


def test_provenance_stores_metadata_not_file_contents(intake, tmp_path):
    secret = "UNIQUE-CONFIDENTIAL-TOKEN-9931"
    source = csv_evidence(
        tmp_path / "alerts.csv",
        f"alert_id,notes\nA-1,{secret}\n",
    )

    record = intake.intake(source)

    for document in (
        intake.manifest_path(record.evidence_id).read_text(),
        intake.provenance_path(record.evidence_id).read_text(),
    ):
        assert secret not in document


# ---------------------------------------------------------------------------
# 9. Original and working copy are separate
# ---------------------------------------------------------------------------


def test_original_and_working_copy_are_separate_files(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)

    assert record.original_path.is_file()
    assert record.working_path.is_file()
    assert record.original_path.resolve() != record.working_path.resolve()
    assert record.original_path != record.working_path
    assert record.working_path.is_relative_to(intake.workspace.working_dir)


def test_original_is_preserved_byte_identical_to_the_submission(
    intake,
    tmp_path,
):
    source = csv_evidence(tmp_path / "alerts.csv")
    expected = calculate_sha256(source)

    record = intake.intake(source)

    assert calculate_sha256(record.original_path) == expected
    assert calculate_sha256(record.working_path) == expected


def test_working_copy_under_originals_directory(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)

    assert record.original_path.is_relative_to(intake.workspace.originals_dir)
    assert not record.working_path.is_relative_to(
        intake.workspace.originals_dir
    )


def test_analysis_of_the_working_copy_does_not_alter_the_original(
    intake,
    tmp_path,
):
    source = csv_evidence(tmp_path / "alerts.csv")
    record = intake.intake(source)
    registered = calculate_sha256(record.original_path)

    # Simulate the analysis layer writing to the working copy.
    record.working_path.write_text("mutated,by,analysis\n", encoding="utf-8")

    assert calculate_sha256(record.working_path) != registered
    assert calculate_sha256(record.original_path) == registered

    results = intake.verify(record.evidence_id)
    original_result = next(
        result for result in results if result.path == str(record.original_path)
    )

    assert original_result.verified is True


def test_original_is_marked_read_only(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)

    mode = stat.S_IMODE(os.stat(record.original_path).st_mode)

    assert not mode & stat.S_IWUSR
    assert record.manifest.originals_read_only is True


def test_workspace_layout_is_created(intake):
    for directory in (
        intake.workspace.originals_dir,
        intake.workspace.manifests_dir,
        intake.workspace.provenance_dir,
        intake.workspace.working_dir,
    ):
        assert directory.is_dir()


def test_existing_evidence_is_never_overwritten(intake, tmp_path):
    first = csv_evidence(tmp_path / "alerts.csv", "alert_id,severity\nA-1,HIGH\n")
    record = intake.intake(first)

    with pytest.raises(EvidenceConflictError):
        intake.intake(first)

    assert calculate_sha256(record.original_path) == calculate_sha256(first)
    assert record.original_path.read_text() == first.read_text()


def test_byte_identical_resubmission_is_refused_regardless_of_time(
    intake,
    tmp_path,
):
    """Duplicate detection must not depend on clock resolution."""

    first = csv_evidence(tmp_path / "alerts.csv")
    record = intake.intake(first)

    later = tmp_path / "resubmission"
    later.mkdir()
    copy = later / "alerts.csv"
    copy.write_bytes(first.read_bytes())

    with pytest.raises(EvidenceConflictError) as error:
        intake.intake(copy)

    assert record.evidence_id in str(error.value)
    assert len(intake.workspace.list_evidence_ids()) == 1


def test_duplicate_can_be_registered_explicitly(intake, tmp_path):
    first = csv_evidence(tmp_path / "alerts.csv")
    record = intake.intake(first)

    second = intake.intake(first, allow_duplicate=True)

    assert second.evidence_id != record.evidence_id
    assert second.original_path != record.original_path
    assert len(intake.workspace.list_evidence_ids()) == 2
    assert calculate_sha256(record.original_path) == calculate_sha256(first)


def test_find_registered_digest_locates_the_original(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")

    record = intake.intake(source)
    located = intake.find_registered_digest(calculate_sha256(source))

    assert located is not None
    assert located["evidence_id"] == record.evidence_id
    assert intake.find_registered_digest("0" * 64) is None


def test_preserved_original_cannot_be_reregistered_as_new_evidence(
    intake,
    tmp_path,
):
    source = csv_evidence(tmp_path / "alerts.csv")
    record = intake.intake(source)

    with pytest.raises(EvidenceValidationError):
        intake.intake(record.original_path)


# ---------------------------------------------------------------------------
# Tamper detection against a preserved original
# ---------------------------------------------------------------------------


def test_tampering_with_a_preserved_original_is_reported(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")
    registered = calculate_sha256(source)
    record = intake.intake(source)

    unlock_preserved_original(record.original_path)
    record.original_path.write_text(
        "alert_id,severity\nA-1,LOW\nA-9,HIGH\n",
        encoding="utf-8",
    )

    results = intake.verify(record.evidence_id)
    tampered = next(
        result for result in results if result.path == str(record.original_path)
    )

    assert tampered.status is IntegrityStatus.INTEGRITY_FAILED
    assert tampered.expected_sha256 == registered
    assert tampered.observed_sha256 != registered
    assert "INTEGRITY FAILED" in tampered.describe().replace("_", " ")


def test_deleted_evidence_is_reported_as_missing(intake, tmp_path):
    source = csv_evidence(tmp_path / "alerts.csv")
    record = intake.intake(source)

    unlock_preserved_original(record.original_path)
    record.original_path.unlink()

    results = intake.verify(record.evidence_id)

    assert [result.status for result in results] == [IntegrityStatus.MISSING]


def test_intake_refuses_to_proceed_on_an_unverifiable_preservation(
    intake,
    tmp_path,
    monkeypatch,
):
    source = csv_evidence(tmp_path / "alerts.csv")

    import framework.evidence.intake as intake_module

    monkeypatch.setattr(
        intake_module,
        "verify_sha256",
        lambda path, expected: _forced_failure(path, expected),
    )

    with pytest.raises(EvidenceValidationError):
        intake.intake(source)

    # A failed intake must not leave a half-registered submission behind.
    assert intake.workspace.list_evidence_ids() == []


def _forced_failure(path, expected):
    from framework.evidence.integrity import IntegrityResult

    return IntegrityResult(
        status=IntegrityStatus.INTEGRITY_FAILED,
        path=str(path),
        expected_sha256=expected,
        observed_sha256="f" * 64,
        detail="forced",
    )


def test_registered_evidence_can_be_listed(intake, tmp_path):
    csv_evidence(tmp_path / "alerts.csv")
    json_evidence(tmp_path / "investigations.json")

    intake.intake(tmp_path / "alerts.csv")
    intake.intake(tmp_path / "investigations.json")

    inventory = intake.list_evidence()

    assert len(inventory) == 2
    assert {entry["integrity"] for entry in inventory} == {"VERIFIED"}


# ---------------------------------------------------------------------------
# 11. ZIP safety
# ---------------------------------------------------------------------------


def test_zip_package_is_registered_with_its_own_digest(intake, tmp_path):
    archive = make_zip(
        tmp_path / "package.zip",
        {"alerts.csv": "alert_id\nA-1\n", "assets.json": "{}"},
    )

    record = intake.intake(archive)
    original_entry = record.manifest.files[0]

    assert original_entry.name == "package.zip"
    assert original_entry.content_type == "zip"
    assert original_entry.sha256 == calculate_sha256(archive)
    assert record.manifest.file_count == 3


def test_zip_members_are_extracted_and_registered(intake, tmp_path):
    archive = make_zip(
        tmp_path / "package.zip",
        {"alerts.csv": "alert_id\nA-1\n", "nested/assets.json": "{}"},
    )

    record = intake.intake(archive)
    working_root = intake.workspace.working_dir / record.evidence_id

    names = {entry.name for entry in record.manifest.files}

    assert "alerts.csv" in names
    assert "nested/assets.json" in names

    for entry in record.manifest.files:
        if entry.role != "extracted":
            continue

        assert entry.location == "working"
        assert entry.relative_path.startswith("package/")

        extracted = resolve_within(working_root, entry.relative_path)

        assert extracted.is_file()
        assert entry.sha256 == calculate_sha256(extracted)

    assert all(
        result.verified
        for result in intake.verify(record.evidence_id)
    )


def test_zip_without_extraction_is_still_registered(intake, tmp_path):
    archive = make_zip(tmp_path / "package.zip", {"alerts.csv": "a\n"})

    record = intake.intake(archive, extract_package=False)

    assert record.manifest.file_count == 1
    assert record.package_members == []


@pytest.mark.parametrize(
    "member_name",
    [
        "../escape.csv",
        "../../etc/passwd",
        "nested/../../escape.csv",
        "/absolute/escape.csv",
        "C:/windows/system32/evil.dll",
        "..\\windows\\escape.csv",
    ],
)
def test_zip_path_traversal_is_rejected(intake, tmp_path, member_name):
    archive = tmp_path / "hostile.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(member_name, "payload")

    with pytest.raises(UnsafeArchiveError):
        intake.intake(archive)

    assert not (tmp_path / "escape.csv").exists()
    assert intake.workspace.list_evidence_ids() == []


def test_unsafe_member_name_rejection_is_case_specific():
    assert safe_member_name("alerts.csv") == "alerts.csv"
    assert safe_member_name("nested/alerts.csv") == "nested/alerts.csv"
    assert safe_member_name("./nested//alerts.csv") == "nested/alerts.csv"

    for hostile in (
        "../x",
        "a/../../x",
        "/x",
        "C:/x",
        "..\\x",
        "",
        "   ",
    ):
        with pytest.raises(UnsafeArchiveError):
            safe_member_name(hostile)


def test_zip_rejects_deeply_nested_members(tmp_path):
    member = "/".join(f"level{index}" for index in range(40)) + "/x.csv"
    archive = make_zip(tmp_path / "deep.zip", {member: "x"})

    with pytest.raises(UnsafeArchiveError):
        validate_package(archive)


def test_zip_rejects_oversized_member_declarations(tmp_path):
    archive = make_zip(tmp_path / "bomb.zip", {"big.csv": "x" * 4096})

    with pytest.raises(UnsafeArchiveError):
        validate_package(archive, max_member_bytes=1024)


def test_zip_rejects_oversized_total_declarations(tmp_path):
    archive = make_zip(
        tmp_path / "bomb.zip",
        {f"file{index}.csv": "x" * 512 for index in range(4)},
    )

    with pytest.raises(UnsafeArchiveError):
        validate_package(archive, max_total_bytes=1024)


def test_zip_rejects_too_many_members(tmp_path):
    archive = make_zip(
        tmp_path / "many.zip",
        {f"file{index}.csv": "x" for index in range(12)},
    )

    with pytest.raises(UnsafeArchiveError):
        validate_package(archive, max_members=5)


def test_non_zip_input_is_not_treated_as_a_package(tmp_path):
    sample = csv_evidence(tmp_path / "alerts.csv")

    with pytest.raises(UnsafeArchiveError):
        validate_package(sample)


def test_zip_symlink_member_is_rejected(tmp_path):
    archive = tmp_path / "link.zip"

    with zipfile.ZipFile(archive, "w") as handle:
        info = zipfile.ZipInfo("link.csv")
        info.external_attr = (0o120777 << 16)
        handle.writestr(info, "/etc/passwd")

    with pytest.raises(UnsafeArchiveError):
        validate_package(archive)


def test_extracted_member_never_escapes_the_workspace(intake, tmp_path):
    archive = make_zip(
        tmp_path / "package.zip",
        {"deep/nested/alerts.csv": "alert_id\nA-1\n"},
    )

    record = intake.intake(archive)
    working_root = (intake.workspace.working_dir / record.evidence_id).resolve()

    extracted = [
        entry
        for entry in record.manifest.files
        if entry.role == "extracted"
    ]

    assert extracted

    for entry in extracted:
        resolved = resolve_within(working_root, entry.relative_path).resolve()

        assert resolved.is_file()
        assert working_root in resolved.parents
        assert resolved.is_relative_to(working_root)


def test_resolve_within_refuses_escaping_paths(tmp_path):
    with pytest.raises(EvidenceValidationError):
        resolve_within(tmp_path, "../../etc/passwd")


# ---------------------------------------------------------------------------
# Naming safety
# ---------------------------------------------------------------------------


def test_path_safe_name_neutralises_hostile_filenames():
    assert path_safe_name("alerts.csv") == "alerts.csv"
    assert "/" not in path_safe_name("../../etc/passwd")
    assert path_safe_name("..") == "evidence_file"
    assert path_safe_name("") == "evidence_file"
    assert len(path_safe_name("x" * 500)) <= 129

    assert path_safe_name("a b;rm -rf.csv").startswith("a_b_rm_-rf.csv")


def test_classify_file_labels_content_without_parsing_it(tmp_path):
    assert classify_file(csv_evidence(tmp_path / "a.csv")) == "csv"
    assert classify_file(json_evidence(tmp_path / "a.json")) == "json"

    archive = make_zip(tmp_path / "a.zip", {"x.csv": "1"})

    assert classify_file(archive) == "zip"
    assert classify_file(binary_evidence(tmp_path / "a.pcap")) == "binary"


# ---------------------------------------------------------------------------
# Manifest construction API
# ---------------------------------------------------------------------------


def test_build_manifest_from_dict_entries():
    manifest = build_manifest(
        evidence_id="SATSA-EV-UNIT-0001",
        files=[
            {
                "name": "alerts.csv",
                "stored_name": "alerts.csv",
                "relative_path": "alerts.csv",
                "size": 12,
                "sha256": "c" * 64,
            }
        ],
    )

    assert manifest.file_count == 1
    assert manifest.total_size == 12
    assert manifest.by_name("alerts.csv") is not None
    assert manifest.files[0].location == "originals"


def test_build_manifest_rejects_unsupported_entries():
    with pytest.raises(EvidenceValidationError):
        build_manifest(evidence_id="SATSA-EV-UNIT-0002", files=[object()])


def test_manifest_save_and_load_round_trip(tmp_path):
    manifest = build_manifest(evidence_id="SATSA-EV-UNIT-0003", files=[])

    target = save_manifest(manifest, tmp_path / "m.json")

    assert load_manifest(target).evidence_id == "SATSA-EV-UNIT-0003"


# ---------------------------------------------------------------------------
# 12. The existing SAT-SA framework is untouched by the evidence layer
# ---------------------------------------------------------------------------


def _imported_modules(module):
    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])

    return imported


def _evidence_modules():
    import framework.evidence.integrity as integrity_module
    import framework.evidence.intake as intake_module
    import framework.evidence.manifest as manifest_module
    import framework.evidence.provenance as provenance_module

    return (
        integrity_module,
        manifest_module,
        provenance_module,
        intake_module,
    )


def test_evidence_layer_does_not_import_the_analytics_framework():
    analytics_modules = {
        "pandas",
        "numpy",
        "sklearn",
        "plotly",
        "streamlit",
    }

    for module in _evidence_modules():
        imported = _imported_modules(module)

        assert not imported & analytics_modules, (
            f"{module.__name__} must not depend on analytics libraries"
        )

        for dependency in imported:
            if dependency == "framework":
                continue

            assert not dependency.startswith("framework.supervis"), (
                f"{module.__name__} must not depend on {dependency}"
            )


def test_evidence_layer_makes_no_network_dependency():
    forbidden = {
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "ftplib",
        "smtplib",
        "asyncio",
        "subprocess",
    }

    for module in _evidence_modules():
        assert not _imported_modules(module) & forbidden, (
            f"{module.__name__} must not import network or process-spawning "
            "modules"
        )


def test_evidence_layer_uses_hashlib_for_digests():
    import framework.evidence.integrity as integrity_module

    assert "hashlib" in _imported_modules(integrity_module)


REPO_ROOT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "framework",
    "config",
    "semantic_patterns.json",
)


@pytest.mark.skipif(
    not os.path.isfile(REPO_ROOT_CONFIG),
    reason="SAT-SA pipeline configuration is not reachable from this "
    "working directory",
)
def test_existing_pipeline_runs_against_a_working_copy(intake, tmp_path):
    """The controlled analysis copy feeds the unmodified SAT-SA framework."""

    source = csv_evidence(
        tmp_path / "alerts.csv",
        "priority,host,close_time\nHIGH,WEB_01,120\nLOW,DB_02,45\n",
    )

    record = intake.intake(source)
    registered = calculate_sha256(record.original_path)

    from framework.pipeline import SATSAPipeline

    result = SATSAPipeline().run(str(record.working_path))

    # The existing framework still performs its full analysis.
    assert result["profile"]["dataset_summary"]["records"] == 2
    assert "supervisory_findings" in result
    assert "entity_assessment" in result

    # Analysis of the working copy left the preserved original untouched.
    assert calculate_sha256(record.original_path) == registered
    assert intake.verify(record.evidence_id)[0].verified is True


# ---------------------------------------------------------------------------
# 14. User-visible wording must not overstate the control
# ---------------------------------------------------------------------------

OVERSTATED_CLAIMS = (
    "immutable",
    "tamper-proof",
    "tamperproof",
    "cryptographically immutable",
    "administrator-proof",
    "original set read-only",
)


def test_intake_cli_reports_control_without_overstating_it(intake, tmp_path, capsys):
    """The CLI must describe the control as what it actually is.

    Write protection is a handling control; the fingerprint is what detects
    change. The tool must not imply the stored bytes are unalterable.
    """
    from framework.evidence.intake import main

    source = csv_evidence(tmp_path / "alerts.csv")

    exit_code = main([str(source), "--root", str(intake.root)])

    assert exit_code == 0
    output = capsys.readouterr().out

    # Accurate descriptions of the two real controls.
    assert "Original evidence preserved:" in output
    assert "Application-level write protection enabled:" in output
    assert "SHA-256 integrity fingerprint registered:" in output

    # The original overclaim, and the absence of any immunity claim.
    assert "Original set read-only:" not in output

    # A strong word may appear only inside an explicit denial, never as an
    # assertion about what the tool guarantees.
    negations = ("not ", "no ", "never", "cannot", "without ")
    for line in output.lower().splitlines():
        for phrase in OVERSTATED_CLAIMS:
            if phrase in line:
                assert any(
                    negation in line for negation in negations
                ), f"unqualified claim in: {line!r}"


def test_intake_cli_states_the_privilege_limitation(intake, tmp_path, capsys):
    """The limitation must be visible where the control is announced."""
    from framework.evidence.intake import main

    source = csv_evidence(tmp_path / "alerts.csv")

    main([str(source), "--root", str(intake.root)])

    output = capsys.readouterr().out.lower()

    assert "not made physically immutable" in output
    assert "privileged filesystem user" in output
    assert "its manifest" in output
