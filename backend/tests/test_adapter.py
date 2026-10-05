"""Tests for the local adapter that serves the React interface.

The adapter is the only part of the system this file is about. Nothing here
exercises, asserts or changes an intelligence layer: the pipeline is treated
as a fixed thing that returns a fixed result, and the checks are about whether
the adapter transported that result faithfully, refused a path it should have
refused, and reported a run's lifecycle honestly.

These tests deliberately do not run the pipeline. A real run over real evidence
takes minutes, which would make the adapter's own behaviour untested. The
pipeline's behaviour is covered by the framework suite.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.app import datasets
from backend.datasets import (
    DEMO_ALLOWLIST,
    curated_datasets,
    dataset_mode,
    list_datasets,
    repository_root,
    resolve_dataset,
)
from backend.jobs import (
    MAX_RETAINED,
    OMITTED_KEY_REASON,
    TRANSPORTED_KEYS,
    VOLUMETRIC_KEYS,
    AnalysisStore,
)
from backend.serialisation import serialisable_result

ROOT = repository_root()


# --------------------------------------------------------------------- fixtures


def _pipeline_result() -> dict:
    """A result shaped like the pipeline's, small enough to reason about.

    Built by hand rather than by running the pipeline, because the point of
    every assertion here is what the adapter does to a result, not what the
    result contains.
    """

    return {
        "dataset": "data/demo/incident_event_log.csv",
        "ingestion": {
            "source": "data/demo/incident_event_log.csv",
            "record_count": 2,
            "column_count": 3,
        },
        "assessment": {
            "scope_count": 1,
            "record_count": 2,
            "entity_resolution": {"available": False, "unavailable_reason": None},
        },
        "capability_assessment": {
            "capability_ids": ["CAP_ONE", "CAP_TWO"],
            "scopes": [
                {
                    "assessment_id": "UNKNOWN_ENTITY::UNKNOWN_PERIOD",
                    "status_counts": {"AVAILABLE": 1, "INSUFFICIENT_EVIDENCE": 1},
                }
            ],
        },
        "execution_gap_findings": {"finding_count": 0, "findings": []},
        "anomaly_findings": {
            "anomaly_model_status": {"status": "AVAILABLE", "reason": None},
            "verdict_counts": {"NOT_EVALUABLE": 1},
        },
        "canonical_records": [{"row": 0}, {"row": 1}],
        "feature_analysis": [{"row": 0}, {"row": 1}],
    }


class _StubPipeline:
    """Stands in for ``SATSAPipeline`` so no evidence is read.

    Records the path it was handed, because one of the adapter's guarantees is
    which form of the path the pipeline receives.
    """

    instances: list = []

    def __init__(self) -> None:
        self.received: list = []
        _StubPipeline.instances.append(self)

    def run(self, dataset: str) -> dict:
        self.received.append(dataset)
        return _pipeline_result()


class _FailingPipeline:
    def run(self, dataset: str) -> dict:
        raise RuntimeError("the pipeline refused this evidence")


@pytest.fixture(autouse=True)
def _stub_the_pipeline(monkeypatch, tmp_path):
    """Point the store's pipeline import at a stub, and keep exports in tmp.

    ``jobs.py`` imports the pipeline inside the worker, so the patch target is
    the module attribute rather than a local name.
    """

    import framework.pipeline

    _StubPipeline.instances = []

    monkeypatch.setattr(framework.pipeline, "SATSAPipeline", _StubPipeline)
    monkeypatch.setattr("backend.jobs.EXPORT_DIRECTORY", str(tmp_path / "analyses"))

    yield


# -------------------------------------------------------------------- datasets


def test_demo_dataset_is_offered_without_special_casing():
    listed = {item["path"] for item in list_datasets()}

    assert "data/demo/incident_event_log.csv" in listed


def test_no_dataset_is_listed_first_for_its_name():
    """The listing is lexicographic and nothing is preferred.

    If a dataset were ever recommended, it would appear first, or carry a
    marker. Both are asserted absent rather than merely unobserved.
    """

    listed = list_datasets()

    assert listed == sorted(listed, key=lambda item: item["path"])
    assert all("recommended" not in item for item in listed)
    assert all("default" not in item for item in listed)


def test_evidence_mode_datasets_are_offered():
    """Evidence submissions are evidence, and the interface must be able to open them."""

    listed = {item["path"] for item in list_datasets()}

    assert any(path.startswith("data/evidence/") for path in listed)


def test_adapter_output_directories_are_not_offered_as_evidence():
    listed = {item["path"] for item in list_datasets()}

    assert not any(
        part in {"venv", "node_modules", "__pycache__", ".git", "artifacts"}
        for path in listed
        for part in path.split("/")
    )


def test_paths_are_repository_relative():
    for item in list_datasets():
        assert not os.path.isabs(item["path"])


# ------------------------------------------------------------------ demo mode
#
# Demo mode is a presentation switch on the listing and nothing else. These
# checks cover the three things it promises: demo mode offers the curated set,
# it never offers what the curated set excludes, and full mode is unchanged.
# They also pin down that it is a listing filter only — an excluded dataset is
# still in the repository and still analysable.


#: Files the curated set deliberately leaves out. Each one is here because its
#: own preview fails the admission criteria, not because of its name.
DEMO_EXCLUDED = (
    "data.csv",
    "dataset_variant_1.csv",
    "dataset_variant_2.csv",
    "execution_gap_test.csv",
    "data/demo/incident_event_log.csv",
    "servicenow_style_secops_cases_q3_2026.csv",
    "servicenow_style_workflow_events_q3_2026.csv",
    "SAT-SA_demo_Q3_2026.csv",
    "validation/unsw/UNSW_NB15_testing-set.csv",
    "validation/unsw/UNSW_NB15_training-set.csv",
)


def test_demo_mode_returns_only_the_curated_allowlist():
    listed = [item["path"] for item in list_datasets(mode="demo")]

    assert listed == sorted(DEMO_ALLOWLIST)


def test_demo_mode_offers_nothing_beyond_the_allowlist():
    """Stated as a set difference, so a new curated entry cannot pass unseen."""

    listed = {item["path"] for item in list_datasets(mode="demo")}

    assert listed <= set(DEMO_ALLOWLIST)


def test_demo_mode_does_not_return_the_excluded_datasets():
    listed = {item["path"] for item in list_datasets(mode="demo")}

    for path in DEMO_EXCLUDED:
        assert path not in listed, f"{path} must not be offered in demo mode"


def test_demo_mode_entries_are_real_files_with_the_usual_fields():
    """A curated entry is described exactly as a discovered one is."""

    for item in list_datasets(mode="demo"):
        absolute = os.path.join(ROOT, item["path"])

        assert os.path.isfile(absolute)
        assert item["filename"] == os.path.basename(item["path"])
        assert item["size_bytes"] == os.path.getsize(absolute)
        assert "recommended" not in item
        assert "default" not in item


def test_full_mode_still_returns_the_whole_repository():
    full = {item["path"] for item in list_datasets(mode="full")}
    demo = {item["path"] for item in list_datasets(mode="demo")}

    assert demo < full
    assert len(full) > len(demo)


def test_full_mode_is_the_default_and_needs_no_configuration(monkeypatch):
    monkeypatch.delenv("SATSA_DATASET_MODE", raising=False)
    monkeypatch.delenv("SATSA_DEMO_DATASETS", raising=False)

    assert dataset_mode() == "full"
    assert [item["path"] for item in list_datasets()] == [
        item["path"] for item in list_datasets(mode="full")
    ]


def test_full_mode_still_offers_the_excluded_datasets():
    """The excluded files are filtered, not gone."""

    listed = {item["path"] for item in list_datasets(mode="full")}

    for path in DEMO_EXCLUDED:
        assert path in listed, f"{path} must remain available in full mode"


def test_demo_mode_is_selected_by_environment(monkeypatch):
    monkeypatch.setenv("SATSA_DATASET_MODE", "demo")

    assert dataset_mode() == "demo"
    assert {item["path"] for item in list_datasets()} == set(DEMO_ALLOWLIST)


def test_an_unknown_mode_is_reported_rather_than_silently_widened(monkeypatch):
    """Falling back to a full walk here would undo the switch quietly."""

    monkeypatch.setenv("SATSA_DATASET_MODE", "demo-ish")

    with pytest.raises(ValueError):
        dataset_mode()

    with pytest.raises(ValueError):
        list_datasets()


def test_the_curated_set_can_be_replaced_from_the_environment(monkeypatch, tmp_path):
    (tmp_path / "curated.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setenv("SATSA_DEMO_DATASETS", "curated.csv")

    listed = list_datasets(root=str(tmp_path), mode="demo")

    assert [item["path"] for item in listed] == ["curated.csv"]


def test_an_allowlisted_dataset_that_is_absent_is_reported(monkeypatch, tmp_path):
    found, missing = curated_datasets(
        allowlist=("here.csv", "gone.csv"), root=str(tmp_path)
    )

    assert found == []
    assert missing == ["here.csv", "gone.csv"]


def test_a_missing_curated_dataset_is_not_silently_dropped():
    """``missing`` is what the endpoint reports instead of a shorter picker."""

    found, missing = curated_datasets()

    assert missing == []
    assert {item["path"] for item in found} == set(DEMO_ALLOWLIST)


def test_demo_mode_filters_the_listing_only(monkeypatch):
    """An excluded dataset is still in the repository and still analysable."""

    monkeypatch.setenv("SATSA_DATASET_MODE", "demo")

    listed = {item["path"] for item in list_datasets()}

    assert "data/demo/incident_event_log.csv" not in listed
    assert os.path.isfile(
        resolve_dataset("data/demo/incident_event_log.csv")
    )


def test_the_datasets_endpoint_reports_the_listing_it_gave(monkeypatch):
    monkeypatch.delenv("SATSA_DATASET_MODE", raising=False)

    body = datasets()

    assert body["mode"] == "full"
    assert [item["path"] for item in body["datasets"]] == [
        item["path"] for item in list_datasets(mode="full")
    ]
    assert "missing" not in body


def test_the_datasets_endpoint_reports_demo_mode_and_no_missing(monkeypatch):
    monkeypatch.setenv("SATSA_DATASET_MODE", "demo")

    body = datasets()

    assert body["mode"] == "demo"
    assert [item["path"] for item in body["datasets"]] == sorted(DEMO_ALLOWLIST)
    assert "missing" not in body


def test_the_datasets_endpoint_names_a_curated_dataset_that_is_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("SATSA_DATASET_MODE", "demo")
    monkeypatch.setenv("SATSA_DEMO_DATASETS", "absent_demo_dataset.csv")
    # ``curated_datasets`` resolves the root inside backend.datasets, so that
    # is the name to replace; patching the app's import would leave the real
    # repository in play and make this pass for the wrong reason.
    monkeypatch.setattr("backend.datasets.repository_root", lambda: str(tmp_path))

    body = datasets()

    assert body["datasets"] == []
    assert body["missing"] == ["absent_demo_dataset.csv"]


def test_resolve_rejects_a_path_outside_the_repository():
    with pytest.raises(ValueError):
        resolve_dataset("../etc/passwd")

    with pytest.raises(ValueError):
        resolve_dataset("data/../../etc/passwd")


def test_resolve_rejects_a_file_that_does_not_exist():
    with pytest.raises(FileNotFoundError):
        resolve_dataset("data/demo/incident_event_log_absent.csv")


def test_resolve_returns_a_readable_absolute_path():
    absolute = resolve_dataset("data/demo/incident_event_log.csv")

    assert os.path.isfile(absolute)
    assert absolute.startswith(ROOT)


# --------------------------------------------------------------- serialisation


def test_zero_and_none_stay_distinct():
    result = serialisable_result({"measured_zero": 0, "resolved_absent": None})

    assert result["measured_zero"] == 0
    assert result["resolved_absent"] is None


def test_a_value_json_cannot_hold_is_marked_rather_than_dropped():
    result = serialisable_result({"not_a_number": float("nan")})

    marker = result["not_a_number"]
    assert marker["__unrepresentable__"] is True
    assert marker["python_type"] == "float"


def test_infinities_are_marked_too():
    result = serialisable_result({"positive_infinity": float("inf")})

    assert result["positive_infinity"]["__unrepresentable__"] is True


def test_nested_numpy_and_pandas_scalars_become_plain_json():
    numpy = pytest.importorskip("numpy")
    pandas = pytest.importorskip("pandas")

    result = serialisable_result(
        {
            "numpy_int": numpy.int64(7),
            "numpy_float": numpy.float64(1.5),
            "numpy_bool": numpy.bool_(True),
            "pandas_timestamp": pandas.Timestamp("2026-01-01T00:00:00"),
        }
    )

    assert result["numpy_int"] == 7
    assert result["numpy_float"] == 1.5
    assert result["numpy_bool"] is True
    assert isinstance(result["pandas_timestamp"], str)

    json.dumps(result)


def test_key_order_is_preserved():
    """The interface reads the result in the order the pipeline wrote it."""

    original = list(_pipeline_result())
    result = serialisable_result(_pipeline_result())

    assert list(result) == original


# ----------------------------------------------------------------------- store


def _run_one(store, dataset="data/demo/incident_event_log.csv"):
    job = store.create(dataset)
    store.run(job)
    return job


def test_a_completed_run_reports_complete_and_keeps_its_dataset():
    store = AnalysisStore()
    job = _run_one(store)

    assert job.status == "complete"
    assert job.finished_at is not None
    assert job.public_state()["dataset"] == "data/demo/incident_event_log.csv"


def test_the_pipeline_receives_a_repository_relative_path():
    """An absolute path would put the local directory layout on screen."""

    store = AnalysisStore()
    _run_one(store)

    assert _StubPipeline.instances[0].received == [
        "data/demo/incident_event_log.csv"
    ]


def test_the_interface_payload_carries_every_declared_key():
    store = AnalysisStore()
    job = _run_one(store)

    for key in TRANSPORTED_KEYS:
        if key in _pipeline_result():
            assert key in job.result, key


def test_per_record_keys_are_declared_rather_than_dropped_silently():
    store = AnalysisStore()
    job = _run_one(store)

    for key in VOLUMETRIC_KEYS:
        assert key not in job.result
        assert {"key": key, "reason": OMITTED_KEY_REASON} in job.omitted_keys


def test_a_key_neither_transported_nor_declared_is_still_reported():
    """A new pipeline key must not disappear without a word."""

    import framework.pipeline

    class _Undeclared(_StubPipeline):
        def run(self, dataset: str) -> dict:
            result = super().run(dataset)
            result["a_key_added_next_year"] = {"value": 1}
            return result

    framework.pipeline.SATSAPipeline = _Undeclared

    store = AnalysisStore()
    job = _run_one(store)

    assert "a_key_added_next_year" not in job.result
    assert {
        "key": "a_key_added_next_year",
        "reason": "Not declared for transport.",
    } in job.omitted_keys


def test_the_full_export_is_the_whole_result():
    store = AnalysisStore()
    job = _run_one(store)

    with open(job.export_path, encoding="utf-8") as handle:
        exported = json.load(handle)

    assert set(exported) == set(_pipeline_result())
    assert exported["canonical_records"] == [{"row": 0}, {"row": 1}]


def test_the_full_export_is_written_before_the_interface_payload():
    """A storage failure must not leave an export that looks authoritative."""

    store = AnalysisStore()
    job = store.create("data/demo/incident_event_log.csv")

    def _unwritable(*args, **kwargs):
        raise OSError("no space left on device")

    import backend.jobs as jobs_module

    original = jobs_module.tempfile.NamedTemporaryFile
    jobs_module.tempfile.NamedTemporaryFile = _unwritable

    try:
        store.run(job)
    finally:
        jobs_module.tempfile.NamedTemporaryFile = original

    assert job.status == "error"
    assert job.result is None
    assert job.export_path is None


def test_a_failing_pipeline_is_reported_as_an_error_and_not_as_an_empty_result():
    import framework.pipeline

    framework.pipeline.SATSAPipeline = _FailingPipeline

    store = AnalysisStore()
    job = _run_one(store)

    assert job.status == "error"
    assert job.result is None
    assert "RuntimeError" in job.public_state()["error"]


def test_a_dataset_outside_the_repository_never_reaches_the_pipeline():
    store = AnalysisStore()
    job = _run_one(store, dataset="../etc/passwd")

    assert job.status == "error"
    assert _StubPipeline.instances == []


def test_only_the_newest_runs_are_retained():
    store = AnalysisStore()

    for _ in range(MAX_RETAINED + 3):
        _run_one(store)

    assert len(store._order) == MAX_RETAINED


def test_evicting_a_run_removes_its_export():
    """A dropped run must not leave a large export file behind on disk."""

    store = AnalysisStore()

    first = _run_one(store)
    first_path = first.export_path
    assert os.path.isfile(first_path)

    for _ in range(MAX_RETAINED):
        _run_one(store)

    newest = _run_one(store)

    assert store.get(first.id) is None
    assert first.export_path is None
    assert not os.path.isfile(first_path)
    assert store.get(newest.id) is not None
    assert os.path.isfile(newest.export_path)


def test_a_job_in_flight_reports_processing_and_carries_no_result():
    store = AnalysisStore()
    job = store.create("data/demo/incident_event_log.csv")

    state = job.public_state()

    assert state["status"] == "processing"
    assert "result" not in state
    assert "omitted_keys" not in state


def test_listing_the_runs_does_not_deadlock():
    """The listing must not take the store's lock and then ask the store again.

    The lock is not reentrant, so a listing that iterates job ids while
    holding it and calls the accessor per id would hang the service instead of
    answering. This runs the real endpoint on a worker thread so a regression
    fails the test rather than the suite.
    """

    import threading

    from backend.app import list_analyses

    store = AnalysisStore()
    _run_one(store)
    _run_one(store)

    import backend.app as app_module

    app_module.store = store

    answered: list = []
    failure: list = []

    def _ask() -> None:
        try:
            answered.append(list_analyses())
        except BaseException as error:  # noqa: BLE001 - reported below
            failure.append(error)

    worker = threading.Thread(target=_ask, daemon=True)
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive(), "the run listing blocked"
    assert not failure, failure
    assert len(answered[0]["analyses"]) == 2
    assert all("result" not in state for state in answered[0]["analyses"])


def test_the_listing_is_ordered_oldest_first():
    """Run order is the order the runs were started, so "most recent" is knowable."""

    store = AnalysisStore()

    first = _run_one(store)
    second = _run_one(store)

    states = store.public_states()

    assert [state["job_id"] for state in states] == [first.id, second.id]
