"""Tests for the operational pattern layer.

The recurring question is not "can an algorithm find something" but "can the
finding be explained well enough for a supervisor to act on". Several tests
therefore assert that *no* signal is produced, and that the reason is
recorded, because a pattern that cannot say why it is unusual should not be
emitted at all.
"""

from __future__ import annotations

import copy
import json

import pytest

from framework.pipeline import SATSAPipeline
from framework.supervision.negative_space_detector import NegativeSpaceDetector
from framework.supervision.operational_pattern_detector import (
    OperationalPatternDetector,
    _binomial_upper_tail,
    _binomial_upper_tail_log10,
    _jaccard,
    _probability_phrase,
    _tokenise,
)
from framework.supervisory.rules.operational_pattern_rules import (
    NOT_EVALUABLE,
    POTENTIAL_OPERATIONAL_ANOMALY,
    OperationalPatternCatalogue,
    OperationalPatternRegistry,
)
from framework.supervisory.rules.rule_engine import RuleConfigError

CONTROLLED = "dataset_operational_pattern_controlled.csv"
RENAMED = "dataset_operational_pattern_renamed.csv"

CONCENTRATION = "REPEATED_ASSET_ACTIVITY"
REPETITION = "REPEATED_INVESTIGATION_EVIDENCE"


@pytest.fixture(scope="module")
def result():

    return SATSAPipeline().run(CONTROLLED)


@pytest.fixture(scope="module")
def renamed():

    return SATSAPipeline().run(RENAMED)


@pytest.fixture(scope="module")
def detector():

    return OperationalPatternDetector()


def findings_for(result, assessment_id):

    return [
        finding
        for finding in result["operational_pattern_findings"]["findings"]
        if finding["assessment_id"] == assessment_id
    ]


def indicators_for(result, assessment_id):

    return {finding["indicator"] for finding in findings_for(result, assessment_id)}


def states_for(result, assessment_id, pattern_id):

    for scope in result["operational_pattern_findings"]["scopes"]:

        if scope["assessment_id"] == assessment_id:

            for state in scope["pattern_states"]:

                if state["pattern_id"] == pattern_id:
                    return state

    return None


# -- 1. existing infrastructure reuse ------------------------------------


class TestExistingInfrastructure:

    def test_canonical_concepts_are_reused_not_redefined(self, detector):

        mappings = json.load(open("framework/config/mappings.json"))

        for pattern in detector.catalogue.patterns:

            for concept in pattern.evidence_concepts:

                assert concept in mappings, (
                    f"{pattern.pattern_id} uses {concept}, which is not a "
                    f"canonical concept"
                )

    def test_concept_projection_is_the_shared_evidence_index(self):

        with open(
            "framework/capability/capability_evaluator.py"
        ) as handle:
            index_source = handle.read()

        with open(
            "framework/supervision/operational_pattern_detector.py"
        ) as handle:
            pattern_source = handle.read()

        assert "def concept_values(" in index_source
        assert "evidence_index.concept_values(records)" in pattern_source

    def test_all_three_supervision_layers_share_the_projection(self):

        for path in (
            "framework/supervision/execution_gap_engine.py",
            "framework/supervision/negative_space_detector.py",
            "framework/supervision/operational_pattern_detector.py",
        ):

            with open(path) as handle:
                assert "evidence_index.concept_values(records)" in handle.read()

    def test_reuses_the_shared_rule_validation_primitives(self):

        with open(
            "framework/supervisory/rules/operational_pattern_rules.py"
        ) as handle:
            source = handle.read()

        assert "RuleConfigError" in source
        assert "normalise_value" in source
        assert "DEFAULT_MAPPINGS_CONFIG" in source
        assert "DEFAULT_CAPABILITIES_CONFIG" in source
        assert "UnavailableRule" in source

    def test_reuses_the_shared_evidence_predicate(self):

        with open(
            "framework/supervision/operational_pattern_detector.py"
        ) as handle:
            source = handle.read()

        assert "from framework.supervision.execution_gap_detector import has_evidence" in source

    def test_orphaned_isolation_forest_is_not_reused(self, detector):

        # The artefact exists but cannot be loaded, and its feature vector
        # corresponds to no canonical concept. It must be recorded as
        # unavailable rather than silently ignored or hand-rolled around.
        import os

        assert os.path.exists("data/generated/isolation_forest.pkl")

        unavailable = {
            rule.pattern_id
            for rule in detector.catalogue.unavailable_patterns
        }

        assert "statistical_isolation_forest_anomaly" in unavailable

    def test_no_sklearn_dependency_is_introduced(self):

        with open(
            "framework/supervision/operational_pattern_detector.py"
        ) as handle:
            assert "sklearn" not in handle.read()


# -- 2. normal distribution -----------------------------------------------


