"""Operational pattern catalogue.

A pattern here describes *operational shape* inside one assessment scope: how
records are distributed, and how similar submitted evidence is to other
submitted evidence. It deliberately does not describe whether a control was
contradicted, which is the execution-gap layer's job, nor whether evidence that
should exist is absent, which is the negative-space layer's job.

Three things are enforced structurally, because each corresponds to a way this
layer could otherwise mislead a supervisor:

**A pattern must declare an analytical method.** The method is what produces the
number, and the method's minimum observation count is configuration, not a
constant buried in a detector. A scope too small for the method yields
``NOT_EVALUABLE`` rather than a confident-looking result.

**A pattern must declare its minimum observations.** This is why ``3``, ``4``
and ``5`` records cannot produce a statistical signal here: the requirement is
stated in the config file where it can be inspected and challenged, and the
detector refuses to evaluate below it.

**A pattern must carry an explanation limitation.** Every pattern in this
catalogue can produce a signal that is entirely innocent, and the catalogue
refuses to load one that does not say so.

Shared with the execution-gap and negative-space rule layers: value
normalisation, canonical concept validation against ``mappings.json``, and
capability validation against the eight capabilities.
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

DEFAULT_OPERATIONAL_PATTERN_CONFIG = (
    "framework/config/operational_pattern_rules.json"
)

POTENTIAL_OPERATIONAL_ANOMALY = "POTENTIAL_OPERATIONAL_ANOMALY"
NOT_EVALUABLE = "NOT_EVALUABLE"
NO_PATTERN_DETECTED = "NO_PATTERN_DETECTED"
EVIDENCE_NOT_PRESENT = "EVIDENCE_NOT_PRESENT"


class Method:
    """An analytical method and the observations it requires."""

    def __init__(
        self,
        name: str,
        definition: Mapping[str, Any],
    ) -> None:

        self.name = name
        self.definition = dict(definition)
        self.summary = list(definition.get("summary", []))
        self.null_hypothesis = definition.get("null_hypothesis")
        self.executable = bool(definition.get("executable"))

        minimums = definition.get("minimum_observations") or {}

        self.minimums = {
            key: value
            for key, value in minimums.items()
            if not key.startswith("_")
        }

        if not self.minimums:
            raise RuleConfigError(
                f"method {name!r} must declare minimum_observations, so the "
                f"small-sample requirement is inspectable configuration rather "
                f"than a constant inside detector code"
            )

    def minimum(self, key: str) -> int:
        return int(self.minimums[key])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.name,
            "summary": list(self.summary),
            "null_hypothesis": self.null_hypothesis,
            "executable": self.executable,
            "minimum_observations": dict(self.minimums),
        }


class OperationalPattern:
    """A configured operational pattern and the method that evaluates it."""

    def __init__(
        self,
        pattern_id: str,
        indicator: str,
        name: str,
        pattern_type: str,
        capability: str,
        status: str,
        method: Method,
        group_concept: str,
        population_concept: str,
        evidence_concepts: Sequence[str],
        text_concept: Optional[str],
        reason_template: Sequence[str],
        why_review_might_be_warranted: Sequence[str],
        explanation_limitations: Sequence[str],
        description: Sequence[str] = (),
        content_disclosure: Sequence[str] = (),
    ) -> None:

        self.pattern_id = pattern_id
        self.indicator = indicator
        self.name = name
        self.pattern_type = pattern_type
        self.capability = capability
        self.status = status
        self.method = method
        self.group_concept = group_concept
        self.population_concept = population_concept
        self.evidence_concepts = list(evidence_concepts)
        self.text_concept = text_concept
        self.reason_template = list(reason_template)
        self.why_review_might_be_warranted = list(
            why_review_might_be_warranted
        )
        self.explanation_limitations = list(explanation_limitations)
        self.description = list(description)
        self.content_disclosure = list(content_disclosure)

    def render_reason(self, **values: Any) -> str:
        """Fill the reason template, leaving unknown placeholders visible.

        A missing value is rendered rather than dropped, so an incomplete
        explanation is obvious instead of quietly reading as a complete one.
        """

        rendered = []

        for line in self.reason_template:

            try:
                rendered.append(line.format(**values))
            except (KeyError, IndexError, ValueError):
                rendered.append(line.strip())

        return " ".join(part for part in rendered if part)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "indicator": self.indicator,
            "name": self.name,
            "pattern_type": self.pattern_type,
            "capability": self.capability,
            "status": self.status,
            "method": self.method.name,
            "group_concept": self.group_concept,
            "population_concept": self.population_concept,
            "text_concept": self.text_concept,
            "evidence_concepts": list(self.evidence_concepts),
            "description": list(self.description),
            "reason_template": list(self.reason_template),
            "why_review_might_be_warranted": list(
                self.why_review_might_be_warranted
            ),
            "explanation_limitations": list(self.explanation_limitations),
            "content_disclosure": list(self.content_disclosure),
        }


class UnavailablePattern(UnavailableRule):
    """An operational pattern deliberately not implemented, and why.

    Extends the shared :class:`UnavailableRule` so the reasoning, missing
    evidence and requirements are recorded identically to the execution-gap and
    negative-space layers, while keeping the pattern vocabulary (``pattern_id``,
    ``indicator``, ``pattern_type``) that those layers have no use for.

    The shared class reads ``rule_id``; this maps it from ``pattern_id`` so a
    pattern unavailable for want of evidence is as visible to a reviewer as a
    supervisory rule unavailable for want of evidence.
    """

    def __init__(self, payload: Mapping[str, Any]) -> None:

        super().__init__(payload)

        self.pattern_id = payload.get("pattern_id") or self.rule_id
        self.rule_id = self.pattern_id
        self.indicator = payload.get("indicator")
        self.pattern_type = payload.get("pattern_type")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "indicator": self.indicator,
            "pattern_type": self.pattern_type,
            "name": self.name,
            "capability": self.capability,
            "status": self.status,
            "missing_evidence": list(self.missing_evidence),
            "why_not_implemented": list(self.why_not_implemented),
            "would_require": list(self.would_require),
        }


class OperationalPatternRegistry:
    """Loads and validates operational pattern configuration."""

    def __init__(
        self,
        config_file: str = DEFAULT_OPERATIONAL_PATTERN_CONFIG,
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

        self.alpha = float(
            self.config.get("statistical_parameters", {}).get("alpha", 0.01)
        )

        if not 0.0 < self.alpha < 1.0:
            raise RuleConfigError(
                f"statistical_parameters.alpha must be strictly between 0 and "
                f"1, got {self.alpha!r}"
            )

        self.methods = {
            name: Method(name, definition)
            for name, definition in (
                self.config.get("methodology") or {}
            ).items()
            if not name.startswith("_")
        }

        self.repetition_similarity = self._repetition_similarity()

        self.patterns: List[OperationalPattern] = [
            self._build_pattern(payload)
            for payload in self.config.get("patterns", [])
        ]

        self.unavailable_patterns: List[UnavailablePattern] = [
            UnavailablePattern(payload)
            for payload in self.config.get("unavailable_patterns", [])
        ]

        self._validate_unique_ids()

    # -- configuration helpers ---------------------------------------------

    def _repetition_similarity(self) -> float:
        method = self.methods.get("investigation_repetition") or {}

        definition = method.definition or {}

        threshold = definition.get("min_similarity")

        if threshold is None:
            raise RuleConfigError(
                "methodology.investigation_repetition must declare "
                "min_similarity as explicit configuration"
            )

        threshold = float(threshold)

        if not 0.0 < threshold <= 1.0:
            raise RuleConfigError(
                f"investigation_repetition.min_similarity must be in (0, 1], "
                f"got {threshold!r}"
            )

        return threshold

    def _build_pattern(
        self, payload: Mapping[str, Any]
    ) -> OperationalPattern:

        pattern_id = payload.get("pattern_id")

        if not pattern_id:
            raise RuleConfigError("a pattern is missing its pattern_id")

        capability = payload.get("capability")

        if capability not in self.known_capabilities:
            raise RuleConfigError(
                f"{pattern_id}: capability {capability!r} is not one of the "
                f"eight defined capabilities"
            )

        status = payload.get("status")

        if status != POTENTIAL_OPERATIONAL_ANOMALY:
            raise RuleConfigError(
                f"{pattern_id}: status must be "
                f"{POTENTIAL_OPERATIONAL_ANOMALY!r}. An operational pattern is "
                f"a request for review, not an established weakness, so no "
                f"other status may be configured here."
            )

        method_name = payload.get("method")

        method = self.methods.get(method_name)

        if method is None:
            raise RuleConfigError(
                f"{pattern_id}: method {method_name!r} is not defined under "
                f"methodology"
            )

        if not method.executable:
            raise RuleConfigError(
                f"{pattern_id}: method {method_name!r} is not executable and "
                f"cannot back a pattern"
            )

        population_concept = payload.get("population_concept")
        group_concept = payload.get("group_concept")
        text_concept = payload.get("text_concept")

        for concept in (population_concept, group_concept, text_concept):

            if concept is None:
                continue

            if concept not in self.known_concepts:
                raise RuleConfigError(
                    f"{pattern_id}: concept {concept!r} does not exist in "
                    f"{self.mappings_file}"
                )

        if not payload.get("reason_template"):
            raise RuleConfigError(
                f"{pattern_id}: a reason_template is required, so every signal "
                f"can state what was unusual and how it was determined"
            )

        if not payload.get("explanation_limitations"):
            raise RuleConfigError(
                f"{pattern_id}: explanation_limitations is required. Every "
                f"operational pattern has innocent explanations, and a pattern "
                f"that cannot state them would read as more conclusive than it "
                f"is."
            )

        if not payload.get("why_review_might_be_warranted"):
            raise RuleConfigError(
                f"{pattern_id}: why_review_might_be_warranted is required, so "
                f"a supervisor is told what inspecting the signal could "
                f"actually reveal"
            )

        evidence_concepts = list(payload.get("evidence_concepts") or [])

        for concept in evidence_concepts:

            if concept not in self.known_concepts:
                raise RuleConfigError(
                    f"{pattern_id}: evidence concept {concept!r} does not "
                    f"exist in {self.mappings_file}"
                )

        return OperationalPattern(
            pattern_id=pattern_id,
            indicator=payload.get("indicator", pattern_id.upper()),
            name=payload.get("name", pattern_id),
            pattern_type=payload.get("pattern_type", "UNSPECIFIED"),
            capability=capability,
            status=status,
            method=method,
            group_concept=group_concept,
            population_concept=population_concept,
            evidence_concepts=evidence_concepts,
            text_concept=text_concept,
            reason_template=payload["reason_template"],
            why_review_might_be_warranted=payload[
                "why_review_might_be_warranted"
            ],
            explanation_limitations=payload["explanation_limitations"],
            description=payload.get("description", []),
            content_disclosure=payload.get("content_disclosure", []),
        )

    def _validate_unique_ids(self) -> None:

        seen = set()

        for pattern in self.patterns:

            if pattern.pattern_id in seen:
                raise RuleConfigError(
                    f"duplicate pattern_id {pattern.pattern_id!r}"
                )

            seen.add(pattern.pattern_id)

    # -- access -------------------------------------------------------------

    def get(self, pattern_id: str) -> Optional[OperationalPattern]:

        for pattern in self.patterns:

            if pattern.pattern_id == pattern_id:
                return pattern

        return None

    def normalise(self, value: Any) -> str:
        return normalise_value(value, self.separators)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_ids": [item.pattern_id for item in self.patterns],
            "patterns": [item.to_dict() for item in self.patterns],
            "methods": {
                name: method.to_dict() for name, method in self.methods.items()
            },
            "statistical_parameters": {"alpha": self.alpha},
            "unavailable_patterns": [
                item.to_dict() for item in self.unavailable_patterns
            ],
        }

    def __len__(self) -> int:
        return len(self.patterns)

    def __repr__(self) -> str:
        return (
            f"OperationalPatternRegistry(patterns={len(self.patterns)}, "
            f"unavailable={len(self.unavailable_patterns)})"
        )


class OperationalPatternCatalogue:
    """Implemented operational patterns plus the unavailable ones."""

    def __init__(
        self,
        config_file: str = DEFAULT_OPERATIONAL_PATTERN_CONFIG,
        mappings_file: str = DEFAULT_MAPPINGS_CONFIG,
        capabilities_file: str = DEFAULT_CAPABILITIES_CONFIG,
    ) -> None:

        self.registry = OperationalPatternRegistry(
            config_file=config_file,
            mappings_file=mappings_file,
            capabilities_file=capabilities_file,
        )

    @property
    def patterns(self):
        return self.registry.patterns

    @property
    def unavailable_patterns(self):
        return self.registry.unavailable_patterns

    def get(self, pattern_id: str) -> Optional[OperationalPattern]:
        return self.registry.get(pattern_id)

    def to_dict(self):
        return self.registry.to_dict()

    def __len__(self) -> int:
        return len(self.registry.patterns)

    def __repr__(self) -> str:
        return (
            f"OperationalPatternCatalogue(available={len(self.registry.patterns)}, "
            f"unavailable={len(self.registry.unavailable_patterns)})"
        )


def _load_json(path: str) -> Dict[str, Any]:
    resolved = (
        path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    )

    try:
        with open(resolved, "r") as handle:
            return json.load(handle)

    except FileNotFoundError as error:
        raise RuleConfigError(f"configuration not found: {path}") from error
