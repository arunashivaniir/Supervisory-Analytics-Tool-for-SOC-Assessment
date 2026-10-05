"""
Tests for SAT-SA evidence-backed execution-gap detection.

The recurring assertion throughout this file is the one the layer exists to
protect: **an execution gap must be provable from submitted evidence**. A rule
that cannot see its required concepts, or that sees a value it does not
recognise, must stay silent. Silence in those cases is the correct behaviour,
and several tests exist purely to prove the detector does not fill them with a
guess.

Required coverage, per the implementation brief:

 1. Rule registry loads                     10. Multi-period isolation
 2. Required evidence validation            11. Evidence traceability
 3. Valid execution                         12. Capability association
 4. Actual execution gap                    13. No raw source-column dependency
 5. Missing evidence                        14. No arbitrary threshold
 6. Null evidence                           15. No finding when not evaluable
 7. Unknown evidence value                  16. dataset_noisy.csv regression
 8. Non-applicable severity                 17. dataset_multi_cse.csv regression
 9. Multi-CSE isolation

Plus semantic generalisation: a deliberate source-column rename must not change
any finding.

Run with::

    python -m pytest framework/tests/test_execution_gap.py -v
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile

import pytest

from framework.assessment import AssessmentCollection, AssessmentScopeBuilder

from framework.capability import CapabilityEvaluator, CapabilityRegistry

from framework.ingestion.ingestion_manager import IngestionManager

from framework.intelligence.semantic_inference import SemanticInference

from framework.profiling.dataset_profiler import DatasetProfiler

from framework.supervision.execution_gap_detector import (
    ExecutionGapDetector,
    has_evidence,
)

from framework.supervision.execution_gap_engine import ExecutionGapEngine

from framework.supervisory.rules.execution_gap_rules import (
    EXPECTATION_SATISFIED,
    EXPECTATION_VIOLATED,
    NOT_APPLICABLE,
    NOT_EVALUABLE,
    ExecutionGapCatalogue,
    RuleConfigError,
    RuleRegistry,
    normalise_value,
)


REPOSITORY_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

CONTROLLED_DATASET = "dataset_execution_gap_controlled.csv"
NOISY_DATASET = "dataset_noisy.csv"
MULTI_CSE_DATASET = "dataset_multi_cse.csv"

PATTERNS_CONFIG = "framework/config/semantic_patterns.json"
RULES_CONFIG = "framework/config/execution_gap_rules.json"

GAP_INDICATOR = "CRITICAL_ALERT_NOT_ESCALATED"
GAP_RULE = "critical_alert_requires_escalation"


def _requires_root() -> None:
    if os.path.abspath(os.getcwd()) != REPOSITORY_ROOT:
        pytest.skip("configuration paths are relative to the repository root")


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


def evaluate(records, scope_settings=None):
    """Run the real profiler, scope builder, capability resolver and engine."""

    with tempfile.TemporaryDirectory() as directory:

        path = _write_csv(directory, records)

        profile = DatasetProfiler().profile(path)

    semantic_results = SemanticInference(PATTERNS_CONFIG).infer(profile)

    collection = AssessmentScopeBuilder(settings=scope_settings).build(
        records=records,
        profile=profile,
        semantic_results=semantic_results,
    )

    return ExecutionGapEngine().evaluate_collection(
        collection, profile, semantic_results, CapabilityEvaluator()
    )


def states_of(result, scope_index=0):
    """Evaluation states for one scope, in record order."""

    return result["scopes"][scope_index]["evaluation_state_counts"]


def indicators(result):
    return [finding["indicator"] for finding in result["findings"]]


# ---------------------------------------------------------------------------
# 1. rule registry loads
# ---------------------------------------------------------------------------


class TestRuleRegistry:

    def test_rule_registry_loads(self):

        registry = RuleRegistry()

        assert registry is not None
        assert len(registry) >= 1

    def test_registry_exposes_exactly_the_defensible_rules(self):

        registry = RuleRegistry()

        # Deliberately one rule. The brief asks for trustworthy findings over
        # numerous ones, and the canonical model supports only this pair.
        assert [rule.rule_id for rule in registry.rules] == [GAP_RULE]

    def test_catalogue_reports_unavailable_rules_with_reasons(self):

        catalogue = ExecutionGapCatalogue()

        ids = {rule.rule_id for rule in catalogue.unavailable_rules}

        assert "investigation_not_performed" in ids
        assert "resolution_sla_breach" in ids

        for rule in catalogue.unavailable_rules:
            assert rule.status == "UNAVAILABLE"
            assert rule.missing_evidence, (
                f"{rule.rule_id} must state what evidence is missing"
            )
            assert rule.why_not_implemented
            assert rule.would_require

    def test_investigation_rule_is_unavailable_because_no_status_concept(self):

        catalogue = ExecutionGapCatalogue()

        rule = [r for r in catalogue.unavailable_rules
                if r.rule_id == "investigation_not_performed"][0]

        assert rule.capability == "INVESTIGATION"
        assert any(
            "INVESTIGATION_STATUS" in item
            for item in rule.missing_evidence
        )

    def test_sla_rule_is_unavailable_because_no_sla_expectation_exists(self):

        catalogue = ExecutionGapCatalogue()

        rule = [r for r in catalogue.unavailable_rules
                if r.rule_id == "resolution_sla_breach"][0]

        assert rule.capability == "INCIDENT_RESPONSE"
        assert any(
            "SLA" in item for item in rule.missing_evidence
        )

    def test_unavailable_rules_produce_no_findings(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        for finding in result["findings"]:
            assert finding["rule_id"] == GAP_RULE

    def test_every_rule_requires_at_least_one_concept(self):

        for rule in RuleRegistry().rules:
            assert rule.required_evidence

    def test_rule_concepts_all_exist_in_mappings(self):

        with open("framework/config/mappings.json") as handle:
            known = set(json.load(handle).keys())

        for rule in RuleRegistry().rules:
            for concept in rule.concepts:
                assert concept in known

    def test_rule_capability_is_one_of_the_eight(self):

        capabilities = set(CapabilityRegistry().capability_ids)

        for rule in RuleRegistry().rules:
            assert rule.capability in capabilities

    def test_registry_rejects_a_rule_with_no_required_evidence(self):

        _requires_root()

        with open(RULES_CONFIG) as handle:
            raw = json.load(handle)

        raw["rules"][0]["required_evidence"] = []

        with pytest.raises(RuleConfigError) as error:
            _write_config(raw)
            RuleRegistry()

        assert "required_evidence" in str(error.value)

    def test_registry_rejects_an_invented_concept(self):

        _requires_root()

        with open(RULES_CONFIG) as handle:
            raw = json.load(handle)

        raw["rules"][0]["required_evidence"] = ["SEVERITY_LEVEL_XL"]

        with pytest.raises(RuleConfigError) as error:
            _write_config(raw)
            RuleRegistry()

        assert "does not exist" in str(error.value)

    def test_registry_rejects_a_capability_outside_the_eight(self):

        _requires_root()

        with open(RULES_CONFIG) as handle:
            raw = json.load(handle)

        raw["rules"][0]["capability"] = "NINTH_CAPABILITY"

        with pytest.raises(RuleConfigError) as error:
            _write_config(raw)
            RuleRegistry()

        assert "not one of the eight" in str(error.value)

    def test_registry_rejects_a_vocabulary_key_that_does_not_exist(self):

        _requires_root()

        with open(RULES_CONFIG) as handle:
            raw = json.load(handle)

        raw["rules"][0]["violation_condition"]["ESCALATION_STATUS"][
            "vocabulary_key"
        ] = "not_a_key"

        with pytest.raises(RuleConfigError) as error:
            _write_config(raw)
            RuleRegistry()

        assert "value_vocabulary" in str(error.value)

    def test_registry_rejects_a_violation_on_a_non_required_concept(self):

        _requires_root()

        with open(RULES_CONFIG) as handle:
            raw = json.load(handle)

        raw["violation_condition_extra"] = True
        raw["rules"][0]["violation_condition"]["EVENT_TIMESTAMP"] = {
            "operator": "in",
            "vocabulary_key": "critical",
        }

        with pytest.raises(RuleConfigError) as error:
            _write_config(raw)
            RuleRegistry()

        assert "required_evidence" in str(error.value)


def _write_config(raw):
    """Overwrite the real config file and return its path.

    Restored by the ``restore`` fixture in the tests that call this.
    """

    with open(RULES_CONFIG, "w") as handle:
        json.dump(raw, handle, indent=4)

    return RULES_CONFIG


@pytest.fixture
def restore_rules_config():
    with open(RULES_CONFIG) as handle:
        original = handle.read()

    yield

    with open(RULES_CONFIG, "w") as handle:
        handle.write(original)


@pytest.fixture(autouse=True)
def _restore_config_after_mutation(restore_rules_config):
    yield


# ---------------------------------------------------------------------------
# 2. required evidence validation
# ---------------------------------------------------------------------------


class TestRequiredEvidenceValidation:

    def test_rule_declares_both_required_concepts(self):

        rule = RuleRegistry().get(GAP_RULE)

        assert set(rule.required_evidence) == {
            "SECURITY_SEVERITY",
            "ESCALATION_STATUS",
        }

    def test_partial_evidence_is_not_evaluable(self):

        detector = ExecutionGapDetector()
        rule = RuleRegistry().get(GAP_RULE)

        # Severity only.
        result = detector.evaluate_record({"SECURITY_SEVERITY": "CRITICAL"}, rule)
        assert result.state == NOT_EVALUABLE
        assert "ESCALATION_STATUS" in result.missing_evidence
        assert not result.is_finding

        # Escalation only.
        result = detector.evaluate_record(
            {"ESCALATION_STATUS": "not_escalated"}, rule
        )
        assert result.state == NOT_EVALUABLE
        assert "SECURITY_SEVERITY" in result.missing_evidence
        assert not result.is_finding

    def test_blank_and_null_markers_count_as_missing_evidence(self):

        detector = ExecutionGapDetector()
        rule = RuleRegistry().get(GAP_RULE)

        for blank in ["", "   ", "N/A", "n/a", "none", "None", "NULL", "-", "nan"]:

            result = detector.evaluate_record(
                {"SECURITY_SEVERITY": "CRITICAL", "ESCALATION_STATUS": blank}, rule
            )

            assert result.state == NOT_EVALUABLE, blank
            assert not result.is_finding, blank

    def test_has_evidence_treats_zero_and_false_as_evidence(self):

        assert has_evidence(0) is True
        assert has_evidence(False) is True
        assert has_evidence("") is False
        assert has_evidence(None) is False
        assert has_evidence("N/A") is False
        assert has_evidence("x") is True

    def test_value_normalisation_folds_equivalent_spellings(self):

        for value in ["not_escalated", "NOT ESCALATED", "not-escalated",
                      "Not Escalated", "  not_escalated  "]:

            assert normalise_value(value) == "NOT_ESCALATED", value

        assert normalise_value("critical") == "CRITICAL"
        assert normalise_value(None) == ""
        assert normalise_value("") == ""


# ---------------------------------------------------------------------------
# 3-4, 7-8. valid execution, actual gap, unknown values, non-applicable
# ---------------------------------------------------------------------------


class TestRuleEvaluationStates:

    def test_valid_execution_produces_no_finding(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "escalated"}]
        )

        assert result["finding_count"] == 0
        assert indicators(result) == []
        assert EXPECTATION_SATISFIED in states_of(result)

    def test_actual_execution_gap_is_detected(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        assert result["finding_count"] == 1

        finding = result["findings"][0]

        assert finding["indicator"] == GAP_INDICATOR
        assert finding["rule_id"] == GAP_RULE
        assert finding["capability"] == "ESCALATION"
        assert finding["status"] == "POTENTIAL_EXECUTION_GAP"
        assert EXPECTATION_VIOLATED in states_of(result)

    def test_missing_escalation_evidence_produces_no_finding(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": ""}]
        )

        assert result["finding_count"] == 0
        assert indicators(result) == []
        assert states_of(result).get(NOT_EVALUABLE) == 1

    def test_absent_escalation_column_produces_no_finding(self):

        # Not merely an empty cell: the column does not exist at all.
        result = evaluate([{"alert_id": "A1", "priority": "CRITICAL"}])

        assert result["finding_count"] == 0
        assert states_of(result).get(NOT_EVALUABLE) == 1

    def test_unknown_evidence_value_produces_no_finding(self):

        for value in ["PENDING", "IN_REVIEW", "deferred", "escalated_later", "7"]:

            result = evaluate(
                [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": value}]
            )

            assert result["finding_count"] == 0, value
            assert indicators(result) == [], value

    def test_unknown_severity_value_produces_no_finding(self):

        for value in ["SEV0", "P1", "urgent", "999"]:

            result = evaluate(
                [{"alert_id": "A1", "priority": value, "escalation_status": "not_escalated"}]
            )

            assert result["finding_count"] == 0, value

    def test_non_critical_severity_is_not_applicable(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "HIGH", "escalation_status": "not_escalated"}]
        )

        assert result["finding_count"] == 0
        assert indicators(result) == []
        # Fully observed, trigger simply does not match.
        assert states_of(result).get(NOT_APPLICABLE) == 1
        assert states_of(result).get(NOT_EVALUABLE, 0) == 0

    def test_only_critical_severity_triggers_the_rule(self):

        for severity in ["CRITICAL", "critical", "Critical"]:
            result = evaluate(
                [{"alert_id": "A1", "priority": severity, "escalation_status": "not_escalated"}]
            )
            assert result["finding_count"] == 1, severity

        for severity in ["HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]:
            result = evaluate(
                [{"alert_id": "A1", "priority": severity, "escalation_status": "not_escalated"}]
            )
            assert result["finding_count"] == 0, severity

    def test_escalated_value_never_creates_a_finding(self):

        for value in ["escalated", "ESCALATED", "Escalated"]:

            result = evaluate(
                [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": value}]
            )

            assert result["finding_count"] == 0, value

    def test_all_four_evaluation_states_are_reachable(self):

        result = evaluate(
            [
                {"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "escalated"},
                {"alert_id": "A2", "priority": "CRITICAL", "escalation_status": "not_escalated"},
                {"alert_id": "A3", "priority": "CRITICAL", "escalation_status": ""},
                {"alert_id": "A4", "priority": "HIGH", "escalation_status": "not_escalated"},
            ]
        )

        counts = states_of(result)

        assert counts[EXPECTATION_SATISFIED] == 1
        assert counts[EXPECTATION_VIOLATED] == 1
        assert counts[NOT_EVALUABLE] == 1
        assert counts[NOT_APPLICABLE] == 1
        assert result["finding_count"] == 1


# ---------------------------------------------------------------------------
# 9-10. multi-CSE and multi-period isolation
# ---------------------------------------------------------------------------


class TestScopeIsolation:

    def test_multi_cse_isolation(self):

        result = evaluate(
            [
                {"cse": "CSE-A", "alert_id": "A1", "priority": "CRITICAL",
                 "escalation_status": "not_escalated"},
                {"cse": "CSE-B", "alert_id": "B1", "priority": "CRITICAL",
                 "escalation_status": "escalated"},
            ]
        )

        assert result["scope_count"] == 2
        assert result["finding_count"] == 1

        finding = result["findings"][0]

        assert finding["entity"]["id"] == "CSE-A"

        by_entity = {
            scope["entity"]["id"]: scope["findings"]
            for scope in result["scopes"]
        }

        assert len(by_entity["CSE-A"]) == 1
        assert by_entity["CSE-B"] == []

    def test_multi_period_isolation(self):

        result = evaluate(
            [
                {"cse": "CSE-A", "period": "Period-1", "alert_id": "A1",
                 "priority": "CRITICAL", "escalation_status": "not_escalated"},
                {"cse": "CSE-A", "period": "Period-2", "alert_id": "A2",
                 "priority": "CRITICAL", "escalation_status": "escalated"},
            ]
        )

        assert result["scope_count"] == 2
        assert result["finding_count"] == 1

        finding = result["findings"][0]

        assert finding["period"]["label"] == "Period-1"
        assert finding["assessment_id"] == "CSE-A::Period-1"

        by_period = {
            scope["period"]["label"]: scope["findings"]
            for scope in result["scopes"]
        }

        assert len(by_period["Period-1"]) == 1
        assert by_period["Period-2"] == []

    def test_findings_are_never_pooled_across_scopes(self):

        result = evaluate(
            [
                {"cse": "CSE-A", "period": "Period-1", "alert_id": "A1",
                 "priority": "CRITICAL", "escalation_status": "not_escalated"},
                {"cse": "CSE-A", "period": "Period-2", "alert_id": "A2",
                 "priority": "CRITICAL", "escalation_status": "escalated"},
                {"cse": "CSE-B", "period": "Period-1", "alert_id": "B1",
                 "priority": "CRITICAL", "escalation_status": "not_escalated"},
                {"cse": "CSE-B", "period": "Period-2", "alert_id": "B2",
                 "priority": "CRITICAL", "escalation_status": "escalated"},
            ]
        )

        assert result["scope_count"] == 4
        assert result["finding_count"] == 2

        for finding in result["findings"]:
            assert finding["assessment_id"] in {
                "CSE-A::Period-1", "CSE-B::Period-1"
            }

        # Each finding sits in the scope that owns it.
        for scope in result["scopes"]:
            for finding in scope["findings"]:
                assert finding["assessment_id"] == scope["assessment_id"]

    def test_unknown_entity_still_evaluates_without_pooling(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        assert result["scope_count"] == 1
        assert result["finding_count"] == 1
        assert result["findings"][0]["entity"]["available"] is False

    def test_empty_scope_collection_produces_nothing(self):

        result = ExecutionGapEngine().evaluate_collection(
            AssessmentCollection(scopes=[]), profile={}, semantic_results=[]
        )

        assert result["scope_count"] == 0
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# 11-12. traceability and capability association
# ---------------------------------------------------------------------------


class TestTraceabilityAndCapability:

    def test_evidence_traceability(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated",
              "investigation_notes": "sensitive unrelated detail"}]
        )

        finding = result["findings"][0]

        assert finding["evidence"] == {
            "SECURITY_SEVERITY": "CRITICAL",
            "ESCALATION_STATUS": "not_escalated",
        }

        # Only the concepts the rule declares; nothing else from the row.
        assert set(finding["evidence"]) == set(finding["evidence_concepts"])
        assert "sensitive" not in json.dumps(finding)

    def test_finding_carries_rule_capability_indicator_and_status(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        finding = result["findings"][0]

        for key in [
            "indicator",
            "capability",
            "status",
            "rule_id",
            "rule_name",
            "reason",
            "evidence",
            "record_reference",
            "assessment_id",
            "entity",
            "period",
        ]:

            assert key in finding, key

        assert finding["indicator"] == GAP_INDICATOR
        assert finding["capability"] == "ESCALATION"
        assert finding["status"] == "POTENTIAL_EXECUTION_GAP"

    def test_finding_records_a_traceable_record_reference(self):

        records = [
            {"cse": "CSE-A", "alert_id": "A1", "priority": "CRITICAL",
             "escalation_status": "not_escalated"},
            {"cse": "CSE-A", "alert_id": "A2", "priority": "HIGH",
             "escalation_status": "escalated"},
        ]

        result = evaluate(records)

        reference = result["findings"][0]["record_reference"]

        assert reference["record_position"] == 0
        assert reference["source_record_index"] == 0

    def test_source_record_index_points_at_the_submitted_row(self):

        records = [
            {"cse": "CSE-A", "alert_id": "A1", "priority": "HIGH",
             "escalation_status": "escalated"},
            {"cse": "CSE-A", "alert_id": "A2", "priority": "CRITICAL",
             "escalation_status": "not_escalated"},
        ]

        result = evaluate(records)

        index = result["findings"][0]["record_reference"]["source_record_index"]

        # The gap is on the second submitted row, and is reported as such.
        assert index == 1
        assert records[index]["alert_id"] == "A2"

    def test_capability_association_uses_the_eight_capability_ids(self):

        capabilities = set(CapabilityRegistry().capability_ids)

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        assert result["findings"][0]["capability"] in capabilities
        assert result["capability_ids"] == ["ESCALATION"]

    def test_capability_statuses_are_not_modified_by_execution_gap(self):

        _requires_root()

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run(CONTROLLED_DATASET)

        for scope in result["capability_assessment"]["scopes"]:
            for context in scope["capabilities"]:
                assert context["status"] in (
                    "AVAILABLE", "INSUFFICIENT_EVIDENCE", "NOT_ASSESSED"
                )
                # The execution-gap layer adds no risk interpretation.
                assert "severity" not in context

    def test_findings_carry_no_severity_or_score(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        finding = result["findings"][0]

        for key in finding:
            assert key not in ("severity", "risk_level", "score", "risk")

        text = json.dumps(finding).lower()

        for word in ["high", "medium", "low"]:
            assert f'"{word}"' not in text

    def test_execution_gap_output_carries_no_risk_score(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        text = json.dumps(result).lower()

        for word in ["risk_score", "attention_score", "risk_level"]:
            assert word not in text

    def test_unavailable_rules_are_reported_alongside_findings(self):

        result = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        ids = {rule["rule_id"] for rule in result["unavailable_rules"]}

        assert "investigation_not_performed" in ids
        assert "resolution_sla_breach" in ids


# ---------------------------------------------------------------------------
# 13. no raw source-column dependency
# ---------------------------------------------------------------------------


class TestSemanticGeneralisation:

    def test_column_rename_does_not_change_the_finding(self):

        original = evaluate(
            [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": "not_escalated"}]
        )

        renamed = evaluate(
            [{"alert_id": "A1", "severity": "CRITICAL", "escalation_state": "not_escalated"}]
        )

        assert original["finding_count"] == 1
        assert renamed["finding_count"] == 1

        a = dict(original["findings"][0])
        b = dict(renamed["findings"][0])

        for key in ["indicator", "capability", "status", "rule_id", "evidence"]:
            assert a[key] == b[key], key

    def test_third_equivalent_column_spelling_also_works(self):

        result = evaluate(
            [{"alert_id": "A1", "severity": "CRITICAL", "is_escalated": "not_escalated"}]
        )

        assert result["finding_count"] == 1
        assert result["findings"][0]["indicator"] == GAP_INDICATOR

    def test_detector_and_engine_source_contain_no_dataset_column_names(self):

        # Phase 12: the generic implementation must not name any source column.
        #
        # The audit is on *subscript access*, not raw text: a structural result
        # key such as the "period" field of a finding is legitimate, while
        # reading a record with a literal source-column name is exactly the
        # defect being guarded against.
        source_columns = [
            "priority", "host", "investigation_notes", "closed_time",
            "closed_by", "alert_id", "threat_type", "security_label",
            "created_time", "escalation_status", "asset_criticality",
            "cse", "period", "telemetry_available",
        ]

        subscript = re.compile(r"""\[\s*["']([^"']+)["']\s*\]""")
        getter = re.compile(r"""\.get\(\s*["']([^"']+)["']""")

        paths = [
            "framework/supervision/execution_gap_detector.py",
            "framework/supervision/execution_gap_engine.py",
            "framework/supervisory/rules/rule_engine.py",
            "framework/supervisory/rules/execution_gap_rules.py",
        ]

        for path in paths:
            with open(path) as handle:
                source = handle.read()

            # Only executable lines; prose may name a field when explaining it.
            code = "\n".join(
                line for line in source.splitlines()
                if not line.strip().startswith("#")
            )

            for pattern in (subscript, getter):
                for literal in pattern.findall(code):
                    assert literal not in source_columns, (
                        f"{path} reads records by the source column "
                        f"{literal!r}"
                    )

    def test_concept_projection_exists_in_exactly_one_place(self):

        # The source-column -> concept translation must have a single owner, so
        # the execution-gap and negative-space layers cannot drift apart in how
        # they read evidence. EvidenceIndex owns it; the engines delegate.
        index_source = open(
            "framework/capability/capability_evaluator.py"
        ).read()

        engine_source = open(
            "framework/supervision/execution_gap_engine.py"
        ).read()

        assert "def concept_values(" in index_source
        assert "record[column]" in index_source

        assert "evidence_index.concept_values(records)" in engine_source
        assert "record[column]" not in engine_source

    def test_both_engines_read_concepts_through_the_shared_index(self):

        from framework.supervision.negative_space_detector import (
            NegativeSpaceDetector,
        )

        negative_source = open(
            "framework/supervision/negative_space_detector.py"
        ).read()

        assert "evidence_index.concept_values(records)" in negative_source
        assert NegativeSpaceDetector is not None

    def test_no_dataset_entity_names_in_generic_code(self):

        forbidden = [
            "CSE-001", "CSE-002", "CSE-A01", "CSE-B02",
            "Period-1", "Period-2", "WEB-PROD-01", "DB-PROD-02",
        ]

        for path in [
            "framework/supervision/execution_gap_detector.py",
            "framework/supervision/execution_gap_engine.py",
            "framework/supervisory/rules/rule_engine.py",
            "framework/config/execution_gap_rules.json",
        ]:
            with open(path) as handle:
                source = handle.read()

            for name in forbidden:
                assert name not in source, f"{path} contains {name}"


# ---------------------------------------------------------------------------
# 14. no arbitrary threshold
# ---------------------------------------------------------------------------


class TestNoArbitraryThreshold:

    def test_rule_config_declares_no_numeric_comparison(self):

        with open(RULES_CONFIG) as handle:
            raw = json.load(handle)

        # Checked structurally, on the executable rule section only. The
        # surrounding prose legitimately discusses thresholds in order to
        # explain why none is used.
        for rule in raw["rules"]:

            for label in ("expected_condition", "violation_condition"):

                for concept, spec in rule[label].items():

                    assert spec["operator"] in ("in", "not_in"), (
                        f"{rule['rule_id']}.{label}.{concept}"
                    )

                    assert "values" not in spec, (
                        f"{rule['rule_id']} inlines values instead of using the "
                        f"declared vocabulary"
                    )

            # A rule declares no numeric literal anywhere in its logic.
            logic = json.dumps(
                {
                    "expected": rule["expected_condition"],
                    "violation": rule["violation_condition"],
                    "required": rule["required_evidence"],
                }
            )

            assert not re.search(r"\d", logic), (
                f"{rule['rule_id']} encodes a numeric threshold: {logic}"
            )

    def test_shipped_vocabulary_contains_no_numeric_tokens(self):

        with open(RULES_CONFIG) as handle:
            raw = json.load(handle)

        for concept, mapping in raw["value_vocabulary"].items():
            if concept.startswith("_"):
                continue
            for key, tokens in mapping.items():
                if key.startswith("_"):
                    continue
                for token in tokens:
                    assert not any(ch.isdigit() for ch in token), (
                        f"{concept}.{key} declares a numeric token {token!r}"
                    )

    def test_legacy_arbitrary_thresholds_are_gone(self):

        with open("framework/supervision/execution_gap_engine.py") as handle:
            source = handle.read()

        # The previous implementation used a word count and a closure-time
        # cutoff. Neither survives.
        assert "word_count" not in source
        assert "< 5" not in source
        assert "len(str(" not in source

    def test_a_near_miss_value_does_not_cross_an_invented_boundary(self):

        # No boundary exists between "not escalated" tokens, so an adjacent
        # value cannot be treated as a violation.
        for value in ["not_escalated_pending", "not escalated later",
                      "partially escalated"]:

            result = evaluate(
                [{"alert_id": "A1", "priority": "CRITICAL", "escalation_status": value}]
            )

            assert result["finding_count"] == 0, value

    def test_rule_matches_exact_tokens_only(self):

        rule = RuleRegistry().get(GAP_RULE)
        condition = rule.violation_condition["ESCALATION_STATUS"]

        assert condition.matches("NOT_ESCALATED") is True
        assert condition.matches("NOT_ESCALATED_PENDING") is False
        assert condition.matches("") is False


# ---------------------------------------------------------------------------
# 15. no finding when a rule cannot evaluate
# ---------------------------------------------------------------------------


class TestNoSpeculativeFindings:

    def test_empty_dataset_produces_nothing(self):

        result = ExecutionGapEngine().evaluate_collection(
            AssessmentCollection(scopes=[]), profile={}, semantic_results=[]
        )

        assert result["findings"] == []

    def test_severity_only_records_produce_nothing(self):

        result = evaluate(
            [
                {"alert_id": "A1", "priority": "CRITICAL"},
                {"alert_id": "A2", "priority": "CRITICAL"},
                {"alert_id": "A3", "priority": "HIGH"},
            ]
        )

        assert result["finding_count"] == 0
        assert states_of(result).get(NOT_EVALUABLE) == 3

    def test_escalation_only_records_produce_nothing(self):

        result = evaluate(
            [
                {"alert_id": "A1", "escalation_status": "not_escalated"},
                {"alert_id": "A2", "escalation_status": "escalated"},
            ]
        )

        assert result["finding_count"] == 0
        assert states_of(result).get(NOT_EVALUABLE) == 2

    def test_record_with_no_mappable_evidence_produces_nothing(self):

        result = evaluate([{"unrelated_column": "value"}])

        assert result["finding_count"] == 0
        assert states_of(result).get(NOT_EVALUABLE) == 1

    def test_not_evaluable_never_becomes_a_finding_or_a_weakness(self):

        detector = ExecutionGapDetector()
        rule = RuleRegistry().get(GAP_RULE)

        for values in [
            {},
            {"SECURITY_SEVERITY": "CRITICAL"},
            {"ESCALATION_STATUS": "not_escalated"},
            {"SECURITY_SEVERITY": None, "ESCALATION_STATUS": "not_escalated"},
        ]:
            evaluation = detector.evaluate_record(values, rule)

            assert evaluation.state == NOT_EVALUABLE
            assert evaluation.is_finding is False
            assert "evidence-availability" in evaluation.reason

    def test_explanation_quotes_only_observed_evidence(self):

        detector = ExecutionGapDetector()
        rule = RuleRegistry().get(GAP_RULE)

        evaluation = detector.evaluate_record(
            {"SECURITY_SEVERITY": "CRITICAL", "ESCALATION_STATUS": "not_escalated"},
            rule,
        )

        assert "CRITICAL" in evaluation.reason
        assert "not_escalated" in evaluation.reason
        # No unrendered placeholder leaks into the prose.
        assert "{" not in evaluation.reason

    def test_single_gap_among_many_records_does_not_spread(self):

        records = [
            {"cse": "CSE-A", "alert_id": f"A{i}", "priority": "CRITICAL",
             "escalation_status": "escalated"}
            for i in range(20)
        ]
        records.append(
            {"cse": "CSE-A", "alert_id": "AX", "priority": "CRITICAL",
             "escalation_status": "not_escalated"}
        )

        result = evaluate(records)

        assert result["finding_count"] == 1


# ---------------------------------------------------------------------------
# 16-17. repository dataset regression
# ---------------------------------------------------------------------------


class TestRepositoryDatasets:

    def _evaluate(self, dataset):

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

            return ExecutionGapEngine().evaluate_collection(
                collection, profile, semantic_results, CapabilityEvaluator()
            )

        finally:

            manager.release(ingestion)

    def test_dataset_noisy_regression(self):

        result = self._evaluate(NOISY_DATASET)

        assert result["scope_count"] == 1
        assert result["finding_count"] == 0

        # dataset_noisy.csv carries no escalation_status column at all, so the
        # rule is never evaluable and must stay silent.
        assert states_of(result).get(NOT_EVALUABLE) == 3

    def test_dataset_multi_cse_regression(self):

        result = self._evaluate(MULTI_CSE_DATASET)

        assert result["scope_count"] == 4
        assert result["finding_count"] == 0

    def test_controlled_dataset_regression(self):

        result = self._evaluate(CONTROLLED_DATASET)

        assert result["scope_count"] == 4
        assert result["finding_count"] == 2

        by_scope = {
            scope["assessment_id"]: len(scope["findings"])
            for scope in result["scopes"]
        }

        assert by_scope == {
            "CSE-A01::Period-1": 1,
            "CSE-A01::Period-2": 0,
            "CSE-B02::Period-1": 1,
            "CSE-B02::Period-2": 0,
        }

    def test_controlled_dataset_first_scope_covers_all_four_states(self):

        result = self._evaluate(CONTROLLED_DATASET)

        scope = result["scopes"][0]

        assert scope["evaluation_state_counts"] == {
            EXPECTATION_SATISFIED: 1,
            EXPECTATION_VIOLATED: 1,
            NOT_EVALUABLE: 1,
            NOT_APPLICABLE: 1,
        }


class TestPipelineIntegration:

    def _result(self, dataset):

        _requires_root()

        from framework.pipeline import SATSAPipeline

        return SATSAPipeline().run(dataset)

    def test_pipeline_exposes_execution_gap_findings(self):

        result = self._result(CONTROLLED_DATASET)

        assert "execution_gap_findings" in result

        payload = result["execution_gap_findings"]

        assert payload["scope_count"] == 4
        assert payload["finding_count"] == 2
        assert payload["rule_ids"] == [GAP_RULE]

    def test_pipeline_preserves_every_pre_existing_result_key(self):

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
            "capability_assessment",
        ]:
            assert key in result, key

    def test_pipeline_leaves_supervisory_findings_and_attention_untouched(self):

        result = self._result(CONTROLLED_DATASET)

        # Execution gaps must not be routed into the attention scorer.
        assert result["supervisory_findings"] == []
        assert result["execution_gap_findings"]["finding_count"] == 2

    def test_pipeline_produces_no_execution_gap_for_existing_datasets(self):

        for dataset in (NOISY_DATASET, MULTI_CSE_DATASET):

            result = self._result(dataset)

            assert result["execution_gap_findings"]["finding_count"] == 0, dataset

    def test_pipeline_reports_unavailable_rules(self):

        result = self._result(NOISY_DATASET)

        unavailable = result["execution_gap_findings"]["unavailable_rules"]

        assert len(unavailable) >= 2
        assert all(rule["status"] == "UNAVAILABLE" for rule in unavailable)

    def test_legacy_supervisory_engine_still_returns_a_list(self):

        from framework.supervision.supervisory_engine import SupervisoryEngine

        findings = SupervisoryEngine().analyse([{"alert_context": {}}], {})

        assert isinstance(findings, list)
        assert findings == []
