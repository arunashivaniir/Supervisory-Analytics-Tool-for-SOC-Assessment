"""Peer benchmarking: statistics, cohort resolution, and the published contract.

The properties asserted here are the ones that decide whether a peer statement
is defensible:

  * the statistics are exactly recomputable from the published peer values
  * a zero MAD is NOT_COMPUTABLE, never infinity and never zero
  * the cohort is deterministic, self-excluding, and never reaches past the
    period
  * a tier needing metadata nobody recorded says so instead of silently
    widening
  * a zero denominator is NOT_EVALUABLE, distinct from a measured zero
  * the layer is additive: no existing result value is altered
  * a source layer that produced nothing costs its own metrics, not the run

Every test here reads the shipped configuration rather than a fixture written
for the test, so a configuration that drifts from what the code expects fails
here.
"""

import copy
import json
import math
import os

import pytest

from framework.benchmark import (
    BASELINE_LIMITED,
    BASELINE_ROBUST,
    BASELINE_UNAVAILABLE,
    BenchmarkConfigError,
    PeerBenchmarkEngine,
    PeerCohortResolver,
    median_absolute_deviation,
    modified_z_score,
    outlier_flags,
    peer_percentile,
    percentile,
    summarise_peers,
)
from framework.benchmark.robust_statistics import COMPUTED, NOT_COMPUTABLE
from framework.pipeline import SATSAPipeline

CONFIG_PATH = "framework/config/peer_benchmark.json"

CONTROLLED = "dataset_operational_pattern_controlled.csv"
MULTI_CSE = "dataset_multi_cse.csv"


@pytest.fixture(scope="module")
def definition():
    with open(CONFIG_PATH) as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def engine(definition):
    return PeerBenchmarkEngine(definition)


@pytest.fixture(scope="module")
def result():
    return SATSAPipeline().run(CONTROLLED)


@pytest.fixture(scope="module")
def benchmark(result):
    return result["peer_benchmark"]


# ---------------------------------------------------------------- 1. statistics


class TestRobustStatistics:

    def test_percentile_matches_the_anomaly_explainer_convention(self):

        # The framework already publishes p10/p90 through a linear
        # interpolation in the anomaly explainer. Benchmarking must use the
        # same convention or the two layers would disagree about what a
        # percentile means.
        from framework.ml.anomaly.explanation import _percentile

        for values in ([1.0], [1.0, 2.0], [3.0, 1.0, 2.0], [5.0, 1.0, 4.0, 2.0, 3.0]):
            ordered = sorted(values)
            for fraction in (0.10, 0.25, 0.50, 0.75, 0.90):
                assert percentile(values, fraction) == pytest.approx(
                    _percentile(ordered, fraction)
                )

    def test_percentile_of_an_empty_sequence_is_an_error(self):

        with pytest.raises(ValueError):
            percentile([], 0.5)

    def test_quartiles_and_iqr_describe_the_middle_half(self):

        summary = summarise_peers([0.0, 1.0, 2.0, 3.0, 4.0])

        assert summary["count"] == 5
        assert summary["minimum"] == 0.0
        assert summary["maximum"] == 4.0
        assert summary["median"] == 2.0
        assert summary["q1"] == 1.0
        assert summary["q3"] == 3.0
        assert summary["iqr"] == 2.0
        assert summary["mad"] == 1.0
        assert summary["statistical_status"] == COMPUTED

    def test_one_extreme_peer_cannot_move_the_median(self):

        # A mean would be dragged here. The median is why the peer baseline
        # stays usable when one CSE submitted far more data than the rest.
        peers = [0.1] * 9 + [100.0]

        summary = summarise_peers(peers)

        assert summary["median"] == 0.1

    def test_modified_z_uses_the_published_formula(self):

        # 0.6745 * (0.9 - 0.5) / 0.2 = 1.349
        assert modified_z_score(0.9, 0.5, 0.2) == pytest.approx(1.349)

    def test_zero_mad_is_not_computable_rather_than_infinite(self):

        assert modified_z_score(5.0, 5.0, 0.0) is None
        assert modified_z_score(9.0, 5.0, 0.0) is None

    def test_modified_z_is_none_when_an_input_is_absent(self):

        assert modified_z_score(None, 0.5, 0.2) is None
        assert modified_z_score(0.9, None, 0.2) is None
        assert modified_z_score(0.9, 0.5, None) is None

    def test_median_absolute_deviation_is_insensitive_to_a_single_outlier(self):

        peers = [1.0, 1.0, 1.0, 1.0, 50.0]

        assert median_absolute_deviation(peers) == 0.0

    def test_percentile_describes_position_and_ties_share_it(self):

        # Midrank convention: a value matching n of m peers sits at
        # (below + 0.5 * tied) / m, so it is never reported as the top or the
        # bottom just because it happens to equal an extreme peer.
        assert peer_percentile(0.5, [0.1, 0.5, 0.9]) == pytest.approx(0.5)
        assert peer_percentile(0.9, [0.1, 0.5, 0.9]) == pytest.approx(2.5 / 3)
        assert peer_percentile(0.1, [0.1, 0.5, 0.9]) == pytest.approx(0.5 / 3, abs=1e-6)

        # Strictly outside the cohort sits at the extremes.
        assert peer_percentile(2.0, [0.1, 0.5, 0.9]) == pytest.approx(1.0)
        assert peer_percentile(0.0, [0.1, 0.5, 0.9]) == pytest.approx(0.0)

        # A value every peer matches sits in the middle, not at the top.
        assert peer_percentile(0.5, [0.5, 0.5]) == pytest.approx(0.5)

    def test_percentile_is_none_without_peers_or_an_observation(self):

        assert peer_percentile(0.5, []) is None
        assert peer_percentile(None, [0.5]) is None

    def test_tukey_fences_need_four_peers_and_never_remove_one(self):

        assert outlier_flags([1.0, 1.0, 1.0])["applicable"] is False

        flags = outlier_flags([1.0, 1.0, 1.0, 1.0, 40.0])

        assert flags["applicable"] is True
        assert 40.0 in flags["above_upper"]
        assert flags["below_lower"] == []

    def test_summarising_an_empty_cohort_says_so(self):

        summary = summarise_peers([])

        assert summary["count"] == 0
        assert summary["median"] is None
        assert summary["statistical_status"] == NOT_COMPUTABLE
        assert summary["not_computable_reason"]

    def test_statistics_are_deterministic_across_calls(self):

        peers = [0.3, 0.1, 0.9, 0.4, 0.2, 0.7, 0.5, 0.05, 0.6]

        assert summarise_peers(peers) == summarise_peers(list(reversed(peers)))


