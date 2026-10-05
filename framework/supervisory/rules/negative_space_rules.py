"""Negative-space rule catalogue.

A negative-space rule declares an *expectation*, a *trigger population* that
makes that expectation apply, the *observable concept* the evidence is read
from, and *why* the evidence is expected. All four live in
``framework/config/negative_space_rules.json``; this module is the importable,
validated surface for them.

The distinction this module enforces is the one the whole layer turns on::

    expected evidence  +  context that makes it expected  +  observed absence
                        -> potential negative space

A rule cannot be constructed without a trigger population. That is deliberate:
a rule with no trigger degenerates into "this field is empty", which is not a
finding. Validation also requires the expectation to state a basis and a
rationale, so a rule cannot present an assumption as a supervisory fact.

Shared with the execution-gap rules: value normalisation, concept validation
against ``mappings.json``, and capability validation against the eight
capabilities. Deliberately *not* shared: the rule contents. Importing one
detector's rule configuration from another would couple two independent
supervisory judgements, so the negative-space configuration restates the two
escalation outcome tokens it relies on, and the test suite asserts the two
configurations agree.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.supervisory.rules.rule_engine import (
    DEFAULT_CAPABILITIES_CONFIG,
    DEFAULT_MAPPINGS_CONFIG,
    RuleConfigError,
    UnavailableRule,
    normalise_value,
)

DEFAULT_NEGATIVE_SPACE_CONFIG = "framework/config/negative_space_rules.json"

COMPLETE_ABSENCE = "COMPLETE_ABSENCE"
PARTIAL_ABSENCE = "PARTIAL_ABSENCE"
NO_ABSENCE = "NO_ABSENCE"
EXPECTATION_NOT_TRIGGERED = "EXPECTATION_NOT_TRIGGERED"
NOT_EVALUABLE = "NOT_EVALUABLE"

ABSENCE_STATES = (
    COMPLETE_ABSENCE,
    PARTIAL_ABSENCE,
    NO_ABSENCE,
    EXPECTATION_NOT_TRIGGERED,
    NOT_EVALUABLE,
)


class ExpectedEvidence:
    """One observable concept an expectation looks for."""

    def __init__(
        self,
        concept: str,
        accepted_tokens: Sequence[str],
        vocabulary_keys: Sequence[str],
    ) -> None:

        self.concept = concept
        self.accepted_tokens = list(accepted_tokens)
        self.vocabulary_keys = list(vocabulary_keys)

    def accepts(self, normalised: str) -> bool:
        """True when a normalised value constitutes submitted evidence.

        Only the configured tokens count. A populated value outside them means
        a determination was not actually recorded, which is reported as
        unusable evidence rather than being treated as present.
        """

        if not normalised:
            return False

        return normalised in self.accepted_tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept": self.concept,
            "accepted_vocabulary_keys": list(self.vocabulary_keys),
            "accepted_tokens": list(self.accepted_tokens),
        }


class NegativeSpaceRule:
    """A configured expectation of evidence, with the context that creates it."""

    def __init__(
        self,
        rule_id: str,
        name: str,
        capability: str,
        indicator: str,
        statement: str,
        basis: str,
        population_concept: str,
        population_tokens: Sequence[str],
        population_label: str,
        expected_evidence: Sequence[ExpectedEvidence],
        why_expected: Sequence[str],
        complete_absence_status: str,
        partial_absence_status: str,
        material_coverage_threshold: Optional[float],
        evidence_concepts: Sequence[str],
        reason_template: Sequence[str],
        partial_reason_template: Sequence[str],
        description: Sequence[str] = (),
        rationale: Sequence[str] = (),
    ) -> None:

        self.rule_id = rule_id
        self.name = name
        self.capability = capability
        self.indicator = indicator
        self.statement = statement
        self.basis = basis
        self.population_concept = population_concept
        self.population_tokens = list(population_tokens)
        self.population_label = population_label
        self.expected_evidence = list(expected_evidence)
        self.why_expected = list(why_expected)
        self.complete_absence_status = complete_absence_status
        self.partial_absence_status = partial_absence_status
        self.material_coverage_threshold = material_coverage_threshold
        self.evidence_concepts = list(evidence_concepts)
        self.reason_template = list(reason_template)
        self.partial_reason_template = list(partial_reason_template)
        self.description = list(description)
        self.rationale = list(rationale)

    @property
    def primary_expected_concept(self) -> str:
        return self.expected_evidence[0].concept

    def is_triggered_by(self, normalised_population_value: str) -> bool:
        """True when a record belongs to the population that creates the duty."""

        if not normalised_population_value:
            return False

        return normalised_population_value in self.population_tokens

    def render_reason(self, partial: bool) -> str:
        template = (
            self.partial_reason_template if partial else self.reason_template
        ) or self.reason_template

        return " ".join(line.strip() for line in template if line.strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "capability": self.capability,
            "indicator": self.indicator,
            "expectation": {
                "statement": self.statement,
                "basis": self.basis,
                "trigger": {
                    "concept": self.population_concept,
                    "vocabulary_key": self.population_label,
                    "population_label": self.population_label,
                },
                "expected_evidence": [
                    item.to_dict() for item in self.expected_evidence
                ],
                "why_expected": list(self.why_expected),
            },
            "classification": {
                "complete_absence_status": self.complete_absence_status,
                "partial_absence_status": self.partial_absence_status,
                "material_coverage_threshold": (
                    self.material_coverage_threshold
                ),
            },
            "evidence_concepts": list(self.evidence_concepts),
            "description": list(self.description),
            "rationale": list(self.rationale),
        }


class NegativeSpaceRegistry:
    """Loads and validates negative-space rules from configuration."""

    def __init__(
        self,
        config_file: str = DEFAULT_NEGATIVE_SPACE_CONFIG,
        mappings_file: str = DEFAULT_MAPPINGS_CONFIG,
        capabilities_file: str = DEFAULT_CAPABILITIES_CONFIG,
    ) -> None:

        self.config_file = config_file
        self.mappings_file = mappings_file
        self.capabilities_file = capabilities_file

        self.config = _load_json(config_file)

        self.known_concepts = set(_load_json(mappings_file).keys())

        self.known_capabilities = set(
            _load_json(capabilities_file).get("capabilities", {}).keys()
        )

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

        self.rules: List[NegativeSpaceRule] = [
            self._build_rule(payload)
            for payload in self.config.get("rules", [])
        ]

        self.unavailable_rules: List[UnavailableRule] = [
            UnavailableRule(payload)
            for payload in self.config.get("unavailable_rules", [])
        ]

        self._validate_unique_ids()

    # -- construction -------------------------------------------------------

    def _tokens_for(
        self, rule_id: str, concept: str, vocabulary_key: str
    ) -> List[str]:
        tokens = self.vocabulary.get(concept, {}).get(vocabulary_key)

        if not tokens:
            raise RuleConfigError(
                f"{rule_id}: value_vocabulary has no entry "
                f"{concept}.{vocabulary_key}"
            )

        return tokens

    def _build_rule(self, payload: Mapping[str, Any]) -> NegativeSpaceRule:

        rule_id = payload.get("rule_id")

        if not rule_id:
            raise RuleConfigError("a rule is missing its rule_id")

        capability = payload.get("capability")

        if capability not in self.known_capabilities:
            raise RuleConfigError(
                f"{rule_id}: capability {capability!r} is not one of the eight "
                f"defined capabilities"
            )

        expectation = payload.get("expectation") or {}

        statement = expectation.get("statement")
        basis = expectation.get("basis")
        why_expected = expectation.get("why_expected") or []

        if not statement:
            raise RuleConfigError(
                f"{rule_id}: an expectation statement is required. A rule with "
                f"no stated expectation would fire on an empty field, which is "
                f"not a negative-space finding."
            )

        if not basis:
            raise RuleConfigError(
                f"{rule_id}: the expectation must declare its basis, so a "
                f"configured expectation is never presented as a discovered fact"
            )

        if not why_expected:
            raise RuleConfigError(
                f"{rule_id}: the expectation must explain why the evidence is "
                f"expected"
            )

        trigger = expectation.get("trigger") or {}
        trigger_concept = trigger.get("concept")
        trigger_key = trigger.get("vocabulary_key")

        if not trigger_concept or not trigger_key:
            raise RuleConfigError(
                f"{rule_id}: the expectation must name a trigger population, i.e. "
                f"the records for which the evidence is expected"
            )

        if trigger_concept not in self.known_concepts:
            raise RuleConfigError(
                f"{rule_id}: trigger concept {trigger_concept!r} does not exist "
                f"in {self.mappings_file}"
            )

        expected_specs = expectation.get("expected_evidence") or []

        if not expected_specs:
            raise RuleConfigError(
                f"{rule_id}: the expectation must name at least one observable "
                f"evidence concept"
            )

        expected_evidence: List[ExpectedEvidence] = []

        for spec in expected_specs:

            concept = spec.get("concept")

            if concept not in self.known_concepts:
                raise RuleConfigError(
                    f"{rule_id}: expected evidence concept {concept!r} does not "
                    f"exist in {self.mappings_file}"
                )

            keys = spec.get("accepted_vocabulary_keys") or []

            if not keys:
                raise RuleConfigError(
                    f"{rule_id}: expected evidence {concept!r} must declare the "
                    f"values that constitute submitted evidence"
                )

            tokens: List[str] = []

            for key in keys:
                tokens.extend(self._tokens_for(rule_id, concept, key))

            expected_evidence.append(
                ExpectedEvidence(
                    concept=concept,
                    accepted_tokens=sorted(set(tokens)),
                    vocabulary_keys=keys,
                )
            )

        classification = payload.get("classification") or {}

        if not classification.get("complete_absence_status"):
            raise RuleConfigError(
                f"{rule_id}: classification.complete_absence_status is required"
            )

        if not classification.get("partial_absence_status"):
            raise RuleConfigError(
                f"{rule_id}: classification.partial_absence_status is required"
            )

        threshold = classification.get("material_coverage_threshold")

        if threshold is not None:

            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                raise RuleConfigError(
                    f"{rule_id}: material_coverage_threshold must be null or a "
                    f"number between 0 and 1"
                )

            if not 0.0 <= float(threshold) <= 1.0:
                raise RuleConfigError(
                    f"{rule_id}: material_coverage_threshold must be between 0 "
                    f"and 1, got {threshold!r}"
                )

        evidence_concepts = list(
            payload.get("evidence_concepts")
            or [trigger_concept] + [item.concept for item in expected_evidence]
        )

        for concept in evidence_concepts:

            if concept not in self.known_concepts:
                raise RuleConfigError(
                    f"{rule_id}: evidence concept {concept!r} does not exist in "
                    f"{self.mappings_file}"
                )

        return NegativeSpaceRule(
            rule_id=rule_id,
            name=payload.get("name", rule_id),
            capability=capability,
            indicator=payload.get("indicator", rule_id.upper()),
            statement=statement,
            basis=basis,
            population_concept=trigger_concept,
            population_tokens=self._tokens_for(
                rule_id, trigger_concept, trigger_key
            ),
            population_label=trigger.get(
                "population_label", trigger_key
            ).upper(),
            expected_evidence=expected_evidence,
            why_expected=why_expected,
            complete_absence_status=classification["complete_absence_status"],
            partial_absence_status=classification["partial_absence_status"],
            material_coverage_threshold=(
                None if threshold is None else float(threshold)
            ),
            evidence_concepts=evidence_concepts,
            reason_template=payload.get("reason_template", []),
            partial_reason_template=payload.get(
                "partial_reason_template", []
            ),
            description=payload.get("description", []),
            rationale=payload.get("rationale", []),
        )

    def _validate_unique_ids(self) -> None:

        seen = set()

        for rule in self.rules:

            if rule.rule_id in seen:
                raise RuleConfigError(f"duplicate rule_id {rule.rule_id!r}")

            seen.add(rule.rule_id)

    # -- access -------------------------------------------------------------

    def get(self, rule_id: str) -> Optional[NegativeSpaceRule]:

        for rule in self.rules:

            if rule.rule_id == rule_id:
                return rule

        return None

    def normalise(self, value: Any) -> str:
        return normalise_value(value, self.separators)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_ids": [rule.rule_id for rule in self.rules],
            "rules": [rule.to_dict() for rule in self.rules],
            "unavailable_rules": [
                rule.to_dict() for rule in self.unavailable_rules
            ],
        }

    def __len__(self) -> int:
        return len(self.rules)

    def __repr__(self) -> str:
        return f"NegativeSpaceRegistry(rules={len(self.rules)})"


class NegativeSpaceCatalogue:
    """Implemented negative-space rules plus the unavailable expectations."""

    def __init__(
        self,
        config_file: str = DEFAULT_NEGATIVE_SPACE_CONFIG,
        mappings_file: str = DEFAULT_MAPPINGS_CONFIG,
        capabilities_file: str = DEFAULT_CAPABILITIES_CONFIG,
    ) -> None:

        self.registry = NegativeSpaceRegistry(
            config_file=config_file,
            mappings_file=mappings_file,
            capabilities_file=capabilities_file,
        )

    @property
    def rules(self):
        return self.registry.rules

    @property
    def unavailable_rules(self):
        return self.registry.unavailable_rules

    def to_dict(self):
        return self.registry.to_dict()

    def __len__(self) -> int:
        return len(self.registry.rules)

    def __repr__(self) -> str:
        return (
            f"NegativeSpaceCatalogue(available={len(self.registry.rules)}, "
            f"unavailable={len(self.registry.unavailable_rules)})"
        )


def _load_json(path: str) -> Dict[str, Any]:
    resolved = path if os.path.isabs(path) else os.path.join(
        os.getcwd(), path
    )

    try:
        with open(resolved, "r") as handle:
            return json.load(handle)

    except FileNotFoundError as error:
        raise RuleConfigError(f"configuration not found: {path}") from error
