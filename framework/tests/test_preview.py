"""Step 2 tests: pre-run dataset preview (Batch D).

A. preview existing CSV | B. exact count | C. schema | D. role |
E. unknown role | F. decisions | G. summary | H. bounded sample |
I. malformed dataset | J. large-path preview | K. small-path preview |
L. no full-row materialization | M. bounded response.

Plus: override recompute (guard/collision/unknown), explicit role,
per-dataset error isolation, and no analytics keys in previews.
"""

from __future__ import annotations

import csv
import json
import os

import pytest

from framework.canonical.preview import apply_reviewer_overrides, preview_dataset
from framework.pipeline import SATSAPipeline

FIXTURE = "dataset_noisy.csv"


def _pipeline():
    return SATSAPipeline()


# A. Preview an existing CSV.
def test_preview_existing_csv():
    preview = preview_dataset(FIXTURE, _pipeline())

    assert preview["dataset"] == FIXTURE
    assert preview["execution_mode"] == "small"
    assert preview["mapping_decisions"], "one decision per column expected"


# B. Exact count matches the file.
def test_preview_exact_count():
    with open(FIXTURE, newline="") as handle:
        expected = sum(1 for _ in csv.DictReader(handle))

    assert preview_dataset(FIXTURE, _pipeline())["record_count"] == expected


# C. Schema returned with names and categories.
def test_preview_schema():
    with open(FIXTURE, newline="") as handle:
        header = next(csv.reader(handle))

    columns = preview_dataset(FIXTURE, _pipeline())["schema"]["columns"]
    names = [column["column_name"] for column in columns]

    assert names == header

    for column in columns:
        assert column["category"], column["column_name"]


# D. Role detection reuses the Phase 1 detector.
def test_preview_role_detection():
    role = preview_dataset(FIXTURE, _pipeline())["detected_role"]

    assert role["role"] in (
        "ALERTS", "CASES", "WORKFLOW_EVENTS", "ASSETS", "UNKNOWN",
    )
    assert isinstance(role["confidence"], (int, float))
    assert role["reason"], "role must be explained, never bare"


# E. Unknown role stays unknown and is reported, never forced.
def test_preview_unknown_role_for_gibberish(tmp_path):
    path = str(tmp_path / "gibberish.csv")

    with open(path, "w", newline="") as handle:
        handle.write("zzqx_aa,zzqx_bb\n1,2\n")

    role = preview_dataset(path, _pipeline())["detected_role"]

    assert role["role"] == "UNKNOWN"


def test_explicit_role_override():
    preview = preview_dataset(FIXTURE, _pipeline(), explicit_role="CASES")

    assert preview["detected_role"]["role"] == "CASES"
    assert preview["detected_role"]["confidence"] == 1.0


# F/G. Canonical decisions and their summary.
def test_preview_mapping_decisions_and_summary():
    preview = preview_dataset(FIXTURE, _pipeline())
    states = preview["mapping_states"]

    assert set(states) == {
        "MAPPED", "LOW_CONFIDENCE", "AMBIGUOUS", "UNMAPPED", "INVALID",
    }
    assert sum(states.values()) == len(preview["mapping_decisions"])
    assert sum(states.values()) == len(preview["schema"]["columns"])

    for decision in preview["mapping_decisions"]:
        assert decision["source_field"]
        assert decision["mapping_state"] in states
        assert decision["reason"]


def test_preview_guard_case_visible():
    by_field = {
        item["source_field"]: item
        for item in preview_dataset(FIXTURE, _pipeline())["mapping_decisions"]
    }

    assert by_field["closed_by"]["mapping_state"] == "INVALID"
    assert by_field["closed_by"]["applied"] is False


# H. Samples bounded to ten values.
def test_preview_bounded_sample():
    for column in preview_dataset(FIXTURE, _pipeline())["schema"]["columns"]:
        assert len(column["sample_values"]) <= 10