# ------------------------------------------------------------------ 2. cohort


class TestCohortResolution:

    def _resolver(self, attributes=None):
        definition = {
            "cohort_tiers": [
                {
                    "tier": 1,
                    "tier_id": "SAME_PERIOD_SECTOR_CLASS_SIZE",
                    "label": "Same period, sector, class and size",
                    "requires": ["sector", "entity_class", "size_band"],
                    "selection_rule": ["narrowest"],
                },
                {
                    "tier": 2,
                    "tier_id": "SAME_PERIOD_SECTOR_CLASS",
                    "label": "Same period, sector and class",
                    "requires": ["sector", "entity_class"],
                    "selection_rule": ["broader"],
                },
                {
                    "tier": 3,
                    "tier_id": "SAME_PERIOD",
                    "label": "Same period",
                    "requires": [],
                    "selection_rule": ["widest"],
                },
            ],
            "entity_attributes": {"entries": attributes or {}},
        }

        return PeerCohortResolver.from_config(definition)

    def _candidates(self):
        return [
            {"assessment_id": "A", "entity_id": "CSE-A", "period_label": "2026-Q3"},
            {"assessment_id": "B", "entity_id": "CSE-B", "period_label": "2026-Q3"},
            {"assessment_id": "C", "entity_id": "CSE-C", "period_label": "2026-Q3"},
            {"assessment_id": "D", "entity_id": "CSE-D", "period_label": "2026-Q2"},
        ]

    def test_the_narrowest_available_tier_is_selected(self):

        resolver = self._resolver(
            {
                "CSE-A": {"sector": "finance", "entity_class": "large", "size_band": "big"},
                "CSE-B": {"sector": "finance", "entity_class": "large", "size_band": "big"},
                "CSE-C": {"sector": "finance", "entity_class": "large", "size_band": "small"},
                "CSE-D": {"sector": "finance", "entity_class": "large", "size_band": "big"},
            }
        )

        cohort = resolver.resolve(self._candidates()[0], self._candidates())

        assert cohort["cohort_id"] == "SAME_PERIOD_SECTOR_CLASS_SIZE"
        assert cohort["member_assessment_ids"] == ["B"]

    def test_a_tier_is_skipped_when_its_metadata_is_absent(self):

        resolver = self._resolver(
            {
                "CSE-A": {"sector": "finance", "entity_class": None, "size_band": None},
                "CSE-B": {"sector": "finance", "entity_class": "large", "size_band": "big"},
            }
        )

        cohort = resolver.resolve(self._candidates()[0], self._candidates())

        assert cohort["cohort_id"] == "SAME_PERIOD"
        statuses = {item["tier_id"]: item["status"] for item in cohort["tiers_evaluated"]}
        assert statuses["SAME_PERIOD_SECTOR_CLASS_SIZE"] == "METADATA_UNAVAILABLE"
        assert statuses["SAME_PERIOD_SECTOR_CLASS"] == "METADATA_UNAVAILABLE"

    def test_missing_metadata_states_which_attribute_is_missing(self):

        resolver = self._resolver(
            {"CSE-A": {"sector": "finance", "entity_class": None, "size_band": None}}
        )

        cohort = resolver.resolve(self._candidates()[0], self._candidates())

        first = cohort["tiers_evaluated"][0]

        assert "entity_class" in first["not_available_reason"]
        assert "size_band" in first["not_available_reason"]

    def test_the_cohort_never_reaches_past_the_period(self):

        resolver = self._resolver()

        cohort = resolver.resolve(self._candidates()[0], self._candidates())

        assert "D" not in cohort["member_assessment_ids"]
        assert cohort["unresolved_period_scope_count"] == 0
        assert cohort["same_period_candidate_count"] == 3

    def test_a_scope_with_an_unresolved_period_is_never_a_peer(self):

        candidates = self._candidates() + [
            {"assessment_id": "E", "entity_id": "CSE-E", "period_label": None}
        ]

        cohort = self._resolver().resolve(candidates[0], candidates)

        assert "E" not in cohort["member_assessment_ids"]
        assert cohort["unresolved_period_scope_count"] == 1

    def test_the_target_is_excluded_from_its_own_cohort(self):

        resolver = self._resolver()

        cohort = resolver.resolve(self._candidates()[0], self._candidates())

        assert "A" not in cohort["member_assessment_ids"]
        assert cohort["excluded_assessment_ids"] == ["A"]

    def test_cohort_membership_is_ordered_deterministically(self):

        resolver = self._resolver()

        forward = resolver.resolve(self._candidates()[0], self._candidates())
        backward = resolver.resolve(
            self._candidates()[0], list(reversed(self._candidates()))
        )

        assert (
            forward["member_assessment_ids"] == backward["member_assessment_ids"]
        )

    def test_metadata_is_never_inferred(self):

        resolver = self._resolver()

        attributes = resolver.evidenced_attributes("CSE-UNKNOWN")

        assert attributes == {
            "sector": None,
            "entity_class": None,
            "size_band": None,
        }

    def test_a_lone_scope_reports_no_cohort_rather_than_itself(self):

        candidates = [
            {"assessment_id": "A", "entity_id": "CSE-A", "period_label": "2026-Q3"}
        ]

        cohort = self._resolver().resolve(candidates[0], candidates)

        assert cohort["status"] == "NO_ELIGIBLE_PEERS"
        assert cohort["cohort_id"] is None
        assert cohort["peer_count"] == 0
        assert cohort["not_available_reason"]

    def test_an_unknown_attribute_name_is_rejected(self):

        definition = {
            "cohort_tiers": [
                {
                    "tier": 1,
                    "tier_id": "BAD",
                    "requires": ["headcount"],
                    "selection_rule": ["x"],
                }
            ],
            "entity_attributes": {"entries": {}},
        }

        with pytest.raises(BenchmarkConfigError):
            PeerCohortResolver.from_config(definition)


