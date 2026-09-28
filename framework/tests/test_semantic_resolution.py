"""
Tests for SAT-SA semantic evidence resolution.

These cover the two evidence-model faults the validation observer found:

 1. ``SECURITY_SEVERITY`` was fed by both the alert severity column and the
    asset criticality column, so a finding could read asset importance as
    alert severity and declare a MEDIUM alert to be CRITICAL.
 2. ``ESCALATION_STATUS`` was declared in ``mappings.json`` but had no pattern
    in ``semantic_patterns.json``. Semantic inference scores a column only
    against patterns present in that file, so the concept was unreachable from
    the main mapping pass and findings citing it were untraceable there.

Both are corrected in configuration, not in code: the concepts are resolved by
the existing :class:`SemanticInference` scorer from
``framework/config/semantic_patterns.json`` and written by the existing
``SchemaMapper``. No test here depends on a column name being special-cased,
and the suite includes a hardcoding audit for that reason.

Run with::

    python -m pytest framework/tests/test_semantic_resolution.py -v
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile

import pytest

from framework.assessment import AssessmentScopeBuilder

from framework.capability import CapabilityEvaluator

from framework.features.adaptive_feature_engine import AdaptiveFeatureEngine

from framework.ingestion.ingestion_manager import IngestionManager

from framework.intelligence.semantic_inference import SemanticInference

from framework.mapping.schema_mapper import SchemaMapper

from framework.profiling.dataset_profiler import DatasetProfiler

from framework.supervision.execution_gap_engine import ExecutionGapEngine


REPOSITORY_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

PATTERNS_CONFIG = "framework/config/semantic_patterns.json"
MAPPINGS_CONFIG = "framework/config/mappings.json"
SCHEMA_CONFIG = "framework/canonical/canonical_schema.json"

CAPABILITY_RICH = "dataset_capability_rich.csv"

GAP_INDICATOR = "CRITICAL_ALERT_NOT_ESCALATED"


def _requires_root() -> None:
    if os.path.abspath(os.getcwd()) != REPOSITORY_ROOT:
        pytest.skip("configuration paths are relative to the repository root")


def _write_csv(directory, records):
    columns: list = []

    for record in records:
        for key in record:
            if key not in columns:
                columns.append(key)

    path = os.path.join(directory, "records.csv")

    with open(path, "w", newline="") as handle:

        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()

        for record in records:
            writer.writerow({key: record.get(key) for key in columns})

    return path


def resolve(records):
    """Map records to concepts and to canonical fields, the real way."""

    with tempfile.TemporaryDirectory() as directory:

        path = _write_csv(directory, records)

        profile = DatasetProfiler().profile(path)

    semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

    mapper = SchemaMapper(MAPPINGS_CONFIG, SCHEMA_CONFIG)

    canonical = [mapper.map_record(record, semantic_results) for record in records]

    return profile, semantic_results, canonical


def concepts_of(semantic_results):
    return {
        entry["source_column"]: entry["canonical_concept"]
        for entry in semantic_results
    }


def gap_indicators(records):
    """Indicators the execution-gap layer actually reports for these records."""

    with tempfile.TemporaryDirectory() as directory:

        path = _write_csv(directory, records)

        profile = DatasetProfiler().profile(path)

    semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

    collection = AssessmentScopeBuilder().build(
        records=records,
        profile=profile,
        semantic_results=semantic_results,
    )

    result = ExecutionGapEngine().evaluate_collection(
        collection, profile, semantic_results, CapabilityEvaluator()
    )

    return [finding["indicator"] for finding in result["findings"]]


# ---------------------------------------------------------------------------
# Phase 2: SECURITY_SEVERITY must not absorb asset criticality
# ---------------------------------------------------------------------------


class TestSeverityIsNotAssetCriticality:

    def test_a_critical_priority_reads_as_critical_severity(self):

        records = [
            {
                "alert_id": "A1",
                "priority": "CRITICAL",
                "asset_criticality": "LOW",
            }
        ]

        _, semantic_results, canonical = resolve(records)

        assert concepts_of(semantic_results)["priority"] == "SECURITY_SEVERITY"
        assert canonical[0]["alert_context"]["severity"] == "CRITICAL"
        assert canonical[0]["asset_context"]["criticality"] == "LOW"

    def test_a_medium_priority_is_never_read_as_critical_severity(self):

        # The exact inversion that produced the false CRITICAL_ALERT_NOT_ESCALATED:
        # a MEDIUM alert on a business-critical asset.
        records = [
            {
                "alert_id": "A1",
                "priority": "MEDIUM",
                "asset_criticality": "CRITICAL",
            }
        ]

        _, semantic_results, canonical = resolve(records)

        assert concepts_of(semantic_results)["priority"] == "SECURITY_SEVERITY"
        assert canonical[0]["alert_context"]["severity"] == "MEDIUM"
        assert canonical[0]["asset_context"]["criticality"] == "CRITICAL"

    def test_severity_and_criticality_are_distinct_concepts(self):

        records = [
            {
                "alert_id": "A1",
                "priority": "HIGH",
                "asset_criticality": "CRITICAL",
            }
        ]

        _, semantic_results, _ = resolve(records)

        concepts = concepts_of(semantic_results)

        assert concepts["priority"] == "SECURITY_SEVERITY"
        assert concepts["asset_criticality"] == "ASSET_CRITICALITY"
        assert concepts["priority"] != concepts["asset_criticality"]

    def test_a_high_priority_alert_on_a_critical_asset_is_not_a_gap(self):

        indicators = gap_indicators(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "asset_criticality": "CRITICAL",
                    "escalation_status": "NOT_ESCALATED",
                }
            ]
        )

        assert GAP_INDICATOR not in indicators

    def test_a_critical_alert_on_a_low_criticality_asset_is_still_a_gap(self):

        # Correcting the collision must not blind the layer: genuine critical
        # alert severity with an explicit non-escalation is still a real gap.
        indicators = gap_indicators(
            [
                {
                    "alert_id": "A1",
                    "priority": "CRITICAL",
                    "asset_criticality": "LOW",
                    "escalation_status": "NOT_ESCALATED",
                }
            ]
        )

        assert indicators == [GAP_INDICATOR]

    def test_severity_is_not_inferred_from_criticality_alone(self):

        # With no severity column at all, no severity may be manufactured from
        # the asset's importance.
        records = [
            {"alert_id": "A1", "asset_criticality": "CRITICAL"}
        ]

        _, semantic_results, canonical = resolve(records)

        assert (
            "SECURITY_SEVERITY" not in concepts_of(semantic_results).values()
        )
        assert canonical[0]["alert_context"]["severity"] is None

    def test_criticality_is_not_inferred_from_severity_alone(self):

        records = [{"alert_id": "A1", "priority": "CRITICAL"}]

        _, semantic_results, canonical = resolve(records)

        assert (
            "ASSET_CRITICALITY" not in concepts_of(semantic_results).values()
        )
        assert canonical[0]["asset_context"]["criticality"] is None

    def test_no_source_column_feeds_severity_and_criticality_together(self):

        for record in (
            {"alert_id": "A1", "priority": "HIGH", "asset_criticality": "LOW"},
            {"alert_id": "A2", "priority": "LOW", "asset_criticality": "HIGH"},
            {"alert_id": "A3", "priority": "MEDIUM", "asset_criticality": "MEDIUM"},
        ):
            _, semantic_results, _ = resolve([record])

            sources: dict = {}

            for entry in semantic_results:
                sources.setdefault(entry["canonical_concept"], []).append(
                    entry["source_column"]
                )

            assert sources.get("SECURITY_SEVERITY") == ["priority"], record
            assert sources.get("ASSET_CRITICALITY") == [
                "asset_criticality"
            ], record


# ---------------------------------------------------------------------------
# The canonical destination and the feature that depends on it
# ---------------------------------------------------------------------------


class TestAssetCriticalityCanonicalDestination:

    def test_the_concept_is_declared_against_the_existing_canonical_path(self):

        with open(MAPPINGS_CONFIG) as handle:
            mappings = json.load(handle)

        assert "ASSET_CRITICALITY" in mappings
        assert (
            mappings["ASSET_CRITICALITY"]["canonical_path"]
            == "asset_context.criticality"
        )

        # The path is a pre-existing canonical field, not one invented here.
        with open(SCHEMA_CONFIG) as handle:
            schema = json.load(handle)

        assert "criticality" in schema["asset_context"]

    def test_the_canonical_field_is_populated(self):

        records = [
            {
                "alert_id": "A1",
                "priority": "MEDIUM",
                "asset_criticality": "CRITICAL",
            }
        ]

        _, _, canonical = resolve(records)

        assert canonical[0]["asset_context"]["criticality"] == "CRITICAL"
        assert canonical[0]["alert_context"]["severity"] == "MEDIUM"

    def test_the_criticality_feature_becomes_available_when_evidence_exists(self):

        records = [
            {
                "alert_id": "A1",
                "priority": "HIGH",
                "asset_criticality": "CRITICAL",
            }
        ]

        _, _, canonical = resolve(records)

        features = {
            item["feature"]: item
            for item in AdaptiveFeatureEngine().evaluate_available_features(
                canonical[0]
            )
        }

        assert features["ASSET_CRITICALITY_RISK"]["available"] is True
        assert features["SEVERITY_RISK"]["available"] is True

    def test_the_criticality_feature_stays_missing_without_evidence(self):

        records = [{"alert_id": "A1", "priority": "HIGH"}]

        _, _, canonical = resolve(records)

        features = {
            item["feature"]: item
            for item in AdaptiveFeatureEngine().evaluate_available_features(
                canonical[0]
            )
        }

        assert features["ASSET_CRITICALITY_RISK"]["available"] is False
        assert features["ASSET_CRITICALITY_RISK"]["missing_fields"] == [
            "asset_context.criticality"
        ]


# ---------------------------------------------------------------------------
# Phase 3: ESCALATION_STATUS must be resolvable by the main mapping pass
# ---------------------------------------------------------------------------


class TestEscalationStatusResolution:

    def test_escalation_status_resolves_to_the_canonical_concept(self):

        records = [
            {
                "alert_id": "A1",
                "priority": "HIGH",
                "host": "WEB-01",
                "investigation_notes": "traced",
                "escalation_status": "not_escalated",
            }
        ]

        _, semantic_results, canonical = resolve(records)

        concepts = concepts_of(semantic_results)

        assert concepts["priority"] == "SECURITY_SEVERITY"
        assert concepts["host"] == "ASSET_IDENTIFIER"
        assert concepts["investigation_notes"] == "INVESTIGATION_EVIDENCE"
        assert concepts["escalation_status"] == "ESCALATION_STATUS"

        assert canonical[0]["response_context"]["escalation_status"] == (
            "not_escalated"
        )

    def test_the_resolved_concept_is_stated_with_a_confidence(self):

        records = [
            {"alert_id": "A1", "escalation_status": "not_escalated"}
        ]

        _, semantic_results, _ = resolve(records)

        entry = next(
            item
            for item in semantic_results
            if item["source_column"] == "escalation_status"
        )

        assert entry["canonical_concept"] == "ESCALATION_STATUS"
        assert 0.45 <= entry["confidence"] <= 1.0

    @pytest.mark.parametrize(
        "column",
        [
            "is_escalated",
            "escalation_state",
            "escalation_level",
        ],
    )
    def test_renamed_equivalents_still_resolve(self, column):

        # Resolution is pattern-driven, so a deliberate rename keeps working
        # without any code change.
        records = [{"alert_id": "A1", column: "no"}]

        _, semantic_results, _ = resolve(records)

        assert concepts_of(semantic_results).get(column) == "ESCALATION_STATUS"

    @pytest.mark.parametrize(
        "column",
        [
            "priority",
            "host",
            "investigation_notes",
            "asset_criticality",
            "escalation_time",
            "alert_id",
        ],
    )
    def test_unrelated_columns_do_not_resolve_to_escalation_status(
        self, column
    ):

        records = [{"alert_id": "A1", column: "escalated"}]

        _, semantic_results, _ = resolve(records)

        assert concepts_of(semantic_results).get(column) != "ESCALATION_STATUS"

    def test_an_escalation_timestamp_is_not_an_escalation_status(self):

        records = [
            {
                "alert_id": "A1",
                "escalation_time": "2026-04-02",
            }
        ]

        _, semantic_results, _ = resolve(records)

        assert (
            concepts_of(semantic_results).get("escalation_time")
            != "ESCALATION_STATUS"
        )

    def test_the_actor_who_escalated_is_not_an_escalation_status(self):

        # escalated_by names a person. Who escalated is not an escalation
        # state, and reading it as one would put a username into
        # response_context.escalation_status.
        records = [
            {
                "alert_id": "A1",
                "escalation_status": "not_escalated",
                "escalated_by": "Alice",
            }
        ]

        _, semantic_results, canonical = resolve(records)

        concepts = concepts_of(semantic_results)

        assert "ESCALATION_STATUS" not in concepts.values() or concepts.get(
            "escalated_by"
        ) != "ESCALATION_STATUS"

        assert concepts.get("escalated_by") in (None, "USER_IDENTIFIER")

        # The genuine status column is unaffected by its actor neighbour.
        assert concepts.get("escalation_status") == "ESCALATION_STATUS"
        assert canonical[0]["response_context"]["escalation_status"] == (
            "not_escalated"
        )

    def test_an_actor_column_alone_does_not_become_an_escalation_status(self):

        records = [{"alert_id": "A1", "escalated_by": "Alice"}]

        _, semantic_results, canonical = resolve(records)

        assert (
            concepts_of(semantic_results).get("escalated_by")
            != "ESCALATION_STATUS"
        )
        assert canonical[0]["response_context"]["escalation_status"] is None

    @pytest.mark.parametrize(
        "column",
        [
            "created_at",
            "created_time",
            "timestamp",
            "event_timestamp",
            "detected_at",
        ],
    )
    def test_timestamp_columns_are_not_escalation_status(self, column):

        records = [{"alert_id": "A1", column: "2026-04-02 09:15:00"}]

        _, semantic_results, _ = resolve(records)

        assert (
            concepts_of(semantic_results).get(column) != "ESCALATION_STATUS"
        )


# ---------------------------------------------------------------------------
# Phase 4: downstream traceability
# ---------------------------------------------------------------------------


class TestTraceability:

    def test_the_mapping_publishes_the_escalation_source_column(self):

        _requires_root()

        result = IngestionManager().load(CAPABILITY_RICH)

        profile = DatasetProfiler().profile(result.profiling_target)

        semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

        sources = {
            entry["canonical_concept"]: entry["source_column"]
            for entry in semantic_results
        }

        assert sources["ESCALATION_STATUS"] == "escalation_status"
        assert sources["SECURITY_SEVERITY"] == "priority"
        assert sources["ASSET_CRITICALITY"] == "asset_criticality"

    def test_the_evidence_index_resolves_escalation_from_the_mapping_pass(
        self
    ):

        _requires_root()

        result = IngestionManager().load(CAPABILITY_RICH)

        profile = DatasetProfiler().profile(result.profiling_target)

        semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

        index = CapabilityEvaluator().build_evidence_index(
            result.records, profile, semantic_results
        )

        assert (
            index.entries_for("ESCALATION_STATUS")["resolution"]
            == "semantic_mapping"
        )
        assert index.entries_for("SECURITY_SEVERITY")["column"] == "priority"
        assert index.entries_for("ASSET_CRITICALITY")["column"] == (
            "asset_criticality"
        )

    def test_a_finding_citing_escalation_is_traceable_to_its_column(self):

        _requires_root()

        records = [
            {
                "cse": "A",
                "period": "P1",
                "alert_id": "A1",
                "priority": "CRITICAL",
                "escalation_status": "not_escalated",
            }
        ]

        with tempfile.TemporaryDirectory() as directory:

            path = _write_csv(directory, records)

            profile = DatasetProfiler().profile(path)

        semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

        collection = AssessmentScopeBuilder().build(
            records=records,
            profile=profile,
            semantic_results=semantic_results,
        )

        result = ExecutionGapEngine().evaluate_collection(
            collection, profile, semantic_results, CapabilityEvaluator()
        )

        finding = next(
            item
            for item in result["findings"]
            if item["indicator"] == GAP_INDICATOR
        )

        # The evidence dictionary names the concept, and the mapping alone
        # says which column supplies it, so no header fallback is needed.
        assert finding["evidence"]["ESCALATION_STATUS"] == "not_escalated"

        declared = {
            entry["canonical_concept"]: entry["source_column"]
            for entry in semantic_results
        }

        assert declared[finding["evidence_concepts"][1]] == "escalation_status"

    def test_the_canonical_record_carries_both_response_and_asset_context(
        self
    ):

        _requires_root()

        result = IngestionManager().load(CAPABILITY_RICH)

        profile = DatasetProfiler().profile(result.profiling_target)

        semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

        mapper = SchemaMapper(MAPPINGS_CONFIG, SCHEMA_CONFIG)

        record = result.records[0]

        canonical = mapper.map_record(record, semantic_results)

        # Whichever column supplied severity, it must be the alert's own.
        assert canonical["alert_context"]["severity"] == record["priority"]
        assert (
            canonical["asset_context"]["criticality"]
            == record["asset_criticality"]
        )


# ---------------------------------------------------------------------------
# Phase 6: no source-column special cases in analytical code
# ---------------------------------------------------------------------------


class TestNoSourceColumnSpecialCases:

    SOURCE_COLUMNS = [
        "priority",
        "asset_criticality",
        "escalation_status",
        "host",
        "investigation_notes",
        "closed_time",
        "closed_by",
        "alert_id",
        "threat_type",
        "security_label",
        "created_time",
    ]

    ANALYTICAL_MODULES = [
        "framework/supervision/execution_gap_detector.py",
        "framework/supervision/execution_gap_engine.py",
        "framework/supervision/negative_space_detector.py",
        "framework/supervision/operational_pattern_detector.py",
        "framework/supervisory/rules/rule_engine.py",
        "framework/supervisory/rules/execution_gap_rules.py",
        "framework/intelligence/semantic_inference.py",
        "framework/mapping/schema_mapper.py",
    ]

    def test_no_module_compares_a_column_name_to_a_literal(self):

        comparison = re.compile(
            r"""(?:==|!=|in)\s*["'](%s)["']""" % "|".join(self.SOURCE_COLUMNS)
        )
        subscript = re.compile(r"""\[\s*["']([^"']+)["']\s*\]""")
        getter = re.compile(r"""\.get\(\s*["']([^"']+)["']""")

        for path in self.ANALYTICAL_MODULES:

            with open(path) as handle:
                source = handle.read()

            code = "\n".join(
                line
                for line in source.splitlines()
                if not line.strip().startswith("#")
            )

            assert not comparison.search(code), (
                f"{path} compares a source column name to a literal"
            )

            for pattern in (subscript, getter):
                for literal in pattern.findall(code):
                    assert literal not in self.SOURCE_COLUMNS, (
                        f"{path} reads records by the source column "
                        f"{literal!r}"
                    )

    def test_the_concepts_are_resolved_only_from_configuration(self):

        with open(PATTERNS_CONFIG) as handle:
            patterns = json.load(handle)

        assert "SECURITY_SEVERITY" in patterns
        assert "ESCALATION_STATUS" in patterns
        assert "ASSET_CRITICALITY" in patterns

        # The generic asset-importance term must not be a severity keyword.
        assert "criticality" not in patterns["SECURITY_SEVERITY"]["keywords"]

        with open(MAPPINGS_CONFIG) as handle:
            mappings = json.load(handle)

        assert (
            mappings["SECURITY_SEVERITY"]["canonical_path"]
            == "alert_context.severity"
        )
        assert (
            mappings["ASSET_CRITICALITY"]["canonical_path"]
            == "asset_context.criticality"
        )
        assert (
            mappings["ESCALATION_STATUS"]["canonical_path"]
            == "response_context.escalation_status"
        )
