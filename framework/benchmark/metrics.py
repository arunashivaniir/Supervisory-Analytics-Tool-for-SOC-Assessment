"""Metric extraction for peer benchmarking.

Each metric is resolved from a result another supervisory layer has already
produced. Nothing here re-evaluates evidence, re-derives a finding, or
invents a denominator: if the layer that owns a quantity declined to produce
it, this module reports NOT_EVALUABLE carrying that layer's own reason.

That constraint is the whole point. A peer benchmark that computed its own
version of a quantity would eventually disagree with the same quantity shown
on the assessment screen, and a supervisory tool that contradicts itself is
worse than one that reports nothing.

NORMALISATION
=============

Incidence is always a rate over an explicit denominator, and both the
numerator and the denominator are published. A record count is not a rate: it
grows with the size of the submission, so a CSE assessed twice as large looks
worse purely for being twice as large.

A metric with no denominator is not a rate and cannot be benchmarked against
peers, so it is reported as unavailable with the reason rather than quietly
compared as a raw count.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

COMPUTED = "COMPUTED"
NOT_EVALUABLE = "NOT_EVALUABLE"

POTENTIAL_EXECUTION_GAP = "POTENTIAL_EXECUTION_GAP"
POTENTIAL_OPERATIONAL_ANOMALY = "POTENTIAL_OPERATIONAL_ANOMALY"
POTENTIAL_NEGATIVE_SPACE = "POTENTIAL_NEGATIVE_SPACE"
PARTIAL_NEGATIVE_SPACE = "PARTIAL_NEGATIVE_SPACE"

AVAILABLE = "AVAILABLE"

# The verdict the anomaly model returns for a scope it could not assess. It is a
# decision about the absence of a verdict, not a verdict, so it must never reach
# the numerator or the denominator of a rate over evaluated scopes.
ANOMALY_NOT_EVALUABLE = "NOT_EVALUABLE"

ABSENCE_STATES_WITH_ABSENCE = (POTENTIAL_NEGATIVE_SPACE, PARTIAL_NEGATIVE_SPACE)


def _rate(numerator: int, denominator: int, precision: int) -> Optional[float]:
    if denominator <= 0:
        return None

    return round(numerator / denominator, precision)


def _metric(
    metric_id: str,
    numerator: Optional[int],
    denominator: Optional[int],
    precision: int,
    reason: Optional[str],
) -> Dict[str, Any]:
    """Assemble the numerator/denominator/rate triple, or say why it is absent."""

    if reason is not None or numerator is None or denominator is None:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "rate": None,
            "metric_status": NOT_EVALUABLE,
            "not_evaluable_reason": reason
            or "this scope produced no denominator for the metric",
        }

    if denominator <= 0:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "rate": None,
            "metric_status": NOT_EVALUABLE,
            "not_evaluable_reason": (
                "the denominator is zero, so the rate is undefined; this is "
                "not a measurement of zero"
            ),
        }

    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": _rate(numerator, denominator, precision),
        "metric_status": COMPUTED,
        "not_evaluable_reason": None,
    }


# -- execution gaps ---------------------------------------------------------


def execution_gap_incidence(
    scope_payload: Mapping[str, Any],
    precision: int,
    unavailable_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Records carrying at least one execution gap, over records in scope."""

    if unavailable_reason is not None:
        return _metric(
            "execution_gap_incidence", None, None, precision, unavailable_reason
        )

    record_count = int(scope_payload.get("record_count") or 0)

    if record_count <= 0:
        return _metric(
            "execution_gap_incidence",
            None,
            record_count,
            precision,
            "the assessment scope holds no records",
        )

    flagged: set = set()

    for finding in scope_payload.get("findings") or ():

        reference = finding.get("record_reference") or {}

        for key in ("record_position", "record_positions"):
            value = reference.get(key)

            if value is None:
                continue

            if isinstance(value, (list, tuple, set)):
                flagged.update(int(item) for item in value)
            else:
                flagged.add(int(value))

    return _metric(
        "execution_gap_incidence", len(flagged), record_count, precision, None
    )


