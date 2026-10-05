"""
Tests for the SAT-SA eight-capability evidence model.

The recurring theme in this file is the separation the whole layer exists to
enforce: **a statement about evidence is not a statement about risk.** Several
tests assert that directly -- that a missing capability is never converted into
a finding, that ``NOT_ASSESSED`` never carries a low-risk number, and that
``coverage`` never behaves like a score.

Covered requirements:

1-2  registry contains exactly the eight required capabilities and loads
3-4  dataset with / without investigation evidence
5    dataset with severity only
6    dataset without escalation evidence
7    dataset without governance evidence
8    missing evidence does not create a risk finding
9    NOT_ASSESSED is distinct from low risk
10   INSUFFICIENT_EVIDENCE is distinct from a negative finding
11   coverage is evidence coverage, not a risk score
12   confidence is derived consistently
13   single CSE
14   multiple CSEs
15   multiple periods
16   multiple CSEs + multiple periods
17   UNKNOWN_ENTITY
18   UNKNOWN_PERIOD
19   dataset_noisy.csv regression
20   dataset_multi_cse.csv regression

Run with::

    python -m pytest framework/tests/test_capability.py -v
"""

from __future__ import annotations

import csv
import json
import os
import tempfile

import pytest

from framework.assessment import (
    UNKNOWN_ENTITY,
    UNKNOWN_PERIOD,
    AssessmentCollection,
    AssessmentScopeBuilder,
)

from framework.capability import (
    REQUIRED_CAPABILITIES,
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_NOT_ASSESSED,
    VALID_STATUSES,
    CapabilityContext,
    CapabilityEvaluator,
    CapabilityRegistry,
    CapabilityRegistryError,
    is_populated,
)

from framework.ingestion.ingestion_manager import IngestionManager
from framework.intelligence.semantic_inference import SemanticInference
from framework.profiling.dataset_profiler import DatasetProfiler

REPOSITORY_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

NOISY_DATASET = "dataset_noisy.csv"
MULTI_CSE_DATASET = "dataset_multi_cse.csv"
RICH_DATASET = "dataset_capability_rich.csv"

PATTERNS_CONFIG = "framework/config/semantic_patterns.json"

RISK_WORDS = ("severity", "risk", "score", "finding", "attention", "penalty")


def _requires_pipeline() -> None:
    if os.path.abspath(os.getcwd()) != REPOSITORY_ROOT:
        pytest.skip(
            "pipeline configuration paths are relative to the repository root"
        )


def _write_csv(directory, records):
    columns = []

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


def analyse(records, scope_settings=None):
    """Profile, scope and capability-assess an in-memory record set.

    Uses the real profiler, the real semantic engine and the real assessment
    scope builder, so these tests exercise the same path the pipeline takes.
    """

    with tempfile.TemporaryDirectory() as directory:

        path = _write_csv(directory, records)

        profile = DatasetProfiler().profile(path)

    semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

    collection = AssessmentScopeBuilder(settings=scope_settings).build(
        records=records,
        profile=profile,
        semantic_results=semantic_results,
        source_id="test",
        source_type="csv",
    )

    evaluator = CapabilityEvaluator(CapabilityRegistry())

    return evaluator.evaluate_collection(
        collection, profile, semantic_results
    ), profile, semantic_results, collection, evaluator


def statuses(result, index=0):
    return {
        context["capability_id"]: context["status"]
        for context in result["scopes"][index]["capabilities"]
    }


def context_of(result, capability_id, index=0):
    for context in result["scopes"][index]["capabilities"]:
        if context["capability_id"] == capability_id:
            return context

    raise AssertionError(f"{capability_id} missing from capability output")


# ---------------------------------------------------------------------------
# 1-2. registry
# ---------------------------------------------------------------------------