class TestNormalDistribution:

    def test_even_distribution_raises_no_signal(self, result):

        # OP-A01: 20 records spread one per asset.
        assert findings_for(result, "OP-A01::Period-1") == []

    def test_the_scope_is_still_evaluated_and_says_why(self, result):

        state = states_for(result, "OP-A01::Period-1", "repeated_asset_activity")

        assert state["pattern_status"] == "NO_PATTERN_DETECTED"
        assert state["explanation"]
        assert state["population_size"] == 20


# -- 3. concentrated activity ---------------------------------------------


class TestConcentratedActivity:

    def test_unusual_concentration_raises_a_signal(self, result):

        assert indicators_for(result, "OP-B02::Period-1") == {CONCENTRATION}

    def test_the_evidence_is_arithmetically_checkable(self, result):

        evidence = findings_for(result, "OP-B02::Period-1")[0]["evidence"]

        assert evidence["group_record_count"] == 14
        assert evidence["scope_record_count"] == 20
        assert evidence["distinct_groups"] == 7
        assert evidence["group_share"] == 0.7
        assert evidence["group_share_pct"] == "70.0"
        assert evidence["uniform_expected_share"] == round(1 / 7, 4)

    def test_the_calculation_is_reproducible_from_the_stated_method(self, result):

        evidence = findings_for(result, "OP-B02::Period-1")[0]["evidence"]

        # A reviewer can recompute the decision from the numbers in the
        # finding, without trusting the tool.
        expected = _binomial_upper_tail(
            evidence["group_record_count"],
            evidence["scope_record_count"],
            1.0 / evidence["distinct_groups"],
        )

        assert expected <= evidence["alpha"]

    def test_the_probability_is_never_reported_as_exactly_zero(self, result):

        for finding in result["operational_pattern_findings"]["findings"]:

            if finding["pattern_type"] != "CONCENTRATION":
                continue

            evidence = finding["evidence"]

            assert evidence["binomial_upper_tail_log10"] is not None
            assert evidence["probability_phrase"]

            # The claim must be a magnitude, never an assertion of certainty.
            reason = finding["reason"].lower()

            assert "probability of 0" not in reason
            assert "probability zero" not in reason
            assert "impossible" not in reason

    def test_a_share_below_the_flagged_count_raises_nothing(self, result):

        # A scope can hold a high share on a small count and still be
        # unremarkable, which is why the count floor exists alongside the test.
        pattern = detector_pattern = OperationalPatternDetector().catalogue.get(
            "repeated_asset_activity"
        )

        evaluation = OperationalPatternDetector().evaluate_pattern(
            detector_pattern,
            [
                {"ASSET_IDENTIFIER": "X"},
                {"ASSET_IDENTIFIER": "X"},
                {"ASSET_IDENTIFIER": "X"},
                {"ASSET_IDENTIFIER": "Y"},
            ]
            + [{"ASSET_IDENTIFIER": f"N{i}"} for i in range(12)],
        )

        assert evaluation["state"] == "NO_PATTERN_DETECTED"
        assert pattern is not None


# -- 4. repetitive investigation ------------------------------------------