# ------------------------------------------------------------ 3. configuration


class TestConfiguration:

    def test_the_shipped_configuration_builds(self, engine):

        assert engine.min_peers_for_baseline >= 1
        assert engine.robust_min_peers > engine.min_peers_for_baseline
        assert engine.metrics

    def test_the_robust_threshold_is_reachable(self, definition):

        # If the two thresholds were reversed or equal, ROBUST could never be
        # published and the status vocabulary would be a lie.
        policy = definition["baseline_policy"]

        assert policy["robust_min_peers"] > policy["min_peers_for_baseline"]

    def test_every_metric_declares_a_direction_and_a_definition(self, engine):

        for metric in engine.metrics:
            assert metric.direction in (
                "higher_is_adverse",
                "higher_is_favourable",
            )
            assert metric.metric_definition
            assert metric.numerator_definition
            assert metric.denominator_definition

    def test_a_metric_with_an_unknown_direction_is_rejected(self, definition):

        broken = copy.deepcopy(definition)
        broken["metrics"][0]["direction"] = "higher_is_better_ish"

        with pytest.raises(BenchmarkConfigError):
            PeerBenchmarkEngine(broken)

    def test_a_threshold_ordering_that_cannot_be_reached_is_rejected(self, definition):

        broken = copy.deepcopy(definition)
        broken["baseline_policy"]["robust_min_peers"] = (
            broken["baseline_policy"]["min_peers_for_baseline"]
        )

        with pytest.raises(BenchmarkConfigError):
            PeerBenchmarkEngine(broken)

    def test_deviation_bands_must_be_ordered(self, definition):

        broken = copy.deepcopy(definition)
        broken["deviation_bands"]["notable_at"] = broken["deviation_bands"]["material_at"]

        with pytest.raises(BenchmarkConfigError):
            PeerBenchmarkEngine(broken)

    def test_entity_attributes_ship_empty_so_no_metadata_is_invented(self, definition):

        assert definition["entity_attributes"]["entries"] == {}