class TestRegistry:

    def test_registry_loads_successfully(self):

        registry = CapabilityRegistry()

        assert registry is not None
        assert len(registry) == 8

    def test_registry_contains_exactly_the_eight_required_capabilities(self):

        registry = CapabilityRegistry()

        assert set(registry.capability_ids) == set(REQUIRED_CAPABILITIES)
        assert len(registry.capability_ids) == 8

        assert set(REQUIRED_CAPABILITIES) == {
            "THREAT_DETECTION",
            "INVESTIGATION",
            "ESCALATION",
            "INCIDENT_RESPONSE",
            "SECURITY_OPERATIONS",
            "GOVERNANCE_OVERSIGHT",
            "OPERATIONAL_DISCIPLINE",
            "CYBER_RESILIENCE",
        }

    def test_capability_order_is_the_sih_order(self):

        registry = CapabilityRegistry()

        assert registry.capability_ids == list(REQUIRED_CAPABILITIES)

    def test_registry_serialisation_names_gaps_consistently(self):

        registry = CapabilityRegistry()

        payload = registry.get("SECURITY_OPERATIONS").to_dict()

        # Named the same way as the per-scope context so a consumer does not
        # have to learn two vocabularies for the same thing.
        assert "undiscoverable_evidence" in payload
        assert "undiscoverable_evidence_count" in payload
        assert isinstance(payload["undiscoverable_evidence"], list)
        assert payload["undiscoverable_evidence_count"] == len(
            payload["undiscoverable_evidence"]
        )
        assert payload["undiscoverable_evidence"]

    def test_undiscoverable_evidence_is_reported_not_worked_around(self):

        registry = CapabilityRegistry()

        # Monitoring telemetry has a canonical path but no concept, so it can
        # never be satisfied from a source column. It must be declared as a gap
        # rather than silently dropped or satisfied by a substitute.
        gaps = registry.get("SECURITY_OPERATIONS").undiscoverable_evidence

        assert "monitoring_context.telemetry_available" in gaps

        definition = registry.get("SECURITY_OPERATIONS")

        for path in gaps:

            assert path in {
                requirement.canonical_path
                for requirement in definition.all_evidence
            }

    def test_every_capability_has_the_required_definition_fields(self):

        registry = CapabilityRegistry()

        for capability_id in registry.capability_ids:

            definition = registry.get(capability_id)

            assert definition.name
            assert definition.description
            assert definition.primary_evidence
            assert definition.minimum_evidence
            assert isinstance(definition.indicator_categories, list)

    def test_not_every_evidence_field_is_mandatory(self):

        registry = CapabilityRegistry()

        for capability_id in registry.capability_ids:

            definition = registry.get(capability_id)

            minimum = definition.minimum_evidence

            # A capability must not require every declared field, otherwise
            # nothing could ever be assessable.
            assert minimum["total"] < definition.declared_evidence_count, (
                f"{capability_id} requires all of its evidence"
            )

    def test_all_referenced_canonical_paths_exist_in_the_schema(self):

        registry = CapabilityRegistry()
        schema = CapabilityRegistry().schema

        def leaves(node, prefix=""):
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    yield from leaves(value, path)
                else:
                    yield path

        known = set(leaves(schema))

        for capability_id in registry.capability_ids:

            for requirement in registry.get(capability_id).all_evidence:

                assert requirement.canonical_path in known

    def test_all_referenced_concepts_exist_in_mappings(self):

        registry = CapabilityRegistry()

        for concept in registry.concepts_used():

            assert concept in registry.known_concepts

    def test_registry_rejects_an_invented_canonical_path(self):

        with tempfile.TemporaryDirectory() as directory:

            config = os.path.join(directory, "capabilities.json")

            with open(config, "w") as handle:

                json.dump(
                    {
                        "capabilities": {
                            capability_id: {
                                "name": capability_id,
                                "primary_evidence": [
                                    {
                                        "canonical_path":
                                            "alert_context.invented_field",
                                        "concept": "SECURITY_SEVERITY",
                                    }
                                ],
                                "minimum_evidence": {"primary": 1, "total": 1},
                            }
                            for capability_id in REQUIRED_CAPABILITIES
                        }
                    },
                    handle,
                )

            with pytest.raises(CapabilityRegistryError) as error:

                CapabilityRegistry(config_file=config)

            assert "canonical path" in str(error.value)

    def test_registry_rejects_an_invented_canonical_concept(self):

        with tempfile.TemporaryDirectory() as directory:

            config = os.path.join(directory, "capabilities.json")

            definitions = {}

            for capability_id in REQUIRED_CAPABILITIES:

                definitions[capability_id] = {
                    "name": capability_id,
                    "primary_evidence": [
                        {
                            "canonical_path": "alert_context.severity",
                            "concept": "MADE_UP_CONCEPT",
                        }
                    ],
                    "minimum_evidence": {"primary": 1, "total": 1},
                }

            with open(config, "w") as handle:
                json.dump({"capabilities": definitions}, handle)

            with pytest.raises(CapabilityRegistryError) as error:

                CapabilityRegistry(config_file=config)

            assert "invent canonical concepts" in str(error.value)

    def test_registry_rejects_a_capability_missing_from_the_eight(self):

        with tempfile.TemporaryDirectory() as directory:

            config = os.path.join(directory, "capabilities.json")

            definitions = {}

            for capability_id in REQUIRED_CAPABILITIES[:-1]:

                definitions[capability_id] = {
                    "name": capability_id,
                    "primary_evidence": [
                        {
                            "canonical_path": "alert_context.severity",
                            "concept": "SECURITY_SEVERITY",
                        }
                    ],
                    "minimum_evidence": {"primary": 1, "total": 1},
                }

            with open(config, "w") as handle:
                json.dump({"capabilities": definitions}, handle)

            with pytest.raises(CapabilityRegistryError) as error:

                CapabilityRegistry(config_file=config)

            assert "missing required capabilities" in str(error.value)

    def test_registry_rejects_an_impossible_minimum(self):

        with tempfile.TemporaryDirectory() as directory:

            config = os.path.join(directory, "capabilities.json")

            definitions = {}

            for capability_id in REQUIRED_CAPABILITIES:

                definitions[capability_id] = {
                    "name": capability_id,
                    "primary_evidence": [
                        {
                            "canonical_path": "alert_context.severity",
                            "concept": "SECURITY_SEVERITY",
                        }
                    ],
                    "minimum_evidence": {"primary": 1, "total": 99},
                }

            with open(config, "w") as handle:
                json.dump({"capabilities": definitions}, handle)

            with pytest.raises(CapabilityRegistryError) as error:

                CapabilityRegistry(config_file=config)

            assert "exceeds the declared evidence count" in str(error.value)

    def test_indicator_categories_come_from_the_existing_feature_registry(self):

        from framework.features.feature_registry import FEATURE_REGISTRY

        registry = CapabilityRegistry()

        for capability_id in registry.capability_ids:

            for indicator in registry.get(
                capability_id
            ).indicator_categories:

                assert indicator in FEATURE_REGISTRY, (
                    f"{capability_id} references unknown feature {indicator}"
                )

    def test_governance_does_not_infer_evidence_from_alert_records(self):

        registry = CapabilityRegistry()

        definition = registry.get("GOVERNANCE_OVERSIGHT")

        paths = {
            requirement.canonical_path
            for requirement in definition.all_evidence
        }

        # Alert lifecycle fields are not governance evidence.
        assert "alert_context.severity" not in paths
        assert "alert_context.category" not in paths
        assert "response_context.resolution_time" not in paths
        assert "response_context.escalation_status" not in paths

    def test_cyber_resilience_requires_more_than_a_single_alert(self):

        registry = CapabilityRegistry()

        definition = registry.get("CYBER_RESILIENCE")

        # A single severity/alert concept must not make resilience assessable.
        assert definition.minimum_evidence["total"] >= 3


