"""The peer benchmarking engine.

Reads the results the supervisory layers already produced, resolves a metric
per assessment scope, selects a peer cohort per target, and publishes the
comparison. Every peer statement in the output is recomputable from the peer
values printed beside it.

WHAT IS PUBLISHED, AND WHY ALL OF IT
====================================

For each benchmarked metric and each target scope:

  observed value, numerator, denominator   what was measured, over what
  peer baseline status and reason           whether the cohort can carry a claim
  peer min / Q1 / median / Q3 / max, IQR, MAD   the cohort the value sits in
  Tukey fences and any outlying peers       whether the cohort is trustworthy
  modified Z-score or NOT_COMPUTABLE       robust standardised deviation
  percentile and rank, or NULL_NOT_RANKABLE where the observed value is absent
  interpretation, backend-generated prose  the sentence a screen shows

Percentile is position, not risk. Only the metric's configured direction makes
it interpretable, and that direction is declared in configuration. The engine
never converts a percentile into a score, a grade or a finding.

A ZERO IS NOT AN ABSENCE
========================

A metric whose denominator is zero reports NOT_EVALUABLE with that reason. It
does not report a rate of zero, and the interface is told the difference so a
scope with no applicable population cannot be presented as the best scope in
its cohort.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.benchmark.cohort import (
    BenchmarkConfigError,
    PeerCohortResolver,
)
from framework.benchmark import metrics as metric_extraction
from framework.benchmark.robust_statistics import (
    COMPUTED,
    NOT_COMPUTABLE,
    modified_z_score,
    outlier_flags,
    peer_percentile,
    rank_of,
    summarise_peers,
)

DEFAULT_PEER_BENCHMARK_CONFIG = "framework/config/peer_benchmark.json"

BASELINE_UNAVAILABLE = "UNAVAILABLE"
BASELINE_LIMITED = "LIMITED"
BASELINE_ROBUST = "ROBUST"

NULL_NOT_RANKABLE = "NULL_NOT_RANKABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"

HIGHER_IS_ADVERSE = "higher_is_adverse"
HIGHER_IS_FAVOURABLE = "higher_is_favourable"

WITHIN_COHORT_SPREAD = "WITHIN_COHORT_SPREAD"
ABOVE_PEER_CENTRE = "ABOVE_PEER_CENTRE"
BELOW_PEER_CENTRE = "BELOW_PEER_CENTRE"
NOT_EVALUABLE = "NOT_EVALUABLE"


def _ordinal(value: int) -> str:
    """Render a whole number with its ordinal suffix: 1st, 2nd, 3rd, 4th, 71st."""
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")

    return f"{value}{suffix}"


def _scope_payloads(collection: Any) -> List[Mapping[str, Any]]:
    """Accept the assessment collection, its payload, or a sequence of scopes.

    The collection object is accepted because that is what the pipeline holds
    at the point it benchmarks; accepting it here keeps the caller's
    responsibility to serialise, and keeps this module the single place that
    knows the scope payload shape.
    """

    if hasattr(collection, "to_dict") and not isinstance(collection, Mapping):
        collection = collection.to_dict()

    if isinstance(collection, Mapping):
        return list(collection.get("scopes") or ())

    if isinstance(collection, Sequence):
        return [item for item in collection if isinstance(item, Mapping)]

    raise BenchmarkConfigError(
        "peer benchmarking requires the assessment collection or a sequence "
        "of scope payloads"
    )


def _as_layer(payload: Any, key: str) -> Dict[str, Any]:
    """Coerce a source layer result, tolerating a layer that produced nothing.

    A pipeline stage can legitimately be disabled or stubbed out. That must
    cost the caller its peer comparison for the affected metrics, stated as
    NOT_EVALUABLE with this reason, rather than raise and cost the caller the
    whole assessment.
    """

    if isinstance(payload, Mapping):
        return {"payload": payload, "reason": None}

    return {
        "payload": {},
        "reason": (
            f"the {key} layer produced no result for this run, so no value "
            "can be resolved from it"
        ),
    }


class MetricDefinition:
    """One declared benchmark metric."""

    def __init__(self, definition: Mapping[str, Any]) -> None:

        if "metric_id" not in definition:
            raise BenchmarkConfigError(
                "every benchmark metric must declare a 'metric_id'"
            )

        self.metric_id = str(definition["metric_id"])
        self.label = str(definition.get("label") or self.metric_id)
        self.source_result = str(definition.get("source_result") or "")
        self.direction = str(
            definition.get("direction") or HIGHER_IS_FAVOURABLE
        )

        if self.direction not in (HIGHER_IS_ADVERSE, HIGHER_IS_FAVOURABLE):
            raise BenchmarkConfigError(
                f"metric {self.metric_id!r} declares unknown direction "
                f"{self.direction!r}; expected one of "
                f"{(HIGHER_IS_ADVERSE, HIGHER_IS_FAVOURABLE)}"
            )

        self.measure_type = str(definition.get("measure_type") or "")
        self.scope_level = bool(definition.get("scope_level", True))
        self.indicator_category = definition.get("indicator_category")
        self.numerator_definition = str(definition.get("numerator_definition") or "")
        self.denominator_definition = str(
            definition.get("denominator_definition") or ""
        )
        self.metric_definition = list(definition.get("metric_definition") or ())
        self.source_concepts = tuple(
            str(concept) for concept in (definition.get("source_concepts") or ())
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "label": self.label,
            "source_result": self.source_result,
            "direction": self.direction,
            "measure_type": self.measure_type,
            "scope_level": self.scope_level,
            "indicator_category": self.indicator_category,
            "numerator_definition": self.numerator_definition,
            "denominator_definition": self.denominator_definition,
            "metric_definition": list(self.metric_definition),
            "source_concepts": list(self.source_concepts),
        }


class PeerBenchmarkEngine:
    """Produces the ``peer_benchmark`` result for one assessment collection."""

    def __init__(self, definition: Mapping[str, Any]) -> None:

        self.definition = dict(definition)

        policy = self.definition.get("baseline_policy") or {}

        self.min_peers_for_baseline = int(policy.get("min_peers_for_baseline", 3))
        self.robust_min_peers = int(policy.get("robust_min_peers", 8))
        self.precision = int(policy.get("rate_precision", 6))

        if self.min_peers_for_baseline < 1:
            raise BenchmarkConfigError(
                "baseline_policy.min_peers_for_baseline must be at least 1"
            )

        if self.robust_min_peers <= self.min_peers_for_baseline:
            raise BenchmarkConfigError(
                "baseline_policy.robust_min_peers must exceed "
                "min_peers_for_baseline, otherwise the ROBUST status could "
                "never be reached"
            )

        bands = self.definition.get("deviation_bands") or {}

        self.notable_at = float(bands.get("notable_at", 1.5))
        self.material_at = float(bands.get("material_at", 3.5))

        if self.notable_at >= self.material_at:
            raise BenchmarkConfigError(
                "deviation_bands.notable_at must be below material_at"
            )

        self.templates = dict(self.definition.get("interpretation_templates") or {})

        self.metrics = [
            MetricDefinition(item)
            for item in self.definition.get("metrics") or ()
        ]

        if not self.metrics:
            raise BenchmarkConfigError(
                "peer benchmarking requires at least one declared metric"
            )

        self.resolver = PeerCohortResolver.from_config(self.definition)

        self.schema_version = str(self.definition.get("schema_version") or "1.0")

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config_path(cls, path: str = DEFAULT_PEER_BENCHMARK_CONFIG) -> "PeerBenchmarkEngine":
        """Load the shipped configuration.

        A missing or unreadable file leaves the layer unavailable rather than
        failing the run: an assessment that loses its peer comparison is
        still an assessment, and the pipeline reports the layer's absence in
        the same way the anomaly layer reports a missing model.
        """

        import json

        if not os.path.exists(path):
            raise BenchmarkConfigError(f"benchmark configuration not found: {path}")

        with open(path, "r", encoding="utf-8") as handle:
            definition = json.load(handle)

        return cls(definition)

    # -- public API ---------------------------------------------------------

    def evaluate_collection(
        self,
        collection: Any,
        capability_assessment: Any,
        execution_gap_findings: Any,
        negative_space_findings: Any,
        operational_pattern_findings: Any,
        anomaly_findings: Any,
    ) -> Dict[str, Any]:
        """Benchmark every scope in the collection against its own cohort.

        ``collection`` accepts the assessment payload or a bare sequence of
        scope payloads. Scope payloads are normalised here rather than by the
        caller so that an unresolved entity or period is handled by the one
        layer that knows the resolution contract, and so that a caller cannot
        accidentally present an unresolved period as a comparable one.

        A source layer that produced no result at all is not an error: its
        metrics are reported NOT_EVALUABLE carrying that fact, so a run with a
        disabled layer loses its peer comparison for that metric rather than
        losing the assessment.
        """

        capability_layer = _as_layer(
            capability_assessment, "capability_assessment"
        )
        gap_layer = _as_layer(execution_gap_findings, "execution_gap_findings")
        negative_layer = _as_layer(
            negative_space_findings, "negative_space_findings"
        )
        pattern_layer = _as_layer(
            operational_pattern_findings, "operational_pattern_findings"
        )
        anomaly_layer = _as_layer(anomaly_findings, "anomaly_findings")

        capability_scopes = metric_extraction.index_by_assessment_id(
            capability_layer["payload"].get("scopes") or ()
        )
        gap_scopes = metric_extraction.index_by_assessment_id(
            gap_layer["payload"].get("scopes") or ()
        )
        negative_scopes = metric_extraction.index_by_assessment_id(
            negative_layer["payload"].get("scopes") or ()
        )
        pattern_scopes = metric_extraction.index_by_assessment_id(
            pattern_layer["payload"].get("scopes") or ()
        )

        unavailable = {
            "capability_assessment": capability_layer["reason"],
            "execution_gap_findings": gap_layer["reason"],
            "negative_space_findings": negative_layer["reason"],
            "operational_pattern_findings": pattern_layer["reason"],
        }

        candidates: List[Dict[str, Any]] = [
            self._candidate_from_scope(scope)
            for scope in _scope_payloads(collection)
        ]

        observed: Dict[str, Dict[str, Dict[str, Any]]] = {}

        for candidate in candidates:

            assessment_id = str(candidate["assessment_id"])

            capability_payload = capability_scopes.get(assessment_id, {})

            observed[assessment_id] = {
                "evidence_coverage": metric_extraction.capability_category_coverage(
                    capability_payload,
                    None,
                    self.precision,
                    unavailable["capability_assessment"],
                ),
                "escalation_coverage": metric_extraction.capability_category_coverage(
                    capability_payload,
                    "ESCALATION_GAP",
                    self.precision,
                    unavailable["capability_assessment"],
                ),
                "investigation_quality": metric_extraction.capability_category_coverage(
                    capability_payload,
                    "INVESTIGATION_QUALITY",
                    self.precision,
                    unavailable["capability_assessment"],
                ),
                "monitoring_visibility": metric_extraction.capability_category_coverage(
                    capability_payload,
                    "MONITORING_VISIBILITY_GAP",
                    self.precision,
                    unavailable["capability_assessment"],
                ),
                "execution_gap_incidence": metric_extraction.execution_gap_incidence(
                    gap_scopes.get(assessment_id, {}),
                    self.precision,
                    unavailable["execution_gap_findings"],
                ),
                "negative_space_incidence": metric_extraction.negative_space_incidence(
                    negative_scopes.get(assessment_id, {}),
                    self.precision,
                    unavailable["negative_space_findings"],
                ),
                "operational_pattern_incidence": metric_extraction.operational_pattern_incidence(
                    pattern_scopes.get(assessment_id, {}),
                    self.precision,
                    unavailable["operational_pattern_findings"],
                ),
            }

        scope_payloads: List[Dict[str, Any]] = []

        for candidate in sorted(
            candidates, key=lambda item: str(item["assessment_id"])
        ):

            assessment_id = str(candidate["assessment_id"])

            cohort = self.resolver.resolve(candidate, candidates)

            scope_payloads.append(
                self._benchmark_scope(
                    candidate=candidate,
                    cohort=cohort,
                    observed=observed[assessment_id],
                    peer_values=self._peer_values(
                        cohort["member_assessment_ids"], observed
                    ),
                    capability_payload=capability_scopes.get(assessment_id, {}),
                )
            )

        collection_metric = self._collection_metric(
            scope_payloads,
            anomaly_layer["payload"],
            [str(item["assessment_id"]) for item in candidates],
            anomaly_layer["reason"],
        )

        return {
            "schema_version": self.schema_version,
            "available": True,
            "unavailable_reason": None,
            "config_path": DEFAULT_PEER_BENCHMARK_CONFIG,
            "scope_count": len(scope_payloads),
            "baseline_policy": {
                "min_peers_for_baseline": self.min_peers_for_baseline,
                "robust_min_peers": self.robust_min_peers,
                "rate_precision": self.precision,
            },
            "deviation_bands": {
                "notable_at": self.notable_at,
                "material_at": self.material_at,
                "note": (
                    "descriptive bands over the absolute modified Z-score; "
                    "they select wording only and never create, suppress or "
                    "reweight a finding"
                ),
            },
            "cohort_hierarchy": self.resolver.describe_hierarchy(),
            "metric_catalogue": [
                metric.to_dict()
                for metric in self.metrics
                if metric.scope_level
            ],
            "scopes": scope_payloads,
            "collection_metrics": collection_metric,
            "limitations": list(self.definition.get("limitations") or ())
            + [
                "Peer comparison is only as sound as the cohort it is drawn "
                "from. Read the baseline status and the cohort membership "
                "before reading any deviation.",
                "A percentile describes where a scope sits among its peers. "
                "It is not a risk score, and no interface may present it as "
                "one.",
                "Deviation bands change wording only. They never create, "
                "suppress or reweight a finding, and they never alter an "
                "evidence state.",
            ],
        }

    # -- internals ----------------------------------------------------------

    def _scope_metric_ids(self) -> List[str]:
        """Declared metrics resolved per scope, in catalogue order."""

        return [
            metric.metric_id for metric in self.metrics if metric.scope_level
        ]

    def _candidate_from_scope(self, scope: Mapping[str, Any]) -> Dict[str, Any]:
        """Normalise an assessment scope payload into a cohort candidate.

        An unresolved entity or period yields ``None`` for the corresponding
        id, never the sentinel the scope payload carries. A cohort is built on
        evidenced identity and evidenced period only.
        """

        entity = scope.get("entity") or {}
        period = scope.get("period") or {}

        entity_available = bool(entity.get("available"))
        period_available = bool(period.get("available"))

        return {
            "assessment_id": scope.get("assessment_id"),
            "entity_id": (
                str(entity.get("id"))
                if entity_available and entity.get("id") is not None
                else None
            ),
            "entity_name": entity.get("name"),
            "entity_available": entity_available,
            "period_label": (
                str(period.get("label")) if period_available and period.get("label") else None
            ),
            "period_available": period_available,
            "record_count": scope.get("record_count"),
        }

    def _peer_values(
        self,
        member_ids: Sequence[str],
        observed: Mapping[str, Mapping[str, Dict[str, Any]]],
    ) -> Dict[str, List[float]]:
        """Peer rates per metric, excluding any member whose value is absent.

        A peer that did not report a metric contributes no value, not a zero.
        The count of contributing peers is published with the baseline, so a
        cohort of eight scopes in which only four reported the metric is
        visible as such.
        """

        values: Dict[str, List[float]] = {}

        for metric_id in self._scope_metric_ids():
            collected: List[float] = []

            for member_id in member_ids:
                member_metric = observed.get(member_id, {}).get(metric_id)

                if not member_metric:
                    continue

                rate = member_metric.get("rate")

                if rate is None:
                    continue

                collected.append(float(rate))

            values[metric_id] = sorted(collected)

        return values

    def _baseline_status(
        self, peer_count: int
    ) -> Dict[str, Any]:
        if peer_count < self.min_peers_for_baseline:
            return {
                "baseline_status": BASELINE_UNAVAILABLE,
                "baseline_reason": (
                    f"{peer_count} peer scope(s) reported this metric, below "
                    f"the configured minimum of "
                    f"{self.min_peers_for_baseline} for publishing a peer "
                    "baseline"
                ),
            }

        if peer_count < self.robust_min_peers:
            return {
                "baseline_status": BASELINE_LIMITED,
                "baseline_reason": (
                    f"{peer_count} peer scope(s) reported this metric, at or "
                    f"above the minimum of {self.min_peers_for_baseline} but "
                    f"below the {self.robust_min_peers} needed for a robust "
                    "baseline; read the quartiles and the fences before "
                    "relying on the median"
                ),
            }

        return {
            "baseline_status": BASELINE_ROBUST,
            "baseline_reason": (
                f"{peer_count} peer scope(s) reported this metric, at or above "
                f"the {self.robust_min_peers} needed for a robust baseline"
            ),
        }

    def _interpretation(
        self,
        definition: MetricDefinition,
        z_score: Optional[float],
        percentile: Optional[float],
        peer_count: int,
        scope_label: str,
        observed: Optional[float],
        peer_median: Optional[float],
    ) -> Optional[str]:
        if z_score is None or percentile is None or observed is None or peer_median is None:
            return None

        whole_percentile = int(round(percentile * 100))
        filled = {
            "scope_label": scope_label,
            "observed": observed,
            "peer_median": peer_median,
            "modified_z": f"{abs(z_score):.1f}",
            "peer_count": peer_count,
            "percentile": f"{percentile * 100:.0f}",
            # The templates name the percentile with its own ordinal suffix, so
            # 71 reads "71st" rather than "71th".
            "percentile_ordinal": _ordinal(whole_percentile),
        }

        if abs(z_score) < self.notable_at:
            key = "within_cohort_spread"
        elif definition.direction == HIGHER_IS_ADVERSE:
            key = (
                "higher_is_adverse_above"
                if z_score > 0
                else "higher_is_adverse_below"
            )
        else:
            key = (
                "higher_is_favourable_above"
                if z_score > 0
                else "higher_is_favourable_below"
            )

        template = self.templates.get(key)

        if not template:
            return None

        return " ".join(part.strip() for part in template if part.strip()).format(
            **filled
        )

    def _benchmark_scope(
        self,
        candidate: Mapping[str, Any],
        cohort: Mapping[str, Any],
        observed: Mapping[str, Dict[str, Any]],
        peer_values: Mapping[str, Sequence[float]],
        capability_payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        scope_label = str(candidate.get("entity_id") or "This scope")

        benchmarks: List[Dict[str, Any]] = []

        for definition in self.metrics:

            if not definition.scope_level:
                continue

            metric = observed.get(definition.metric_id)

            if metric is None:
                continue

            peers = list(peer_values.get(definition.metric_id) or ())

            baseline = self._baseline_status(len(peers))

            distribution = summarise_peers(peers)

            fences = outlier_flags(peers)

            z_score = modified_z_score(
                metric.get("rate"),
                distribution.get("median"),
                distribution.get("mad"),
            )

            percentile = (
                peer_percentile(metric["rate"], peers)
                if baseline["baseline_status"] != BASELINE_UNAVAILABLE
                else None
            )

            rank = (
                rank_of(metric["rate"], peers)
                if baseline["baseline_status"] != BASELINE_UNAVAILABLE
                else None
            )

            declared = list(definition.source_concepts)

            benchmarks.append(
                {
                    "metric_id": definition.metric_id,
                    "label": definition.label,
                    "direction": definition.direction,
                    "measure_type": definition.measure_type,
                    "metric_definition": list(definition.metric_definition),
                    "numerator_definition": definition.numerator_definition,
                    "denominator_definition": definition.denominator_definition,
                    "observed_value": metric.get("rate"),
                    "numerator": metric.get("numerator"),
                    "denominator": metric.get("denominator"),
                    "metric_status": metric.get("metric_status"),
                    "not_evaluable_reason": metric.get("not_evaluable_reason"),
                    "source_result": definition.source_result,
                    "source_concepts": metric_extraction.evidenced_concepts(
                        capability_payload, declared
                    ),
                    "unresolved_concepts": metric_extraction.unresolved_concepts(
                        capability_payload, declared
                    ),
                    "peer_count": len(peers),
                    "cohort_size": int(cohort.get("peer_count") or 0),
                    **baseline,
                    "peer_distribution": distribution,
                    "cohort_outliers": fences,
                    "modified_z_score": z_score,
                    "statistical_status": (
                        COMPUTED if z_score is not None else NOT_COMPUTABLE
                    ),
                    "statistical_not_computable_reason": (
                        None
                        if z_score is not None
                        else (
                            "the peer cohort has zero spread (MAD = 0), so a "
                            "standardised deviation is undefined; every peer "
                            "reported the same value"
                            if distribution.get("mad") == 0
                            else (
                                "the peer median and spread are not both "
                                "available, so no standardised deviation can "
                                "be computed"
                                if baseline["baseline_status"]
                                != BASELINE_UNAVAILABLE
                                else baseline["baseline_reason"]
                            )
                        )
                    ),
                    "deviation_band": (
                        NOT_EVALUABLE
                        if z_score is None
                        else (
                            "WITHIN_COHORT_SPREAD"
                            if abs(z_score) < self.notable_at
                            else (
                                "NOTABLE"
                                if abs(z_score) < self.material_at
                                else "MATERIAL"
                            )
                        )
                    ),
                    "percentile": percentile,
                    "percentile_status": (
                        NOT_APPLICABLE if percentile is None else "COMPUTED"
                    ),
                    "rank_of_observed": rank,
                    "rank_status": NOT_APPLICABLE if rank is None else "COMPUTED",
                    "interpretation": self._interpretation(
                        definition,
                        z_score,
                        percentile,
                        len(peers),
                        scope_label,
                        metric.get("rate"),
                        distribution.get("median"),
                    ),
                }
            )

        return {
            "assessment_id": candidate.get("assessment_id"),
            "entity_id": candidate.get("entity_id"),
            "entity_name": candidate.get("entity_name"),
            "entity_available": bool(candidate.get("entity_available")),
            "period_label": candidate.get("period_label"),
            "period_available": bool(candidate.get("period_available")),
            "record_count": self._record_count(candidate),
            "cohort": cohort,
            "benchmarks": benchmarks,
        }

    def _record_count(self, candidate: Mapping[str, Any]) -> int:
        value = candidate.get("record_count")

        return 0 if value is None else int(value)

    def _collection_metric(
        self,
        scope_payloads: Sequence[Mapping[str, Any]],
        anomaly_findings: Mapping[str, Any],
        assessment_ids: Sequence[str],
        unavailable_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """The collection-level anomaly incidence the catalogue declares.

        Scoped to this assessment's own scopes, so the rate cannot be diluted
        by scopes from another run.
        """

        anomalous, evaluated, not_evaluable, reason = (
            metric_extraction.anomaly_verdict_rate(
                anomaly_findings.get("scope_results") or (),
                assessment_ids,
                self.precision,
            )
        )

        if unavailable_reason is not None:
            reason = unavailable_reason

        payload = metric_extraction._metric(
            "anomaly_scope_verdict",
            anomalous if evaluated else None,
            evaluated if evaluated else None,
            self.precision,
            reason,
        )

        definition = next(
            (
                item
                for item in self.metrics
                if item.metric_id == "anomaly_scope_verdict"
            ),
            None,
        )

        return {
            **(
                definition.to_dict()
                if definition is not None
                else {"metric_id": "anomaly_scope_verdict"}
            ),
            "metric_scope": "collection",
            "observed_value": payload["rate"],
            "numerator": payload["numerator"],
            "denominator": payload["denominator"],
            "metric_status": payload["metric_status"],
            "not_evaluable_reason": payload["not_evaluable_reason"],
            "source_result": "anomaly_findings",
            "scope_count": len(scope_payloads),
            "evaluated_scope_count": evaluated,
            "not_evaluable_scope_count": not_evaluable,
            "note": (
                "This rate counts the anomaly layer's own verdicts across the "
                "scopes of this assessment. It is a property of this "
                "submission, not a comparison between submissions. Scopes the "
                "model declined to judge sit outside the denominator and are "
                "counted separately."
            ),
        }


def evaluate_collection_or_report_unavailable(
    engine: Optional[PeerBenchmarkEngine],
    **layers: Any,
) -> Dict[str, Any]:
    """Run the engine, or state plainly that the layer could not run.

    Every other layer in the pipeline degrades this way. Peer comparison is
    additive, so a configuration or import failure must not cost the caller an
    assessment; the reason travels with the result instead.
    """

    if engine is None:
        return {
            "schema_version": "1.0",
            "available": False,
            "unavailable_reason": (
                "the peer benchmarking layer could not be initialised, so no "
                "peer comparison is offered for this assessment"
            ),
            "scope_count": 0,
            "scopes": [],
            "collection_metrics": None,
            "metric_catalogue": [],
            "cohort_hierarchy": [],
        }

    try:
        return engine.evaluate_collection(**layers)
    except BenchmarkConfigError as error:
        return {
            "schema_version": "1.0",
            "available": False,
            "unavailable_reason": str(error),
            "scope_count": 0,
            "scopes": [],
            "collection_metrics": None,
            "metric_catalogue": [],
            "cohort_hierarchy": [],
        }