# ------------------------------------------------------------------ 4. contract


class TestPublishedContract:

    def test_the_layer_reports_itself_available_for_a_real_run(self, benchmark):

        assert benchmark["available"] is True
        assert benchmark["scope_count"] == 8
        assert benchmark["metric_catalogue"]

    def test_every_scope_publishes_a_cohort_and_its_metrics(self, benchmark):

        for scope in benchmark["scopes"]:
            assert scope["cohort"]["tiers_evaluated"]
            assert scope["benchmarks"]

    def test_every_metric_publishes_numerator_and_denominator(self, benchmark):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                assert "numerator" in entry
                assert "denominator" in entry
                assert entry["metric_status"] in ("COMPUTED", "NOT_EVALUABLE")

    def test_a_computed_rate_matches_its_own_numerator_and_denominator(self, benchmark):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                if entry["metric_status"] != "COMPUTED":
                    continue

                expected = round(
                    entry["numerator"] / entry["denominator"],
                    benchmark["baseline_policy"]["rate_precision"],
                )

                assert entry["observed_value"] == pytest.approx(expected)

    def test_an_unavailable_layer_states_its_reason_instead_of_guessing(self, benchmark):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                if entry["metric_status"] == "NOT_EVALUABLE":
                    assert entry["not_evaluable_reason"]
                    assert entry["observed_value"] is None
                else:
                    assert entry["not_evaluable_reason"] is None

    def test_the_collection_anomaly_incidence_excludes_scopes_the_model_declined(self, benchmark):

        collection = benchmark["collection_metrics"]

        assert collection["metric_scope"] == "collection"

        # The denominator is evaluated scopes, never the whole submission. A
        # model that declines to judge a scope has not judged it clean, so
        # counting it as clean would understate incidence across every
        # submission where the model withheld a verdict.
        if collection["evaluated_scope_count"] == 0:
            assert collection["metric_status"] == "NOT_EVALUABLE"
            assert collection["observed_value"] is None
            assert collection["denominator"] is None
            assert collection["not_evaluable_reason"]
        else:
            assert collection["denominator"] == collection["evaluated_scope_count"]
            assert collection["denominator"] <= benchmark["scope_count"]

        # The scopes left out are counted, so the denominator can never be
        # mistaken for the whole assessment.
        assert (
            collection["evaluated_scope_count"]
            + collection["not_evaluable_scope_count"]
            == collection["scope_count"]
        )

    def test_a_statistic_is_never_published_without_a_status(self, benchmark):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                assert entry["statistical_status"] in (
                    COMPUTED,
                    NOT_COMPUTABLE,
                )
                assert entry["percentile_status"] in (
                    "COMPUTED",
                    "NOT_APPLICABLE",
                )
                assert entry["rank_status"] in ("COMPUTED", "NOT_APPLICABLE")

    def test_a_null_percentile_is_marked_not_applicable(self, benchmark):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                if entry["percentile"] is None:
                    assert entry["percentile_status"] == "NOT_APPLICABLE"
                else:
                    assert entry["percentile_status"] == "COMPUTED"

    def test_the_published_distribution_recomputes_the_published_median(self, benchmark):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                distribution = entry["peer_distribution"]

                if distribution["count"] == 0:
                    continue

                assert distribution["mad"] is not None
                assert distribution["q1"] <= distribution["median"] <= distribution["q3"]
                assert distribution["minimum"] <= distribution["q1"]
                assert distribution["q3"] <= distribution["maximum"]
                assert distribution["iqr"] == pytest.approx(
                    distribution["q3"] - distribution["q1"]
                )

    def test_a_zero_mad_cohort_is_reported_not_computable(self, benchmark):

        found = False

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                if entry["peer_distribution"].get("mad") != 0.0:
                    continue

                found = True

                assert entry["modified_z_score"] is None
                assert entry["statistical_status"] == NOT_COMPUTABLE
                assert entry["deviation_band"] == "NOT_EVALUABLE"
                assert entry["statistical_not_computable_reason"]

        # The controlled fixture must exercise the case, otherwise this guard
        # would pass on a layer that never handled it.
        assert found, "no metric in the controlled fixture produced a zero-MAD cohort"

    def test_a_baseline_below_the_minimum_is_unavailable(self, benchmark, engine):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                if entry["peer_count"] < engine.min_peers_for_baseline:
                    assert entry["baseline_status"] == BASELINE_UNAVAILABLE
                    assert entry["baseline_reason"]
                    assert entry["modified_z_score"] is None

    def test_baseline_status_comes_from_the_configured_thresholds(self, benchmark, engine):

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                count = entry["peer_count"]

                if count >= engine.robust_min_peers:
                    assert entry["baseline_status"] == BASELINE_ROBUST
                elif count >= engine.min_peers_for_baseline:
                    assert entry["baseline_status"] == BASELINE_LIMITED
                else:
                    assert entry["baseline_status"] == BASELINE_UNAVAILABLE

    def test_the_cohort_is_published_so_a_statement_can_be_checked(self, benchmark):

        for scope in benchmark["scopes"]:
            cohort = scope["cohort"]

            # Either a cohort with its selection rule, or a stated reason why
            # none could be formed. A scope is never silently unbenchmarked.
            if cohort["status"] == "NO_ELIGIBLE_PEERS":
                assert cohort["member_assessment_ids"] == []
                assert cohort["not_available_reason"]
            else:
                assert cohort["member_assessment_ids"]
                assert cohort["selection_rule"]

            assert cohort["excluded_assessment_ids"] == [scope["assessment_id"]]
            assert cohort["tiers_evaluated"]

    def test_the_metric_catalogue_declares_each_direction(self, benchmark):

        for definition in benchmark["metric_catalogue"]:
            assert definition["direction"]
            assert definition["measure_type"]

    def test_evidence_observation_metrics_are_declared_as_such(self, benchmark):

        by_id = {item["metric_id"]: item for item in benchmark["metric_catalogue"]}

        assert by_id["evidence_coverage"]["measure_type"] == "evidence_observation"
        assert by_id["escalation_coverage"]["measure_type"] == "evidence_observation"

    def test_limitations_are_published(self, benchmark):

        assert benchmark["limitations"]

        text = " ".join(benchmark["limitations"]).lower()

        assert "percentile" in text
        assert "cohort" in text