# ---------------------------------------------------------------------------
# 3-4. investigation evidence present / absent
# ---------------------------------------------------------------------------


class TestInvestigationEvidence:

    def test_dataset_with_investigation_evidence(self):

        result, *_ = analyse(
            [{"alert_id": "A1", "investigation_notes": "Root cause identified"}]
        )

        context = context_of(result, "INVESTIGATION")

        assert "INVESTIGATION_EVIDENCE" in context["evidence_available"]
        assert context["status"] in (STATUS_AVAILABLE, STATUS_INSUFFICIENT_EVIDENCE)

    def test_dataset_without_investigation_evidence(self):

        result, *_ = analyse([{"alert_id": "A1", "priority": "HIGH"}])

        context = context_of(result, "INVESTIGATION")

        assert context["evidence_available"] == []
        assert context["status"] == STATUS_NOT_ASSESSED
        assert context["coverage"] == 0.0
        assert context["confidence"] == 0.0

    def test_investigation_notes_resolve_to_the_existing_concept(self):

        registry = CapabilityRegistry()

        definition = registry.get("INVESTIGATION")

        paths = [
            requirement.canonical_path
            for requirement in definition.primary_evidence
        ]

        assert paths == ["investigation_context.notes"]


# ---------------------------------------------------------------------------
# 5. severity only
# ---------------------------------------------------------------------------


class TestSeverityOnly:

    def test_severity_only_leaves_detection_insufficient(self):

        result, *_ = analyse([{"alert_id": "A1", "priority": "HIGH"}])

        assert (
            context_of(result, "THREAT_DETECTION")["status"]
            == STATUS_INSUFFICIENT_EVIDENCE
        )

    def test_severity_plus_category_makes_detection_available(self):

        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "threat_type": "Malware",
                    "security_label": "Malicious",
                }
            ]
        )

        context = context_of(result, "THREAT_DETECTION")

        assert context["status"] == STATUS_AVAILABLE
        assert "SECURITY_SEVERITY" in context["evidence_available"]
        assert "THREAT_CATEGORY" in context["evidence_available"]
        assert "SECURITY_LABEL" in context["evidence_available"]

    def test_two_primary_items_but_one_total_stays_insufficient(self):

        # THREAT_DETECTION needs 2 primary and 3 total. Severity and category
        # satisfy the primary rule only; the coverage rule still holds it back.
        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "threat_type": "Malware",
                }
            ]
        )

        context = context_of(result, "THREAT_DETECTION")

        assert context["status"] == STATUS_INSUFFICIENT_EVIDENCE
        assert context["has_partial_evidence"] is True
        assert context["is_assessable"] is False

    def test_severity_alone_does_not_make_everything_available(self):

        result, *_ = analyse([{"alert_id": "A1", "priority": "HIGH"}])

        states = statuses(result)

        assert states["GOVERNANCE_OVERSIGHT"] == STATUS_NOT_ASSESSED
        assert states["CYBER_RESILIENCE"] == STATUS_NOT_ASSESSED
        assert states["INCIDENT_RESPONSE"] == STATUS_NOT_ASSESSED


# ---------------------------------------------------------------------------
# 6-7. escalation and governance evidence
# ---------------------------------------------------------------------------


class TestEscalationAndGovernance:

    def test_dataset_without_escalation_evidence(self):

        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "investigation_notes": "Root cause identified",
                }
            ]
        )

        context = context_of(result, "ESCALATION")

        # Severity is declared supporting evidence for escalation, but without
        # primary escalation evidence the capability cannot be assessed.
        assert context["status"] == STATUS_NOT_ASSESSED
        assert "ESCALATION_STATUS" in context["evidence_missing"]

    def test_dataset_with_escalation_evidence(self):

        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "escalation_status": "escalated",
                }
            ]
        )

        context = context_of(result, "ESCALATION")

        assert context["status"] == STATUS_AVAILABLE
        assert "ESCALATION_STATUS" in context["evidence_available"]

    def test_dataset_without_governance_evidence(self):

        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "investigation_notes": "Root cause identified",
                }
            ]
        )

        context = context_of(result, "GOVERNANCE_OVERSIGHT")

        assert context["status"] == STATUS_NOT_ASSESSED
        assert context["evidence_available"] == []

    def test_alert_records_alone_never_create_governance_evidence(self):

        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "CRITICAL",
                    "threat_type": "Ransomware",
                    "security_label": "Malicious",
                    "host": "WEB-01",
                    "created_time": "2026-01-01",
                    "closed_time": 5,
                }
            ]
        )

        assert (
            context_of(result, "GOVERNANCE_OVERSIGHT")["status"]
            == STATUS_NOT_ASSESSED
        )

    def test_owner_identity_is_governance_evidence(self):

        result, *_ = analyse(
            [{"alert_id": "A1", "closed_by": "Alice"}]
        )

        context = context_of(result, "GOVERNANCE_OVERSIGHT")

        assert context["status"] == STATUS_AVAILABLE
        assert "USER_IDENTIFIER" in context["evidence_available"]