# -- negative space ---------------------------------------------------------


def negative_space_incidence(
    scope_payload: Mapping[str, Any],
    precision: int,
    unavailable_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger-population records lacking expected evidence, over that population.

    The absence counts come from the findings themselves. An expectation that
    reported NO_ABSENCE contributes zero to the numerator and its trigger
    records to the denominator, which is exact rather than reconstructed from
    the rounded coverage ratio.
    """

    if unavailable_reason is not None:
        return _metric(
            "negative_space_incidence", None, None, precision, unavailable_reason
        )

    states = scope_payload.get("expectation_states") or ()

    if not states:
        return _metric(
            "negative_space_incidence",
            None,
            None,
            precision,
            "no negative-space expectation was evaluated for this scope, so "
            "there is no population to measure",
        )

    denominator = 0
    numerator = 0
    evaluable = False

    for state in states:

        trigger_records = int(state.get("trigger_records") or 0)

        if trigger_records <= 0:
            continue

        evaluable = True
        denominator += trigger_records

        if state.get("absence_state") not in ABSENCE_STATES_WITH_ABSENCE:
            continue

        # Match on rule_id, never on absence_state alone. Two configured rules
        # can reach the same absence state, and pairing a state with whichever
        # finding happened to come first would attribute one rule's absent-record
        # count to a different rule's population.
        for finding in scope_payload.get("findings") or ():

            if finding.get("rule_id") != state.get("rule_id"):
                continue

            evidence = finding.get("evidence_summary") or {}

            numerator += int(
                evidence.get("records_without_expected_evidence") or 0
            )
            break

    if not evaluable:
        return _metric(
            "negative_space_incidence",
            None,
            0,
            precision,
            "no configured expectation's trigger population is present in this "
            "scope, so expected evidence cannot be expected here",
        )

    return _metric(
        "negative_space_incidence", numerator, denominator, precision, None
    )


# -- operational patterns ---------------------------------------------------


def operational_pattern_incidence(
    scope_payload: Mapping[str, Any],
    precision: int,
    unavailable_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Records placed in at least one unexplained cluster, over records in scope."""

    if unavailable_reason is not None:
        return _metric(
            "operational_pattern_incidence", None, None, precision, unavailable_reason
        )

    record_count = int(scope_payload.get("record_count") or 0)

    if record_count <= 0:
        return _metric(
            "operational_pattern_incidence",
            None,
            record_count,
            precision,
            "the assessment scope holds no records",
        )

    flagged: set = set()

    for finding in scope_payload.get("findings") or ():

        if finding.get("status") != POTENTIAL_OPERATIONAL_ANOMALY:
            continue

        reference = finding.get("record_reference") or {}

        for key in ("record_position", "record_positions"):
            value = reference.get(key)

            if value is None:
                continue

            if isinstance(value, (list, tuple, set)):
                flagged.update(int(item) for item in value)
            else:
                flagged.add(int(value))

    return _metric(
        "operational_pattern_incidence",
        len(flagged),
        record_count,
        precision,
        None,
    )


# -- anomaly ---------------------------------------------------------------


def anomaly_verdict_rate(
    scope_results: Sequence[Mapping[str, Any]],
    scope_assessment_ids: Sequence[str],
    precision: int,
) -> Tuple[int, int, int, Optional[str]]:
    """Anomalous scopes over evaluated scopes, across the whole assessment.

    A scope the model declined to evaluate is excluded from the denominator
    rather than counted as clean, and the count of such scopes is published so
    a reader can see the denominator is not the whole assessment.

    The model states non-evaluation two ways and both are honoured: a missing
    ``verdict`` field, and the literal ``NOT_EVALUABLE`` verdict. The second is
    the one the pipeline actually emits, and treating it as an evaluated clean
    scope would understate anomaly incidence across every submission where the
    model declined to judge.
    """

    wanted = set(str(item) for item in scope_assessment_ids)

    evaluated = 0
    anomalous = 0
    not_evaluable = 0

    for result in scope_results:

        if str(result.get("assessment_id")) not in wanted:
            continue

        verdict = result.get("verdict")

        if verdict is None or verdict == ANOMALY_NOT_EVALUABLE:
            not_evaluable += 1
            continue

        evaluated += 1

        if verdict == POTENTIAL_OPERATIONAL_ANOMALY:
            anomalous += 1

    if evaluated == 0:
        return 0, 0, not_evaluable, (
            "the anomaly layer evaluated no scope in this assessment"
            if not_evaluable
            else "the anomaly layer produced no scope result"
        )

    return anomalous, evaluated, not_evaluable, None


# -- capability evidence ----------------------------------------------------


def _capabilities_in_category(
    scope_payload: Mapping[str, Any], category: Optional[str]
) -> List[Mapping[str, Any]]:
    capabilities = scope_payload.get("capabilities") or ()

    if category is None:
        return [item for item in capabilities if item.get("capability_id")]

    return [
        item
        for item in capabilities
        if category in (item.get("indicator_categories") or ())
    ]


def capability_category_coverage(
    scope_payload: Mapping[str, Any],
    category: Optional[str],
    precision: int,
    unavailable_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """AVAILABLE capabilities over evaluated capabilities, optionally filtered.

    ``category is None`` gives whole-submission evidence coverage. A category
    restricts the same computation to the capabilities whose configured
    indicator category it is. INSUFFICIENT_EVIDENCE and NOT_ASSESSED both sit
    in the denominator: the submission did not let those capabilities be
    assessed, and quietly dropping them would report a partially evidenced
    assessment as a well evidenced one.
    """

    if unavailable_reason is not None:
        return _metric(
            "capability_category_coverage",
            None,
            None,
            precision,
            unavailable_reason,
        )

    capabilities = _capabilities_in_category(scope_payload, category)

    if not capabilities:
        return _metric(
            "capability_category_coverage",
            None,
            None,
            precision,
            "no configured capability declares this indicator category, so "
            "there is nothing to measure"
            if category is not None
            else "the capability layer evaluated no capability for this scope",
        )

    available = sum(1 for item in capabilities if item.get("status") == AVAILABLE)

    return _metric(
        "capability_category_coverage",
        available,
        len(capabilities),
        precision,
        None,
    )


# -- concepts --------------------------------------------------------------


def unresolved_concepts(
    scope_payload: Mapping[str, Any], declared: Sequence[str]
) -> List[str]:
    """Declared metric concepts this scope's evidence did not resolve.

    Published next to the concepts that were evidenced, so a reviewer can see
    that a peer comparison was drawn over a narrower set of concepts than the
    metric's definition assumes.
    """

    available: set = set()

    for capability in scope_payload.get("capabilities") or ():

        for concept in capability.get("evidence_available") or ():
            if concept:
                available.add(str(concept))

    return [
        concept for concept in declared if str(concept) not in available
    ]


def evidenced_concepts(
    scope_payload: Mapping[str, Any], declared: Sequence[str]
) -> List[str]:
    """Declared metric concepts the scope's evidence actually resolved."""

    available: set = set()

    for capability in scope_payload.get("capabilities") or ():

        for concept in capability.get("evidence_available") or ():
            if concept:
                available.add(str(concept))

    return [
        concept for concept in declared if str(concept) in available
    ]


def index_by_assessment_id(
    payloads: Sequence[Mapping[str, Any]],
) -> Dict[str, Mapping[str, Any]]:
    """Index a layer's scope payloads by assessment id.

    Layers report a scope payload for every scope they evaluated, but a
    defensive index means a missing payload surfaces as a stated absence
    rather than a KeyError in the middle of a run.
    """

    indexed: Dict[str, Mapping[str, Any]] = {}

    for payload in payloads:
        assessment_id = payload.get("assessment_id")

        if assessment_id is not None:
            indexed[str(assessment_id)] = payload

    return indexed