# I. Malformed dataset raises instead of returning fake data.
def test_preview_malformed_raises(tmp_path):
    path = str(tmp_path / "empty.csv")

    with open(path, "w") as handle:
        handle.write("")

    with pytest.raises(Exception):
        preview_dataset(path, _pipeline())


def test_preview_missing_file_raises():
    with pytest.raises(Exception):
        preview_dataset("no-such-file.csv", _pipeline())


# J/K. Execution paths.
def test_preview_small_path_default():
    assert preview_dataset(FIXTURE, _pipeline())["execution_mode"] == "small"


def test_preview_large_path_uses_scan():
    preview = preview_dataset(FIXTURE, _pipeline(), execution_mode="large")

    assert preview["execution_mode"] == "large_scan"
    assert preview["record_count"] > 0
    assert preview["mapping_decisions"]
    assert preview["detected_role"]["role"]


# L. No full-row materialization: preview carries aggregates, never rows.
def test_preview_has_no_row_materialization():
    preview = preview_dataset(FIXTURE, _pipeline(), execution_mode="large")

    assert "records" not in preview
    assert "canonical_records" not in preview
    assert "feature_analysis" not in preview


# M. Bounded response with no analytics keys.
def test_preview_bounded_and_analysis_free():
    preview = preview_dataset(FIXTURE, _pipeline())
    size = len(json.dumps(preview))

    assert size < 1_000_000, "schema-level preview must stay small"

    for key in (
        "execution_gap_findings",
        "negative_space_findings",
        "operational_pattern_findings",
        "anomaly_findings",
        "entity_assessment",
        "supervisory_findings",
    ):
        assert key not in preview, key


def test_preview_validation_shape():
    validation = preview_dataset(FIXTURE, _pipeline())["validation"]

    assert isinstance(validation["error_count"], int)
    assert isinstance(validation["warning_count"], int)

    for issue in validation["issues"]:
        assert issue["severity"] in ("error", "warning", "info")
        assert issue["message"]


# Overrides: applied only when safe; automatic preserved; rejected reported.
def test_override_applies_and_preserves_automatic():
    preview = preview_dataset(
        FIXTURE, _pipeline(), mapping_overrides={"closed_by": "ANALYST_ID"}
    )
    decision = {
        item["source_field"]: item
        for item in preview["mapping_decisions"]
    }["closed_by"]

    assert decision["canonical_concept"] == "ANALYST_ID"
    assert decision["applied"] is True
    assert decision["reviewer_override"]["previous_state"] == "INVALID"
    assert decision["reviewer_override"]["previous_concept"] == "CLOSED_AT"
    assert decision["reviewer_override"]["source"] == "REVIEWER_OVERRIDE"
    assert preview["mapping_overrides_rejected"] == []


def test_override_to_unmapped():
    preview = preview_dataset(
        FIXTURE, _pipeline(), mapping_overrides={"alert_id": None}
    )
    decision = {
        item["source_field"]: item for item in preview["mapping_decisions"]
    }["alert_id"]

    assert decision["mapping_state"] == "UNMAPPED"
    assert decision["applied"] is False


def test_override_guard_violation_rejected():
    preview = preview_dataset(
        FIXTURE, _pipeline(), mapping_overrides={"closed_by": "CLOSED_AT"}
    )
    by_field = {
        item["source_field"]: item for item in preview["mapping_decisions"]
    }

    assert by_field["closed_by"]["mapping_state"] == "INVALID"
    assert len(preview["mapping_overrides_rejected"]) == 1


def test_override_unknown_concept_rejected():
    preview = preview_dataset(
        FIXTURE, _pipeline(), mapping_overrides={"alert_id": "NOT_A_CONCEPT"}
    )
    by_field = {
        item["source_field"]: item for item in preview["mapping_decisions"]
    }

    assert by_field["alert_id"]["canonical_concept"] != "NOT_A_CONCEPT"
    assert len(preview["mapping_overrides_rejected"]) == 1