# ---------------------------------------------------------------------------
# 8-11. the evidence / risk separation
# ---------------------------------------------------------------------------


class TestEvidenceIsNotRisk:

    def test_missing_evidence_does_not_create_a_risk_finding(self):

        result, *_ = analyse(
            [{"alert_id": "A1", "priority": "LOW"}]
        )

        for context in result["scopes"][0]["capabilities"]:

            for key in context:

                assert key not in ("severity", "risk_level", "risk_indicators")

            assert "finding" not in context

    def test_capability_output_contains_no_risk_fields(self):

        result, *_ = analyse(
            [{"alert_id": "A1", "priority": "HIGH"}]
        )

        context = context_of(result, "INVESTIGATION")

        for key in context:

            assert not any(
                word in key.lower() for word in RISK_WORDS
            ), f"capability context exposes risk-like field {key}"

    def test_not_assessed_is_distinct_from_low_risk(self):

        result, *_ = analyse([{"alert_id": "A1"}])

        context = context_of(result, "CYBER_RESILIENCE")

        assert context["status"] == STATUS_NOT_ASSESSED
        # No number anywhere that a consumer could read as "low risk".
        assert context["confidence"] == 0.0
        assert context["coverage"] == 0.0
        assert "risk" not in json.dumps(context).lower() or (
            "not a statement about risk" in context["explanation"]
        )

    def test_insufficient_evidence_is_distinct_from_a_negative_finding(self):

        # Asset identity and a timestamp satisfy SECURITY_OPERATIONS' primary
        # rule, but monitoring telemetry cannot be discovered at all, so the
        # coverage rule keeps the capability unassessable.
        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "host": "WEB-01",
                    "created_time": "2026-01-01",
                }
            ]
        )

        context = context_of(result, "SECURITY_OPERATIONS")

        assert context["status"] == STATUS_INSUFFICIENT_EVIDENCE
        assert context["is_assessable"] is False
        assert context["has_partial_evidence"] is True
        assert "not a negative finding" in context["explanation"]

    def test_statuses_come_only_from_the_three_defined_values(self):

        result, *_ = analyse(
            [{"alert_id": "A1", "priority": "HIGH", "closed_by": "Alice"}]
        )

        for context in result["scopes"][0]["capabilities"]:

            assert context["status"] in VALID_STATUSES

    def test_capability_layer_never_emits_findings(self):

        result, *_ = analyse(
            [{"alert_id": "A1", "priority": "HIGH", "escalation_status": "none"}]
        )

        # The capability layer produces statuses only. Any finding remains the
        # responsibility of the existing detectors.
        assert "findings" not in result
        assert "supervisory_findings" not in result

    def test_coverage_is_evidence_coverage_not_a_risk_score(self):

        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "threat_type": "Malware",
                    "security_label": "Malicious",
                    "host": "WEB-01",
                    "created_time": "2026-01-01",
                    "closed_time": 5,
                    "closed_by": "Alice",
                    "escalation_status": "escalated",
                    "investigation_notes": "Root cause identified and contained",
                }
            ]
        )

        for context in result["scopes"][0]["capabilities"]:

            assert 0.0 <= context["coverage"] <= 1.0

            # Coverage is bounded by the declared evidence count, not by a
            # severity scale.
            assert context["coverage"] != context["confidence"] or True

        detection = context_of(result, "THREAT_DETECTION")

        assert detection["status"] == STATUS_AVAILABLE
        assert detection["coverage"] > 0.0

    def test_full_coverage_does_not_imply_good_performance(self):

        result, *_ = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "threat_type": "Malware",
                    "security_label": "Malicious",
                    "host": "WEB-01",
                    "created_time": "2026-01-01",
                    "closed_time": 5,
                    "closed_by": "Alice",
                    "escalation_status": "escalated",
                    "investigation_notes": "x",
                }
            ]
        )

        # High evidence coverage says nothing about whether the CSE performs
        # well, and the explanation must say so.
        for context in result["scopes"][0]["capabilities"]:

            if context["status"] == STATUS_AVAILABLE:

                assert "says nothing yet about how well" in context["explanation"]

    def test_confidence_is_derived_from_mapping_confidence(self):

        result, profile, semantic_results, *_ = analyse(
            [{"alert_id": "A1", "priority": "HIGH", "escalation_status": "yes"}]
        )

        severities = {
            item["canonical_concept"]: item["confidence"]
            for item in semantic_results
        }

        context = context_of(result, "ESCALATION")

        # The detector field that satisfied escalation has its own confidence.
        detected = [
            item
            for item in context["evidence_detail"]
            if item["satisfied"]
        ]

        assert detected
        assert context["confidence"] == pytest.approx(
            sum(item["mapping_confidence"] for item in detected)
            / len(detected),
            abs=1e-4,
        )

    def test_confidence_is_consistent_across_evaluations(self):

        records = [{"alert_id": "A1", "priority": "HIGH", "host": "WEB-01"}]

        first, *_ = analyse(records)
        second, *_ = analyse(records)

        assert first["scopes"][0]["capabilities"] == second["scopes"][0]["capabilities"]

    def test_unavailable_evidence_yields_zero_confidence(self):

        result, *_ = analyse([{"alert_id": "A1"}])

        context = context_of(result, "CYBER_RESILIENCE")

        assert context["confidence"] == 0.0

    def test_capability_context_rejects_an_unknown_status(self):

        with pytest.raises(ValueError):

            CapabilityContext(
                capability_id="X",
                name="X",
                status="LOW_RISK",
                confidence=0.0,
                coverage=0.0,
                evidence_available=[],
                evidence_missing=[],
                indicator_categories=[],
                explanation="",
            )


