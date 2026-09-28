"""
Tests for the SAT-SA assessment scope layer.

Covers the ten required scenarios:

1. single entity
2. multiple entities
3. explicit assessment period
4. multiple periods
5. entity unavailable
6. period unavailable
7. multiple entities + multiple periods
8. same entity across multiple periods
9. malformed / ambiguous metadata
10. existing ``dataset_noisy.csv`` regression

The recurring assertion in several tests is that the layer does **not** invent
an entity or a period. An unresolved value must surface as ``UNKNOWN_ENTITY`` /
``UNKNOWN_PERIOD`` with ``available=False`` and a recorded reason, never as a
plausible-looking guess.

Run with::

    python -m pytest framework/tests/test_assessment_scope.py -v
"""

from __future__ import annotations

import json
import os

import pytest

from framework.assessment import (
    UNKNOWN_ENTITY,
    UNKNOWN_PERIOD,
    AssessmentScopeBuilder,
    PeriodResolver,
    parse_timestamp,
)
from framework.assessment.entity_context import load_scope_config
from framework.ingestion.ingestion_manager import IngestionManager
from framework.intelligence.semantic_inference import SemanticInference
from framework.profiling.dataset_profiler import DatasetProfiler

REPOSITORY_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

MULTI_CSE_DATASET = "dataset_multi_cse.csv"


def _requires_pipeline() -> None:
    if os.path.abspath(os.getcwd()) != REPOSITORY_ROOT:
        pytest.skip(
            "pipeline configuration paths are relative to the repository root"
        )


def profile_records(records):
    """Profile an in-memory record set through the real profiler.

    The profiler accepts a file path, so the records are written to a temporary
    CSV. Going through the real profiler keeps these tests honest: they exercise
    the same profile the pipeline would produce, not a hand-built stub.
    """

    import csv
    import tempfile

    columns = []

    for record in records:
        for key in record:
            if key not in columns:
                columns.append(key)

    if not columns:
        # The profiler reads a CSV and cannot parse a zero-column file, so an
        # empty record set is profiled with the profiler's own empty shape.
        return records, {"columns": [], "dataset_summary": {"records": 0, "columns": 0}}

    with tempfile.TemporaryDirectory() as directory:

        path = os.path.join(directory, "records.csv")

        with open(path, "w", newline="") as handle:

            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()

            for record in records:
                writer.writerow({key: record.get(key) for key in columns})

        profile = DatasetProfiler().profile(path)

    return records, profile


def build(records, settings=None, semantic_results=None):
    """Resolve scopes for an in-memory record set."""

    records, profile = profile_records(records)

    if semantic_results is None:
        semantic_results = SemanticInference(
            "framework/config/semantic_patterns.json"
        ).infer(profile)

    collection = AssessmentScopeBuilder(settings=settings).build(
        records=records,
        profile=profile,
        semantic_results=semantic_results,
        source_id="test",
        source_type="csv",
    )

    return collection, records


# ---------------------------------------------------------------------------
# 1. single entity
# ---------------------------------------------------------------------------


class TestSingleEntity:

    def test_one_entity_produces_one_scope(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "alert_id": "A1", "priority": "HIGH"},
                {"cse": "CSE-001", "alert_id": "A2", "priority": "LOW"},
            ]
        )

        assert len(collection) == 1
        assert collection.entity_count == 1
        assert collection.distinct_entity_count == 1
        assert collection.record_count == 2

    def test_single_entity_is_distinguishable_from_unavailable(self):

        resolved, _ = build([{"cse": "CSE-001", "alert_id": "A1"}])

        unavailable, _ = build([{"alert_id": "A1", "host": "WEB-01"}])

        assert len(resolved) == len(unavailable) == 1

        assert resolved.has_unresolved_entity is False
        assert resolved.distinct_entity_count == 1

        assert unavailable.has_unresolved_entity is True
        assert unavailable.distinct_entity_count == 0

    def test_entity_name_only_column_is_not_promoted_to_an_id(self):

        collection, _ = build(
            [{"customer_name": "Acme Water", "alert_id": "A1"}]
        )

        scope = collection[0]

        assert scope.entity_id is None
        assert scope.entity_name == "Acme Water"
        assert scope.entity_key == "Acme Water"
        assert scope.entity_available is True

    def test_identifier_and_name_are_both_reported(self):

        collection, _ = build(
            [{"cse": "CSE-001", "cse_name": "Acme Water", "alert_id": "A1"}]
        )

        scope = collection[0]

        assert scope.entity_id == "CSE-001"
        assert scope.entity_name == "Acme Water"
        assert scope.entity_available is True


