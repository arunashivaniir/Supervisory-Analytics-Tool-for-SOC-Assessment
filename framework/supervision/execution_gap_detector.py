"""Per-record execution-gap evaluation.

The detector answers one question per rule per record:

    given the canonical concepts this record carries, is an explicitly expected
    control contradicted by explicitly observed evidence?

It contains **no per-rule code**. Every expectation, contradiction and allowed
value comes from :mod:`framework.supervisory.rules.rule_engine`, so the same
code path evaluates every rule and a new rule needs no new detector logic.

Two properties are enforced here rather than trusted to configuration:

**Missing evidence never becomes a gap.** If a concept in ``required_evidence``
is absent or empty for this record, the rule evaluates to ``NOT_EVALUABLE`` and
no finding is produced. An absent escalation status is an evidence-availability
fact owned by the capability layer; it is not proof that escalation was skipped.

**Unrecognised values never match.** A submitted value outside the configured
vocabulary matches no condition, so it yields ``NOT_EVALUABLE`` rather than
being guessed into a verdict.

This replaces an earlier implementation that looked for raw source column
names on records that the pipeline supplies in canonical form, so its lookups
never matched anything and it produced no findings for any dataset in the
repository. Its word-count and closure-time thresholds were also arbitrary
numbers rather than declared supervisory expectations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.supervisory.rules.rule_engine import (
    EXPECTATION_SATISFIED,
    EXPECTATION_VIOLATED,
    NOT_APPLICABLE,
    NOT_EVALUABLE,
    ExecutionGapRule,
    RuleRegistry,
)

#: Values that carry no information even when the source cell is non-empty.
BLANK_VALUES = frozenset(
    {"", "NAN", "N/A", "NA", "NONE", "NULL", "NIL", "-", "--", "UNKNOWN"}
)


def has_evidence(value: Any) -> bool:
    """True when a value is real submitted evidence.

    ``0`` and ``False`` are evidence; a blank, a null marker or a placeholder
    is not. This mirrors the capability layer's ``is_populated`` contract so the
    two layers never disagree about whether evidence exists.
    """

    if value is None:
        return False

    if isinstance(value, float) and value != value:
        return False

    if isinstance(value, bool):
        return True

    if isinstance(value, str):

        text = value.strip()

        if not text:
            return False

        return text.upper() not in BLANK_VALUES

    return True


class ExecutionGapDetector:
    """Evaluates configured rules against one record's canonical concepts."""

    def __init__(self, registry: Optional[RuleRegistry] = None) -> None:

        self.registry = registry or RuleRegistry()

    def evaluate_record(
        self,
        concept_values: Mapping[str, Any],
        rule: ExecutionGapRule,
    ) -> "Any":
        """Evaluate one rule against one record's concept values.

        ``concept_values`` maps canonical concept names to the submitted values
        for this single record. Concepts that are absent from the mapping are
        treated as unobserved.
        """

        observed: Dict[str, Any] = {}
        normalised: Dict[str, str] = {}
        missing: List[str] = []

        for concept in rule.required_evidence:

            value = concept_values.get(concept)

            if not has_evidence(value):
                missing.append(concept)
                continue

            observed[concept] = value
            normalised[concept] = self.registry.normalise(value)

        if missing:
            return self._not_evaluable(rule, missing, observed, normalised)

        violation_matched = all(
            condition.matches(normalised[condition.concept])
            for condition in rule.violation_condition.values()
            if condition.concept in normalised
        )

        if violation_matched:
            return self._violated(rule, observed, normalised)

        expected_matched = bool(rule.expected_condition) and all(
            condition.matches(normalised[condition.concept])
            for condition in rule.expected_condition.values()
            if condition.concept in normalised
        )

        if expected_matched:
            return self._satisfied(rule, observed, normalised)

        return self._not_applicable(rule, observed, normalised)

    def evaluate(
        self,
        concept_values: Mapping[str, Any],
        rules: Optional[Sequence[ExecutionGapRule]] = None,
    ):
        """Evaluate every configured rule against one record."""

        from framework.supervisory.rules.rule_engine import RuleEvaluation

        evaluations: List[RuleEvaluation] = []

        for rule in (rules if rules is not None else self.registry.rules):

            evaluations.append(self.evaluate_record(concept_values, rule))

        return evaluations

    # -- state construction -------------------------------------------------

    def _violated(self, rule, observed, normalised):
        from framework.supervisory.rules.rule_engine import RuleEvaluation

        return RuleEvaluation(
            rule_id=rule.rule_id,
            state=EXPECTATION_VIOLATED,
            reason=rule.render_explanation(observed),
            evidence=observed,
            missing_evidence=[],
            normalised_values=normalised,
        )

    def _satisfied(self, rule, observed, normalised):
        from framework.supervisory.rules.rule_engine import RuleEvaluation

        return RuleEvaluation(
            rule_id=rule.rule_id,
            state=EXPECTATION_SATISFIED,
            reason=(
                f"Evidence shows the expectation was met: "
                f"{self._describe(observed)}."
            ),
            evidence=observed,
            missing_evidence=[],
            normalised_values=normalised,
        )

    def _not_applicable(self, rule, observed, normalised):
        from framework.supervisory.rules.rule_engine import RuleEvaluation

        return RuleEvaluation(
            rule_id=rule.rule_id,
            state=NOT_APPLICABLE,
            reason=(
                f"Evidence was fully observed but does not meet this rule's "
                f"trigger: {self._describe(observed)}."
            ),
            evidence=observed,
            missing_evidence=[],
            normalised_values=normalised,
        )

    def _not_evaluable(self, rule, missing, observed, normalised):
        from framework.supervisory.rules.rule_engine import RuleEvaluation

        return RuleEvaluation(
            rule_id=rule.rule_id,
            state=NOT_EVALUABLE,
            reason=(
                f"Rule not evaluated: required evidence "
                f"{', '.join(sorted(missing))} is absent or empty. Absence of "
                f"evidence is an evidence-availability matter, not proof that "
                f"the expected control was not executed."
            ),
            evidence=observed,
            missing_evidence=sorted(missing),
            normalised_values=normalised,
        )

    @staticmethod
    def _describe(observed: Mapping[str, Any]) -> str:
        return ", ".join(
            f"{concept}={value}" for concept, value in sorted(observed.items())
        )

    def __repr__(self) -> str:
        return f"ExecutionGapDetector(rules={len(self.registry.rules)})"