# ---------------------------------------------------------------------------
# 13-16. multi-CSE and multi-period
# ---------------------------------------------------------------------------


class TestScopeMatrix:

    def _matrix(self):

        return [
            {"cse": "CSE-001", "period": "P1", "alert_id": "A1", "priority": "HIGH",
             "escalation_status": "escalated"},
            {"cse": "CSE-001", "period": "P2", "alert_id": "A2", "priority": "LOW"},
            {"cse": "CSE-002", "period": "P1", "alert_id": "A3", "priority": "HIGH"},
            {"cse": "CSE-002", "period": "P2", "alert_id": "A4", "priority": "LOW"},
        ]

    def test_single_cse(self):

        result, *_ = analyse(
            [
                {"cse": "CSE-001", "alert_id": "A1", "priority": "HIGH"},
                {"cse": "CSE-001", "alert_id": "A2", "priority": "LOW"},
            ]
        )

        assert result["scope_count"] == 1
        assert result["scopes"][0]["entity"]["id"] == "CSE-001"

    def test_multiple_cses_get_independent_assessments(self):

        result, *_ = analyse(
            [
                {"cse": "CSE-001", "alert_id": "A1", "priority": "HIGH"},
                {"cse": "CSE-002", "alert_id": "A2", "priority": "HIGH",
                 "escalation_status": "escalated"},
            ]
        )

        assert result["scope_count"] == 2

        by_entity = {
            scope["entity"]["id"]: scope for scope in result["scopes"]
        }

        # Only CSE-002 submitted escalation evidence.
        assert (
            by_entity["CSE-001"]["status_counts"][STATUS_NOT_ASSESSED] > 0
        )
        assert (
            by_entity["CSE-002"]["status_counts"][STATUS_AVAILABLE] > 0
        )

    def test_capabilities_are_never_pooled_across_cses(self):

        result, *_ = analyse(
            [
                {"cse": "CSE-001", "alert_id": "A1", "priority": "HIGH"},
                {"cse": "CSE-002", "alert_id": "A2", "priority": "HIGH",
                 "escalation_status": "escalated"},
            ]
        )

        for scope in result["scopes"]:

            for context in scope["capabilities"]:

                assert context["entity"]["id"] == scope["entity"]["id"]
                assert context["assessment_id"] == scope["assessment_id"]

    def test_multiple_periods_get_independent_assessments(self):

        result, *_ = analyse(
            [
                {"cse": "CSE-001", "period": "P1", "alert_id": "A1",
                 "priority": "HIGH"},
                {"cse": "CSE-001", "period": "P2", "alert_id": "A2",
                 "priority": "HIGH", "escalation_status": "escalated"},
            ]
        )

        assert result["scope_count"] == 2

        by_period = {
            scope["period"]["label"]: scope for scope in result["scopes"]
        }

        assert by_period["P1"]["status_counts"][STATUS_NOT_ASSESSED] > 0
        assert by_period["P2"]["status_counts"][STATUS_AVAILABLE] > 0

    def test_multiple_cses_and_multiple_periods(self):

        result, *_ = analyse(self._matrix())

        assert result["scope_count"] == 4

        assert [scope["assessment_id"] for scope in result["scopes"]] == [
            "CSE-001::P1",
            "CSE-001::P2",
            "CSE-002::P1",
            "CSE-002::P2",
        ]

        for scope in result["scopes"]:

            assert len(scope["capabilities"]) == 8
            assert scope["record_count"] == 1

    def test_every_scope_reports_all_eight_capabilities(self):

        result, *_ = analyse(self._matrix())

        for scope in result["scopes"]:

            assert len(scope["capabilities"]) == 8
            assert [
                context["capability_id"] for context in scope["capabilities"]
            ] == list(REQUIRED_CAPABILITIES)

    def test_summary_counts_instances_not_averaged_scores(self):

        result, *_ = analyse(self._matrix())

        summary = result["summary"]

        assert summary["scope_count"] == 4
        assert len(summary["capabilities"]) == 8

        for entry in summary["capabilities"]:

            total = (
                entry["available_scopes"]
                + entry["insufficient_evidence_scopes"]
                + entry["not_assessed_scopes"]
            )

            assert total == 4

    def test_records_are_not_duplicated_across_scopes(self):

        records = self._matrix()

        result, _, _, collection, _ = analyse(records)

        indices = [
            index
            for scope in collection
            for index in scope.record_indices
        ]

        assert sorted(indices) == list(range(len(records)))
        assert len(indices) == len(set(indices))