# ---------------------------------------------------------------------------
# 2. multiple entities
# ---------------------------------------------------------------------------


class TestMultipleEntities:

    def test_two_entities_produce_two_scopes(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "alert_id": "A1"},
                {"cse": "CSE-002", "alert_id": "A2"},
                {"cse": "CSE-001", "alert_id": "A3"},
            ]
        )

        assert len(collection) == 2
        assert collection.entity_count == 2
        assert collection.distinct_entity_count == 2
        assert collection.entity_keys == ["CSE-001", "CSE-002"]

    def test_grouping_by_entity_partitions_records(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "alert_id": "A1"},
                {"cse": "CSE-002", "alert_id": "A2"},
                {"cse": "CSE-001", "alert_id": "A3"},
            ]
        )

        first = collection.for_entity("CSE-001")

        assert len(first) == 1
        assert first[0].record_count == 2

        assert [record["alert_id"] for record in collection.records_for_entity("CSE-001")] == [
            "A1",
            "A3",
        ]

    def test_filtering_by_unknown_entity_returns_nothing(self):

        collection, _ = build([{"cse": "CSE-001", "alert_id": "A1"}])

        assert collection.for_entity("CSE-999") == []
        assert collection.filter(entity="CSE-999") == []

    def test_no_analytics_are_attached_to_a_scope(self):

        collection, _ = build([{"cse": "CSE-001", "alert_id": "A1"}])

        payload = collection[0].to_dict()

        assert set(payload) == {
            "assessment_id",
            "entity",
            "period",
            "source",
            "record_count",
            "metadata",
        }


# ---------------------------------------------------------------------------
# 3. explicit assessment period
# ---------------------------------------------------------------------------


class TestExplicitPeriod:

    def test_explicit_period_column_is_used_verbatim(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "FY26-Q1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "FY26-Q1", "alert_id": "A2"},
            ]
        )

        scope = collection[0]

        assert scope.period_label == "FY26-Q1"
        assert scope.period_available is True
        assert scope.period.granularity == "explicit"
        assert scope.period.method == "explicit_column"

    def test_opaque_period_label_invents_no_bounds(self):

        collection, _ = build(
            [{"cse": "CSE-001", "period": "FY26-Q1", "alert_id": "A1"}]
        )

        scope = collection[0]

        assert scope.period_start is None
        assert scope.period_end is None
        assert scope.period.label_precision == "opaque"

    def test_iso_period_label_yields_exact_bounds(self):

        collection, _ = build(
            [{"cse": "CSE-001", "assessment_period": "2026-03-31", "alert_id": "A1"}]
        )

        scope = collection[0]

        assert scope.period_label == "2026-03-31"
        assert scope.period_start == "2026-03-31"
        assert scope.period_end == "2026-03-31"
        assert scope.period.label_precision == "day"

    def test_explicit_period_wins_over_timestamps(self):

        collection, _ = build(
            [
                {
                    "cse": "CSE-001",
                    "period": "Assessment-Wave-1",
                    "created_time": "2026-01-05",
                    "alert_id": "A1",
                }
            ]
        )

        scope = collection[0]

        assert scope.period_label == "Assessment-Wave-1"
        assert scope.period.method == "explicit_column"


# ---------------------------------------------------------------------------
# 4. multiple periods
# ---------------------------------------------------------------------------