def test_override_collision_rejected():
    preview = preview_dataset(FIXTURE, _pipeline())
    applied = [item for item in preview["mapping_decisions"] if item["applied"]]

    assert len(applied) >= 2

    first, second = applied[0], applied[1]

    assert first["canonical_concept"] != second["canonical_concept"]

    fresh, rejected = apply_reviewer_overrides(
        preview["mapping_decisions"],
        {second["source_field"]: first["canonical_concept"]},
        preview["canonical_contract"],
    )

    assert len(rejected) == 1
    assert "Collision" in rejected[0]["reason"]

    kept = {
        item["source_field"]: item for item in fresh
    }[second["source_field"]]

    assert kept["canonical_concept"] == second["canonical_concept"]


def test_apply_overrides_pure():
    decisions = preview_dataset(FIXTURE, _pipeline())["mapping_decisions"]
    snapshot = json.dumps(decisions, sort_keys=True, default=str)

    apply_reviewer_overrides(
        decisions, {"closed_by": "ANALYST_ID"},
        preview_dataset(FIXTURE, _pipeline())["canonical_contract"],
    )

    assert json.dumps(decisions, sort_keys=True, default=str) == snapshot


# J-scale. 1M fixture takes the scan path with an exact count and a
# bounded payload (verified: ~25 KB). Skipped when the gitignored scale
# fixtures were never generated; the forced-large test above covers the
# path itself.
@pytest.mark.skipif(
    not os.path.isfile("data/scale/scale_1000000.csv"),
    reason="scale fixtures are gitignored and generated on demand",
)
def test_preview_1m_scale_fixture():
    preview = preview_dataset("data/scale/scale_1000000.csv", _pipeline())

    assert preview["execution_mode"] == "large_scan"
    assert preview["record_count"] == 1001000
    assert len(json.dumps(preview)) < 1_000_000


# Endpoint: per-dataset isolation, batch shape, serialisable.
def test_previews_endpoint_isolates_errors():
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)
    response = client.post(
        "/api/previews",
        json={"datasets": [FIXTURE, "no-such-file.csv"]},
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body["previews"]) == 2
    assert body["previews"][0]["record_count"] > 0
    assert body["previews"][1]["error"] == "Dataset not found"


def test_previews_endpoint_accepts_overrides():
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)
    response = client.post(
        "/api/previews",
        json={
            "datasets": [FIXTURE],
            "explicit_roles": {FIXTURE: "CASES"},
            "mapping_overrides": {FIXTURE: {"closed_by": "ANALYST_ID"}},
        },
    )

    assert response.status_code == 200

    (preview,) = response.json()["previews"]

    assert preview["detected_role"]["role"] == "CASES"

    decision = {
        item["source_field"]: item for item in preview["mapping_decisions"]
    }["closed_by"]

    assert decision["canonical_concept"] == "ANALYST_ID"


def test_analysis_endpoint_still_single_dataset():
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)
    response = client.post("/api/analyses", json={"dataset": FIXTURE})

    assert response.status_code == 200
    assert response.json()["dataset"] == FIXTURE


# Data-root resolution: packaged builds resolve relative submissions
# against SATSA_DATA_ROOT; unset, paths pass through unchanged.
def test_resolve_source_passthrough_by_default():
    from framework.ingestion.paths import resolve_source

    assert resolve_source("data/x.csv") == "data/x.csv"
    assert resolve_source("/abs/x.csv") == "/abs/x.csv"


def test_run_resolves_against_data_root(tmp_path, monkeypatch):
    import shutil

    shutil.copy(FIXTURE, tmp_path / "noisy.csv")
    monkeypatch.setenv("SATSA_DATA_ROOT", str(tmp_path))

    from framework.pipeline import SATSAPipeline

    result = SATSAPipeline().run("noisy.csv")

    assert result["dataset"] == "noisy.csv"
    assert result["canonical_package"]["mapping_decisions"]