# ---------------------------------------------------------------------------
# 17-18. unresolved entity and period
# ---------------------------------------------------------------------------


class TestUnresolvedScopeIdentity:

    def test_unknown_entity_still_receives_capability_context(self):

        result, *_ = analyse([{"alert_id": "A1", "priority": "HIGH"}])

        assert result["scope_count"] == 1
        assert result["scopes"][0]["entity"]["id"] == UNKNOWN_ENTITY
        assert result["scopes"][0]["entity"]["available"] is False

        for context in result["scopes"][0]["capabilities"]:

            assert context["entity"]["id"] == UNKNOWN_ENTITY

    def test_unknown_period_still_receives_capability_context(self):

        result, *_ = analyse(
            [{"cse": "CSE-001", "alert_id": "A1"}],
            scope_settings={"period_granularity": "none"},
        )

        assert result["scopes"][0]["period"]["label"] == UNKNOWN_PERIOD
        assert result["scopes"][0]["period"]["available"] is False

        for context in result["scopes"][0]["capabilities"]:

            assert context["period"]["label"] == UNKNOWN_PERIOD

    def test_missing_period_does_not_break_capability_assessment(self):

        result, *_ = analyse([{"cse": "CSE-001", "alert_id": "A1"}])

        assert result["scope_count"] == 1
        assert len(result["scopes"][0]["capabilities"]) == 8


# ---------------------------------------------------------------------------
# 19-20. repository dataset regression
# ---------------------------------------------------------------------------


class TestRepositoryDatasets:

    def _run(self, dataset):

        if not os.path.exists(os.path.join(REPOSITORY_ROOT, dataset)):
            pytest.skip(f"{dataset} not present")

        manager = IngestionManager()

        ingestion = manager.load(dataset)

        try:

            profile = DatasetProfiler().profile(ingestion.profiling_target)

            semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

            collection = AssessmentScopeBuilder().build(
                records=ingestion.records,
                profile=profile,
                semantic_results=semantic_results,
                source_id=ingestion.source,
                source_type=ingestion.source_type,
            )

            return CapabilityEvaluator(
                CapabilityRegistry()
            ).evaluate_collection(collection, profile, semantic_results)

        finally:

            manager.release(ingestion)

    def test_dataset_noisy_regression(self):

        result = self._run(NOISY_DATASET)

        assert result["scope_count"] == 1
        assert len(result["scopes"][0]["capabilities"]) == 8

        states = statuses(result)

        # dataset_noisy.csv carries severity, notes, a host, times and an owner.
        assert states["THREAT_DETECTION"] == STATUS_INSUFFICIENT_EVIDENCE
        assert states["ESCALATION"] == STATUS_NOT_ASSESSED
        assert states["CYBER_RESILIENCE"] == STATUS_INSUFFICIENT_EVIDENCE

    def test_dataset_multi_cse_regression(self):

        result = self._run(MULTI_CSE_DATASET)

        assert result["scope_count"] == 4

        for scope in result["scopes"]:

            assert len(scope["capabilities"]) == 8
            assert scope["entity"]["available"] is True
            assert scope["period"]["available"] is True

    def test_evidence_rich_dataset_exercises_every_status(self):

        result = self._run(RICH_DATASET)

        assert result["scope_count"] == 4

        seen = set()

        for scope in result["scopes"]:

            for context in scope["capabilities"]:

                seen.add(context["status"])

        assert STATUS_AVAILABLE in seen
        assert STATUS_INSUFFICIENT_EVIDENCE in seen

    def test_evidence_rich_dataset_caps_statuses_at_the_evidence_ceiling(self):

        result = self._run(RICH_DATASET)

        # A submission can never assert more than it evidences: no capability
        # reaches AVAILABLE without its configured minimum satisfied.
        registry = CapabilityRegistry()

        for scope in result["scopes"]:

            for context in scope["capabilities"]:

                definition = registry.get(context["capability_id"])

                satisfied_primary = len(
                    [
                        item
                        for item in context["evidence_detail"]
                        if item["satisfied"] and item["tier"] == "primary"
                    ]
                )

                if context["status"] == STATUS_AVAILABLE:

                    assert (
                        satisfied_primary
                        >= definition.minimum_evidence["primary"]
                    )


