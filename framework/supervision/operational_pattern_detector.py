"""Scope-level operational pattern analysis.

What this layer looks for
-------------------------
The shape of operational activity inside one assessment scope: how records are
distributed across the assets a scope touches, and how similar the submitted
investigation evidence is to other submitted investigation evidence. A count
dashboard shows how *many* alerts there are. This shows whether their
distribution or their wording has a shape worth a supervisor's attention.

It is deliberately not
----------------------
**Not an anomaly-detection framework.** The only statistics used are an exact
binomial tail and token-set overlap, both computed in this file with no model
file, no training step and no dependency. The one place a statistical model
would belong -- the orphaned Isolation Forest in ``data/generated/`` -- is
recorded as an unavailable pattern with its reason, because its 16-feature
vector does not correspond to any canonical concept and scikit-learn is not
importable from the SAT-SA runtime.

**Not a risk or severity assessment.** No finding carries a score, a severity
or a priority, and nothing here is routed into the attention scorer.

**Not a judgement about any individual record.** Both patterns are statements
about a distribution across a population. A single terse note and a single
busy asset are unremarkable; the pattern only appears when the population as a
whole has a shape.

Why the concentration test needs no cut-point
---------------------------------------------
"More than 10 alerts on one asset" is meaningless without knowing how many
alerts and how many assets the scope has: 12 of 20 records on one asset is
routine, 12 of 400 is not. So instead of a threshold this asks whether the
observed concentration could have arisen by chance, treating the count on the
busiest asset as a binomial variable under uniform random allocation. The
decision boundary then comes from the test, and ``alpha`` is a statistical
significance level rather than a supervisory policy. The exact tail is
computed with integer combinatorics, so there is no floating-point
accumulation and no dependency.

Small samples
-------------
Every method declares its minimum observations in
``framework/config/operational_pattern_rules.json``, and this module refuses to
evaluate below that floor. Three, four or five records return
``NOT_EVALUABLE`` with an explanation instead of a number that would look
precise and mean nothing.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from framework.ml.anomaly.minhash_lsh import find_connected_components_minhash
from framework.supervision.execution_gap_detector import has_evidence
from framework.supervision.text_similarity import _jaccard, _tokenise
from framework.supervisory.rules.rule_engine import normalise_value
from framework.supervisory.rules.operational_pattern_rules import (
    EVIDENCE_NOT_PRESENT,
    NO_PATTERN_DETECTED,
    NOT_EVALUABLE,
    POTENTIAL_OPERATIONAL_ANOMALY,
    OperationalPattern,
    OperationalPatternCatalogue,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class OperationalPatternDetector:
    """Detects operational shape within a single assessment scope."""

    def __init__(
        self,
        catalogue: Optional[OperationalPatternCatalogue] = None,
    ) -> None:

        self.catalogue = catalogue or OperationalPatternCatalogue()

    # -- public API ---------------------------------------------------------

    def evaluate_scope(
        self,
        scope,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Evaluate every configured pattern over one scope's population."""

        findings: List[Dict[str, Any]] = []
        states: List[Dict[str, Any]] = []

        for pattern in self.catalogue.patterns:

            evaluation = self.evaluate_pattern(pattern, concept_values)

            states.append(evaluation["state_record"])

            if evaluation["state"] == POTENTIAL_OPERATIONAL_ANOMALY:
                findings.append(
                    self._build_finding(pattern, evaluation, scope)
                )

        counts: Dict[str, int] = {}

        for state in states:
            counts[state["pattern_status"]] = (
                counts.get(state["pattern_status"], 0) + 1
            )

        return {
            "assessment_id": scope.assessment_id,
            "entity": scope.entity.to_dict(),
            "period": scope.period.to_dict(),
            "record_count": scope.record_count,
            "findings": findings,
            "pattern_status_counts": counts,
            "pattern_states": states,
        }

    def evaluate_collection(
        self,
        collection,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
        capability_evaluator=None,
    ) -> Dict[str, Any]:
        """Evaluate every assessment scope independently.

        Scopes are never pooled. An operational shape that is unusual in one
        CSE or period can be entirely routine in another, so a cross-scope
        comparison would manufacture signals out of differences between
        organisations rather than out of anything unusual.
        """

        from framework.capability.capability_evaluator import (
            CapabilityEvaluator,
        )

        evaluator = capability_evaluator or CapabilityEvaluator()

        scope_payloads: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []

        for scope in collection:

            records = scope.records

            evidence_index = evaluator.build_evidence_index(
                records, profile, semantic_results
            )

            concept_values = evidence_index.concept_values(records)

            payload = self.evaluate_scope(scope, concept_values)

            scope_payloads.append(payload)
            findings.extend(payload["findings"])

        counts: Dict[str, int] = {}

        for payload in scope_payloads:
            for state, count in payload["pattern_status_counts"].items():
                counts[state] = counts.get(state, 0) + count

        return {
            "pattern_ids": [
                pattern.pattern_id for pattern in self.catalogue.patterns
            ],
            "capability_ids": sorted(
                {pattern.capability for pattern in self.catalogue.patterns}
            ),
            "methodology": {
                name: method.to_dict()
                for name, method in self.catalogue.registry.methods.items()
            },
            "statistical_parameters": {
                "alpha": self.catalogue.registry.alpha
            },
            "scope_count": len(scope_payloads),
            "scopes": scope_payloads,
            "finding_count": len(findings),
            "findings": findings,
            "pattern_status_counts": counts,
            "unavailable_patterns": [
                item.to_dict()
                for item in self.catalogue.unavailable_patterns
            ],
        }

    # -- pattern evaluation -------------------------------------------------

    def evaluate_pattern(
        self,
        pattern: OperationalPattern,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Run one pattern's method over a scope's population."""

        method = pattern.method.name

        if method == "asset_concentration":
            return self._evaluate_concentration(pattern, concept_values)

        if method == "investigation_repetition":
            return self._evaluate_repetition(pattern, concept_values)

        raise RuleMethodError(
            f"{pattern.pattern_id}: no implementation for method {method!r}"
        )

    # -- method: asset concentration ---------------------------------------

    def _evaluate_concentration(
        self,
        pattern: OperationalPattern,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Exact binomial tail on the busiest asset within the scope."""

        method = pattern.method

        total = len(concept_values)

        groups = self._group_counts(
            concept_values, pattern.group_concept
        )

        distinct = len(groups)

        state_record = {
            "pattern_id": pattern.pattern_id,
            "indicator": pattern.indicator,
            "pattern_type": pattern.pattern_type,
            "method": method.name,
            "population_concept": pattern.population_concept,
            "group_concept": pattern.group_concept,
            "pattern_status": NOT_EVALUABLE,
            "population_size": total,
            "distinct_groups": distinct,
            "minimum_observations": dict(method.minimums),
        }

        if not total:
            state_record["explanation"] = (
                "No records in this assessment scope."
            )
            state_record["pattern_status"] = EVIDENCE_NOT_PRESENT
            return {"state": EVIDENCE_NOT_PRESENT, "state_record": state_record}

        if distinct < 2:
            state_record["explanation"] = (
                "Only one distinct value is present for the grouping concept, "
                "so there is no distribution to describe."
            )
            state_record["pattern_status"] = EVIDENCE_NOT_PRESENT
            return {
                "state": EVIDENCE_NOT_PRESENT,
                "state_record": state_record,
            }

        floor_records = method.minimum("min_scope_records")
        floor_groups = method.minimum("min_distinct_assets")
        floor_group_size = method.minimum("min_records_on_flagged_asset")

        shortfalls = []

        if total < floor_records:
            shortfalls.append(
                f"{total} records, below the {floor_records} this method needs"
            )

        if distinct < floor_groups:
            shortfalls.append(
                f"{_plural(distinct, 'distinct value')}, below the "
                f"{floor_groups} this method needs"
            )

        if shortfalls:
            state_record["explanation"] = (
                "Insufficient observations to establish an operational "
                f"pattern: {'; '.join(shortfalls)}."
            )
            return {"state": NOT_EVALUABLE, "state_record": state_record}

        group_value, group_count = max(groups.items(), key=lambda kv: kv[1])

        share = group_count / total
        uniform_share = 1.0 / distinct

        p_value = _binomial_upper_tail(group_count, total, 1.0 / distinct)
        p_log10 = _binomial_upper_tail_log10(
            group_count, total, 1.0 / distinct
        )
        probability_phrase = _probability_phrase(p_log10)

        alpha = self.catalogue.registry.alpha

        evidence = {
            "group_value": group_value,
            "group_record_count": group_count,
            "scope_record_count": total,
            "distinct_groups": distinct,
            "group_share": round(share, 4),
            "group_share_pct": f"{share * 100:.1f}",
            "uniform_expected_share": round(uniform_share, 4),
            "share_versus_uniform_ratio": round(share / uniform_share, 4),
            "binomial_upper_tail_probability": _round_probability(p_value),
            "binomial_upper_tail_log10": (
                None if p_log10 is None else round(p_log10, 3)
            ),
            "probability_phrase": probability_phrase,
            "alpha": alpha,
            "method": method.name,
            "null_hypothesis": method.null_hypothesis,
            "group_record_positions": _positions_for(
                concept_values, pattern.group_concept, group_value
            ),
        }

        state_record["group_value"] = group_value
        state_record["group_share"] = round(share, 4)
        state_record["binomial_upper_tail_probability"] = (
            _round_probability(p_value)
        )
        state_record["probability_phrase"] = probability_phrase

        if group_count < floor_group_size:
            state_record["pattern_status"] = NO_PATTERN_DETECTED
            state_record["explanation"] = (
                f"The busiest value carries {_plural(group_count, 'record')}, "
                f"below the {floor_group_size} this method requires before a "
                f"concentration is meaningful."
            )
            return {
                "state": NO_PATTERN_DETECTED,
                "state_record": state_record,
                "evidence": evidence,
            }

        if p_value > alpha:
            state_record["pattern_status"] = NO_PATTERN_DETECTED
            state_record["explanation"] = (
                f"Distribution across the {distinct} observed values is not "
                f"unusual for a scope of {total} records "
                f"(tail probability {probability_phrase} does not exceed "
                f"alpha {alpha})."
            )
            return {
                "state": NO_PATTERN_DETECTED,
                "state_record": state_record,
                "evidence": evidence,
            }

        state_record["pattern_status"] = POTENTIAL_OPERATIONAL_ANOMALY
        state_record["explanation"] = (
            f"{group_count} of {total} records fall on one value, with tail "
            f"probability {probability_phrase}."
        )

        return {
            "state": POTENTIAL_OPERATIONAL_ANOMALY,
            "state_record": state_record,
            "evidence": evidence,
        }

    # -- method: investigation repetition ----------------------------------

    def _evaluate_repetition(
        self,
        pattern: OperationalPattern,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Connected components of mutual token-set similarity."""

        method = pattern.method
        registry = self.catalogue.registry

        total = len(concept_values)

        state_record = {
            "pattern_id": pattern.pattern_id,
            "indicator": pattern.indicator,
            "pattern_type": pattern.pattern_type,
            "method": method.name,
            "population_concept": pattern.population_concept,
            "group_concept": pattern.group_concept,
            "pattern_status": NOT_EVALUABLE,
            "population_size": total,
            "minimum_observations": dict(method.minimums),
        }

        if not total:
            state_record["pattern_status"] = EVIDENCE_NOT_PRESENT
            state_record["explanation"] = (
                "No records in this assessment scope."
            )
            return {"state": EVIDENCE_NOT_PRESENT, "state_record": state_record}

        threshold = registry.repetition_similarity
        floor_records = method.minimum("min_scope_records")
        floor_group = method.minimum("min_similar_records")

        if total < floor_records:
            state_record["explanation"] = (
                "Insufficient observations to establish an operational "
                f"pattern: {total} below the {floor_records} this method "
                f"needs."
            )
            return {"state": NOT_EVALUABLE, "state_record": state_record}

        token_sets: List[Optional[frozenset]] = []

        for values in concept_values:

            raw = values.get(pattern.text_concept)

            token_sets.append(_tokenise(raw) if has_evidence(raw) else None)

        observed = sum(1 for tokens in token_sets if tokens)

        if observed < floor_group:
            state_record["pattern_status"] = EVIDENCE_NOT_PRESENT
            state_record["explanation"] = (
                f"Only {_plural(observed, 'record')} "
                f"{'carries' if observed == 1 else 'carry'} submitted evidence "
                f"for {pattern.text_concept}, below the {floor_group} this "
                f"method needs."
            )
            state_record["records_with_evidence"] = observed
            return {
                "state": EVIDENCE_NOT_PRESENT,
                "state_record": state_record,
            }

        state_record["records_with_evidence"] = observed

        components = _similarity_components(token_sets, threshold)

        qualifying = [
            component
            for component in components
            if len(component) >= floor_group
        ]

        if not qualifying:
            state_record["pattern_status"] = NO_PATTERN_DETECTED
            state_record["explanation"] = (
                f"No group of {floor_group} or more records shares evidence "
                f"text at a token overlap of {threshold}."
            )
            return {
                "state": NO_PATTERN_DETECTED,
                "state_record": state_record,
            }

        qualifying.sort(key=len, reverse=True)

        group = qualifying[0]
        pairs = _similarity_pairs(token_sets, group, threshold)

        similarities = [pair[2] for pair in pairs]

        group_assets = {
            concept_values[index].get(pattern.group_concept)
            for index in group
        }
        group_assets.discard(None)

        state_record["pattern_status"] = POTENTIAL_OPERATIONAL_ANOMALY
        state_record["repeating_group_size"] = len(group)
        state_record["distinct_assets_in_group"] = len(group_assets)

        evidence = {
            "records_analysed": observed,
            "records_in_scope": total,
            "repeating_group_size": len(group),
            "qualifying_group_count": len(qualifying),
            "distinct_assets_in_group": len(group_assets),
            "min_similarity_threshold": threshold,
            "min_pairwise_similarity": (
                round(min(similarities), 4) if similarities else None
            ),
            "max_pairwise_similarity": (
                round(max(similarities), 4) if similarities else None
            ),
            "mean_pairwise_similarity": (
                round(sum(similarities) / len(similarities), 4)
                if similarities
                else None
            ),
            "comparisons_made": len(pairs),
            "method": method.name,
            "similarity_measure": method.definition.get(
                "similarity_measure"
            ),
            "group_record_positions": list(group),
            "raw_text_disclosed": False,
        }

        state_record["explanation"] = (
            f"{len(group)} records share near-identical evidence text across "
            f"{len(group_assets)} assets."
        )

        return {
            "state": POTENTIAL_OPERATIONAL_ANOMALY,
            "state_record": state_record,
            "evidence": evidence,
            "render": {
                "group_size": len(group),
                "min_similarity": threshold,
                "observed_min_similarity": (
                    round(min(similarities), 4) if similarities else None
                ),
                "distinct_assets": len(group_assets),
            },
        }

    # -- finding construction ----------------------------------------------

    def _build_finding(
        self,
        pattern: OperationalPattern,
        evaluation: Mapping[str, Any],
        scope,
    ) -> Dict[str, Any]:
        """Assemble a reviewable signal with its evidence and limits.

        The finding is written so an examiner can answer, without opening the
        code: what was unusual, how it was determined, over what population,
        on what evidence, and what the pattern cannot tell them.
        """

        evidence = dict(evaluation.get("evidence") or {})
        render = dict(evaluation.get("render") or {})

        group_value = evidence.get("group_value")

        if group_value is not None:
            render.setdefault("group_value", group_value)
            render.setdefault(
                "group_record_count", evidence["group_record_count"]
            )
            render.setdefault(
                "scope_record_count", evidence["scope_record_count"]
            )
            render.setdefault("distinct_groups", evidence["distinct_groups"])
            render.setdefault("share_pct", evidence["group_share_pct"])
            render.setdefault(
                "probability_phrase", evidence["probability_phrase"]
            )

        positions = evidence.get("group_record_positions") or []

        return {
            "indicator": pattern.indicator,
            "status": POTENTIAL_OPERATIONAL_ANOMALY,
            "pattern_type": pattern.pattern_type,
            "capability": pattern.capability,
            "pattern_id": pattern.pattern_id,
            "pattern_name": pattern.name,
            "method": pattern.method.name,

            "reason": pattern.render_reason(**render),

            "population": {
                "assessment_id": scope.assessment_id,
                "scope_record_count": scope.record_count,
                "records_analysed": evidence.get(
                    "records_analysed", scope.record_count
                ),
                "distinct_groups": evidence.get("distinct_groups"),
            },

            "evidence": evidence,

            "evidence_concepts": list(pattern.evidence_concepts),

            "why_review_might_be_warranted": list(
                pattern.why_review_might_be_warranted
            ),

            "explanation_limitations": list(
                pattern.explanation_limitations
            ),

            "is_not_a_control_failure": (
                "This signal describes operational shape only. It does not "
                "establish that a control failed and does not imply "
                "misconduct. The execution-gap layer is the only layer whose "
                "logic can establish a contradicted expectation."
            ),

            "record_reference": {
                "record_positions": list(positions),
                "source_record_indices": _source_indices(scope, positions),
            },

            "assessment_id": scope.assessment_id,
            "entity": scope.entity.to_dict(),
            "period": scope.period.to_dict(),
        }

    # -- helpers ------------------------------------------------------------

    def _group_counts(
        self,
        concept_values: Sequence[Mapping[str, Any]],
        concept: Optional[str],
    ) -> Dict[str, int]:
        """Count records per normalised concept value."""

        normalise = self.catalogue.registry.normalise

        counts: Dict[str, int] = {}

        for values in concept_values:

            raw = values.get(concept) if concept else None

            if not has_evidence(raw):
                continue

            key = normalise(raw)

            if not key:
                continue

            counts[key] = counts.get(key, 0) + 1

        return counts

    def __repr__(self) -> str:
        return (
            f"OperationalPatternDetector(patterns={len(self.catalogue.patterns)}, "
            f"unavailable={len(self.catalogue.unavailable_patterns)})"
        )


class RuleMethodError(RuntimeError):
    """Raised when a configured method has no implementation."""


# -- statistical helpers ---------------------------------------------------


def _binomial_upper_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), computed with exact combinatorics.

    Uses integer binomial coefficients from :mod:`math` rather than a
    floating-point recurrence, so the result does not drift with n and needs no
    numerical library.

    The terms are summed in log space. Multiplying a binomial coefficient by
    ``p ** i * q ** (n - i)`` in linear space coerces the coefficient to a float,
    and for a population of a few thousand records that coefficient exceeds the
    range of a float outright: the run raised ``OverflowError`` on a submission
    whose population was large enough for the coefficient to overflow, losing
    the whole assessment rather than one statistic. Long tails underflow to 0.0;
    use :func:`_binomial_upper_tail_log10` for the magnitude, because reporting
    a probability of exactly 0.0 would be a false claim of certainty.
    """

    if k <= 0:
        return 1.0

    if k > n:
        return 0.0

    log_total = _binomial_upper_tail_log10(k, n, p)

    if log_total is None:
        return 0.0

    return min(1.0, max(0.0, 10.0**log_total))


def _binomial_upper_tail_log10(k: int, n: int, p: float) -> Optional[float]:
    """log10 of P(X >= k), accumulated in log space to avoid underflow.

    A concentration such as 14 of 20 records on one asset has a tail
    probability far below the range of a float, so the direct computation
    returns 0.0. Reporting that as "0.0" would tell a supervisor the event is
    impossible, which is not what was established. Summing the same terms
    through logarithms keeps the magnitude available.
    """

    if k <= 0:
        return 0.0

    if k > n:
        return None

    q = 1.0 - p

    if p <= 0.0:
        return None

    if q <= 0.0:
        return 0.0

    log_terms = []

    for i in range(k, n + 1):

        coefficient = math.comb(n, i)

        if coefficient == 0:
            continue

        log_terms.append(
            math.log(coefficient)
            + i * math.log(p)
            + (n - i) * math.log(q)
        )

    if not log_terms:
        return None

    highest = max(log_terms)

    if highest == float("-inf"):
        return None

    total = highest + math.log(
        sum(math.exp(term - highest) for term in log_terms)
    )

    return total / math.log(10)


def _probability_phrase(log10: Optional[float]) -> str:
    """Describe a tail probability without implying false precision."""

    if log10 is None:
        return "an immeasurably small probability"

    if log10 > -1:
        return f"approximately 1 in {max(1, round(10 ** -log10))}"

    if log10 > -6:
        return f"about 1 in {int(round(10 ** -log10)):,}"

    exponent = int(math.ceil(-log10))

    return f"below 1 in 10^{exponent}"


def _plural(count: int, noun: str) -> str:
    """Render a count with its noun, so user-facing text reads correctly."""

    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _round_probability(value: float) -> float:
    """Round a probability for display.

    Very small probabilities collapse to 0.0, which is why every finding also
    carries ``*_log10`` and a verbal ``probability_phrase``: a reader must
    never read 0.0 as certainty.
    """

    if value <= 0.0:
        return 0.0

    if value < 1e-4:
        return 0.0

    return round(value, 6)


def _tokenise(value: Any) -> Optional[frozenset]:
    """Reduce submitted text to a comparable set of lowercase tokens.

    Token *sets* are used rather than counts so that reordering or repeating
    words does not by itself break similarity, and so no submitted text is
    retained beyond the set of words used for the comparison.
    """

    if not isinstance(value, str):
        return None

    tokens = _TOKEN_PATTERN.findall(value.lower())

    if not tokens:
        return None

    return frozenset(tokens)


def _similarity_components(
    token_sets: Sequence[Optional[frozenset]],
    threshold: float,
) -> List[List[int]]:
    """Group indices into connected components of mutual similarity.

    Transitive grouping is used deliberately: if record A matches B and B
    matches C, the three are reported together even if A and C differ, because
    a chain of near-identical notes is itself the pattern of interest.

    Uses exact deduplication + MinHash LSH for sub-quadratic component detection.
    """

    return find_connected_components_minhash(
        token_sets, threshold=threshold, exact_jaccard_fn=_jaccard
    )


def _similarity_pairs(
    token_sets: Sequence[Optional[frozenset]],
    group: Sequence[int],
    threshold: float,
) -> List[Tuple[int, int, float]]:
    """All within-group pairs that met the similarity threshold."""

    pairs: List[Tuple[int, int, float]] = []

    for position, left in enumerate(group):

        for right in group[position + 1:]:

            if token_sets[left] is None or token_sets[right] is None:
                continue

            score = _jaccard(token_sets[left], token_sets[right])

            if score >= threshold:
                pairs.append((left, right, score))

    return pairs


def _positions_for(
    concept_values: Sequence[Mapping[str, Any]],
    concept: Optional[str],
    value: str,
) -> List[int]:
    """Positions of records whose concept value normalises to ``value``."""

    normalise = normalise_value
    separators = [" ", "-", ".", "/"]

    return [
        index
        for index, values in enumerate(concept_values)
        if (
            normalise(values.get(concept) if concept else None, separators)
            == value
        )
    ]


def _source_indices(
    scope, record_positions: Sequence[int]
) -> List[int]:
    """Map scope-relative positions back to the shared record sequence.

    Lets an examiner open the exact source rows behind a signal. A pattern
    without this is a claim; with it, the claim is checkable.
    """

    indices = getattr(scope, "record_indices", []) or []

    resolved: List[int] = []

    for position in record_positions:

        if 0 <= position < len(indices):
            resolved.append(indices[position])

    return resolved