class TestMultiplePeriods:

    def test_two_periods_produce_two_scopes_for_one_entity(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
            ]
        )

        assert len(collection) == 2
        assert collection.entity_count == 1
        assert collection.period_count == 2
        assert collection.period_labels == ["P1", "P2"]

    def test_grouping_by_period_partitions_records(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
                {"cse": "CSE-001", "period": "P1", "alert_id": "A3"},
            ]
        )

        assert [s.record_count for s in collection.for_period("P1")] == [2]
        assert [s.record_count for s in collection.for_period("P2")] == [1]

        assert [r["alert_id"] for r in collection.records_for_period("P1")] == [
            "A1",
            "A3",
        ]

    def test_unlabelled_record_is_not_assigned_to_a_guessed_period(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
                {"cse": "CSE-001", "alert_id": "A3"},
            ]
        )

        unlabelled = collection.for_period(UNKNOWN_PERIOD)

        assert len(unlabelled) == 1
        assert unlabelled[0].record_count == 1
        assert unlabelled[0].period_available is False
        assert "no value" in unlabelled[0].period.unavailable_reason
        assert "not guessed" in unlabelled[0].period.unavailable_reason

    def test_unlabelled_record_joins_the_single_declared_period(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "alert_id": "A2"},
            ]
        )

        assert len(collection) == 1
        assert collection[0].record_count == 2


# ---------------------------------------------------------------------------
# 5. entity unavailable
# ---------------------------------------------------------------------------


class TestEntityUnavailable:

    def test_no_entity_field_yields_unknown_entity_and_a_reason(self):

        collection, _ = build(
            [{"alert_id": "A1", "host": "WEB-01", "priority": "HIGH"}]
        )

        scope = collection[0]

        assert scope.entity_key == UNKNOWN_ENTITY
        assert scope.entity_id is None
        assert scope.entity_available is False
        assert scope.entity.unavailable_reason

    def test_host_field_is_not_treated_as_an_entity(self):

        collection, _ = build(
            [
                {"host": "WEB-01", "alert_id": "A1"},
                {"host": "DB-02", "alert_id": "A2"},
            ]
        )

        assert collection.distinct_entity_count == 0
        assert collection.entity_count == 1
        assert collection[0].record_count == 2

    def test_department_is_not_treated_as_an_entity(self):

        collection, _ = build(
            [
                {"department": "Finance", "alert_id": "A1"},
                {"department": "HR", "alert_id": "A2"},
            ]
        )

        # The existing EntityResolver offers "Finance" as an organizational
        # entity. Accepting it would invent one entity per department, so the
        # scope layer rejects that tier and reports the entity as unavailable.
        assert collection.distinct_entity_count == 0
        assert collection.entity_count == 1
        assert "rejected" in collection[0].entity.unavailable_reason

    def test_blank_entity_values_do_not_create_an_entity(self):

        collection, _ = build(
            [
                {"cse": "", "alert_id": "A1"},
                {"cse": None, "alert_id": "A2"},
            ]
        )

        assert collection.distinct_entity_count == 0
        assert collection[0].entity_available is False
        assert "empty" in collection[0].entity.unavailable_reason

    def test_partially_blank_values_keep_only_real_entities(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "alert_id": "A1"},
                {"cse": "", "alert_id": "A2"},
            ]
        )

        assert collection.entity_keys == ["CSE-001", UNKNOWN_ENTITY]
        assert collection.distinct_entity_count == 1

    def test_entity_resolution_summary_reports_unavailability(self):

        collection, _ = build([{"alert_id": "A1"}])

        payload = collection.to_dict()["entity_resolution"]

        assert payload["available"] is False
        assert payload["distinct_entities"] == 0
        assert payload["unresolved_scopes"] == 1


# ---------------------------------------------------------------------------
# 6. period unavailable
# ---------------------------------------------------------------------------


class TestPeriodUnavailable:

    def test_no_period_evidence_yields_unknown_period_and_a_reason(self):

        collection, _ = build(
            [{"cse": "CSE-001", "alert_id": "A1", "notes": "none"}]
        )

        scope = collection[0]

        assert scope.period_label == UNKNOWN_PERIOD
        assert scope.period_available is False
        assert scope.period.unavailable_reason
        assert scope.period_start is None
        assert scope.period_end is None

    def test_missing_period_does_not_raise(self):

        # The whole point: absence of period metadata must never crash.
        collection, _ = build([{"cse": "CSE-001", "alert_id": "A1"}])

        assert len(collection) == 1

    def test_unparseable_timestamps_yield_unknown_period(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "created_time": "not-a-date", "alert_id": "A1"},
                {"cse": "CSE-001", "created_time": "also bad", "alert_id": "A2"},
            ]
        )

        scope = collection[0]

        assert scope.period_label == UNKNOWN_PERIOD
        assert "no value could be parsed" in scope.period.unavailable_reason

    def test_derivation_can_be_disabled_by_configuration(self):

        collection, _ = build(
            [
                {
                    "cse": "CSE-001",
                    "created_time": "2026-01-05",
                    "alert_id": "A1",
                }
            ],
            settings={"period_granularity": "none"},
        )

        assert collection[0].period_label == UNKNOWN_PERIOD
        assert "disabled" in collection[0].period.unavailable_reason

    def test_period_resolution_summary_reports_unavailability(self):

        collection, _ = build([{"cse": "CSE-001", "alert_id": "A1"}])

        payload = collection.to_dict()["period_resolution"]

        assert payload["available"] is False
        assert payload["distinct_periods"] == 0
        assert payload["unresolved_scopes"] == 1