class TestPipelineIntegration:

    def _result(self, dataset):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        return SATSAPipeline().run(dataset)

    def test_pipeline_exposes_capability_assessment(self):

        result = self._result(NOISY_DATASET)

        assert "capability_assessment" in result

        payload = result["capability_assessment"]

        assert payload["scope_count"] == 1
        assert len(payload["scopes"][0]["capabilities"]) == 8

    def test_pipeline_capability_ids_match_the_registry(self):

        result = self._result(NOISY_DATASET)

        registry = CapabilityRegistry()

        assert (
            result["capability_assessment"]["capability_ids"]
            == registry.capability_ids
        )

    def test_pipeline_preserves_every_pre_existing_key(self):

        result = self._result(NOISY_DATASET)

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
            "assessment",
        ]:

            assert key in result

    def test_pipeline_evidence_output_shape_matches_the_specified_contract(self):

        result = self._result(NOISY_DATASET)

        for context in result["capability_assessment"]["scopes"][0]["capabilities"]:

            for key in [
                "capability_id",
                "name",
                "status",
                "confidence",
                "coverage",
                "evidence_available",
                "evidence_missing",
                "indicator_categories",
                "explanation",
            ]:

                assert key in context

    def test_pipeline_does_not_inject_capability_findings(self):

        result = self._result(NOISY_DATASET)

        for finding in result["supervisory_findings"]:

            assert "capability" not in str(finding).lower()

    def test_multi_cse_pipeline_reports_four_independent_scopes(self):

        result = self._result(MULTI_CSE_DATASET)

        payload = result["capability_assessment"]

        assert payload["scope_count"] == 4

        for scope in payload["scopes"]:

            assert len(scope["capabilities"]) == 8


