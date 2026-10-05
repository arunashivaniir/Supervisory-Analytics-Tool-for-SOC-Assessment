"""Tests for the negative-space layer.

The organising question throughout is not "is a field empty" but "is evidence
absent from a population that makes the evidence expected". Several tests
therefore assert that fields are *blank* and no finding is raised, because a
blank field outside a triggered population is not a supervisory signal.
"""

from __future__ import annotations

import copy
import json

import pytest

from framework.assessment.scope import AssessmentScope
from framework.capability.capability_evaluator import EvidenceIndex
from framework.pipeline import SATSAPipeline
from framework.supervision.negative_space_detector import NegativeSpaceDetector
from framework.supervisory.rules.negative_space_rules import (
    COMPLETE_ABSENCE,
    EXPECTATION_NOT_TRIGGERED,
    NO_ABSENCE,
    PARTIAL_ABSENCE,
    NegativeSpaceCatalogue,
    NegativeSpaceRegistry,
)
from framework.supervisory.rules.rule_engine import RuleConfigError

DATASET = "dataset_negative_space_controlled.csv"

RULE_ID = "critical_alerts_expect_escalation_evidence"
INDICATOR = "MISSING_ESCALATION_EVIDENCE"


@pytest.fixture(scope="module")
def result():

    return SATSAPipeline().run(DATASET)


@pytest.fixture(scope="module")
def detector():

    return NegativeSpaceDetector()


def findings_for(result, assessment_id):

    return [
        finding
        for finding in result["negative_space_findings"]["findings"]
        if finding["assessment_id"] == assessment_id
    ]


def scope_state(result, assessment_id):

    for scope in result["negative_space_findings"]["scopes"]:

        if scope["assessment_id"] == assessment_id:
            return scope

    return None


def test_controlled_dataset_covers_every_state(result):

    counts = result["negative_space_findings"]["absence_state_counts"]

    assert counts[COMPLETE_ABSENCE] == 3
    assert counts[PARTIAL_ABSENCE] == 1
    assert counts[NO_ABSENCE] == 3
    assert counts[EXPECTATION_NOT_TRIGGERED] == 5
    assert result["negative_space_findings"]["scope_count"] == 12


# -- the distinction this layer exists to make ---------------------------


class TestNegativeSpaceIsNotAMissingField:

    def test_blank_escalation_without_critical_alerts_raises_nothing(self, result):

        # NS-C03 and NS-F06 have blank escalation status throughout, but no
        # critical alert activity. Nothing creates the duty, so nothing is
        # absent. This is the case a "missing field" reading would get wrong.
        for assessment_id in (
            "NS-C03::Period-1",
            "NS-C03::Period-2",
            "NS-E05::Period-2",
            "NS-F06::Period-1",
            "NS-F06::Period-2",
        ):

            assert findings_for(result, assessment_id) == []

            state = scope_state(result, assessment_id)

            assert state["absence_state_counts"] == {
                EXPECTATION_NOT_TRIGGERED: 1
            }

    def test_critical_activity_with_full_evidence_raises_nothing(self, result):

        # NS-E05 Period-1 does contain a critical alert, and it was escalated.
        # The expectation was triggered and satisfied, which is the state a
        # naive "critical implies weakness" reading would get wrong.
        assert findings_for(result, "NS-E05::Period-1") == []

        state = scope_state(result, "NS-E05::Period-1")

        assert state["absence_state_counts"] == {NO_ABSENCE: 1}
        assert state["expectation_states"][0]["trigger_records"] == 1

    def test_a_single_blank_critical_record_does_not_speak_for_a_scope(self, result):

        # One blank record inside a population that otherwise carries
        # evidence is partial absence, not a claim that the scope has no
        # escalation evidence at all.
        finding = findings_for(result, "NS-B02::Period-1")[0]

        assert finding["absence_state"] == PARTIAL_ABSENCE
        assert finding["evidence_summary"]["trigger_records"] == 3
        assert finding["evidence_summary"]["records_with_expected_evidence"] == 2
        assert finding["evidence_summary"]["records_without_expected_evidence"] == 1

    def test_finding_states_the_expectation_not_just_the_absence(self, result):

        finding = findings_for(result, "NS-A01::Period-1")[0]

        assert finding["expectation"]["trigger"] == "CRITICAL_ALERT_ACTIVITY"
        assert finding["expectation"]["expected_evidence"] == [
            "ESCALATION_STATUS"
        ]
        assert finding["expectation"]["basis"] == (
            "configured supervisory expectation"
        )
        assert finding["expectation"]["why_expected"]
        assert finding["indicator"] == INDICATOR
        assert finding["capability"] == "ESCALATION"