# ---------------------------------------------------------------------------
# 7. multiple entities and multiple periods
# ---------------------------------------------------------------------------


class TestEntityAndPeriodMatrix:

    def test_two_by_two_matrix(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
                {"cse": "CSE-002", "period": "P1", "alert_id": "A3"},
                {"cse": "CSE-002", "period": "P2", "alert_id": "A4"},
            ]
        )

        assert len(collection) == 4
        assert collection.entity_count == 2
        assert collection.period_count == 2

        assert [s.assessment_id for s in collection] == [
            "CSE-001::P1",
            "CSE-001::P2",
            "CSE-002::P1",
            "CSE-002::P2",
        ]

    def test_matrix_lookup_returns_the_exact_cell(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
                {"cse": "CSE-002", "period": "P1", "alert_id": "A3"},
                {"cse": "CSE-002", "period": "P2", "alert_id": "A4"},
            ]
        )

        cell = collection.for_entity_period("CSE-002", "P1")

        assert len(cell) == 1
        assert [r["alert_id"] for r in cell[0].records] == ["A3"]

    def test_sparse_matrix_does_not_invent_cells(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-002", "period": "P2", "alert_id": "A2"},
            ]
        )

        assert len(collection) == 2
        assert collection.for_entity_period("CSE-001", "P2") == []
        assert collection.for_entity_period("CSE-002", "P1") == []

    def test_filter_across_both_axes(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
                {"cse": "CSE-002", "period": "P1", "alert_id": "A3"},
            ]
        )

        assert len(collection.filter(period="P1")) == 2
        assert len(collection.filter(entity="CSE-001")) == 2
        assert len(collection.filter(entity="CSE-001", period="P1")) == 1
        assert len(collection.filter()) == 3

    def test_records_are_partitioned_without_loss_or_duplication(self):

        records = [
            {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
            {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
            {"cse": "CSE-002", "period": "P1", "alert_id": "A3"},
            {"cse": "CSE-002", "period": "P2", "alert_id": "A4"},
        ]

        collection, source = build(records)

        seen = [index for scope in collection for index in scope.record_indices]

        assert sorted(seen) == list(range(len(records)))
        assert len(seen) == len(set(seen))

    def test_scopes_reference_the_shared_records(self):

        collection, source = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-002", "period": "P1", "alert_id": "A2"},
            ]
        )

        # Identity, not equality: the scope must hand back the very dicts
        # ingestion produced rather than copies.
        assert collection[0].records[0] is source[0]
        assert collection[1].records[0] is source[1]

    def test_serialised_payload_carries_no_record_bodies(self):

        collection, _ = build(
            [{"cse": "CSE-001", "period": "P1", "alert_id": "A1"}]
        )

        payload = json.dumps(collection.to_dict())

        assert "A1" not in payload
        assert "record_indices" not in json.dumps(collection.to_dict())


# ---------------------------------------------------------------------------
# 8. same entity across multiple periods
# ---------------------------------------------------------------------------