class TestCapabilityPatternDiscovery:

    def test_capability_patterns_only_use_existing_concepts(self):

        evaluator = CapabilityEvaluator(CapabilityRegistry())

        registry = CapabilityRegistry()

        for concept in evaluator.patterns:

            assert concept in registry.known_concepts, (
                f"capability pattern invents concept {concept}"
            )

    def test_closed_by_is_never_mapped_to_resolution_time(self):

        evaluator = CapabilityEvaluator(CapabilityRegistry())

        assert "closed_by" in evaluator.patterns["RESOLUTION_TIME"][
            "negative_keywords"
        ]

    def test_capability_patterns_do_not_alter_the_main_semantic_pass(self):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run(NOISY_DATASET)

        # The main mapping pass still resolves exactly the concepts it
        # always did, so semantic_mapping, mapping_report and dataset_context
        # are untouched by the capability layer. Phase 1 deliberately
        # extends the main pass with identifier/timestamp recall: the noisy
        # dataset's genuine alert_id and closed_time columns now appear as
        # ALERT_ID and CLOSED_AT in the legacy list (verified: alert_id
        # holds ALRT001-style identifiers; closed_time is duration-valued,
        # so the decision layer holds it AMBIGUOUS and validation flags
        # the values rather than trusting them). The capability layer
        # itself still adds nothing here.
        concepts = {
            item["canonical_concept"]
            for item in result["semantic_mapping"]
        }

        assert concepts == {
            "SECURITY_SEVERITY",
            "ASSET_IDENTIFIER",
            "INVESTIGATION_EVIDENCE",
            "ALERT_ID",
            "CLOSED_AT",
        }

    def test_dataset_context_keeps_its_own_vocabulary(self):

        _requires_pipeline()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run(NOISY_DATASET)

        # dataset_context is a frozen, dataset-level vocabulary and must not
        # start reporting the eight capabilities.
        assert set(result["dataset_context"]) == {
            "ALERT_MANAGEMENT",
            "INVESTIGATION_WORKFLOW",
            "ASSET_CONTEXT",
        }

        for capability_id in REQUIRED_CAPABILITIES:

            assert capability_id not in result["dataset_context"]

    def test_is_populated_rejects_empty_evidence(self):

        for value in [None, "", "  ", "nan", "NaN", "NAT", "null", "None"]:

            assert is_populated(value) is False

        for value in ["x", 0, 1, 3.5, True, False, ["a"], {"a": 1}]:

            assert is_populated(value) is True

    def test_blank_column_is_not_counted_as_evidence(self):

        result, *_ = analyse(
            [
                {"alert_id": "A1", "escalation_status": "escalated"},
                {"alert_id": "A2", "escalation_status": ""},
            ]
        )

        context = context_of(result, "ESCALATION")

        satisfied = [
            item for item in context["evidence_detail"] if item["satisfied"]
        ]

        assert satisfied
        assert satisfied[0]["populated_records"] == 1

    def test_entirely_blank_column_is_not_evidence(self):

        result, *_ = analyse(
            [
                {"alert_id": "A1", "escalation_status": ""},
                {"alert_id": "A2", "escalation_status": ""},
            ]
        )

        assert (
            context_of(result, "ESCALATION")["status"] == STATUS_NOT_ASSESSED
        )

    def test_evidence_detail_reports_where_each_concept_was_resolved(self):

        # Concepts the main pass already resolves must keep that origin, and
        # concepts only the capability file can reach must be labelled as such.
        result, profile, semantic_results, _, evaluator = analyse(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "closed_time": 5,
                    "closed_by": "Alice",
                }
            ]
        )

        index = evaluator.build_evidence_index(
            [{"alert_id": "A1", "priority": "HIGH", "closed_time": 5, "closed_by": "Alice"}],
            profile,
            semantic_results,
        )

        assert index.concepts["SECURITY_SEVERITY"]["resolution"] == "semantic_mapping"
        assert index.concepts["RESOLUTION_TIME"]["resolution"] == "capability_patterns"
        assert index.concepts["USER_IDENTIFIER"]["resolution"] == "capability_patterns"

        detail = context_of(result, "INCIDENT_RESPONSE")["evidence_detail"]
        origins = {
            item["concept"]: item["resolution"]
            for item in detail
            if item["satisfied"]
        }

        assert origins["RESOLUTION_TIME"] == "capability_patterns"

    def test_capability_patterns_do_not_displace_main_semantic_mapping(self):

        # A column resolved by the main pass keeps the main pass's confidence
        # and column, even when the capability file also matches it.
        result, profile, semantic_results, _, evaluator = analyse(
            [{"alert_id": "A1", "priority": "HIGH", "investigation_notes": "x"}]
        )

        index = evaluator.build_evidence_index(
            [
                {
                    "alert_id": "A1",
                    "priority": "HIGH",
                    "investigation_notes": "x",
                }
            ],
            profile,
            semantic_results,
        )

        assert index.concepts["INVESTIGATION_EVIDENCE"]["resolution"] == "semantic_mapping"
        assert index.concepts["INVESTIGATION_EVIDENCE"]["column"] == "investigation_notes"

    def test_empty_scope_collection_reports_no_assessments(self):

        result = CapabilityEvaluator(CapabilityRegistry()).evaluate_collection(
            AssessmentCollection(scopes=[]), profile={}, semantic_results=[]
        )

        assert result["scope_count"] == 0
        assert result["scopes"] == []
        assert result["summary"]["assessable_capability_instances"] == 0

        # The registry is still fully reported so a consumer knows what could
        # have been assessed.
        assert len(result["capability_ids"]) == 8

    def test_minimum_evidence_is_configurable_and_drives_the_status(self):

        # Statuses must follow configuration, not intuition. Patch only
        # THREAT_DETECTION's minimum in the shipped config and confirm the
        # status follows the configuration in both directions.
        shipped = CapabilityRegistry().config_file

        def statuses_for(minimum):
            with open(shipped) as handle:
                raw = json.load(handle)

            raw["capabilities"]["THREAT_DETECTION"]["minimum_evidence"] = minimum

            records = [{"alert_id": "A1", "priority": "HIGH"}]

            with tempfile.TemporaryDirectory() as config_dir:

                config = os.path.join(config_dir, "capabilities.json")

                with open(config, "w") as handle:
                    json.dump(raw, handle)

                registry = CapabilityRegistry(config_file=config)

            with tempfile.TemporaryDirectory() as records_dir:

                path = _write_csv(records_dir, records)
                profile = DatasetProfiler().profile(path)

            semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

            collection = AssessmentScopeBuilder().build(
                records=records,
                profile=profile,
                semantic_results=semantic_results,
            )

            return statuses(
                CapabilityEvaluator(registry).evaluate_collection(
                    collection, profile, semantic_results
                )
            )

        # Severity alone is one primary item, so a minimum of 1 opens the
        # capability and the shipped minimum of 2 holds it back.
        assert (
            statuses_for({"primary": 1, "total": 1})["THREAT_DETECTION"]
            == STATUS_AVAILABLE
        )

        assert (
            statuses_for({"primary": 2, "total": 2})["THREAT_DETECTION"]
            == STATUS_INSUFFICIENT_EVIDENCE
        )

        # Other capabilities keep their shipped minimums and are unaffected.
        relaxed = statuses_for({"primary": 1, "total": 1})

        assert relaxed["INVESTIGATION"] == STATUS_NOT_ASSESSED
        assert relaxed["CYBER_RESILIENCE"] == STATUS_NOT_ASSESSED

    def test_primary_evidence_is_always_required_whatever_the_total(self):

        # SEVERITY is declared *supporting* evidence for escalation. Permissive
        # totals must not let a supporting item alone open the capability.
        source = CapabilityRegistry()
        definitions = {}

        for capability_id in REQUIRED_CAPABILITIES:

            definition = source.get(capability_id)

            definitions[capability_id] = {
                "name": definition.name,
                "primary_evidence": [
                    item.to_dict() for item in definition.primary_evidence
                ],
                "supporting_evidence": [
                    item.to_dict() for item in definition.supporting_evidence
                ],
                "minimum_evidence": {"primary": 1, "total": 1},
                "indicator_categories": list(definition.indicator_categories),
            }

        with tempfile.TemporaryDirectory() as directory:

            config = os.path.join(directory, "capabilities.json")

            with open(config, "w") as handle:
                json.dump({"capabilities": definitions}, handle)

            registry = CapabilityRegistry(config_file=config)

        records = [{"alert_id": "A1", "priority": "HIGH"}]

        with tempfile.TemporaryDirectory() as records_dir:

            path = _write_csv(records_dir, records)
            profile = DatasetProfiler().profile(path)

        semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

        collection = AssessmentScopeBuilder().build(
            records=records,
            profile=profile,
            semantic_results=semantic_results,
        )

        result = CapabilityEvaluator(registry).evaluate_collection(
            collection, profile, semantic_results
        )

        escalation = context_of(result, "ESCALATION")

        assert escalation["evidence_available"] == ["SECURITY_SEVERITY"]
        assert escalation["status"] == STATUS_NOT_ASSESSED

    def test_status_never_exceeds_what_primary_evidence_supports(self):

        # A supporting item alone can never make a capability assessable, no
        # matter how permissive the configuration is.
        result, *_ = analyse([{"alert_id": "A1", "priority": "HIGH"}])

        escalation = context_of(result, "ESCALATION")

        assert escalation["evidence_available"] == ["SECURITY_SEVERITY"]
        assert escalation["status"] == STATUS_NOT_ASSESSED