# -- separation from the execution-gap layer ------------------------------


class TestSeparationFromExecutionGap:

    def test_explicit_not_escalated_counts_as_evidence_present(self, result):

        # NS-D04 Period-2 holds one escalated and one explicitly not escalated
        # critical alert. Both submitted an outcome, so coverage is complete
        # and no negative space is reported for that scope.
        assert findings_for(result, "NS-D04::Period-2") == []

        state = scope_state(result, "NS-D04::Period-2")

        assert state["absence_state_counts"] == {NO_ABSENCE: 1}

    def test_not_escalated_raises_an_execution_gap_and_no_negative_space(self, result):

        gaps = [
            finding
            for finding in result["execution_gap_findings"]["findings"]
            if finding["assessment_id"] == "NS-D04::Period-2"
        ]

        assert len(gaps) == 1
        assert gaps[0]["status"] == "POTENTIAL_EXECUTION_GAP"
        assert findings_for(result, "NS-D04::Period-2") == []

    def test_missing_escalation_raises_negative_space_and_no_execution_gap(self, result):

        # NS-A01 Period-1: critical alerts, no escalation evidence at all. The
        # execution-gap rule cannot fire because no decision was contradicted.
        assert findings_for(result, "NS-A01::Period-1")
        assert [
            finding
            for finding in result["execution_gap_findings"]["findings"]
            if finding["assessment_id"] == "NS-A01::Period-1"
        ] == []

    def test_the_two_layers_never_claim_the_same_record(self, result):

        # Scope-level overlap is legitimate: a scope can hold one critical
        # alert that was explicitly declined and another with no evidence at
        # all. What must never happen is one record satisfying both rules, so
        # the check is per scope, since record_position is scope-local.
        negative_records = set()
        gap_records = set()

        for finding in result["negative_space_findings"]["findings"]:

            for position in finding["record_reference"]["record_positions"]:
                negative_records.add((finding["assessment_id"], position))

        for finding in result["execution_gap_findings"]["findings"]:

            gap_records.add(
                (
                    finding["assessment_id"],
                    finding["record_reference"]["record_position"],
                )
            )

        assert negative_records & gap_records == set()

    def test_a_scope_may_report_both_independently(self, result):

        # Guards the test above from passing simply because nothing overlaps.
        assert findings_for(result, "NS-B02::Period-1")
        assert [
            finding
            for finding in result["execution_gap_findings"]["findings"]
            if finding["assessment_id"] == "NS-B02::Period-1"
        ]


# -- evidence classification ---------------------------------------------


class TestUnusableEvidence:

    def test_unknown_populated_value_is_unusable_not_present(self, result):

        # pending_review states no escalation outcome. Counting it as evidence
        # would overstate coverage; counting it as a decision would invent one.
        finding = findings_for(result, "NS-B02::Period-2")[0]

        summary = finding["evidence_summary"]

        assert summary["records_with_unusable_evidence"] == 1
        assert summary["records_with_expected_evidence"] == 0
        assert summary["coverage"] == 0.0
        assert finding["absence_state"] == COMPLETE_ABSENCE

    def test_not_applicable_is_treated_as_no_evidence(self, result):

        # NS-D04 Period-1 mixes N/A with a blank.
        summary = findings_for(result, "NS-D04::Period-1")[0]["evidence_summary"]

        assert summary["trigger_records"] == 2
        assert summary["records_with_expected_evidence"] == 0
        assert summary["records_without_expected_evidence"] == 2

    def test_value_casing_and_separators_do_not_change_classification(
        self, result
    ):

        # NS-D04 Period-2 submits "ESCALATED" and "Not Escalated".
        state = scope_state(result, "NS-D04::Period-2")

        assert state["absence_state_counts"] == {NO_ABSENCE: 1}


# -- no invented policy ---------------------------------------------------