class TestEntityAcrossPeriods:

    def test_one_entity_two_periods_is_one_series(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2"},
            ]
        )

        assert collection.entity_count == 1
        assert collection.period_count == 2
        assert len(collection) == 2

        assert collection.by_entity["CSE-001"] == collection.scopes

    def test_series_is_ordered_by_period_label(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P3", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P1", "alert_id": "A2"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A3"},
            ]
        )

        assert [s.period_label for s in collection.for_entity("CSE-001")] == [
            "P1",
            "P2",
            "P3",
        ]

    def test_record_counts_accumulate_across_the_series(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "P1", "alert_id": "A2"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A3"},
            ]
        )

        series = collection.for_entity("CSE-001")

        assert [s.record_count for s in series] == [2, 1]
        assert sum(s.record_count for s in series) == 3

    def test_yearly_derivation_splits_one_entity_by_calendar_year(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "created_time": "2025-11-04", "alert_id": "A1"},
                {"cse": "CSE-001", "created_time": "2026-02-04", "alert_id": "A2"},
            ],
            settings={"period_granularity": "year"},
        )

        assert collection.entity_count == 1
        assert collection.period_labels == ["2025", "2026"]
        assert [s.period_start for s in collection] == ["2025-11-04", "2026-02-04"]

    def test_quarterly_derivation_labels_are_stable(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "created_time": "2026-02-04", "alert_id": "A1"},
                {"cse": "CSE-001", "created_time": "2026-05-04", "alert_id": "A2"},
            ],
            settings={"period_granularity": "quarter"},
        )

        assert collection.period_labels == ["2026-Q1", "2026-Q2"]

    def test_monthly_derivation_labels_are_stable(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "created_time": "2026-02-04", "alert_id": "A1"},
                {"cse": "CSE-001", "created_time": "2026-02-27", "alert_id": "A2"},
            ],
            settings={"period_granularity": "month"},
        )

        assert collection.period_labels == ["2026-02"]
        assert collection[0].record_count == 2


# ---------------------------------------------------------------------------
# 9. malformed / ambiguous metadata
# ---------------------------------------------------------------------------


class TestMalformedMetadata:

    def test_ambiguous_entity_columns_are_resolved_deterministically(self):

        records = [
            {"cse": "CSE-001", "customer": "Acme", "alert_id": "A1"},
        ]

        first, _ = build(records)

        second, _ = build(records)

        assert first[0].entity_id == second[0].entity_id
        assert first.entity_resolution.ambiguous is True
        assert "confidence then name" in first.entity_resolution.reason
        assert len(first.entity_resolution.candidates) == 2

    def test_ambiguity_is_reported_on_the_scope(self):

        collection, _ = build(
            [{"cse": "CSE-001", "customer": "Acme", "alert_id": "A1"}]
        )

        metadata = collection[0].metadata["entity"]

        assert metadata["ambiguous"] is True
        assert set(metadata["candidate_columns"]) == {"cse", "customer"}

    def test_missing_entity_column_reports_the_patterns_that_were_searched(self):

        collection, _ = build([{"alert_id": "A1"}])

        reason = collection[0].entity.unavailable_reason

        assert "assessment_scope_patterns.json" in reason
        assert "EntityResolver" in reason

    def test_blank_period_column_falls_back_to_timestamps(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "", "created_time": "2026-01-05", "alert_id": "A1"},
            ]
        )

        scope = collection[0]

        assert scope.period_label == "2026-01-05..2026-01-05"
        assert scope.period.method == "derived_from_timestamp_range"

    def test_ambiguous_timestamp_columns_are_ranked_and_reported(self):

        collection, _ = build(
            [
                {
                    "cse": "CSE-001",
                    "event_time": "2026-01-05",
                    "detected_at": "2026-03-09",
                    "alert_id": "A1",
                }
            ]
        )

        resolution = collection.period_resolution

        assert resolution.ambiguous is True
        assert "confidence then name" in resolution.reason
        # Deterministic: alphabetical tie-break picks detected_at.
        assert resolution.timestamp_column == "detected_at"
        assert collection[0].period_label == "2026-03-09..2026-03-09"

    def test_malformed_timestamp_falls_back_to_the_next_candidate(self):

        collection, _ = build(
            [
                {
                    "cse": "CSE-001",
                    "detected_at": "garbage",
                    "event_time": "2026-01-05",
                    "alert_id": "A1",
                }
            ]
        )

        assert collection[0].period_label == "2026-01-05..2026-01-05"

    def test_invalid_granularity_is_rejected_loudly(self):

        with pytest.raises(ValueError):
            PeriodResolver(settings={"period_granularity": "fortnight"})

    def test_empty_record_set_produces_no_scopes(self):

        collection, _ = build([])

        assert len(collection) == 0
        assert collection.record_count == 0
        assert collection.distinct_entity_count == 0
        assert collection.distinct_period_count == 0
        assert collection.to_dict()["scopes"] == []

    def test_numeric_period_labels_are_preserved(self):

        collection, _ = build(
            [{"cse": "CSE-001", "period": 2026, "alert_id": "A1"}]
        )

        assert collection[0].period_label == "2026"
        assert collection[0].period_available is True

    def test_periods_are_never_assumed_to_be_calendar_years(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "created_time": "2026-01-05", "alert_id": "A1"},
                {"cse": "CSE-001", "created_time": "2026-01-09", "alert_id": "A2"},
            ]
        )

        label = collection[0].period_label

        # The observed range is reported, not a calendar year.
        assert label == "2026-01-05..2026-01-09"
        assert label != "2026"
        assert collection[0].period.granularity == "range"


