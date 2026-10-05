"""Scope-level negative-space analysis.

Negative space is a statement about a *population*, not about a field. One
record with a blank escalation status is a blank field; a scope in which every
critical alert lacks escalation evidence is an absence of evidence from a
population that the evidence itself identified as critical. Only the second is
reported, which is why this operates per :class:`AssessmentScope` and never per
record.

The detector is generic. It contains no rule-specific code: the expectation, the
trigger population, the observable concept and the reasons all come from
:class:`framework.supervisory.rules.negative_space_rules.NegativeSpaceRule`.

What this layer deliberately does not do
----------------------------------------
**It does not judge values.** A record carrying an explicit ``NOT_ESCALATED``
*has* escalation evidence, so its coverage counts and it can never raise a
negative-space signal. Judging that value is the execution-gap engine's job,
and the two therefore never report the same logical condition.

**It does not invent policy.** Complete absence and partial absence are
different factual states, and both are reported. Neither is escalated into a
weakness by a coverage number the tool chose for itself; ``
material_coverage_threshold`` is null in the shipped configuration and is
honoured only if a supervisory authority supplies one.

**It does not treat blanks as findings.** A blank, ``N/A`` or absent cell is
simply not evidence. It contributes to the absence count for a triggered
expectation and to nothing at all when the expectation is not triggered.

Relationship to the previous implementation
-------------------------------------------
The earlier ``NegativeSpaceDetector`` evaluated one record at a time and gated on
``RESOLUTION_TIME`` appearing in the dataset-level ``ALERT_MANAGEMENT`` evidence
list. That list never contained ``RESOLUTION_TIME`` for any dataset in the
repository, so the detector produced nothing anywhere, and the resulting finding
carried a hardcoded ``severity`` of ``LOW``, which is a risk judgement rather
than an observation. Both problems are resolved: the analysis is population
based and scope scoped, and no severity, score or priority is emitted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.supervision.execution_gap_detector import has_evidence
from framework.supervisory.rules.negative_space_rules import (
    COMPLETE_ABSENCE,
    EXPECTATION_NOT_TRIGGERED,
    NO_ABSENCE,
    NOT_EVALUABLE,
    PARTIAL_ABSENCE,
    NegativeSpaceCatalogue,
    NegativeSpaceRule,
)


class NegativeSpaceDetector:
    """Measures absence of expected evidence within one assessment scope."""

    def __init__(
        self, catalogue: Optional[NegativeSpaceCatalogue] = None
    ) -> None:

        self.catalogue = catalogue or NegativeSpaceCatalogue()

    # -- measurement --------------------------------------------------------

    def measure(
        self,
        rule: NegativeSpaceRule,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Measure expected-evidence coverage across a scope's population.

        Returns a factual measurement: how many records formed the triggering
        population, how many carried usable evidence, how many did not, and the
        coverage ratio. No threshold is applied here.
        """

        population_indices: List[int] = []

        for index, values in enumerate(concept_values):

            normalised = self.catalogue.registry.normalise(
                values.get(rule.population_concept)
            )

            if rule.is_triggered_by(normalised):
                population_indices.append(index)

        measurement: Dict[str, Any] = {
            "trigger_population": rule.population_label,
            "trigger_concept": rule.population_concept,
            "expected_evidence": [
                item.to_dict() for item in rule.expected_evidence
            ],
            "trigger_records": len(population_indices),
            "records_with_expected_evidence": 0,
            "records_without_expected_evidence": 0,
            "records_with_unusable_evidence": 0,
            "coverage": None,
            "coverage_by_concept": {},
            "record_positions_without_evidence": [],
            "record_positions_with_unusable_evidence": [],
        }

        if not population_indices:
            return measurement

        for item in rule.expected_evidence:

            with_evidence = 0
            without_evidence = 0
            unusable = 0
            without_positions: List[int] = []
            unusable_positions: List[int] = []

            for index in population_indices:

                raw = concept_values[index].get(item.concept)

                if not has_evidence(raw):
                    without_evidence += 1
                    without_positions.append(index)
                    continue

                normalised = self.catalogue.registry.normalise(raw)

                if item.accepts(normalised):
                    with_evidence += 1
                else:
                    # Submitted, but states no usable outcome. Counted
                    # separately so the absence figure stays truthful.
                    unusable += 1
                    without_evidence += 1
                    without_positions.append(index)
                    unusable_positions.append(index)

            measurement["coverage_by_concept"][item.concept] = {
                "records_with_expected_evidence": with_evidence,
                "records_without_expected_evidence": without_evidence,
                "records_with_unusable_evidence": unusable,
                "coverage": _ratio(with_evidence, len(population_indices)),
            }

            if item is rule.expected_evidence[0]:
                measurement["record_positions_without_evidence"] = (
                    without_positions
                )
                measurement["record_positions_with_unusable_evidence"] = (
                    unusable_positions
                )

        primary = rule.expected_evidence[0]

        with_evidence = measurement["coverage_by_concept"][primary.concept][
            "records_with_expected_evidence"
        ]
        without_evidence = measurement["coverage_by_concept"][
            primary.concept
        ]["records_without_expected_evidence"]
        unusable = measurement["coverage_by_concept"][primary.concept][
            "records_with_unusable_evidence"
        ]

        measurement["records_with_expected_evidence"] = with_evidence
        measurement["records_without_expected_evidence"] = without_evidence
        measurement["records_with_unusable_evidence"] = unusable
        measurement["coverage"] = _ratio(with_evidence, len(population_indices))

        return measurement

    def classify(
        self,
        rule: NegativeSpaceRule,
        measurement: Mapping[str, Any],
    ) -> str:
        """Classify a measurement against the rule's configured semantics.

        The only states are factual. No state is derived from a coverage number
        the tool chose for itself.
        """

        trigger_records = measurement["trigger_records"]

        if trigger_records == 0:
            return EXPECTATION_NOT_TRIGGERED

        with_evidence = measurement["records_with_expected_evidence"]
        without_evidence = measurement["records_without_expected_evidence"]

        if with_evidence == 0 and without_evidence > 0:
            state = COMPLETE_ABSENCE

        elif without_evidence == 0:
            state = NO_ABSENCE

        else:
            state = PARTIAL_ABSENCE

        if (
            state == PARTIAL_ABSENCE
            and rule.material_coverage_threshold is not None
            and measurement["coverage"] is not None
            and measurement["coverage"] < rule.material_coverage_threshold
        ):
            # Only reachable when a supervisory authority configured a
            # threshold. The shipped configuration sets none.
            return rule.complete_absence_status

        return state

    # -- scope evaluation ---------------------------------------------------

    def evaluate_scope(
        self,
        scope,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Evaluate every configured rule over one scope's population."""

        findings: List[Dict[str, Any]] = []

        states: List[Dict[str, Any]] = []

        for rule in self.catalogue.rules:

            measurement = self.measure(rule, concept_values)
            state = self.classify(rule, measurement)

            states.append(
                {
                    "rule_id": rule.rule_id,
                    "absence_state": state,
                    "trigger_records": measurement["trigger_records"],
                    "coverage": measurement["coverage"],
                }
            )

            if state not in (COMPLETE_ABSENCE, PARTIAL_ABSENCE):
                continue

            findings.append(
                self._build_finding(rule, measurement, state, scope)
            )

        counts: Dict[str, int] = {}

        for state in states:
            counts[state["absence_state"]] = (
                counts.get(state["absence_state"], 0) + 1
            )

        return {
            "assessment_id": scope.assessment_id,
            "entity": scope.entity.to_dict(),
            "period": scope.period.to_dict(),
            "record_count": scope.record_count,
            "findings": findings,
            "absence_state_counts": counts,
            "expectation_states": states,
        }

    # -- collection evaluation ----------------------------------------------

    def evaluate_collection(
        self,
        collection,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
        capability_evaluator=None,
    ) -> Dict[str, Any]:
        """Evaluate every assessment scope independently.

        Nothing is pooled across scopes. A summary is reported so a reviewer can
        see that a rule was evaluated and not triggered, which is different from
        a rule that was never evaluated.
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
            for state, count in payload["absence_state_counts"].items():
                counts[state] = counts.get(state, 0) + count

        return {
            "rule_ids": [rule.rule_id for rule in self.catalogue.rules],
            "capability_ids": sorted(
                {rule.capability for rule in self.catalogue.rules}
            ),
            "scope_count": len(scope_payloads),
            "scopes": scope_payloads,
            "finding_count": len(findings),
            "findings": findings,
            "absence_state_counts": counts,
            "unavailable_rules": [
                rule.to_dict() for rule in self.catalogue.unavailable_rules
            ],
        }

    # -- finding construction ----------------------------------------------

    def _build_finding(
        self,
        rule: NegativeSpaceRule,
        measurement: Mapping[str, Any],
        state: str,
        scope,
    ) -> Dict[str, Any]:
        """Assemble a finding that explains the whole expectation.

        A negative-space finding is only useful to a supervisor if it answers
        what was expected, why, for which population, what was observed and what
        was absent. All five are carried explicitly.
        """

        complete = state == COMPLETE_ABSENCE

        status = (
            rule.complete_absence_status
            if complete
            else rule.partial_absence_status
        )

        return {
            "indicator": rule.indicator,
            "capability": rule.capability,
            "status": status,
            "absence_state": state,
            "rule_id": rule.rule_id,
            "rule_name": rule.name,
            "reason": rule.render_reason(partial=not complete),

            "expectation": {
                "trigger": rule.population_label,
                "expected_evidence": [
                    item.concept for item in rule.expected_evidence
                ],
                "basis": rule.basis,
                "statement": rule.statement,
                "why_expected": list(rule.why_expected),
            },

            "evidence_summary": {
                "trigger_population": measurement["trigger_population"],
                "trigger_records": measurement["trigger_records"],
                "records_with_expected_evidence": measurement[
                    "records_with_expected_evidence"
                ],
                "records_without_expected_evidence": measurement[
                    "records_without_expected_evidence"
                ],
                "records_with_unusable_evidence": measurement[
                    "records_with_unusable_evidence"
                ],
                "coverage": measurement["coverage"],
                "coverage_by_concept": measurement["coverage_by_concept"],
            },

            "evidence_concepts": list(rule.evidence_concepts),

            "record_reference": {
                "record_positions": list(
                    measurement["record_positions_without_evidence"]
                ),
                "source_record_indices": _source_indices(
                    scope,
                    measurement["record_positions_without_evidence"],
                ),
                "records_with_unusable_evidence": list(
                    measurement[
                        "record_positions_with_unusable_evidence"
                    ]
                ),
            },

            "assessment_id": scope.assessment_id,
            "entity": scope.entity.to_dict(),
            "period": scope.period.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"NegativeSpaceDetector(rules={len(self.catalogue.rules)}, "
            f"unavailable={len(self.catalogue.unavailable_rules)})"
        )


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """A derived count ratio, not a policy threshold."""

    if not denominator:
        return None

    return round(numerator / denominator, 4)


def _source_indices(
    scope, record_positions: Sequence[int]
) -> List[int]:
    """Map positions within a scope back to the shared record sequence.

    Lets a reviewer open the exact source rows that lack evidence, which is
    what makes an absence claim checkable rather than merely stated.
    """

    indices = getattr(scope, "record_indices", []) or []

    resolved: List[int] = []

    for position in record_positions:

        if 0 <= position < len(indices):
            resolved.append(indices[position])

    return resolved