class TestNoInventedPolicy:

    def test_partial_absence_is_reported_without_being_escalated(self, result):

        finding = findings_for(result, "NS-B02::Period-1")[0]

        assert finding["status"] == "PARTIAL_NEGATIVE_SPACE"
        assert finding["evidence_summary"]["coverage"] == 0.6667

    def test_no_rule_configures_a_coverage_threshold(self, detector):

        for rule in detector.catalogue.rules:

            assert rule.material_coverage_threshold is None

    def test_no_finding_carries_severity_or_score(self, result):

        forbidden = (
            "severity",
            "risk_score",
            "attention_score",
            "priority",
            "weight",
            "level",
        )

        for finding in result["negative_space_findings"]["findings"]:

            for key in forbidden:

                assert key not in finding

    def test_status_values_are_qualitative_only(self, result):

        statuses = {
            finding["status"]
            for finding in result["negative_space_findings"]["findings"]
        }

        assert statuses <= {
            "POTENTIAL_NEGATIVE_SPACE",
            "PARTIAL_NEGATIVE_SPACE",
        }


# -- traceability ---------------------------------------------------------


class TestTraceability:

    def test_absent_records_point_at_source_rows(self, result):

        import csv

        with open(DATASET) as handle:
            rows = list(csv.DictReader(handle))

        finding = findings_for(result, "NS-A01::Period-1")[0]

        indices = finding["record_reference"]["source_record_indices"]

        assert indices == [0, 1]
        assert all(row["escalation_status"] == "" for row in (rows[i] for i in indices))
        assert all(row["priority"] == "CRITICAL" for row in (rows[i] for i in indices))

    def test_indicates_which_record_failed_within_a_partial_scope(self, result):

        import csv

        with open(DATASET) as handle:
            rows = list(csv.DictReader(handle))

        finding = findings_for(result, "NS-B02::Period-1")[0]

        (index,) = finding["record_reference"]["source_record_indices"]

        assert rows[index]["alert_id"] == "NS-0024"
        assert rows[index]["escalation_status"] == ""
        assert rows[index]["priority"] == "CRITICAL"


# -- rule configuration ---------------------------------------------------


class TestRuleConfiguration:

    def test_registry_loads_the_shipped_configuration(self, detector):

        assert len(detector.catalogue.rules) == 1

        rule = detector.catalogue.rules[0]

        assert rule.rule_id == RULE_ID
        assert rule.indicator == INDICATOR
        assert rule.population_concept == "SECURITY_SEVERITY"
        assert rule.expected_evidence[0].concept == "ESCALATION_STATUS"

    def test_unavailable_expectations_are_recorded_with_reasons(self, detector):

        unavailable = detector.catalogue.unavailable_rules

        assert len(unavailable) >= 4

        for rule in unavailable:

            assert rule.status == "UNAVAILABLE"
            assert rule.missing_evidence
            assert rule.why_not_implemented

    def test_expectations_left_unavailable_cover_the_requested_set(self, detector):

        ids = {rule.rule_id for rule in detector.catalogue.unavailable_rules}

        assert "alert_activity_expects_investigation_evidence" in ids
        assert "critical_systems_expect_telemetry" in ids
        assert "expected_alert_categories_present" in ids
        assert "activity_not_unexpectedly_low" in ids

    def test_rule_without_a_trigger_population_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="trigger population"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path, drop="expectation.trigger.vocabulary_key"
                )
            )

    def test_rule_without_a_statement_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="expectation statement"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path, drop="expectation.statement"
                )
            )

    def test_rule_without_a_basis_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="basis"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path, drop="expectation.basis"
                )
            )

    def test_rule_without_a_reason_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="why the evidence is expected"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path, drop="expectation.why_expected"
                )
            )

    def test_unknown_concept_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="does not exist"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path,
                    set_path="expectation.expected_evidence.0.concept",
                    value="NOT_A_CONCEPT",
                )
            )

    def test_unknown_capability_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="eight defined capabilities"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path, set_path="capability", value="MADE_UP"
                )
            )

    def test_threshold_outside_the_unit_interval_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="between 0 and 1"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path,
                    set_path="classification.material_coverage_threshold",
                    value=1.5,
                )
            )

    def test_non_numeric_threshold_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="null or a number"):

            NegativeSpaceRegistry(
                config_file=_write_config(
                    tmp_path,
                    set_path="classification.material_coverage_threshold",
                    value="most",
                )
            )

    def test_a_plausible_threshold_is_not_silently_accepted_by_default(self):

        # 0.8 is a legal number, so validation alone would let a plausible-
        # looking threshold through. What stops it shipping is that the
        # committed configuration carries none, asserted separately. This test
        # records that the number is only ever applied if written down.
        shipped = json.load(
            open("framework/config/negative_space_rules.json")
        )

        for rule in shipped["rules"]:

            assert (
                rule["classification"]["material_coverage_threshold"] is None
            )

    def test_configured_threshold_is_honoured_when_supplied(self, tmp_path):

        # The mechanism must work if an authority supplies a number, otherwise
        # "no threshold" would only mean the feature was never built.
        registry = NegativeSpaceRegistry(
            config_file=_write_config(
                tmp_path,
                set_path="classification.material_coverage_threshold",
                value=0.9,
            )
        )

        rule = registry.rules[0]

        assert rule.material_coverage_threshold == 0.9

        detector = NegativeSpaceDetector(catalogue=_catalogue(registry))

        values = [
            {"SECURITY_SEVERITY": "CRITICAL", "ESCALATION_STATUS": "escalated"},
            {"SECURITY_SEVERITY": "CRITICAL", "ESCALATION_STATUS": None},
        ]

        measurement = detector.measure(rule, values)

        assert measurement["coverage"] == 0.5
        assert detector.classify(rule, measurement) == (
            rule.complete_absence_status
        )