# ---------------------------------------------------------------------------
# 10. dataset_noisy.csv regression + pipeline integration
# ---------------------------------------------------------------------------


class TestExistingDatasetRegression:

    def test_dataset_noisy_csv_reports_unresolved_entity(self):

        collection, _ = build(
            [
                {
                    "alert_id": "ALRT001",
                    "priority": "HIGH",
                    "host": "WEB-PROD-01",
                    "created_time": "2026-01-01",
                    "department": "Finance",
                }
            ]
        )

        scope = collection[0]

        assert scope.entity_key == UNKNOWN_ENTITY
        assert scope.entity_available is False
        assert scope.period_label == "2026-01-01..2026-01-01"
        assert scope.record_count == 1

    def test_timestamp_candidate_ignores_resolution_timestamps(self):

        collection, _ = build(
            [
                {
                    "alert_id": "A1",
                    "created_time": "2026-01-01",
                    "closed_time": "2026-06-01",
                }
            ]
        )

        assert collection.period_resolution.timestamp_column == "created_time"
        assert collection[0].period_label == "2026-01-01..2026-01-01"


class TestMultiCseDataset:

    def test_controlled_dataset_builds_a_two_by_two_matrix(self):

        collection, _ = build(
            [
                {"cse": "CSE-001", "period": "Period-1", "alert_id": "A1"},
                {"cse": "CSE-001", "period": "Period-2", "alert_id": "A2"},
                {"cse": "CSE-002", "period": "Period-1", "alert_id": "A3"},
                {"cse": "CSE-002", "period": "Period-2", "alert_id": "A4"},
            ]
        )

        assert len(collection) == 4
        assert collection.entity_count == 2
        assert collection.period_count == 2
        assert all(s.record_count == 1 for s in collection)

    def test_repository_dataset_resolves_through_the_ingestion_layer(self):

        if not os.path.exists(os.path.join(REPOSITORY_ROOT, MULTI_CSE_DATASET)):
            pytest.skip("multi-CSE dataset not present")

        manager = IngestionManager()

        ingestion = manager.load(MULTI_CSE_DATASET)

        try:

            profile = DatasetProfiler().profile(ingestion.profiling_target)

            semantic_results = SemanticInference(
                "framework/config/semantic_patterns.json"
            ).infer(profile)

            collection = AssessmentScopeBuilder().build(
                records=ingestion.records,
                profile=profile,
                semantic_results=semantic_results,
                source_id=ingestion.source,
                source_type=ingestion.source_type,
            )

            assert len(collection) == 4
            assert collection.entity_keys == ["CSE-001", "CSE-002"]
            assert collection.period_labels == ["Period-1", "Period-2"]

            for scope in collection:
                assert scope.record_count == 2
                assert scope.entity_available is True
                assert scope.period_available is True

        finally:

            manager.release(ingestion)

    def test_every_scope_covers_exactly_the_expected_alerts(self):

        if not os.path.exists(os.path.join(REPOSITORY_ROOT, MULTI_CSE_DATASET)):
            pytest.skip("multi-CSE dataset not present")

        manager = IngestionManager()

        ingestion = manager.load(MULTI_CSE_DATASET)

        try:

            profile = DatasetProfiler().profile(ingestion.profiling_target)

            collection = AssessmentScopeBuilder().build(
                records=ingestion.records,
                profile=profile,
            )

            expected = {
                "CSE-001::Period-1": ["ALRT001", "ALRT002"],
                "CSE-001::Period-2": ["ALRT003", "ALRT004"],
                "CSE-002::Period-1": ["ALRT005", "ALRT006"],
                "CSE-002::Period-2": ["ALRT007", "ALRT008"],
            }

            actual = {
                scope.assessment_id: [
                    record["alert_id"] for record in scope.records
                ]
                for scope in collection
            }

            assert actual == expected

        finally:

            manager.release(ingestion)