class TestRepetitiveInvestigation:

    def test_repeated_evidence_raises_a_signal(self, result):

        assert indicators_for(result, "OP-C03::Period-1") == {REPETITION}

    def test_the_group_is_described_without_disclosing_the_text(self, result):

        finding = findings_for(result, "OP-C03::Period-1")[0]
        evidence = finding["evidence"]

        assert evidence["repeating_group_size"] == 16
        assert evidence["min_pairwise_similarity"] == 1.0
        assert evidence["raw_text_disclosed"] is False

        serialised = json.dumps(finding)

        # The submitted sentence must not appear anywhere in the finding.
        assert "quarantined pending review" not in serialised
        assert "Host isolated and malware binary" not in serialised

    def test_repetition_spanning_assets_is_reported_as_such(self, result):

        evidence = findings_for(result, "OP-C03::Period-1")[0]["evidence"]

        assert evidence["distinct_assets_in_group"] > 1

    def test_distinct_evidence_raises_nothing(self, result):

        # OP-A01 carries 20 different notes.
        assert indicators_for(result, "OP-A01::Period-1") == set()

    def test_the_reason_reports_the_measured_similarity_not_the_floor(
        self, result
    ):

        finding = findings_for(result, "OP-C03::Period-1")[0]
        evidence = finding["evidence"]
        reason = finding["reason"]

        # The configured floor must never be presented as an observation. Here
        # the observed minimum is 1.0 while the floor is 0.8, so quoting "0.8
        # across the group" would understate what was actually measured.
        assert evidence["min_similarity_threshold"] == 0.8
        assert evidence["min_pairwise_similarity"] == 1.0

        assert "1.0" in reason
        assert "floor of 0.8" in reason

    def test_a_measured_similarity_below_the_floor_is_still_reported(
        self, detector
    ):
        # Notes of 12 tokens differing in one: Jaccard 11/13 = 0.846, which
        # qualifies against the 0.8 floor but is clearly not a perfect match.
        base = (
            "host isolated and the malicious binary was quarantined pending "
            "further triage by the analyst on duty"
        ).split()

        records = []
        for index in range(16):
            tokens = list(base)
            tokens[4] = f"quarantined_variant_{index}"
            records.append(
                {
                    "ASSET_IDENTIFIER": f"NODE_{index:02d}",
                    "INVESTIGATION_EVIDENCE": " ".join(tokens),
                }
            )

        pattern = detector.catalogue.get("repetitive_investigation_evidence")
        evaluation = detector.evaluate_pattern(pattern, records)
        evidence = evaluation["evidence"]

        assert evaluation["state"] == POTENTIAL_OPERATIONAL_ANOMALY
        assert evidence["min_similarity_threshold"] == 0.8
        assert 0.8 <= evidence["min_pairwise_similarity"] < 1.0

    def test_similarity_is_token_set_overlap(self):

        left = _tokenise("Host isolated and binary quarantined")
        right = _tokenise("Host isolated and binary quarantined")

        assert _jaccard(left, right) == 1.0
        assert _jaccard(_tokenise("a b c"), _tokenise("x y z")) == 0.0

    def test_word_order_does_not_defeat_similarity(self):

        left = _tokenise("host isolated binary")
        right = _tokenise("binary host isolated")

        assert _jaccard(left, right) == 1.0

    def test_short_or_absent_text_yields_no_token_set(self):

        assert _tokenise("") is None
        assert _tokenise(None) is None
        assert _tokenise(42) is None


# -- 5. statistical anomaly support ---------------------------------------


class TestStatisticalSupport:

    def test_binomial_tail_matches_hand_computed_values(self):

        # P(X >= 2) for Binomial(4, 0.5) = (6+4+1)/16
        assert _binomial_upper_tail(2, 4, 0.5) == pytest.approx(11 / 16)

        # P(X >= 4) for Binomial(4, 0.5) = 1/16
        assert _binomial_upper_tail(4, 4, 0.5) == pytest.approx(1 / 16)

    def test_tail_is_monotonic_in_the_threshold(self):

        values = [_binomial_upper_tail(k, 20, 1 / 5) for k in range(1, 21)]

        assert all(
            earlier >= later for earlier, later in zip(values, values[1:])
        )

    def test_a_tiny_tail_is_never_reported_as_zero(self):

        # The raw probability for a concentrated scope is far below display
        # precision, so it is rounded to 0.0 for the evidence field. The
        # log10 magnitude is what stops that reading as certainty.
        from framework.supervision.operational_pattern_detector import (
            _round_probability,
        )

        raw = _binomial_upper_tail(14, 20, 1 / 7)
        log10 = _binomial_upper_tail_log10(14, 20, 1 / 7)

        assert 0 < raw < 1e-6
        assert _round_probability(raw) == 0.0
        assert log10 < -6
        assert _probability_phrase(log10).startswith("below 1 in")

    def test_log10_agrees_with_the_direct_value_when_representable(self):

        direct = _binomial_upper_tail(16, 20, 1 / 5)
        log10 = _binomial_upper_tail_log10(16, 20, 1 / 5)

        assert direct > 0.0
        assert log10 == pytest.approx(__import__("math").log10(direct), abs=1e-9)

    def test_probability_phrase_never_claims_certainty(self):

        assert _probability_phrase(-7.6).startswith("below 1 in")
        assert "0.0" not in _probability_phrase(-30.0)
        assert _probability_phrase(None) == "an immeasurably small probability"

    def test_alpha_is_configured_not_hardcoded(self, detector):

        assert detector.catalogue.registry.alpha == 0.01

        configured = json.load(
            open("framework/config/operational_pattern_rules.json")
        )["statistical_parameters"]["alpha"]

        assert configured == detector.catalogue.registry.alpha


# -- 6. insufficient data -------------------------------------------------