# -- scope isolation ------------------------------------------------------


class TestScopeIsolation:

    def test_scopes_are_evaluated_independently(self, result):

        # NS-A01 Period-2 has complete evidence while Period-1 has none. If
        # periods were pooled, Period-1's finding would disappear.
        assert findings_for(result, "NS-A01::Period-2") == []
        assert findings_for(result, "NS-A01::Period-1")

    def test_findings_carry_their_own_scope_identity(self, result):

        for finding in result["negative_space_findings"]["findings"]:

            assert finding["entity"]["id"].startswith("NS-")
            assert finding["period"]["label"].startswith("Period-")


# -- genericity -----------------------------------------------------------


class TestGenericity:

    def test_detector_holds_no_dataset_specific_literals(self):

        code = _executable_source(
            "framework/supervision/negative_space_detector.py"
        )

        # Dataset column names and dataset-specific severity/escalation tokens
        # must not appear in code. "period" is deliberately absent from this
        # list: scope.period is the assessment scope's own API, not a column.
        for literal in (
            "escalation_status",
            "priority",
            "alert_id",
            "investigation_notes",
            "host",
            "cse",
            "CRITICAL",
            "ESCALATED",
            "NOT_ESCALATED",
        ):

            assert literal not in code

    def test_config_holds_no_dataset_specific_literals(self):

        with open("framework/config/negative_space_rules.json") as handle:
            config = json.load(handle)

        text = json.dumps(config)

        for literal in ("cse", "alert_id", "investigation_notes", "host"):
            assert literal not in text

    def test_detector_behaviour_follows_configuration(self):

        # Renaming the concept in configuration must change what the detector
        # reads, proving the logic is driven by the rule and not hardcoded.
        registry = NegativeSpaceRegistry(
            config_file="framework/config/negative_space_rules.json"
        )

        rule = registry.rules[0]

        assert rule.primary_expected_concept == "ESCALATION_STATUS"

        detector = NegativeSpaceDetector(catalogue=_catalogue(registry))

        measurement = detector.measure(
            rule,
            [
                {"SECURITY_SEVERITY": "CRITICAL", "ESCALATION_STATUS": "escalated"},
                {"SECURITY_SEVERITY": "LOW", "ESCALATION_STATUS": None},
            ],
        )

        assert measurement["trigger_records"] == 1
        assert measurement["records_with_expected_evidence"] == 1

    def test_escalation_vocabulary_agrees_with_the_execution_gap_layer(self):

        # Two independent configurations describe the same canonical tokens.
        # They must not drift, so the agreement is asserted rather than assumed.
        negative = json.load(
            open("framework/config/negative_space_rules.json")
        )["value_vocabulary"]
        execution = json.load(
            open("framework/config/execution_gap_rules.json")
        )["value_vocabulary"]

        for key in ("escalated", "not_escalated"):

            assert negative["ESCALATION_STATUS"][key] == (
                execution["ESCALATION_STATUS"][key]
            )

        assert negative["SECURITY_SEVERITY"]["critical"] == (
            execution["SECURITY_SEVERITY"]["critical"]
        )


# -- non-interference with the existing pipeline --------------------------