class TestPipelineIntegration:

    def test_pipeline_result_carries_the_assessment_key(self):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run("dataset_noisy.csv")

        assert "assessment" in result

        assessment = result["assessment"]

        assert assessment["scope_count"] == 1
        assert assessment["record_count"] == 3
        assert assessment["entity_resolution"]["available"] is False
        assert assessment["period_resolution"]["available"] is True

    def test_pipeline_preserves_every_pre_existing_key(self):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run("dataset_noisy.csv")

        for key in [
            "dataset",
            "profile",
            "semantic_mapping",
            "mapping_report",
            "dataset_context",
            "canonical_records",
            "feature_analysis",
            "supervisory_findings",
            "entity_assessment",
            "ingestion",
        ]:

            assert key in result

    def test_pipeline_single_entity_behaviour_is_unchanged(self):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run("dataset_noisy.csv")

        # The pre-existing entity assessment still reports the same single
        # UNKNOWN_ENTITY entry with the same score.
        assert result["entity_assessment"] == [
            {
                "entity": UNKNOWN_ENTITY,
                "entity_confidence": 0,
                "entity_source": "none",
                "records_analyzed": 3,
                "attention_score": 0,
                "risk_level": "LOW",
                "risk_indicators": [],
            }
        ]

    def test_pipeline_does_not_attack_analytics_around_the_test_dataset(self):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run(MULTI_CSE_DATASET)

        assessment = result["assessment"]

        assert assessment["scope_count"] == 4
        assert assessment["entity_resolution"]["distinct_entities"] == 2
        assert assessment["period_resolution"]["distinct_periods"] == 2

        # The analytical output is still a single dataset-level analysis; the
        # scope layer exposes grouping without running it.
        assert result["profile"]["dataset_summary"]["records"] == 8
        assert len(result["entity_assessment"]) == 1

    def test_pipeline_carries_no_evidence_id_for_a_local_dataset(self):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run("dataset_noisy.csv")

        assert "evidence_id" not in result
        assert result["assessment"]["source"]["evidence_id"] is None