class TestInsufficientData:

    def test_a_tiny_scope_raises_nothing(self, result):

        # OP-D04 holds 4 records.
        assert findings_for(result, "OP-D04::Period-1") == []

    def test_both_patterns_report_not_evaluable(self, result):

        for pattern_id in (
            "repeated_asset_activity",
            "repetitive_investigation_evidence",
        ):

            state = states_for(result, "OP-D04::Period-1", pattern_id)

            assert state["pattern_status"] == NOT_EVALUABLE
            assert "Insufficient observations" in state["explanation"]

    @pytest.mark.parametrize("size", [3, 4, 5, 11])
    def test_no_statistical_signal_below_the_configured_floor(self, size):

        pattern = OperationalPatternDetector().catalogue.get(
            "repeated_asset_activity"
        )

        detector = OperationalPatternDetector()

        values = [
            {"ASSET_IDENTIFIER": "BUSY" if i < size - 1 else f"N{i}"}
            for i in range(size)
        ]

        assert detector.evaluate_pattern(pattern, values)["state"] == NOT_EVALUABLE

    def test_the_floor_is_configuration_not_detector_logic(self, detector):

        pattern = detector.catalogue.get("repeated_asset_activity")

        assert pattern.method.minimums["min_scope_records"] == 12
        assert pattern.method.minimums["min_distinct_assets"] == 3
        assert pattern.method.minimums["min_records_on_flagged_asset"] == 4

    def test_minimums_are_reported_with_every_state(self, result):

        for scope in result["operational_pattern_findings"]["scopes"]:

            for state in scope["pattern_states"]:

                assert state["minimum_observations"]

    def test_a_configured_floor_is_actually_honoured(self, tmp_path):

        # Proves the floor is enforced from configuration rather than being a
        # constant: lowering it must make a small scope evaluable.
        registry = OperationalPatternRegistry(
            config_file=_write_config(
                tmp_path,
                path=(
                    "methodology",
                    "asset_concentration",
                    "minimum_observations",
                    "min_scope_records",
                ),
                value=3,
            )
        )

        pattern = registry.get("repeated_asset_activity")

        evaluation = OperationalPatternDetector(
            catalogue=_catalogue(registry)
        ).evaluate_pattern(
            pattern,
            [
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "A"},
                {"ASSET_IDENTIFIER": "B"},
                {"ASSET_IDENTIFIER": "C"},
                {"ASSET_IDENTIFIER": "D"},
            ],
        )

        assert evaluation["state"] == POTENTIAL_OPERATIONAL_ANOMALY


# -- 7. missing evidence ---------------------------------------------------


class TestMissingEvidence:

    def test_a_scope_without_the_grouping_concept_is_not_evaluated(
        self, detector
    ):

        pattern = detector.catalogue.get("repeated_asset_activity")

        evaluation = detector.evaluate_pattern(
            pattern, [{"SECURITY_SEVERITY": "CRITICAL"}] * 14
        )

        assert evaluation["state"] == "EVIDENCE_NOT_PRESENT"
        assert evaluation["state_record"]["explanation"]

    def test_a_single_valued_scope_has_no_distribution(self, detector):

        pattern = detector.catalogue.get("repeated_asset_activity")

        evaluation = detector.evaluate_pattern(
            pattern, [{"ASSET_IDENTIFIER": "ONLY"}] * 20
        )

        assert evaluation["state"] == "EVIDENCE_NOT_PRESENT"

    def test_absent_text_yields_no_repetition_signal(self, detector):

        pattern = detector.catalogue.get("repetitive_investigation_evidence")

        evaluation = detector.evaluate_pattern(
            pattern, [{"ASSET_IDENTIFIER": f"N{i}"} for i in range(16)]
        )

        assert evaluation["state"] == "EVIDENCE_NOT_PRESENT"
        assert evaluation["state_record"]["records_with_evidence"] == 0

    def test_empty_population_is_handled(self, detector):

        pattern = detector.catalogue.get("repeated_asset_activity")

        assert detector.evaluate_pattern(pattern, [])["state"] == (
            "EVIDENCE_NOT_PRESENT"
        )


# -- 8. unknown values -----------------------------------------------------


class TestUnknownValues:

    def test_blank_and_placeholder_values_are_ignored(self, detector):

        pattern = detector.catalogue.get("repeated_asset_activity")

        values = [{"ASSET_IDENTIFIER": v} for v in ("A", "B", "", "N/A", None)]
        values += [{"ASSET_IDENTIFIER": f"N{i}"} for i in range(10)]

        evaluation = detector.evaluate_pattern(pattern, values)

        assert evaluation["evidence"]["scope_record_count"] == 15
        assert evaluation["evidence"]["distinct_groups"] == 12

    def test_values_are_normalised_before_grouping(self, detector):

        pattern = detector.catalogue.get("repeated_asset_activity")

        values = [{"ASSET_IDENTIFIER": v} for v in ("NODE-1", "node 1", "NODE_1")]
        values += [{"ASSET_IDENTIFIER": "NODE-2"}]
        values += [{"ASSET_IDENTIFIER": f"X{i}"} for i in range(10)]

        evaluation = detector.evaluate_pattern(pattern, values)

        assert evaluation["evidence"]["distinct_groups"] == 12
        assert evaluation["evidence"]["group_record_count"] == 3

    def test_an_unrecognised_value_is_still_a_value(self, result):

        # Unknown-severity text must not crash the pattern layer.
        for finding in result["operational_pattern_findings"]["findings"]:

            assert finding["status"] == POTENTIAL_OPERATIONAL_ANOMALY