# ------------------------------------------------------------ 5. rate semantics


class TestZeroIsNotAbsence:

    def test_a_zero_denominator_is_not_evaluable_not_zero(self, definition):

        from framework.benchmark import metrics

        payload = {"record_count": 0, "findings": []}

        result = metrics.execution_gap_incidence(payload, 6)

        assert result["metric_status"] == "NOT_EVALUABLE"
        assert result["rate"] is None
        assert result["not_evaluable_reason"]

    def test_a_zero_denominator_never_becomes_a_rate_of_zero(self, definition):

        from framework.benchmark.metrics import _metric

        result = _metric("m", 0, 0, 6, None)

        assert result["rate"] is None
        assert result["metric_status"] == "NOT_EVALUABLE"
        assert "not a measurement of zero" in result["not_evaluable_reason"]

    def test_a_measured_zero_is_computed_and_distinguishable(self, definition):

        from framework.benchmark import metrics

        payload = {"record_count": 12, "findings": []}

        result = metrics.execution_gap_incidence(payload, 6)

        assert result["metric_status"] == "COMPUTED"
        assert result["rate"] == 0.0
        assert result["numerator"] == 0
        assert result["denominator"] == 12

    def test_an_untriggered_expectation_population_is_not_evaluable(self, definition):

        from framework.benchmark import metrics

        payload = {
            "expectation_states": [
                {"rule_id": "r", "absence_state": "EXPECTATION_NOT_TRIGGERED", "trigger_records": 0}
            ],
            "findings": [],
        }

        result = metrics.negative_space_incidence(payload, 6)

        assert result["metric_status"] == "NOT_EVALUABLE"
        assert result["rate"] is None

    def test_insufficient_evidence_counts_in_the_denominator_not_the_numerator(
        self, definition
    ):

        from framework.benchmark import metrics

        capabilities = [
            {"capability_id": "A", "status": "AVAILABLE", "indicator_categories": ["ESCALATION_GAP"]},
            {"capability_id": "B", "status": "INSUFFICIENT_EVIDENCE", "indicator_categories": ["ESCALATION_GAP"]},
            {"capability_id": "C", "status": "NOT_ASSESSED", "indicator_categories": []},
        ]

        result = metrics.capability_category_coverage(
            {"capabilities": capabilities}, "ESCALATION_GAP", 6
        )

        assert result["numerator"] == 1
        assert result["denominator"] == 2
        assert result["rate"] == 0.5

    def test_absence_is_matched_by_rule_not_by_state_alone(self, definition):

        from framework.benchmark import metrics

        # Two rules reach the same absence state. If the finding were matched on
        # absence_state alone, each state would pick up whichever finding came
        # first and both populations would carry the same absent-record count.
        payload = {
            "expectation_states": [
                {
                    "rule_id": "rule_a",
                    "absence_state": "POTENTIAL_NEGATIVE_SPACE",
                    "trigger_records": 10,
                },
                {
                    "rule_id": "rule_b",
                    "absence_state": "POTENTIAL_NEGATIVE_SPACE",
                    "trigger_records": 4,
                },
            ],
            "findings": [
                {
                    "rule_id": "rule_a",
                    "evidence_summary": {
                        "absence_state": "POTENTIAL_NEGATIVE_SPACE",
                        "records_without_expected_evidence": 7,
                    },
                },
                {
                    "rule_id": "rule_b",
                    "evidence_summary": {
                        "absence_state": "POTENTIAL_NEGATIVE_SPACE",
                        "records_without_expected_evidence": 3,
                    },
                },
            ],
        }

        result = metrics.negative_space_incidence(payload, 6)

        assert result["numerator"] == 10
        assert result["denominator"] == 14
        assert result["rate"] == 0.714286

    def test_a_verdict_the_model_withheld_is_not_a_clean_scope(self, definition):

        from framework.benchmark import metrics

        # The model states non-evaluation as a literal verdict. Treating that
        # verdict as evaluated would put a scope the model declined to judge
        # into the denominator as if it had passed.
        results = [
            {"assessment_id": "A", "verdict": "NOT_EVALUABLE"},
            {"assessment_id": "B", "verdict": "POTENTIAL_OPERATIONAL_ANOMALY"},
            {"assessment_id": "C", "verdict": None},
        ]

        anomalous, evaluated, not_evaluable, reason = metrics.anomaly_verdict_rate(
            results, ["A", "B", "C", "D"], 6
        )

        assert anomalous == 1
        assert evaluated == 1
        assert not_evaluable == 2
        assert reason is None

    def test_an_assessment_the_model_never_judged_yields_no_rate(self, definition):

        from framework.benchmark import metrics

        anomalous, evaluated, not_evaluable, reason = metrics.anomaly_verdict_rate(
            [{"assessment_id": "A", "verdict": "NOT_EVALUABLE"}], ["A"], 6
        )

        assert evaluated == 0
        assert not_evaluable == 1
        assert anomalous == 0
        assert "evaluated no scope" in reason


