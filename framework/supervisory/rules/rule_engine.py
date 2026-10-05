"""Configuration-driven execution-gap rule architecture.

A rule here is **data, not logic**. It declares an expectation, a contradicting
condition, and the canonical concepts required to tell them apart. The
evaluator in :mod:`framework.supervision.execution_gap_detector` contains no
per-rule branching at all, so a new supervisory expectation is added by editing
``framework/config/execution_gap_rules.json`` and nothing else.

The distinction this module exists to protect::

    expected control  ->  observed evidence  ->  contradiction -> execution gap

Only a contradiction qualifies. Absent evidence cannot, which is why the
evaluation vocabulary below is deliberately wider than ``violated``/``satisfied``:
a rule that cannot see enough evidence reports :data:`NOT_EVALUABLE` and emits
nothing at all.

Evaluation states
-----------------
``EXPECTATION_VIOLATED``
    Both sides of the expectation were explicitly observed and they contradict
    each other. This is the only state that may produce a finding.
``EXPECTATION_SATISFIED``
    Both sides were observed and agree.
``NOT_APPLICABLE``
    The record was fully observable but the rule's trigger did not match, e.g.
    a non-critical alert under a critical-alert rule.
``NOT_EVALUABLE``
    At least one required concept was absent or empty. No conclusion is drawn.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

# -- evaluation states -------------------------------------------------------

EXPECTATION_VIOLATED = "EXPECTATION_VIOLATED"
EXPECTATION_SATISFIED = "EXPECTATION_SATISFIED"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_EVALUABLE = "NOT_EVALUABLE"

EVALUATION_STATES = (
    EXPECTATION_VIOLATED,
    EXPECTATION_SATISFIED,
    NOT_APPLICABLE,
    NOT_EVALUABLE,
)

#: The only state permitted to become a supervisory finding.
FINDING_STATES = (EXPECTATION_VIOLATED,)

FINDING_STATUS = "POTENTIAL_EXECUTION_GAP"

DEFAULT_RULES_CONFIG = "framework/config/execution_gap_rules.json"
DEFAULT_MAPPINGS_CONFIG = "framework/config/mappings.json"
DEFAULT_CAPABILITIES_CONFIG = "framework/config/capabilities.json"


class RuleConfigError(Exception):
    """Raised when the rule configuration cannot be trusted."""


def normalise_value(
    value: Any, separators: Sequence[str] = (" ", "-", ".", "/")
) -> str:
    """Reduce a submitted value to its canonical comparable form.

    Trims, upper-cases and folds separators to underscores so that
    ``"not escalated"``, ``"NOT-ESCALATED"`` and ``"not_escalated"`` all become
    ``NOT_ESCALATED``. Normalisation never widens a match: it only makes
    equivalent spellings comparable.
    """

    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    for separator in separators:

        text = text.replace(separator, "_")

    text = re.sub(r"_+", "_", text)

    return text.upper().strip("_")


class Condition:
    """One ``concept <vocabulary_key>`` comparison inside a rule condition."""

    def __init__(
        self,
        concept: str,
        operator: str,
        values: Sequence[str],
        vocabulary_key: str,
    ) -> None:

        self.concept = concept
        self.operator = operator
        self.values = [str(item) for item in values]
        self.vocabulary_key = vocabulary_key

    def matches(self, observed: str) -> bool:
        """True only when the observed value is explicitly listed.

        An unrecognised value never matches. That is what keeps an unexpected
        token from being read as either satisfaction or violation.
        """

        if not observed:
            return False

        if self.operator == "in":
            return observed in self.values

        if self.operator == "not_in":
            return observed not in self.values

        raise RuleConfigError(
            f"{self.concept}: unsupported operator {self.operator!r}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept": self.concept,
            "operator": self.operator,
            "values": list(self.values),
            "vocabulary_key": self.vocabulary_key,
        }


class RuleEvaluation:
    """The outcome of evaluating one rule against one record."""

    def __init__(
        self,
        rule_id: str,
        state: str,
        reason: str,
        evidence: Mapping[str, Any],
        missing_evidence: Sequence[str] = (),
        normalised_values: Optional[Mapping[str, str]] = None,
    ) -> None:

        self.rule_id = rule_id
        self.state = state
        self.reason = reason
        self.evidence = dict(evidence)
        self.missing_evidence = list(missing_evidence)
        self.normalised_values = dict(normalised_values or {})

    @property
    def is_finding(self) -> bool:
        return self.state in FINDING_STATES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "state": self.state,
            "reason": self.reason,
            "evidence": dict(self.evidence),
            "missing_evidence": list(self.missing_evidence),
        }

    def __repr__(self) -> str:
        return f"RuleEvaluation({self.rule_id!r}, {self.state})"


class ExecutionGapRule:
    """One declared supervisory expectation.

    A rule can only be constructed once its concepts are known to exist in
    ``mappings.json`` and its capability is known to exist in
    ``capabilities.json``. That validation is what stops a rule from silently
    depending on a canonical concept that was never defined.
    """

    def __init__(
        self,
        rule_id: str,
        name: str,
        capability: str,
        indicator: str,
        status: str,
        required_evidence: Sequence[str],
        expected_condition: Mapping[str, Condition],
        violation_condition: Mapping[str, Condition],
        evidence_concepts: Sequence[str],
        explanation_template: Sequence[str],
        description: Sequence[str] = (),
        rationale: Sequence[str] = (),
        vocabulary_confidence: Optional[Mapping[str, Any]] = None,
    ) -> None:

        self.rule_id = rule_id
        self.name = name
        self.capability = capability
        self.indicator = indicator
        self.status = status
        self.required_evidence = list(required_evidence)
        self.expected_condition = dict(expected_condition)
        self.violation_condition = dict(violation_condition)
        self.evidence_concepts = list(evidence_concepts)
        self.explanation_template = list(explanation_template)
        self.description = list(description)
        self.rationale = list(rationale)
        self.vocabulary_confidence = dict(vocabulary_confidence or {})

    @property
    def concepts(self) -> List[str]:
        return sorted(
            set(self.required_evidence) | set(self.evidence_concepts)
        )

    def render_explanation(self, evidence: Mapping[str, Any]) -> str:
        """Fill the configured template with the observed evidence only.

        Only values the rule actually observed are interpolated, so the
        explanation cannot quote evidence the rule never saw.
        """

        parts = []

        for line in self.explanation_template:

            try:
                parts.append(line.format(**evidence))
            except (KeyError, IndexError, ValueError):
                # An unfilled placeholder is dropped rather than guessed at.
                parts.append(line.replace("{", "").replace("}", ""))

        return " ".join(part.strip() for part in parts if part.strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "capability": self.capability,
            "indicator": self.indicator,
            "status": self.status,
            "required_evidence": list(self.required_evidence),
            "expected_condition": {
                concept: condition.to_dict()
                for concept, condition in self.expected_condition.items()
            },
            "violation_condition": {
                concept: condition.to_dict()
                for concept, condition in self.violation_condition.items()
            },
            "evidence_concepts": list(self.evidence_concepts),
            "description": list(self.description),
            "rationale": list(self.rationale),
        }


class UnavailableRule:
    """A supervisory expectation deliberately not implemented, and why.

    Recording these is the point: a reviewer can see that the absence of an
    investigation-failure rule is a deliberate evidence limit, not an oversight.
    """

    def __init__(self, payload: Mapping[str, Any]) -> None:

        self.rule_id = payload.get("rule_id")
        self.name = payload.get("name")
        self.capability = payload.get("capability")
        self.status = payload.get("status", "UNAVAILABLE")
        self.required_evidence_ideal = list(
            payload.get("required_evidence_ideal", [])
        )
        self.missing_evidence = list(payload.get("missing_evidence", []))
        self.why_not_implemented = list(payload.get("why_not_implemented", []))
        self.would_require = list(payload.get("would_require", []))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "capability": self.capability,
            "status": self.status,
            "required_evidence_ideal": list(self.required_evidence_ideal),
            "missing_evidence": list(self.missing_evidence),
            "why_not_implemented": list(self.why_not_implemented),
            "would_require": list(self.would_require),
        }


class RuleRegistry:
    """Loads and validates execution-gap rules from configuration."""

    def __init__(
        self,
        config_file: str = DEFAULT_RULES_CONFIG,
        mappings_file: str = DEFAULT_MAPPINGS_CONFIG,
        capabilities_file: str = DEFAULT_CAPABILITIES_CONFIG,
    ) -> None:

        self.config_file = config_file
        self.mappings_file = mappings_file
        self.capabilities_file = capabilities_file

        self.config = _load_json(config_file)

        self.known_concepts = set(_load_json(mappings_file).keys())

        capabilities = _load_json(capabilities_file).get("capabilities", {})

        self.known_capabilities = set(capabilities.keys())

        self.separators = list(
            self.config.get("value_normalisation", {}).get(
                "separators_folded_to_underscore", [" ", "-", ".", "/"]
            )
        )

        self.vocabulary = {
            concept: {
                key: [
                    normalise_value(token, self.separators)
                    for token in tokens
                ]
                for key, tokens in mapping.items()
                if not key.startswith("_")
            }
            for concept, mapping in self.config.get(
                "value_vocabulary", {}
            ).items()
            if isinstance(mapping, Mapping)
        }

        self.rules: List[ExecutionGapRule] = [
            self._build_rule(payload)
            for payload in self.config.get("rules", [])
        ]

        self.unavailable_rules: List[UnavailableRule] = [
            UnavailableRule(payload)
            for payload in self.config.get("unavailable_rules", [])
        ]

        self._validate_unique_rule_ids()

    # -- construction -------------------------------------------------------

    def _build_rule(self, payload: Mapping[str, Any]) -> ExecutionGapRule:

        rule_id = payload.get("rule_id")

        if not rule_id:
            raise RuleConfigError("a rule is missing its rule_id")

        capability = payload.get("capability")

        if capability not in self.known_capabilities:
            raise RuleConfigError(
                f"{rule_id}: capability {capability!r} is not one of the eight "
                f"defined capabilities"
            )

        required = list(payload.get("required_evidence", []))

        if not required:
            raise RuleConfigError(
                f"{rule_id}: required_evidence must not be empty; a rule with "
                f"no required evidence could never distinguish a gap from "
                f"missing data"
            )

        for concept in required:

            if concept not in self.known_concepts:
                raise RuleConfigError(
                    f"{rule_id}: required concept {concept!r} does not exist in "
                    f"{self.mappings_file}. Execution-gap rules may only use "
                    f"canonical concepts that already exist."
                )

        expected = self._build_condition(rule_id, "expected", payload)

        # Membership is checked against raw condition keys before conditions
        # are built, so the more fundamental error surfaces first: a violation
        # on a concept the rule never required is a design error, not a
        # vocabulary lookup failure.
        raw_violation = payload.get("violation_condition") or {}

        for concept in raw_violation:

            if concept not in required:
                raise RuleConfigError(
                    f"{rule_id}: violation_condition references {concept!r}, "
                    f"which is not in required_evidence"
                )

        violation = self._build_condition(rule_id, "violation", payload)

        if not violation:
            raise RuleConfigError(
                f"{rule_id}: a rule must declare a violation_condition"
            )

        evidence_concepts = list(
            payload.get("evidence_concepts") or sorted(violation)
        )

        for concept in evidence_concepts:

            if concept not in self.known_concepts:
                raise RuleConfigError(
                    f"{rule_id}: evidence concept {concept!r} does not exist in "
                    f"{self.mappings_file}"
                )

        return ExecutionGapRule(
            rule_id=rule_id,
            name=payload.get("name", rule_id),
            capability=capability,
            indicator=payload.get("indicator", rule_id.upper()),
            status=payload.get("status", FINDING_STATUS),
            required_evidence=required,
            expected_condition=expected,
            violation_condition=violation,
            evidence_concepts=evidence_concepts,
            explanation_template=payload.get("explanation_template", []),
            description=payload.get("description", []),
            rationale=payload.get("rationale", []),
            vocabulary_confidence={
                concept: self.vocabulary.get(concept, {})
                for concept in evidence_concepts
            },
        )

    def _build_condition(
        self,
        rule_id: str,
        label: str,
        payload: Mapping[str, Any],
    ) -> Dict[str, Condition]:

        conditions: Dict[str, Condition] = {}

        for concept, spec in (payload.get(f"{label}_condition") or {}).items():

            if concept not in self.known_concepts:
                raise RuleConfigError(
                    f"{rule_id}: {label}_condition references unknown concept "
                    f"{concept!r}"
                )

            vocabulary_key = spec.get("vocabulary_key")

            if not vocabulary_key:
                raise RuleConfigError(
                    f"{rule_id}: {label}_condition for {concept!r} must name a "
                    f"vocabulary_key from value_vocabulary"
                )

            tokens = self.vocabulary.get(concept, {}).get(vocabulary_key)

            if not tokens:
                raise RuleConfigError(
                    f"{rule_id}: value_vocabulary has no entry "
                    f"{concept}.{vocabulary_key}"
                )

            conditions[concept] = Condition(
                concept=concept,
                operator=spec.get("operator", "in"),
                values=tokens,
                vocabulary_key=vocabulary_key,
            )

        return conditions

    def _validate_unique_rule_ids(self) -> None:

        seen = set()

        for rule in self.rules:

            if rule.rule_id in seen:
                raise RuleConfigError(
                    f"duplicate rule_id {rule.rule_id!r}"
                )

            seen.add(rule.rule_id)

    # -- access -------------------------------------------------------------

    def get(self, rule_id: str) -> Optional[ExecutionGapRule]:

        for rule in self.rules:

            if rule.rule_id == rule_id:
                return rule

        return None

    def rules_for_capability(self, capability: str) -> List[ExecutionGapRule]:
        return [rule for rule in self.rules if rule.capability == capability]

    def normalise(self, value: Any) -> str:
        return normalise_value(value, self.separators)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_ids": [rule.rule_id for rule in self.rules],
            "rules": [rule.to_dict() for rule in self.rules],
            "unavailable_rules": [
                rule.to_dict() for rule in self.unavailable_rules
            ],
            "vocabulary": {
                concept: {key: list(values) for key, values in mapping.items()}
                for concept, mapping in self.vocabulary.items()
            },
        }

    def __len__(self) -> int:
        return len(self.rules)

    def __repr__(self) -> str:
        return f"RuleRegistry(rules={len(self.rules)})"


def _load_json(path: str) -> Dict[str, Any]:
    """Read a JSON object from a path relative to the repository root."""

    resolved = path if os.path.isabs(path) else os.path.join(
        os.getcwd(), path
    )

    try:
        with open(resolved, "r") as handle:
            return json.load(handle)

    except FileNotFoundError as error:
        raise RuleConfigError(f"configuration not found: {path}") from error