# -- 9/10. scope isolation ------------------------------------------------


class TestMultiCseIsolation:

    def test_only_the_concentrated_entity_signals(self, result):

        assert indicators_for(result, "OP-E05::Period-1") == set()
        assert indicators_for(result, "OP-E06::Period-1") == {CONCENTRATION}

    def test_pooling_would_misattribute_one_entitys_pattern(self, result):

        # OP-E05 and OP-E06 are different Critical Sector Entities. Pooled, a
        # single verdict would be attributed to both, but within each scope the
        # same absolute count means opposite things.
        alpha = findings_for(result, "OP-E06::Period-1")[0]["evidence"]["alpha"]

        # Within E06, 16 of 20 on one asset is improbable.
        within_concentrated = _binomial_upper_tail(16, 20, 1 / 5)

        # Within E05, one record on one of 18 assets is exactly what uniform
        # allocation predicts, so the same *kind* of observation is ordinary.
        within_normal = _binomial_upper_tail(1, 18, 1 / 18)

        assert within_concentrated <= alpha
        assert within_normal > alpha

        # Both scopes are therefore evaluated, and reach different verdicts.
        assert indicators_for(result, "OP-E06::Period-1") == {CONCENTRATION}
        assert indicators_for(result, "OP-E05::Period-1") == set()

        # A pooled population of 38 records cannot represent both truths at
        # once, which is why the layer refuses to pool.
        pooled_records = 18 + 20
        pooled_assets = 18 + 5

        pooled = _binomial_upper_tail(16, pooled_records, 1 / pooled_assets)

        assert pooled <= alpha, (
            "pooling still flags here, but it flags a population of two "
            "entities as one, which would import E06's pattern onto E05"
        )

    def test_the_population_of_each_finding_is_only_its_own_scope(self, result):

        for finding in result["operational_pattern_findings"]["findings"]:

            scope_total = finding["population"]["scope_record_count"]
            evidence = finding["evidence"]

            evidence_total = evidence.get(
                "records_in_scope", evidence.get("scope_record_count")
            )

            if evidence_total is not None:

                assert evidence_total == scope_total

            # Whichever pattern produced the finding, the number of records it
            # attributes to the signal cannot exceed its own scope.
            contributing = evidence.get(
                "group_record_count", evidence.get("repeating_group_size")
            )

            assert contributing is not None
            assert contributing <= scope_total

            assert len(
                finding["record_reference"]["record_positions"]
            ) == contributing


class TestMultiPeriodIsolation:

    def test_only_the_affected_period_signals(self, result):

        assert indicators_for(result, "OP-F06::Period-1") == {CONCENTRATION}
        assert indicators_for(result, "OP-F06::Period-2") == set()

    def test_both_periods_of_one_entity_are_evaluated(self, result):

        scopes = {
            scope["assessment_id"]
            for scope in result["operational_pattern_findings"]["scopes"]
            if scope["assessment_id"].startswith("OP-F06")
        }

        assert scopes == {"OP-F06::Period-1", "OP-F06::Period-2"}


# -- 11. evidence traceability --------------------------------------------


class TestTraceability:

    def test_findings_point_at_the_underlying_source_rows(self, result):

        import csv

        with open(CONTROLLED) as handle:
            rows = list(csv.DictReader(handle))

        finding = findings_for(result, "OP-B02::Period-1")[0]

        indices = finding["record_reference"]["source_record_indices"]

        assert len(indices) == 14

        for index in indices:

            assert rows[index]["cse"] == "OP-B02"
            assert rows[index]["host"] == "NODE-77"

    def test_positions_and_source_indices_agree_in_length(self, result):

        for finding in result["operational_pattern_findings"]["findings"]:

            reference = finding["record_reference"]

            assert len(reference["record_positions"]) == len(
                reference["source_record_indices"]
            )

    def test_repetition_findings_are_traceable_without_text(self, result):

        import csv

        with open(CONTROLLED) as handle:
            rows = list(csv.DictReader(handle))

        finding = findings_for(result, "OP-C03::Period-1")[0]

        indices = finding["record_reference"]["source_record_indices"]

        assert len(indices) == 16

        # The examiner can reach the text; the finding does not carry it.
        assert rows[indices[0]]["investigation_notes"]


# -- 12. explanation generation -------------------------------------------