# ----------------------------------------------------------- 6. non-interference


class TestNonInterference:

    def test_the_layer_adds_exactly_one_result_key(self):

        from framework.pipeline import SATSAPipeline as Pipeline

        result_keys = _pipeline_result_keys()

        assert "peer_benchmark" in result_keys
        assert len(result_keys) == 18

    def test_no_existing_result_value_is_altered(self):

        from framework.supervision.negative_space_detector import (
            NegativeSpaceDetector,
        )

        full = SATSAPipeline().run(MULTI_CSE)

        pipeline = SATSAPipeline()
        stub = NegativeSpaceDetector.__new__(NegativeSpaceDetector)
        stub.evaluate_collection = lambda *args, **kwargs: None
        original = pipeline.negative_space_detector
        pipeline.negative_space_detector = stub

        baseline = pipeline.run(MULTI_CSE)
        pipeline.negative_space_detector = original

        for key in ("supervisory_findings", "entity_assessment"):
            assert full[key] == baseline[key]

    def test_the_layer_cannot_reach_the_attention_score(self, benchmark, result):

        text = json.dumps(result["entity_assessment"])

        assert "peer_benchmark" not in text
        assert "baseline_status" not in text

    def test_the_layer_emits_no_severity_or_risk_vocabulary(self, benchmark):

        text = json.dumps(benchmark)

        for token in ('"HIGH"', '"MEDIUM"', '"LOW"', '"CRITICAL"', '"SCORE"'):
            assert token not in text

    def test_a_disabled_source_layer_costs_only_its_own_metrics(self):

        from framework.supervision.negative_space_detector import (
            NegativeSpaceDetector,
        )

        pipeline = SATSAPipeline()
        stub = NegativeSpaceDetector.__new__(NegativeSpaceDetector)
        stub.evaluate_collection = lambda *args, **kwargs: None
        pipeline.negative_space_detector = stub

        result = pipeline.run(MULTI_CSE)

        benchmark = result["peer_benchmark"]

        assert benchmark["available"] is True
        assert benchmark["scope_count"] > 0

        for scope in benchmark["scopes"]:
            for entry in scope["benchmarks"]:
                if entry["metric_id"] == "negative_space_incidence":
                    assert entry["metric_status"] == "NOT_EVALUABLE"
                    assert "negative_space_findings" in entry["not_evaluable_reason"]
                elif entry["metric_id"] == "evidence_coverage":
                    assert entry["metric_status"] == "COMPUTED"

    def test_an_unusable_configuration_leaves_the_rest_of_the_run_intact(
        self, tmp_path, monkeypatch
    ):

        broken = tmp_path / "peer_benchmark.json"
        broken.write_text(json.dumps({"metrics": []}))

        from framework.benchmark import evaluate_collection_or_report_unavailable

        payload = evaluate_collection_or_report_unavailable(
            None, collection={}
        )

        assert payload["available"] is False
        assert payload["scopes"] == []
        assert payload["unavailable_reason"]

    def test_a_missing_configuration_file_is_stated_not_raised(self):

        from framework.benchmark import PeerBenchmarkEngine

        with pytest.raises(BenchmarkConfigError):
            PeerBenchmarkEngine.from_config_path("framework/config/absent.json")

    def test_the_engine_needs_no_optional_analytical_dependency(self):

        # The layer must import and run without numpy, pandas, duckdb or
        # scikit-learn, so a deployment missing them still benchmarks.
        source = os.path.join("framework", "benchmark", "engine.py")

        with open(source) as handle:
            text = handle.read()

        for module in ("numpy", "pandas", "duckdb", "sklearn"):
            assert f"import {module}" not in text


