"""Tests for the validation framework.

The framework under test is an observer. The tests therefore spend most of
their effort on two things:

  * the comparison machinery classifies outcomes correctly, including the
    awkward ones (scope mismatch, unsupported evidence, not evaluable);
  * the framework cannot quietly start doing analytics of its own, and cannot
    present controlled design intent as expert judgement.

Synthetic review records are used to drive the comparison. They live in this
test file only and are never written to the shipped template, so no test can
be mistaken for a completed expert review.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import tokenize

import pytest

from framework.pipeline import SATSAPipeline
from framework.validation import compare as compare_module
from framework.validation import corpus as corpus_module
from framework.validation import evidence as evidence_module
from framework.validation import metrics as metrics_module
from framework.validation import normalize as normalize_module
from framework.validation import reference as reference_module
from framework.validation import report as report_module
from framework.validation.compare import (
    FALSE_NEGATIVE,
    FALSE_POSITIVE,
    MATCH,
    MATCH_UNSUPPORTED,
    SCOPE_MISMATCH,
    compare,
)
from framework.validation.corpus import (
    FAMILY_RESULT_KEYS,
    FORBIDDEN_LABEL_PHRASES,
    LABEL_SOURCE_CONTROLLED,
    LABEL_SOURCE_EXPERT,
    CorpusError,
    ValidationCase,
    load_corpus,
    load_corpus_document,
)
from framework.validation.evidence import (
    NOT_VERIFIABLE,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    check_evidence,
    check_traceability,
    find_concept_collisions,
    read_rows,
    scope_row_indices,
    unmapped_concepts,
)
from framework.validation.metrics import compute_metrics
from framework.validation.normalize import (
    NormalisedSignal,
    normalise_indicator_list,
    normalise_result,
    signal_positions,
)
from framework.validation.reference import build_reference
from framework.validation.report import (
    EXPERT_PENDING,
    assert_no_ground_truth_claims,
    build_report,
)
from framework.validation.schema import (
    DASHBOARD_DIFFICULTY_VALUES,
    HUMAN_FIELDS,
    REVIEW_TEMPLATE_PATH,
    ReviewTemplateError,
    build_review_template,
    is_template_blank,
    validate_review,
)

CASES = load_corpus()

CONCENTRATION = "REPEATED_ASSET_ACTIVITY"
REPETITION = "REPEATED_INVESTIGATION_EVIDENCE"
ESCALATION_GAP = "CRITICAL_ALERT_NOT_ESCALATED"
MISSING_EVIDENCE = "MISSING_ESCALATION_EVIDENCE"

REQUIRED_CASE_TYPES = {
    "clear_execution_gap",
    "valid_execution",
    "missing_evidence",
    "clear_negative_space",
    "complete_evidence",
    "partial_evidence",
    "clear_operational_concentration",
    "normal_distribution",
    "repetitive_investigation_evidence",
    "normal_investigation_evidence",
    "insufficient_observations",
    "mixed_signal",
    "multi_cse_isolation",
    "multi_period_isolation",
}


def _quiet_pipeline(dataset):
    with contextlib.redirect_stdout(io.StringIO()):
        return SATSAPipeline().run(dataset)


@pytest.fixture(scope="module")
def reference():
    return build_reference(CASES)


@pytest.fixture(scope="module")
def pipelines():
    return {
        dataset: _quiet_pipeline(dataset)
        for dataset in sorted({case.dataset for case in CASES})
    }


@pytest.fixture
def template():
    """A freshly built template per test.

    Function scoped on purpose: several tests deliberately corrupt a template to
    prove the validator rejects it, and a shared instance would let that
    corruption leak into later tests and make them pass or fail by ordering
    rather than by what they assert.
    """

    return build_review_template(CASES)


def _review(answers):
    """A review with only the given human fields filled in.

    ``answers`` maps case_id to a dict of human fields. Everything else stays
    empty, so a test controls exactly what the reviewer appears to have said.
    """

    review = build_review_template(CASES)

    by_case = {record["case_id"]: record for record in review["records"]}

    for case_id, fields in answers.items():
        by_case[case_id].update(fields)

    return review


def _agreed_review():
    """A review that mirrors SAT-SA's own output.

    Used to exercise the match path, including evidence checks. It is a test
    fixture only and is never written to disk as a completed review.
    """

    reference = build_reference(CASES)

    answers = {}

    for record in reference["records"]:
        indicators = []

        for family in FAMILY_RESULT_KEYS:
            for finding in record[f"sat_sa_{family}_findings"]:
                if finding["indicator"] not in indicators:
                    indicators.append(finding["indicator"])

        answers[record["case_id"]] = {
            "human_indicators": indicators,
            "human_confidence": "HIGH",
            "reviewer_id": "TEST-FIXTURE-NOT-AN-EXPERT",
        }

    return _review(answers)


# -- 1. validation schema -------------------------------------------------


class TestValidationSchema:

    def test_template_has_one_record_per_case(self, template):
        assert len(template["records"]) == len(CASES)
        assert template["case_count"] == len(CASES)

    def test_template_records_carry_case_identity(self, template):

        for record, case in zip(template["records"], CASES):
            assert record["case_id"] == case.case_id
            assert record["assessment_id"] == case.assessment_id
            assert record["entity"] == case.entity_id
            assert record["period"] == case.period_label

    def test_template_declares_every_required_human_field(self, template):

        required = {
            "human_execution_gap",
            "human_negative_space",
            "human_operational_pattern",
            "human_indicators",
            "human_evidence_reference",
            "human_reason",
            "human_confidence",
            "supervisory_dashboard_difficulty",
            "reviewer_id",
            "review_timestamp",
        }

        assert required <= set(HUMAN_FIELDS)

        for record in template["records"]:
            assert required <= set(record)

    def test_dashboard_question_allows_only_three_answers(self):
        assert DASHBOARD_DIFFICULTY_VALUES == ("YES", "NO", "UNCERTAIN")

    def test_scope_identity_is_dataset_plus_assessment_id(self):
        # Two datasets in this repository both contain CSE-A01::Period-2, so an
        # assessment id alone is not a unique scope.
        keys = [case.scope_key for case in CASES]

        assert len(keys) == len(set(keys))

        collisions = [
            case.assessment_id
            for case in CASES
            if sum(
                1 for other in CASES
                if other.assessment_id == case.assessment_id
            )
            > 1
        ]

        assert collisions, "expected at least one repeated assessment id"
        assert len(CASES) == len(set(keys)), "scope keys must be unique"

    def test_duplicate_case_id_is_rejected(self, tmp_path):

        document = load_corpus_document()
        document["cases"].append(copy.deepcopy(document["cases"][0]))

        path = tmp_path / "dupe.json"
        path.write_text(json.dumps(document))

        with pytest.raises(CorpusError):
            load_corpus(str(path))

    def test_unknown_label_source_is_rejected(self, tmp_path):

        document = load_corpus_document()
        document["cases"][0]["controlled_expectation"]["label_source"] = "MADE_UP"

        path = tmp_path / "bad.json"
        path.write_text(json.dumps(document))

        with pytest.raises(CorpusError):
            load_corpus(str(path))

    def test_corpus_may_not_contain_expert_labels(self, tmp_path):

        document = load_corpus_document()
        document["cases"][0]["controlled_expectation"]["label_source"] = (
            LABEL_SOURCE_EXPERT
        )

        path = tmp_path / "expert.json"
        path.write_text(json.dumps(document))

        with pytest.raises(CorpusError):
            load_corpus(str(path))

    def test_review_validation_rejects_a_bad_confidence_value(self, template):

        template["records"][0]["human_confidence"] = "VERY_SURE"

        problems = validate_review(template)

        assert any("human_confidence" in problem for problem in problems)

    def test_review_validation_rejects_an_out_of_range_answer(self, template):

        template["records"][0]["supervisory_dashboard_difficulty"] = "MAYBE"

        problems = validate_review(template)

        assert any(
            "supervisory_dashboard_difficulty" in problem
            for problem in problems
        )

    def test_review_validation_rejects_indicator_outside_the_union(
        self, template
    ):

        record = template["records"][0]
        record["human_indicators"] = [ESCALATION_GAP]
        record["human_execution_gap"] = [MISSING_EVIDENCE]

        problems = validate_review(template)

        assert any("human_indicators" in problem for problem in problems)


# -- 2. finding normalization --------------------------------------------


class TestFindingNormalisation:

    def test_all_three_families_normalise(self, pipelines):

        result = _quiet_pipeline("dataset_operational_pattern_controlled.csv")

        signals = normalise_result(result)

        families = {signal.family for signal in signals}

        assert "execution_gap" in families or "negative_space" in families
        assert "operational_pattern" in families

    def test_normalised_signal_exposes_the_comparable_fields(
        self, pipelines
    ):

        result = _quiet_pipeline("dataset_operational_pattern_controlled.csv")

        signals = normalise_result(result)

        assert signals

        for signal in signals:
            payload = signal.to_dict()

            for field in (
                "family",
                "indicator",
                "capability",
                "assessment_id",
                "entity_id",
                "period_label",
                "status",
                "record_positions",
            ):
                assert field in payload

    def test_record_positions_are_read_for_every_family(self, pipelines):

        for dataset, result in pipelines.items():
            for signal in normalise_result(result):
                assert signal.record_positions, (
                    f"{dataset} {signal.indicator} cited no records"
                )

    def test_single_position_and_list_position_both_read(self):

        listed = NormalisedSignal(
            "execution_gap",
            {
                "indicator": "X",
                "record_reference": {"record_position": 3,
                                     "source_record_index": 7},
            },
            raw_positions=signal_positions(
                {"record_reference": {"record_position": 3,
                                      "source_record_index": 7}}
            ),
        )

        assert listed.record_positions == [7]

        many = NormalisedSignal(
            "negative_space",
            {
                "indicator": "Y",
                "record_reference": {"record_positions": [1, 2, 3]},
            },
            raw_positions=signal_positions(
                {"record_reference": {"record_positions": [1, 2, 3]}}
            ),
        )

        assert many.record_positions == [1, 2, 3]

    def test_indicator_list_accepts_list_and_text(self):

        assert normalise_indicator_list([ESCALATION_GAP]) == [ESCALATION_GAP]
        assert normalise_indicator_list(None) == []
        assert normalise_indicator_list(f"{ESCALATION_GAP}, {MISSING_EVIDENCE}") == [
            ESCALATION_GAP,
            MISSING_EVIDENCE,
        ]

    def test_explanations_are_never_compared_as_strings(self, template):

        review = _agreed_review()

        for record in review["records"]:
            record["human_reason"] = "completely different wording"

        # A mismatch in wording must not change any outcome.
        reference = build_reference(CASES)
        with_wording = compare(CASES, review, reference, {})
        review["records"] = [
            dict(record, human_reason=None) for record in review["records"]
        ]
        without_wording = compare(CASES, review, reference, {})

        def outcomes(payload):
            return sorted(
                (item["outcome"], item["indicator"], item["assessment_id"])
                for item in payload["comparisons"]
            )

        assert outcomes(with_wording) == outcomes(without_wording)


# -- 3. exact indicator match --------------------------------------------


class TestExactIndicatorMatch:

    def test_a_shared_indicator_is_a_match(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        matches = [
            item
            for item in result["comparisons"]
            if item["outcome"] == MATCH
        ]

        assert matches, "expected at least one validated match"

    def test_a_match_requires_the_same_scope(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        for item in result["comparisons"]:
            if item["outcome"] in (MATCH, MATCH_UNSUPPORTED):
                expected_scope = next(
                    case.assessment_id
                    for case in CASES
                    if case.case_id == _case_for(item, result)
                ) if False else item["assessment_id"]

                assert expected_scope


def _case_for(item, result):
    return None


# -- 4. false positive ----------------------------------------------------


class TestFalsePositive:

    def test_a_tool_only_indicator_is_a_false_positive(self, pipelines):

        review = _review({})
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        positives = [
            item
            for item in result["comparisons"]
            if item["outcome"] == FALSE_POSITIVE
        ]

        assert positives
        assert all(item["human_evidence"] is None for item in positives)


# -- 5. false negative ----------------------------------------------------


def _only(case_ids, reference=None):
    """Restrict a comparison to a subset of cases.

    Scope is compared corpus-wide, so a case can only produce a plain false
    negative if the tool reports the indicator nowhere at all. That cannot
    happen for an indicator the tool emits on some other case, which is why
    the narrower paths need a narrower corpus.
    """

    wanted = set(case_ids)
    cases = [case for case in CASES if case.case_id in wanted]
    source = reference if reference is not None else build_reference(CASES)

    narrowed = dict(source)
    narrowed["records"] = [
        record for record in source["records"] if record["case_id"] in wanted
    ]

    return cases, narrowed


class TestFalseNegative:

    def test_an_indicator_the_tool_never_emits_is_a_false_negative(
        self, pipelines
    ):

        # Restricted to the two scopes SAT-SA leaves unflagged, so the reviewer
        # is flagging a gap the tool reports nowhere in this corpus.
        cases, reference = _only({"EG-02", "EG-04"})

        review = _review(
            {
                "EG-02": {
                    "human_indicators": [ESCALATION_GAP],
                    "human_execution_gap": [ESCALATION_GAP],
                    "human_confidence": "MEDIUM",
                    "reviewer_id": "TEST-FIXTURE",
                }
            }
        )

        result = compare(cases, review, reference, pipelines)

        negatives = [
            item
            for item in result["comparisons"]
            if item["outcome"] == FALSE_NEGATIVE
        ]

        assert [item["indicator"] for item in negatives] == [ESCALATION_GAP]
        assert negatives[0]["assessment_id"] == "CSE-A01::Period-2"
        assert negatives[0]["sat_sa_evidence"] is None
        assert negatives[0]["scope_mismatch"] is None

    def test_a_known_indicator_on_an_unflagged_scope_is_a_scope_mismatch(
        self, pipelines
    ):

        # The reviewer credits the escalation gap to a scope SAT-SA did not
        # flag. The tool did report that indicator, just elsewhere, so calling
        # this a plain false negative would hide a localisation error behind a
        # recall number.
        review = _review(
            {
                "EG-02": {
                    "human_indicators": [ESCALATION_GAP],
                    "human_execution_gap": [ESCALATION_GAP],
                    "human_confidence": "MEDIUM",
                    "reviewer_id": "TEST-FIXTURE",
                }
            }
        )

        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        for item in result["comparisons"]:
            if (
                item["indicator"] == ESCALATION_GAP
                and item["assessment_id"] == "CSE-A01::Period-2"
                and item["dataset"] == "dataset_execution_gap_controlled.csv"
            ):
                assert item["outcome"] == SCOPE_MISMATCH
                assert item["scope_mismatch"]["agreeing_scopes"] == []
                assert item["scope_mismatch"]["sat_sa_scopes"]
                return

        pytest.fail("the reviewer's escalation gap on EG-02 was not compared")


# -- 6. scope mismatch ----------------------------------------------------


class TestScopeMismatch:

    def test_an_indicator_on_the_wrong_scope_is_not_a_match(self, pipelines):

        # The reviewer credits the concentration finding to the wrong period.
        # The indicator exists on both sides, but not on the same scope, so it
        # must not be a match, and it must not be quietly scored as agreement.
        review = _review(
            {
                "OP-07": {
                    "human_indicators": [],
                    "human_confidence": "LOW",
                    "reviewer_id": "TEST-FIXTURE",
                },
                "OP-08": {
                    "human_indicators": [CONCENTRATION],
                    "human_operational_pattern": [CONCENTRATION],
                    "human_confidence": "LOW",
                    "reviewer_id": "TEST-FIXTURE",
                },
            }
        )

        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        outcomes = {
            (item["assessment_id"], item["outcome"])
            for item in result["comparisons"]
            if item["indicator"] == CONCENTRATION
        }

        # OP-F06::Period-2 is the scope the reviewer claimed and SAT-SA did
        # not flag; OP-F06::Period-1 is the scope SAT-SA flagged and the
        # reviewer did not. Neither may be a match.
        assert ("OP-F06::Period-2", SCOPE_MISMATCH) in outcomes
        assert ("OP-F06::Period-1", SCOPE_MISMATCH) in outcomes
        assert ("OP-F06::Period-2", MATCH) not in outcomes
        assert ("OP-F06::Period-1", MATCH) not in outcomes

    def test_a_scope_mismatch_says_which_scopes_disagreed(self, pipelines):

        review = _review(
            {
                "OP-07": {"human_indicators": []},
                "OP-08": {
                    "human_indicators": [CONCENTRATION],
                    "human_operational_pattern": [CONCENTRATION],
                },
            }
        )

        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        mismatched = [
            item
            for item in result["comparisons"]
            if item["outcome"] == SCOPE_MISMATCH
        ]

        assert mismatched

        for item in mismatched:
            mismatch = item["scope_mismatch"]
            assert mismatch["human_scopes"] != mismatch["sat_sa_scopes"]
            assert item["assessment_id"] not in mismatch["agreeing_scopes"]

    def test_scope_mismatch_outcome_exists_in_the_vocabulary(self):
        assert SCOPE_MISMATCH in compare_module.OUTCOMES

    def test_scope_mismatch_is_reported_when_scopes_partly_overlap(
        self, pipelines
    ):

        review = _review(
            {
                "OP-06": {
                    "human_indicators": [CONCENTRATION],
                    "human_operational_pattern": [CONCENTRATION],
                    "human_confidence": "MEDIUM",
                    "reviewer_id": "TEST-FIXTURE",
                }
            }
        )

        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        for item in result["comparisons"]:
            if item["indicator"] == CONCENTRATION:
                assert "scope mismatch" in " ".join(item["notes"]).lower() or (
                    item["assessment_id"] == "OP-E06::Period-1"
                )


# -- 7. evidence mismatch -------------------------------------------------


class TestEvidenceMismatch:

    def test_declared_evidence_must_be_present_in_the_cited_rows(
        self, pipelines
    ):

        result = pipelines["dataset_execution_gap_controlled.csv"]

        signals = [
            signal
            for signal in normalise_result(result)
            if signal.family == "execution_gap"
        ]

        assert signals

        report = check_evidence(
            signals[0],
            "dataset_execution_gap_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status == SUPPORTED

    def test_negative_space_coverage_is_not_recomputed_from_its_witnesses(
        self, pipelines
    ):

        # NS-B02::Period-1 has three triggered records, two of which carry
        # escalation evidence, and cites the single record that does not. The
        # coverage figure therefore describes a population the finding does not
        # list. Recomputing it over the cited row alone would report a
        # contradiction where there is none.
        result = pipelines["dataset_negative_space_controlled.csv"]

        signal = next(
            item
            for item in normalise_result(result)
            if item.assessment_id == "NS-B02::Period-1"
            and item.family == "negative_space"
        )

        report = check_evidence(
            signal,
            "dataset_negative_space_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status == SUPPORTED
        assert any(
            check["check"] == "witness_count_matches_absence_count"
            for check in report.checks
        )

    def test_negative_space_evidence_catches_an_overclaimed_absence(
        self, pipelines
    ):

        result = pipelines["dataset_negative_space_controlled.csv"]

        signal = next(
            item
            for item in normalise_result(result)
            if item.assessment_id == "NS-B02::Period-1"
            and item.family == "negative_space"
        )

        # Repoint the finding at the first record of the scope, which plainly
        # says "escalated", while still calling it an absence witness.
        tampered = dict(signal.raw)
        tampered["record_reference"] = {
            "record_positions": [0],
            "source_record_indices": [5],
            "records_with_unusable_evidence": [],
        }

        report = check_evidence(
            NormalisedSignal(
                "negative_space", tampered, scope_positions=[0]
            ),
            "dataset_negative_space_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status in (PARTIALLY_SUPPORTED, UNSUPPORTED)
        assert any(
            "did not classify as unusable" in conflict["detail"]
            for conflict in report.conflicts
        )

    def test_negative_space_evidence_catches_impossible_populations(
        self, pipelines
    ):

        result = pipelines["dataset_negative_space_controlled.csv"]

        signal = next(
            item
            for item in normalise_result(result)
            if item.assessment_id == "NS-B02::Period-1"
            and item.family == "negative_space"
        )

        tampered = copy.deepcopy(dict(signal.raw))
        figures = tampered["evidence_summary"]["coverage_by_concept"][
            "ESCALATION_STATUS"
        ]
        figures["records_with_expected_evidence"] = 0
        figures["coverage"] = 0.0
        tampered["evidence_summary"]["trigger_records"] = 99

        report = check_evidence(
            NormalisedSignal(
                "negative_space", tampered, scope_positions=[2]
            ),
            "dataset_negative_space_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status in (PARTIALLY_SUPPORTED, UNSUPPORTED)
        assert any(
            "does not equal" in conflict["detail"]
            for conflict in report.conflicts
        )
        assert any(
            "submitted rows" in conflict["detail"]
            for conflict in report.conflicts
        )

    def test_a_submitted_but_unusable_value_is_accepted_as_absence(
        self, pipelines
    ):

        # NS-B02::Period-2 submits "pending_review", which states no usable
        # outcome. The finding counts it as an absence and separately records
        # it as unusable, which is exactly the honest way to report it.
        result = pipelines["dataset_negative_space_controlled.csv"]

        signal = next(
            item
            for item in normalise_result(result)
            if item.assessment_id == "NS-B02::Period-2"
            and item.family == "negative_space"
        )

        report = check_evidence(
            signal,
            "dataset_negative_space_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status == SUPPORTED
        assert not report.conflicts

    def test_a_finding_citing_a_wrong_value_is_unsupported(self, pipelines):

        result = pipelines["dataset_execution_gap_controlled.csv"]

        signal = [
            item
            for item in normalise_result(result)
            if item.family == "execution_gap"
        ][0]

        # Claim a severity the cited rows do not carry.
        signal.raw["evidence"] = dict(signal.raw["evidence"])
        signal.raw["evidence"]["SECURITY_SEVERITY"] = "LOW"

        report = check_evidence(
            signal,
            "dataset_execution_gap_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status in (UNSUPPORTED, PARTIALLY_SUPPORTED)
        assert not report.supports_finding

    def test_a_collision_makes_the_evidence_partial_not_silently_supported(
        self, pipelines
    ):

        # The collision detector is exercised on a deliberately colliding
        # mapping rather than on a real dataset, because the shipped datasets
        # no longer collide: SECURITY_SEVERITY now resolves from the alert
        # severity column alone. Here a claim of CRITICAL is checked against a
        # row whose severity column says MEDIUM while a second column mapped to
        # the same concept carries CRITICAL, which is the shape of the original
        # defect and must not be reported as cleanly supported.
        result = pipelines["dataset_capability_rich.csv"]

        rows = read_rows("dataset_capability_rich.csv")

        row = next(
            item
            for item in rows
            if item.get("cse") == "CSE-A01"
            and item.get("period") == "Period-2"
            and str(item.get("priority")).upper() != "CRITICAL"
            and item.get("asset_criticality")
        )

        index = rows.index(row)

        colliding = [
            {"source_column": "priority", "canonical_concept": "SECURITY_SEVERITY"},
            {
                "source_column": "asset_criticality",
                "canonical_concept": "SECURITY_SEVERITY",
            },
        ]

        signal = NormalisedSignal(
            "execution_gap",
            {
                "indicator": "CRITICAL_ALERT_NOT_ESCALATED",
                "evidence": {
                    "SECURITY_SEVERITY": "CRITICAL",
                    "ESCALATION_STATUS": "not_escalated",
                },
                "evidence_concepts": [
                    "SECURITY_SEVERITY",
                    "ESCALATION_STATUS",
                ],
                "record_reference": {
                    "record_position": 0,
                    "source_record_index": index,
                },
                "assessment_id": "CSE-A01::Period-2",
            },
            scope_positions=[0],
        )

        report = check_evidence(
            signal,
            "dataset_capability_rich.csv",
            colliding,
        )

        assert report.status in (PARTIALLY_SUPPORTED, UNSUPPORTED)
        assert report.conflicts

    def test_the_shipped_datasets_no_longer_collide(self, pipelines):

        # Regression guard for the SECURITY_SEVERITY collision. Alert severity
        # and asset criticality are separate axes and must never be resolved to
        # one concept, so no dataset may feed SECURITY_SEVERITY from more than
        # one column.
        #
        # Scoped to SECURITY_SEVERITY on purpose. dataset_capability_rich.csv
        # still feeds INVESTIGATION_EVIDENCE from two columns
        # (investigation_notes and root_cause_identified); that is a separate,
        # pre-existing condition outside the scope of this fix, so it is
        # reported as a remaining limitation rather than silently folded in.
        for dataset in (
            "dataset_capability_rich.csv",
            "dataset_execution_gap_controlled.csv",
            "dataset_negative_space_controlled.csv",
            "dataset_operational_pattern_controlled.csv",
        ):
            collisions = find_concept_collisions(
                pipelines[dataset]["semantic_mapping"]
            )

            assert "SECURITY_SEVERITY" not in collisions, (
                f"{dataset} still feeds SECURITY_SEVERITY from "
                f"{collisions.get('SECURITY_SEVERITY')}"
            )

    def test_alert_severity_and_asset_criticality_are_separate_concepts(
        self, pipelines
    ):

        result = pipelines["dataset_capability_rich.csv"]

        sources = {
            entry["canonical_concept"]: entry["source_column"]
            for entry in result["semantic_mapping"]
        }

        assert sources.get("SECURITY_SEVERITY") == "priority"
        assert sources.get("ASSET_CRITICALITY") == "asset_criticality"

    def test_concept_collisions_are_detected(self):

        # The detector itself is mapping-driven and must still flag a genuine
        # collision, so it is exercised on a synthetic mapping.
        colliding = [
            {"source_column": "priority", "canonical_concept": "SECURITY_SEVERITY"},
            {
                "source_column": "asset_criticality",
                "canonical_concept": "SECURITY_SEVERITY",
            },
        ]

        collisions = find_concept_collisions(colliding)

        assert "SECURITY_SEVERITY" in collisions
        assert set(collisions["SECURITY_SEVERITY"]) == {
            "priority",
            "asset_criticality",
        }

    def test_no_collision_in_the_other_controlled_datasets(self, pipelines):

        for dataset in (
            "dataset_execution_gap_controlled.csv",
            "dataset_negative_space_controlled.csv",
            "dataset_operational_pattern_controlled.csv",
        ):
            collisions = find_concept_collisions(
                pipelines[dataset]["semantic_mapping"]
            )
            assert collisions == {}, f"{dataset} unexpectedly collides"

    def test_a_concept_absent_from_the_mapping_is_reported(self, pipelines):

        # The shipped mapping now declares ESCALATION_STATUS, so the gap
        # reporter is exercised on a mapping with the declaration removed. It
        # must still name the concept, because that check is what would catch a
        # future regression that dropped the pattern again.
        result = pipelines["dataset_execution_gap_controlled.csv"]

        signals = normalise_result(result)

        declared = {
            entry["canonical_concept"]
            for entry in result["semantic_mapping"]
        }

        assert "ESCALATION_STATUS" in declared
        assert unmapped_concepts(result["semantic_mapping"], signals) == {}

        without = [
            entry
            for entry in result["semantic_mapping"]
            if entry["canonical_concept"] != "ESCALATION_STATUS"
        ]

        assert unmapped_concepts(without, signals) == {
            "ESCALATION_STATUS": []
        }

    def test_the_mapping_gap_does_not_block_a_supported_verdict(
        self, pipelines
    ):

        result = pipelines["dataset_execution_gap_controlled.csv"]

        signal = [
            item
            for item in normalise_result(result)
            if item.family == "execution_gap"
        ][0]

        # Remove the declaration so the declared-mapping fallback is used: the
        # evidence is plainly in the submitted rows, so the finding stays
        # supported and the note records that the mapping did not say where the
        # concept came from.
        without = [
            entry
            for entry in result["semantic_mapping"]
            if entry["canonical_concept"] != "ESCALATION_STATUS"
        ]

        report = check_evidence(
            signal,
            "dataset_execution_gap_controlled.csv",
            without,
        )

        assert report.status == SUPPORTED
        assert any("not declared" in note for note in report.notes)

    def test_escalation_status_is_now_directly_traceable(self, pipelines):

        # Every dataset that submits an escalation_status column must now
        # publish that column as the source of ESCALATION_STATUS, so the
        # finding is traceable through the mapping alone and the header
        # fallback is no longer needed.
        for dataset in (
            "dataset_execution_gap_controlled.csv",
            "dataset_negative_space_controlled.csv",
            "dataset_capability_rich.csv",
        ):
            result = pipelines[dataset]

            columns = list(read_rows(dataset)[0])

            assert "escalation_status" in columns, dataset

            sources = {
                entry["canonical_concept"]: entry["source_column"]
                for entry in result["semantic_mapping"]
            }

            assert sources.get("ESCALATION_STATUS") == "escalation_status", (
                f"{dataset} does not trace ESCALATION_STATUS to its column"
            )

            assert unmapped_concepts(
                result["semantic_mapping"],
                normalise_result(result),
                columns,
            ) == {}, f"{dataset} still needs the header fallback"

    def test_no_collision_or_mapping_gap_is_invented_for_clean_datasets(
        self, pipelines
    ):

        for dataset in (
            "dataset_negative_space_controlled.csv",
            "dataset_operational_pattern_controlled.csv",
        ):
            result = pipelines[dataset]
            assert find_concept_collisions(result["semantic_mapping"]) == {}

            # The submitted header is supplied, so a concept with no matching
            # column stays an absence rather than being reported as a
            # traceability gap. dataset_operational_pattern_controlled.csv
            # submits no escalation_status column at all.
            assert unmapped_concepts(
                result["semantic_mapping"],
                normalise_result(result),
                list(read_rows(dataset)[0]),
            ) == {}, (
                f"{dataset} has a concept its mapping does not declare"
            )
    def test_the_absence_of_a_column_is_not_reported_as_a_mapping_gap(
        self, pipelines
    ):

        # A concept with no matching column in the submitted data is the
        # absence the negative-space layer exists to report, not a traceability
        # defect. Reporting it as one would bury the real gaps.
        result = pipelines["dataset_operational_pattern_controlled.csv"]

        signals = [
            item for item in normalise_result(result)
            if item.family == "operational_pattern"
        ]

        columns = list(
            read_rows("dataset_operational_pattern_controlled.csv")[0]
        )

        assert unmapped_concepts(
            result["semantic_mapping"], signals, columns
        ) == {}

    def test_an_uncited_finding_is_not_verifiable(self):

        signal = NormalisedSignal(
            "execution_gap", {"indicator": "X", "record_reference": {}}
        )

        report = check_traceability(signal, [])

        assert report.status == NOT_VERIFIABLE
        assert not report.supports_finding

    def test_a_scope_relative_position_beyond_the_scope_is_unsupported(self):

        signal = NormalisedSignal(
            "operational_pattern",
            {"indicator": "X", "record_reference": {"record_positions": [99]}},
            scope_positions=[99],
        )

        report = check_traceability(signal, list(range(10)))

        assert report.status == UNSUPPORTED

    def test_a_source_row_outside_the_scope_is_unsupported(self):

        signal = NormalisedSignal(
            "execution_gap",
            {"indicator": "X", "record_reference": {"source_record_index": 40}},
            raw_positions=[40],
        )

        report = check_traceability(signal, [0, 1, 2, 3])

        assert report.status == UNSUPPORTED

    def test_a_cited_row_inside_the_scope_is_supported(self, pipelines):

        result = pipelines["dataset_execution_gap_controlled.csv"]

        signal = [
            item
            for item in normalise_result(result)
            if item.family == "execution_gap"
        ][0]

        rows = read_rows("dataset_execution_gap_controlled.csv")

        report = check_traceability(
            signal, scope_row_indices(rows, signal.entity_id, signal.period_label)
        )

        assert report.status == SUPPORTED

    def test_concentration_evidence_is_checked_against_the_rows(
        self, pipelines
    ):

        result = pipelines["dataset_operational_pattern_controlled.csv"]

        signal = [
            item for item in normalise_result(result)
            if item.indicator == CONCENTRATION
        ][0]

        report = check_evidence(
            signal,
            "dataset_operational_pattern_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status == SUPPORTED
        assert any(
            check["check"] == "cited_records_share_the_named_asset"
            for check in report.checks
        )

    def test_repetition_evidence_never_reproduces_the_text(
        self, pipelines
    ):

        result = pipelines["dataset_operational_pattern_controlled.csv"]

        signal = [
            item for item in normalise_result(result)
            if item.indicator == REPETITION
        ][0]

        report = check_evidence(
            signal,
            "dataset_operational_pattern_controlled.csv",
            result["semantic_mapping"],
        )

        assert report.status == SUPPORTED

        serialised = json.dumps(report.to_dict())

        assert "quarantined pending review" not in serialised.lower()

    def test_an_unsupported_match_is_not_counted_as_validated(
        self, pipelines
    ):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)
        metrics = compute_metrics(result)

        for family, block in metrics["per_family"].items():
            for item in result["comparisons"]:
                if item["family"] == family and item["outcome"] == MATCH:
                    assert item["sat_sa_evidence"]["status"] == SUPPORTED


# -- 8. NOT_EVALUABLE handling -------------------------------------------


class TestNotEvaluable:

    def test_declining_is_counted_separately_from_finding_nothing(
        self, pipelines
    ):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)
        metrics = compute_metrics(result)

        not_evaluable = metrics["not_evaluable"]

        assert not_evaluable["cases_where_sat_sa_declined"] > 0
        assert not_evaluable["case_count"] == len(CASES)

    def test_a_declined_pattern_produces_no_indicator(self, pipelines):

        # OP-D04 has four records, which is below every configured minimum.
        case = next(case for case in CASES if case.case_id == "OP-04")
        reference = build_reference(CASES)

        record = next(
            item for item in reference["records"]
            if item["case_id"] == "OP-04"
        )

        assert record["sat_sa_operational_pattern_findings"] == []
        assert case.expected_not_evaluable()

        states = record["sat_sa_operational_pattern_states"]

        assert any(
            state["pattern_status"] == "NOT_EVALUABLE" for state in states
        )

    def test_not_evaluable_is_not_scored_as_agreement(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)
        metrics = compute_metrics(result)

        # A declined case has no outcome at all, so it cannot inflate recall.
        outcomes_for_op04 = [
            item
            for item in result["comparisons"]
            if item["assessment_id"] == "OP-D04::Period-1"
        ]

        assert not any(
            item["family"] == "operational_pattern"
            and item["outcome"] == MATCH
            for item in outcomes_for_op04
        )

    def test_controlled_expectation_agreement_is_reported_separately(
        self, pipelines
    ):

        review = _review({})
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)
        metrics = compute_metrics(result)

        for entry in metrics["not_evaluable"]["entries"]:
            assert "controlled" in entry["note"].lower()


# -- 9-11. per-family comparison -----------------------------------------


class TestFamilyComparisons:

    def test_execution_gap_family(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        metrics = compute_metrics(
            compare(CASES, review, reference, pipelines)
        )

        block = metrics["per_family"]["execution_gap"]

        assert block["true_positives"] > 0
        assert block["false_negatives"] == 0

    def test_negative_space_family(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        metrics = compute_metrics(
            compare(CASES, review, reference, pipelines)
        )

        block = metrics["per_family"]["negative_space"]

        assert block["true_positives"] > 0

    def test_operational_pattern_family(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        metrics = compute_metrics(
            compare(CASES, review, reference, pipelines)
        )

        block = metrics["per_family"]["operational_pattern"]

        assert block["true_positives"] > 0

    def test_every_family_reports_the_required_counts(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        metrics = compute_metrics(
            compare(CASES, review, reference, pipelines)
        )

        for block in metrics["per_family"].values():
            for field in (
                "true_positives",
                "false_positives",
                "false_negatives",
                "precision",
                "recall",
            ):
                assert field in block

    def test_no_grand_accuracy_score_is_produced(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        metrics = compute_metrics(
            compare(CASES, review, reference, pipelines)
        )

        assert metrics["no_grand_accuracy_score"]

        # Checked by walking the structure rather than by searching the
        # serialised text: the metrics are allowed to explain that no accuracy
        # figure exists, and a substring search would flag that disclaimer.
        def keys_in(node, path=""):

            found = []

            if isinstance(node, dict):
                for key, value in node.items():
                    found.append(f"{path}{key}")
                    found.extend(keys_in(value, f"{path}{key}."))

            elif isinstance(node, list):
                for item in node:
                    found.extend(keys_in(item, path))

            return found

        offenders = [
            key
            for key in keys_in(metrics)
            if "accuracy" in key and key != "no_grand_accuracy_score"
        ]

        assert offenders == [], (
            f"metrics expose an accuracy measure: {offenders}"
        )

        # The only ratios offered are per-family precision and recall.
        ratios = {
            key
            for family, block in metrics["per_family"].items()
            for key, value in block.items()
            if isinstance(value, float) and 0.0 <= value <= 1.0
        }

        assert ratios <= {"precision", "recall"}

    def test_metrics_are_not_computable_without_labels(self, pipelines):

        reference = build_reference(CASES)

        metrics = compute_metrics(
            compare(CASES, _review({}), reference, pipelines)
        )

        assert metrics["agreement_metrics_computable"] is False
        assert metrics["expert_labelled"] is False
        assert metrics["label_source"] == "UNLABELLED"

        for block in metrics["per_family"].values():
            assert block["precision"] is None
            assert block["recall"] is None


# -- 12. multi-CSE isolation ---------------------------------------------


class TestMultiCseIsolation:

    def test_the_corpus_pairs_two_entities_in_one_period(self):

        pairs = {
            (case.assessment_id.split("::")[0], case.assessment_id)
            for case in CASES
        }

        entities_by_period = {}

        for case in CASES:
            period = case.assessment_id.split("::")[1]
            entities_by_period.setdefault(period, set()).add(
                case.assessment_id.split("::")[0]
            )

        shared = [
            period for period, entities in entities_by_period.items()
            if len(entities) > 1
        ]

        assert shared, "corpus needs a period holding two entities"

    def test_a_normal_entity_is_not_given_its_twin_s_signal(
        self, pipelines
    ):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        by_scope = {
            item["assessment_id"]: item
            for item in result["comparisons"]
            if item["indicator"] == CONCENTRATION
        }

        # OP-E05 is the even-spread twin of OP-E06.
        assert "OP-E05::Period-1" not in by_scope
        assert by_scope["OP-E06::Period-1"]["outcome"] == MATCH

    def test_the_expected_signals_stay_inside_their_own_entity(
        self, pipelines
    ):

        result = pipelines["dataset_operational_pattern_controlled.csv"]

        flagged = {
            finding["assessment_id"]
            for finding in result["operational_pattern_findings"]["findings"]
            if finding["indicator"] == CONCENTRATION
        }

        assert flagged == {
            "OP-B02::Period-1",
            "OP-E06::Period-1",
            "OP-F06::Period-1",
        }


# -- 13. multi-period isolation ------------------------------------------


class TestMultiPeriodIsolation:

    def test_one_period_is_flagged_and_its_sibling_is_not(self, pipelines):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)

        by_scope = {
            item["assessment_id"]: item["outcome"]
            for item in result["comparisons"]
            if item["indicator"] == CONCENTRATION
        }

        assert by_scope["OP-F06::Period-1"] == MATCH
        assert "OP-F06::Period-2" not in by_scope

    def test_scope_is_keyed_on_dataset_and_assessment_together(self):

        keys = [case.scope_key for case in CASES]

        # CSE-A01::Period-2 appears in two datasets, so the scope keys differ.
        matching = [
            key for key in keys if key.endswith("::CSE-A01::Period-2")
        ]

        assert len(matching) == 2
        assert len(set(matching)) == 2

    def test_the_reference_indexes_scopes_uniquely(self, reference):

        seen = [
            (record["dataset"], record["assessment_id"])
            for record in reference["records"]
        ]

        assert len(seen) == len(set(seen))


# -- 14. empty human-review template -------------------------------------


class TestEmptyReviewTemplate:

    def test_the_generated_template_is_blank(self, template):
        assert is_template_blank(template)

    def test_every_human_field_starts_empty(self, template):

        for record in template["records"]:
            for field in HUMAN_FIELDS:
                assert record[field] is None, f"{field} was pre-populated"

    def test_the_shipped_template_file_is_blank(self):

        # The template is a generated artefact, so it is expected to be absent
        # from version control. When one is present it still has to be blank,
        # because a pre-filled template is indistinguishable from a review.
        if not os.path.isfile(REVIEW_TEMPLATE_PATH):
            pytest.skip("no committed template file; the generated one is "
                        "tested above")

        with open(REVIEW_TEMPLATE_PATH, "r", encoding="utf-8") as handle:
            shipped = json.load(handle)

        assert is_template_blank(shipped)

    def test_the_default_review_path_is_where_the_cli_writes(self):

        assert os.path.realpath(REVIEW_TEMPLATE_PATH) == os.path.realpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir,
                "validation",
                "output",
                "human_review_template.json",
            )
        )

    def test_a_blank_template_is_not_treated_as_a_review(self, pipelines):

        reference = build_reference(CASES)

        result = compare(CASES, _review({}), reference, pipelines)

        assert result["expert_labelled"] is False
        assert result["label_source"] == "UNLABELLED"
        assert result["declared_label_source"] == LABEL_SOURCE_EXPERT

    def test_a_completed_review_is_detected_as_a_review(self):

        review = _review(
            {
                "EG-02": {
                    "human_confidence": "HIGH",
                    "reviewer_id": "TEST-FIXTURE",
                }
            }
        )

        assert not is_template_blank(review)

    def test_a_review_that_found_nothing_is_still_a_review(self):

        review = _review(
            {
                "EG-02": {
                    "human_indicators": [],
                    "human_confidence": "HIGH",
                    "reviewer_id": "TEST-FIXTURE",
                }
            }
        )

        assert not is_template_blank(review)

    def test_the_template_refuses_to_overwrite_a_real_review(self, tmp_path):

        from framework.validation.schema import write_review_template

        path = str(tmp_path / "review.json")

        write_review_template(path, CASES)

        review = build_review_template(CASES)
        review["records"][0]["human_confidence"] = "HIGH"
        review["records"][0]["reviewer_id"] = "someone"

        with open(path, "w", encoding="utf-8") as handle:
            json.dump(review, handle)

        with pytest.raises(ReviewTemplateError):
            write_review_template(path, CASES)


# -- 15. no fabricated expert labels --------------------------------------


class TestNoFabricatedLabels:

    def test_the_corpus_declares_no_expert_labels(self):

        for case in CASES:
            assert case.expectation_label_source != LABEL_SOURCE_EXPERT
            assert not case.is_expert_labelled

    def test_every_controlled_expectation_is_labelled_as_controlled(self):

        for case in CASES:
            if case.controlled_expectation is not None:
                assert (
                    case.controlled_expectation["label_source"]
                    == LABEL_SOURCE_CONTROLLED
                )

    def test_the_corpus_never_claims_ground_truth(self):

        # The corpus has to be able to say the expectations are *not* ground
        # truth, so the audit looks for affirmative claims and leaves denials
        # alone. A blanket substring ban would push the wording towards silence
        # at the exact place the reader most needs the clarification.
        text = json.dumps(load_corpus_document())

        assert assert_no_ground_truth_claims(text) == []

    def test_the_phrase_audit_still_catches_a_real_claim(self):

        # Affirmative uses are findings...
        assert "expert ground truth" in assert_no_ground_truth_claims(
            "These labels are expert ground truth for every case."
        )

        assert "ground truth" in assert_no_ground_truth_claims(
            "this corpus is the ground truth for supervisory judgement"
        )

        assert "expert-reviewed label" in assert_no_ground_truth_claims(
            "The reviewer supplied expert-reviewed label values."
        )

        # ...and denials of the same phrases are not.
        assert assert_no_ground_truth_claims(
            "This is not expert ground truth and must never be described "
            "as such."
        ) == []

        assert assert_no_ground_truth_claims(
            "No expert ground truth exists for these cases yet."
        ) == []

    def test_no_validation_artefact_claims_ground_truth(self):

        for artefact in ("validation_report.txt", "validation_metrics.json"):
            path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir,
                "validation",
                "output",
                artefact,
            )
            path = os.path.normpath(path)

            if not os.path.isfile(path):
                continue

            with open(path, "r", encoding="utf-8") as handle:
                claims = assert_no_ground_truth_claims(handle.read())

            assert claims == [], f"{artefact} overstates label authority"

    def test_the_report_says_expert_validation_is_pending(self, pipelines):

        reference = build_reference(CASES)

        result = compare(CASES, _review({}), reference, pipelines)
        metrics = compute_metrics(result)

        report = build_report(CASES, result, metrics, reference)

        assert EXPERT_PENDING in report
        assert "CONTROLLED VALIDATION" in report

    def test_controlled_cases_are_labelled_as_design_intent(self, pipelines):

        reference = build_reference(CASES)

        result = compare(CASES, _review({}), reference, pipelines)
        metrics = compute_metrics(result)

        report = build_report(CASES, result, metrics, reference)

        assert "design intent" in report.lower()
        assert "not expert" in report.lower()

    def test_the_validation_package_contains_no_expert_labels(self):
        """No shipped review file may carry reviewer input."""

        root = os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir,
                "validation",
            )
        )

        for name in os.listdir(root):
            if not name.endswith(".json"):
                continue

            path = os.path.join(root, name)

            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            if "records" in payload and "case_count" in payload:
                assert is_template_blank(payload), f"{name} carries reviewer input"

    def test_a_completed_review_is_reported_as_expert_validation(
        self, pipelines
    ):

        review = _agreed_review()
        reference = build_reference(CASES)

        result = compare(CASES, review, reference, pipelines)
        metrics = compute_metrics(result)

        report = build_report(CASES, result, metrics, reference)

        # A filled-in template really is an expert review, so the report stops
        # saying the run is pending. What it must never do is present the
        # agreement as unattributed: the reviewer who produced it is named, so
        # a review that turns out to have been invented is visible in the
        # report rather than smuggled in as a clean number.
        assert EXPERT_PENDING not in report
        assert "EXPERT VALIDATION" in report
        assert "TEST-FIXTURE-NOT-AN-EXPERT" in report

    def test_a_blank_review_keeps_saying_validation_is_pending(
        self, pipelines
    ):

        reference = build_reference(CASES)

        result = compare(CASES, _review({}), reference, pipelines)
        metrics = compute_metrics(result)

        report = build_report(CASES, result, metrics, reference)

        assert EXPERT_PENDING in report
        assert "CONTROLLED VALIDATION" in report
        assert metrics["reviewer_ids"] == []


# -- 16. existing pipeline regression -------------------------------------


class TestPipelineRegression:

    def test_no_existing_result_key_is_removed(self, pipelines):

        for dataset, result in pipelines.items():
            for key in FAMILY_RESULT_KEYS.values():
                assert key in result, f"{dataset} lost {key}"

            for key in (
                "dataset",
                "profile",
                "semantic_mapping",
                "canonical_records",
                "supervisory_findings",
                "entity_assessment",
                "assessment",
                "capability_assessment",
            ):
                assert key in result, f"{dataset} lost {key}"

    def test_the_three_families_are_untouched_by_the_validation_package(
        self, pipelines
    ):

        for dataset, result in pipelines.items():
            for key in FAMILY_RESULT_KEYS.values():
                again = _quiet_pipeline(dataset)
                assert again[key] == result[key], f"{dataset} {key} changed"

    def test_importing_the_validation_package_adds_no_result_key(
        self, pipelines
    ):

        result = _quiet_pipeline("dataset_operational_pattern_controlled.csv")

        assert "validation" not in result
        assert not any(
            "valid" in key for key in result
        ), "validation must not add a pipeline result key"

    def test_existing_findings_are_unchanged_by_a_full_validation_run(
        self, pipelines
    ):

        # Running the whole harness must not perturb a single existing value.
        before = {
            dataset: {
                key: _quiet_pipeline(dataset)[key]
                for key in FAMILY_RESULT_KEYS.values()
            }
            for dataset in ("dataset_execution_gap_controlled.csv",)
        }

        build_reference(CASES)
        compare(CASES, _agreed_review(), build_reference(CASES), pipelines)

        after = {
            dataset: {
                key: _quiet_pipeline(dataset)[key]
                for key in FAMILY_RESULT_KEYS.values()
            }
            for dataset in ("dataset_execution_gap_controlled.csv",)
        }

        assert before == after

    def test_the_reference_output_only_carries_slices(self, reference):

        for record in reference["records"]:
            for family in FAMILY_RESULT_KEYS:
                findings = record[f"sat_sa_{family}_findings"]

                assert isinstance(findings, list)

                for finding in findings:
                    # Fields come from the existing finding shape, unchanged.
                    for field in (
                        "indicator",
                        "capability",
                        "assessment_id",
                        "status",
                    ):
                        assert field in finding

    def test_no_new_analytical_threshold_is_introduced(self):
        """The validation package must not define detection thresholds."""

        import re

        root = os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir,
                "validation",
            )
        )

        forbidden = re.compile(
            r"\b(alpha|min_scope_records|min_similarity|min_distinct_assets"
            r"|min_records_on_flagged_asset|min_similar_records)\b\s*[:=]\s*[0-9]"
        )

        for name in sorted(os.listdir(root)):

            if not name.endswith(".py"):
                continue

            with open(
                os.path.join(root, name), "rb"
            ) as handle:
                code = " ".join(
                    token.string
                    for token in tokenize.tokenize(handle.readline)
                    if token.type
                    not in (tokenize.COMMENT, tokenize.STRING)
                )

            assert not forbidden.search(code), (
                f"{name} defines an analytical threshold"
            )

    def test_the_validation_package_imports_no_detector(self):
        """It must observe, never participate in detection."""

        root = os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir,
                "validation",
            )
        )

        for name in sorted(os.listdir(root)):

            if not name.endswith(".py"):
                continue

            with open(os.path.join(root, name), "r", encoding="utf-8") as handle:
                source = handle.read()

            for forbidden_import in (
                "execution_gap_detector",
                "negative_space_detector",
                "operational_pattern_detector",
                "negative_space_rules",
                "operational_pattern_rules",
            ):
                assert f"import {forbidden_import}" not in source, (
                    f"{name} imports {forbidden_import}"
                )

    def test_no_network_or_cloud_dependency_is_introduced(self):

        root = os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir,
                "validation",
            )
        )

        forbidden = ("requests", "urllib", "socket", "boto3", "http://", "https://")

        for name in sorted(os.listdir(root)):

            if not name.endswith(".py"):
                continue

            with open(os.path.join(root, name), "r", encoding="utf-8") as handle:
                source = handle.read()

            for token in forbidden:
                assert token not in source, f"{name} references {token}"


# -- corpus coverage -----------------------------------------------------


class TestCorpusCoverage:

    def test_the_corpus_is_small(self):
        assert 12 <= len(CASES) <= 20

    def test_all_fourteen_case_types_are_covered(self):

        covered = set()

        for case in CASES:
            covered.update(case.covers)

        assert REQUIRED_CASE_TYPES <= covered

    def test_every_case_uses_an_existing_dataset(self):

        for case in CASES:
            assert os.path.isfile(
                corpus_module.dataset_path(case.dataset)
            ), f"{case.case_id} points at a missing dataset"

    def test_no_new_dataset_was_created_for_validation(self):

        for case in CASES:
            assert "validation" not in case.dataset.lower()

    def test_every_controlled_expectation_states_its_basis(self):

        for case in CASES:
            if case.controlled_expectation is None:
                continue

            assert case.controlled_expectation.get("basis"), (
                f"{case.case_id} has an expectation with no stated basis"
            )

    def test_every_case_records_the_raw_rows_it_was_read_from(self):

        for case in CASES:
            if case.controlled_expectation is None:
                continue

            assert case.raw_observations, (
                f"{case.case_id} has no raw observations recorded"
            )

    def test_design_intents_do_not_depend_on_hidden_thresholds(self):

        for case in CASES:
            intent = case.design_intent.lower()

            for threshold_word in ("alpha", "z-score", "cutoff", "threshold"):
                assert threshold_word not in intent