class TestExplanation:

    def test_every_finding_answers_the_required_questions(self, result):

        for finding in result["operational_pattern_findings"]["findings"]:

            assert finding["reason"]
            assert "{" not in finding["reason"], "unfilled template placeholder"
            assert finding["population"]["scope_record_count"] > 0
            assert finding["evidence"]
            assert finding["why_review_might_be_warranted"]
            assert finding["explanation_limitations"]
            assert finding["is_not_a_control_failure"]

    def test_the_reason_states_the_numbers_it_depends_on(self, result):

        reason = findings_for(result, "OP-B02::Period-1")[0]["reason"]

        assert "14" in reason
        assert "20" in reason
        assert "70.0%" in reason
        assert "below 1 in" in reason

    def test_findings_do_not_assert_risk(self, result):

        for finding in result["operational_pattern_findings"]["findings"]:

            lowered = json.dumps(finding).lower()

            for phrase in ("is risky", "high risk", "control failure established"):
                assert phrase not in lowered

    def test_explanation_is_required_by_the_catalogue(self, tmp_path):

        with pytest.raises(RuleConfigError, match="explanation_limitations"):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=("patterns", 0, "explanation_limitations"),
                    remove=True,
                )
            )

    def test_rationale_for_review_is_required_by_the_catalogue(self, tmp_path):

        with pytest.raises(
            RuleConfigError, match="why_review_might_be_warranted"
        ):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=("patterns", 0, "why_review_might_be_warranted"),
                    remove=True,
                )
            )


# -- 13/14. no severity, no risk score ------------------------------------


class TestNoScoring:

    def test_no_finding_carries_a_severity_or_score(self, result):

        forbidden = (
            "severity",
            "risk_score",
            "attention_score",
            "priority",
            "weight",
            "level",
            "score",
        )

        for finding in result["operational_pattern_findings"]["findings"]:

            for key in forbidden:

                assert key not in finding

    def test_status_vocabulary_is_qualitative(self, result):

        statuses = {
            finding["status"]
            for finding in result["operational_pattern_findings"]["findings"]
        }

        assert statuses == {POTENTIAL_OPERATIONAL_ANOMALY}

    def test_non_signals_use_factual_statuses_only(self, result):

        statuses = set(result["operational_pattern_findings"]["pattern_status_counts"])

        assert statuses <= {
            POTENTIAL_OPERATIONAL_ANOMALY,
            "NO_PATTERN_DETECTED",
            NOT_EVALUABLE,
            "EVIDENCE_NOT_PRESENT",
        }


# -- 15. no AttentionScorer integration -----------------------------------


class TestNoScorerIntegration:

    def test_findings_do_not_reach_the_attention_scorer(self, result):

        assert "operational_pattern" not in json.dumps(
            result["entity_assessment"]
        )
        assert "operational_pattern" not in json.dumps(
            result["supervisory_findings"]
        )

    def test_findings_do_not_reach_capability_or_gap_layers(self, result):

        for key in (
            "execution_gap_findings",
            "negative_space_findings",
            "capability_assessment",
        ):

            assert "operational_pattern" not in json.dumps(result[key])

    def test_the_scorer_module_is_untouched(self):

        with open("framework/supervision/attention_scorer.py") as handle:
            assert "operational_pattern" not in handle.read()


# -- 16/17. no source-column dependency -----------------------------------


def _executable_source(path):
    """Source with comments and string literals removed.

    The hard-coding audit inspects code, not prose: a module may describe the
    absence of risk scoring in its docstring without that counting as scoring.
    """

    import io
    import tokenize

    with open(path, "rb") as handle:
        tokens = list(tokenize.tokenize(handle.readline))

    kept = [
        token.string
        for token in tokens
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    ]

    return " ".join(kept)