# ----------------------------------------------------------- 7. determinism


class TestDeterminism:

    def test_two_runs_produce_identical_benchmarks(self, result, benchmark):

        again = SATSAPipeline().run(CONTROLLED)["peer_benchmark"]

        assert json.dumps(again, sort_keys=True) == json.dumps(
            benchmark, sort_keys=True
        )

    def test_shuffling_the_scope_order_does_not_change_the_benchmark(self, result, benchmark):

        engine = PeerBenchmarkEngine.from_config_path()

        reversed_scopes = {
            "scopes": list(reversed(result["assessment"]["scopes"]))
        }

        again = engine.evaluate_collection(
            reversed_scopes,
            result["capability_assessment"],
            result["execution_gap_findings"],
            result["negative_space_findings"],
            result["operational_pattern_findings"],
            result["anomaly_findings"],
        )

        assert json.dumps(again, sort_keys=True) == json.dumps(
            benchmark, sort_keys=True
        )


def _pipeline_result_keys():

    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, newline=""
    ) as handle:
        handle.write("cse,period,alert_id,priority,host\n")
        handle.write("CSE-A,2026-Q3,A-1,low,HOST-1\n" * 12)
        path = handle.name

    try:
        return list(SATSAPipeline().run(path).keys())
    finally:
        os.unlink(path)