class TestNonInterference:

    def test_new_key_is_the_only_addition(self, result, baseline):

        # peer_benchmark is a later additive layer, not part of what this guard
        # measures, so it is removed from both sides before the key comparison.
        result = {key: value for key, value in result.items() if key != "peer_benchmark"}

        # Every result key that existed before this layer still exists and
        # still holds exactly the same value.
        for key, value in baseline.items():

            assert key in result, f"{key} disappeared"
            assert result[key] == value, f"{key} changed"

        added = set(result) - set(baseline)

        assert added == {"negative_space_findings"}

    def test_findings_do_not_reach_the_attention_scorer(self, result):

        assert "negative_space" not in json.dumps(
            result["entity_assessment"]
        )
        assert "negative_space" not in json.dumps(
            result["supervisory_findings"]
        )

    def test_negative_space_states_are_not_severity_vocabulary(self, result):

        text = json.dumps(result["negative_space_findings"])

        for token in ('"HIGH"', '"MEDIUM"', '"LOW"', '"CRITICAL"'):
            assert token not in text


# -- shared evidence projection ------------------------------------------


class TestSharedEvidenceProjection:

    def test_evidence_index_is_the_single_source_column_projection(self):

        with open("framework/capability/capability_evaluator.py") as handle:
            code = handle.read()

        assert "def concept_values(" in code
        assert "record[column]" in code

    def test_both_supervision_layers_consume_the_shared_projection(self, result):

        from framework.supervision.execution_gap_engine import (
            ExecutionGapEngine,
        )

        engine = ExecutionGapEngine()

        assert "evidence_index.concept_values(records)" in (
            open("framework/supervision/execution_gap_engine.py").read()
        )
        assert "evidence_index.concept_values(records)" in (
            open("framework/supervision/negative_space_detector.py").read()
        )
        assert engine is not None

    def test_projection_returns_one_mapping_per_record(self, result):

        # The projection resolves *known concepts*, not arbitrary record keys,
        # so an unmapped column is correctly absent from the result.
        index = EvidenceIndex(
            concepts={"KNOWN": {"column": "a"}}, columns=["a"]
        )

        values = index.concept_values([{"a": 1}, {"b": 2}, {}])

        assert len(values) == 3
        assert values[0] == {"KNOWN": 1}
        assert values[1] == {}
        assert values[2] == {}


@pytest.fixture(scope="module")
def baseline():

    return copy.deepcopy(
        _run_without_negative_space()
    )


def _run_without_negative_space():

    # The existing-key comparison reads the same dataset through a pipeline
    # whose negative-space stage is disabled, which is the closest available
    # representation of the pre-layer result.
    from framework.pipeline import SATSAPipeline

    pipeline = SATSAPipeline()
    original = pipeline.negative_space_detector
    pipeline.negative_space_detector = NegativeSpaceDetector.__new__(
        NegativeSpaceDetector
    )
    pipeline.negative_space_detector.evaluate_collection = (
        lambda *args, **kwargs: None
    )

    result = pipeline.run(DATASET)
    result.pop("negative_space_findings", None)

    # peer_benchmark is a separate additive layer that reads the negative-space
    # result, so it necessarily differs when that result is stubbed out. It is
    # excluded here so this guard keeps measuring only what this layer did.
    result.pop("peer_benchmark", None)

    pipeline.negative_space_detector = original

    return result


def _executable_source(path):
    """Source with comments and string literals removed.

    The dataset-literal audit must inspect code, not prose: a module is free to
    *describe* the absence of a risk score in its docstring without that
    counting as emitting one.
    """

    import io
    import tokenize

    with open(path, "rb") as handle:
        tokens = list(tokenize.tokenize(handle.readline))

    kept = []

    for token in tokens:

        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue

        kept.append(token.string)

    return " ".join(kept)


def _catalogue(registry):

    catalogue = NegativeSpaceCatalogue.__new__(NegativeSpaceCatalogue)
    catalogue.registry = registry

    return catalogue


def _write_config(tmp_path, drop=None, set_path=None, value=None):

    with open("framework/config/negative_space_rules.json") as handle:
        config = json.load(handle)

    rule = config["rules"][0]

    if drop:
        cursor = rule
        parts = drop.split(".")
        for part in parts[:-1]:
            cursor = cursor[part]
        cursor.pop(parts[-1], None)

    if set_path:
        cursor = rule
        parts = set_path.split(".")
        for part in parts[:-1]:
            cursor = cursor[int(part)] if part.isdigit() else cursor[part]
        cursor[parts[-1]] = value

    path = tmp_path / "negative_space_rules.json"
    path.write_text(json.dumps(config))

    return str(path)