class TestNoSourceColumnHardcoding:

    def test_detector_code_has_no_source_column_or_dataset_literals(self):

        code = _executable_source(
            "framework/supervision/operational_pattern_detector.py"
        )

        for literal in (
            "priority",
            "host",
            "investigation_notes",
            "alert_id",
            "cse",
            "dataset_noisy",
            "dataset_multi_cse",
            "CSE-001",
            "CSE-002",
            "Period-1",
            "Period-2",
            "WEB-PROD-01",
            "DB-PROD-02",
        ):

            assert literal not in code, f"detector code contains {literal}"

    def test_catalogue_code_has_no_source_column_literals(self):

        code = _executable_source(
            "framework/supervisory/rules/operational_pattern_rules.py"
        )

        for literal in (
            "priority",
            "investigation_notes",
            "alert_id",
            "dataset_noisy",
            "Period-1",
        ):

            assert literal not in code

    def test_configuration_holds_no_dataset_or_column_literals(self):

        with open(
            "framework/config/operational_pattern_rules.json"
        ) as handle:
            text = json.dumps(json.load(handle))

        for literal in (
            "dataset_noisy",
            "dataset_multi_cse",
            "CSE-001",
            "CSE-002",
            "Period-1",
            "Period-2",
            "WEB-PROD-01",
            "DB-PROD-02",
        ):

            assert literal not in text

        for literal in ("priority", "investigation_notes", "alert_id"):
            assert literal not in text

    def test_no_legacy_arbitrary_thresholds_reappear(self):

        with open(
            "framework/supervision/operational_pattern_detector.py"
        ) as handle:
            code = handle.read()

        # The deliberately removed legacy rules.
        assert "closure < 5" not in code
        assert "word_count" not in code

    def test_no_share_or_count_cutpoints_in_code(self):

        code = _executable_source(
            "framework/supervision/operational_pattern_detector.py"
        )

        # A bare comparison against a share or a raw count is the pattern this
        # layer was told to avoid; every count bound must come from config.
        for literal in ("> 0.8", ">0.8", "< 0.7", "> 10", ">10"):
            assert literal not in code

    def test_semantic_column_rename_generalises(self, result, renamed):

        assert (
            result["operational_pattern_findings"]["finding_count"]
            == renamed["operational_pattern_findings"]["finding_count"]
        )

        assert (
            result["operational_pattern_findings"]["pattern_status_counts"]
            == renamed["operational_pattern_findings"]["pattern_status_counts"]
        )

        original = {
            (f["assessment_id"], f["indicator"]): f["evidence"]
            for f in result["operational_pattern_findings"]["findings"]
        }

        equivalent = {
            (f["assessment_id"], f["indicator"]): f["evidence"]
            for f in renamed["operational_pattern_findings"]["findings"]
        }

        assert original == equivalent

    def test_renamed_dataset_really_resolves_the_same_concepts(self, renamed):

        mapped = {
            entry["canonical_concept"]: entry["source_column"]
            for entry in renamed["semantic_mapping"]
        }

        assert mapped["ASSET_IDENTIFIER"] == "asset_name"
        assert mapped["SECURITY_SEVERITY"] == "severity"
        assert mapped["INVESTIGATION_EVIDENCE"] == "analyst_findings"


# -- 18/19/20/21. existing regressions -------------------------------------


class TestExistingLayerRegressions:

    def test_execution_gap_findings_are_unchanged_by_this_layer(
        self, result, baseline
    ):

        assert (
            result["execution_gap_findings"]
            == baseline["execution_gap_findings"]
        )

    def test_negative_space_findings_are_unchanged_by_this_layer(
        self, result, baseline
    ):

        assert (
            result["negative_space_findings"]
            == baseline["negative_space_findings"]
        )

    def test_capability_assessment_is_unchanged(self, result, baseline):

        assert result["capability_assessment"] == baseline["capability_assessment"]

    def test_ingestion_is_unchanged(self, result, baseline):

        assert result["ingestion"] == baseline["ingestion"]

    def test_evidence_integrity_is_unchanged(self, result, baseline):

        assert result["canonical_records"] == baseline["canonical_records"]
        assert result["semantic_mapping"] == baseline["semantic_mapping"]

    def test_only_the_new_key_is_added(self, result, baseline):

        # peer_benchmark is a later additive layer, not part of what this
        # guard measures, so it is removed from both sides first.
        result = {key: value for key, value in result.items() if key != "peer_benchmark"}

        for key, value in baseline.items():

            assert key in result, f"{key} disappeared"
            assert result[key] == value, f"{key} changed"

        assert set(result) - set(baseline) == {"operational_pattern_findings"}

    @pytest.mark.parametrize(
        "dataset", ["dataset_noisy.csv", "dataset_multi_cse.csv"]
    )
    def test_small_regression_datasets_gain_only_the_new_key(self, dataset):

        full = SATSAPipeline().run(dataset)

        pipeline = SATSAPipeline()
        pipeline.operational_pattern_detector = _disabled_detector()

        before = pipeline.run(dataset)
        before.pop("operational_pattern_findings", None)

        # peer_benchmark reads this layer's result, so it is compared in its
        # own right below rather than through this layer's guard.
        before.pop("peer_benchmark", None)
        full_without_peer = {
            key: value for key, value in full.items() if key != "peer_benchmark"
        }

        for key, value in before.items():

            assert key in full_without_peer
            assert full_without_peer[key] == value, f"{dataset}: {key} changed"

        assert set(full_without_peer) - set(before) == {
            "operational_pattern_findings"
        }

    @pytest.mark.parametrize(
        "dataset", ["dataset_noisy.csv", "dataset_multi_cse.csv"]
    )
    def test_small_datasets_report_no_pattern_signal(self, dataset):

        result = SATSAPipeline().run(dataset)

        operational = result["operational_pattern_findings"]

        # Both hold too few records for any method here, and that must be said
        # rather than papered over.
        assert operational["finding_count"] == 0
        assert set(operational["pattern_status_counts"]) <= {
            NOT_EVALUABLE,
            "EVIDENCE_NOT_PRESENT",
            "NO_PATTERN_DETECTED",
        }


# -- catalogue integrity ---------------------------------------------------