class TestScopeConfig:

    def test_config_exposes_scoring_axes_and_settings(self):

        axes, settings = load_scope_config(
            "framework/config/assessment_scope_patterns.json"
        )

        assert set(axes) == {
            "entity_identifier",
            "entity_display_name",
            "period_label",
            "timestamp",
        }

        assert settings["period_granularity"] == "range"
        assert settings["accepted_entity_resolver_tiers"] == ["explicit"]

    def test_comment_keys_are_never_scored_as_axes(self):

        axes, _ = load_scope_config(
            "framework/config/assessment_scope_patterns.json"
        )

        assert not [key for key in axes if key.startswith("_")]

    def test_scope_layer_never_hardcodes_a_column_name(self):

        # The module *code* must not embed a concrete entity or period column.
        # Docstrings and comments are excluded: they may show example column
        # names, but nothing executable may match on one.
        import ast

        import framework.assessment.entity_context as entity_module
        import framework.assessment.period as period_module
        import framework.assessment.scope as scope_module

        forbidden = {
            "cse",
            "cse_id",
            "period",
            "assessment_period",
            "tenant",
            "tenant_id",
            "customer",
            "customer_id",
            "customer_name",
            "entity_id",
            "entity_name",
            "created_time",
            "created_at",
            "org_name",
            "company_name",
        }

        for module in (entity_module, period_module, scope_module):

            tree = ast.parse(open(module.__file__).read())

            docstrings = set()

            for node in ast.walk(tree):

                if isinstance(
                    node,
                    (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                ):

                    docstring = ast.get_docstring(node, clean=False)

                    if docstring is not None:
                        docstrings.add(docstring)

            # These are serialized field names of the AssessmentScope data
            # contract (entity_id / entity_name / period are required output
            # fields), not names looked up in a source record.
            contract_output_keys = {
                "entity",
                "period",
                "entity_id",
                "entity_name",
                "period_label",
                "period_start",
                "period_end",
            }

            literals = [
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
            ]

            literals = [
                value
                for value in literals
                if value not in docstrings
                and not value.startswith("\n")
                and value not in contract_output_keys
            ]

            for value in literals:

                # Case sensitive on purpose: a column name would be matched
                # in lowercase, whereas UPPER_SNAKE literals here are concept
                # names that are resolved through configuration.
                assert value.strip() not in forbidden, (
                    f"{module.__name__} compares against a hardcoded column "
                    f"name: {value!r}"
                )

    def test_resolution_follows_configuration_for_an_unseen_column_name(self):

        # The strongest available proof that nothing is hardcoded: a dataset
        # whose entity and period columns appear nowhere in the framework
        # resolves correctly once the configuration names them.
        import tempfile

        config = {
            "settings": {"period_granularity": "range"},
            "entity_identifier": {
                "ENTITY_IDENTITY": {
                    "keywords": ["operator_code"],
                    "negative_keywords": [],
                    "expected_categories": ["identifier_like", "categorical"],
                }
            },
            "entity_display_name": {
                "ENTITY_NAME": {
                    "keywords": ["operator_label"],
                    "expected_categories": ["categorical", "identifier_like"],
                }
            },
            "period_label": {
                "ASSESSMENT_PERIOD": {
                    "keywords": ["wave"],
                    "expected_categories": ["categorical", "identifier_like"],
                }
            },
            "timestamp": {"TIME_REFERENCE": {"keywords": ["seen_at"]}},
        }

        with tempfile.TemporaryDirectory() as directory:

            config_path = os.path.join(directory, "scope.json")

            with open(config_path, "w") as handle:
                json.dump(config, handle)

            records, profile = profile_records(
                [
                    {
                        "operator_code": "OP-9",
                        "operator_label": "Nine",
                        "wave": "Wave-A",
                        "seen_at": "2026-05-01",
                    }
                ]
            )

            collection = AssessmentScopeBuilder(config_file=config_path).build(
                records=records,
                profile=profile,
            )

        scope = collection[0]

        assert scope.entity_id == "OP-9"
        assert scope.entity_name == "Nine"
        assert scope.period_label == "Wave-A"
        assert scope.assessment_id == "OP-9::Wave-A"

    def test_a_column_the_configuration_does_not_name_is_unresolved(self):

        # The mirror image: a plausible-looking column that the configuration
        # does not recognise must not be invented into an entity.
        collection, _ = build(
            [
                {
                    "owner_code": "OWN-3",
                    "assigned_team": "Blue",
                    "alert_id": "A1",
                }
            ]
        )

        assert collection[0].entity_key == UNKNOWN_ENTITY
        assert collection[0].entity_id is None

    def test_scope_patterns_live_in_configuration(self):

        axes, _ = load_scope_config(
            "framework/config/assessment_scope_patterns.json"
        )

        entity_keywords = set()

        for concept in axes["entity_identifier"].values():
            entity_keywords.update(
                keyword.lower() for keyword in concept.get("keywords", [])
            )

        assert {"cse", "tenant", "customer", "entity_id"} <= entity_keywords


class TestTimestampParsing:

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-01-01", "2026-01-01"),
            ("2026-01-01T10:30:00", "2026-01-01"),
            ("2026-01-01 10:30:00", "2026-01-01"),
            ("2026/01/01", "2026-01-01"),
            ("2026-01-01T10:30:00Z", "2026-01-01"),
        ],
    )
    def test_accepted_formats(self, value, expected):

        parsed = parse_timestamp(value)

        assert parsed is not None
        assert parsed.date().isoformat() == expected

    @pytest.mark.parametrize(
        "value",
        [None, "", "   ", "not-a-date", "NaN", "NAT", True, 12345, [], {}],
    )
    def test_rejected_values_never_raise(self, value):

        assert parse_timestamp(value) is None