class TestCatalogueIntegrity:

    def test_only_two_patterns_are_implemented(self, detector):

        # Deliberately small. A large rule set would be harder to defend than
        # a narrow one.
        assert len(detector.catalogue.patterns) == 2

    def test_unavailable_patterns_record_their_reasons(self, detector):

        for rule in detector.catalogue.unavailable_patterns:

            assert rule.status == "UNAVAILABLE"
            assert rule.missing_evidence
            assert rule.why_not_implemented
            assert rule.would_require

    def test_closure_and_isolation_forest_are_recorded_unavailable(
        self, detector
    ):

        ids = {rule.pattern_id for rule in detector.catalogue.unavailable_patterns}

        assert "unusual_closure_behaviour" in ids
        assert "statistical_isolation_forest_anomaly" in ids

    def test_closure_is_unavailable_because_no_expectation_exists(self, detector):

        rule = next(
            item
            for item in detector.catalogue.unavailable_patterns
            if item.pattern_id == "unusual_closure_behaviour"
        )

        joined = " ".join(rule.why_not_implemented).lower()

        assert "expectation" in joined
        assert "closure < 5" in joined

    def test_status_must_be_a_qualified_signal(self, tmp_path):

        with pytest.raises(
            RuleConfigError, match="POTENTIAL_OPERATIONAL_ANOMALY"
        ):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=("patterns", 0, "status"),
                    value="CONTROL_FAILURE",
                )
            )

    def test_control_failure_status_is_rejected_outright(self):

        with open(
            "framework/config/operational_pattern_rules.json"
        ) as handle:
            text = handle.read()

        assert '"CONTROL FAILURE"' not in text

    def test_unknown_capability_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="eight defined capabilities"):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=("patterns", 0, "capability"),
                    value="MADE_UP",
                )
            )

    def test_unknown_concept_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="does not exist"):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=("patterns", 0, "population_concept"),
                    value="NOT_A_CONCEPT",
                )
            )

    def test_method_must_be_declared(self, tmp_path):

        with pytest.raises(RuleConfigError, match="reason_template"):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=("patterns", 0, "reason_template"),
                    remove=True,
                )
            )

    def test_method_must_declare_minimum_observations(self, tmp_path):

        with pytest.raises(RuleConfigError, match="minimum_observations"):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=(
                        "methodology",
                        "asset_concentration",
                        "minimum_observations",
                    ),
                    remove=True,
                )
            )

    def test_similarity_must_be_explicit_configuration(self, tmp_path):

        with pytest.raises(RuleConfigError, match="min_similarity"):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=(
                        "methodology",
                        "investigation_repetition",
                        "min_similarity",
                    ),
                    remove=True,
                )
            )

    def test_invalid_alpha_is_rejected(self, tmp_path):

        with pytest.raises(RuleConfigError, match="alpha"):

            OperationalPatternRegistry(
                config_file=_write_config(
                    tmp_path,
                    path=("statistical_parameters", "alpha"),
                    value=1.5,
                )
            )

    def test_methodology_is_published_with_the_findings(self, result):

        methodology = result["operational_pattern_findings"]["methodology"]

        assert "asset_concentration" in methodology
        assert "investigation_repetition" in methodology
        assert methodology["asset_concentration"]["minimum_observations"]
        assert methodology["asset_concentration"]["null_hypothesis"]


# -- helpers ---------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline():

    return copy.deepcopy(_run_without_operational_patterns())


def _disabled_detector():

    stub = OperationalPatternDetector.__new__(OperationalPatternDetector)
    stub.evaluate_collection = lambda *args, **kwargs: None

    return stub


def _run_without_operational_patterns():

    pipeline = SATSAPipeline()
    pipeline.operational_pattern_detector = _disabled_detector()

    result = pipeline.run(CONTROLLED)
    result.pop("operational_pattern_findings", None)

    # peer_benchmark is a separate additive layer that reads this layer's
    # result, so it necessarily differs when that result is stubbed out. It is
    # excluded here so this guard keeps measuring only what this layer did.
    result.pop("peer_benchmark", None)

    return result


def _catalogue(registry):

    catalogue = OperationalPatternCatalogue.__new__(OperationalPatternCatalogue)
    catalogue.registry = registry

    return catalogue


def _write_config(tmp_path, path, value=None, remove=False):
    """Write a mutated copy of the shipped config into tmp_path.

    Always mutates a temporary copy, never the shipped configuration.
    """

    with open("framework/config/operational_pattern_rules.json") as handle:
        config = json.load(handle)

    cursor = config

    for key in path[:-1]:
        cursor = cursor[key]

    if remove:
        cursor.pop(path[-1], None)
    else:
        cursor[path[-1]] = value

    target = tmp_path / "operational_pattern_rules.json"
    target.write_text(json.dumps(config))

    return str(target)
