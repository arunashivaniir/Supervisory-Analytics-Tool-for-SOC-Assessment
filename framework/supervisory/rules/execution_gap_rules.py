"""Execution-gap rule catalogue.

Owns the supervisory expectations SAT-SA can actually defend, and the record of
the ones it deliberately cannot. The expectations themselves live in
``framework/config/execution_gap_rules.json``; this module is the importable
surface for loading and querying them.

The important property of this catalogue is that it distinguishes three things
that are easy to conflate:

* an **implemented rule** -- the evidence to prove it exists;
* an **unavailable rule** -- a real expectation with named, specific missing
  evidence, so the limitation is visible rather than inferred from silence;
* a **not-yet-considered rule** -- nothing declared at all.

Only the first produces findings. The second is reported so a supervisory
reader can tell the difference between "SAT-SA found no gap here" and "SAT-SA
cannot make this determination from the evidence available".
"""

from __future__ import annotations

from framework.supervisory.rules.rule_engine import (
    DEFAULT_CAPABILITIES_CONFIG,
    DEFAULT_MAPPINGS_CONFIG,
    DEFAULT_RULES_CONFIG,
    EXPECTATION_SATISFIED,
    EXPECTATION_VIOLATED,
    FINDING_STATUS,
    NOT_APPLICABLE,
    NOT_EVALUABLE,
    Condition,
    ExecutionGapRule,
    RuleConfigError,
    RuleEvaluation,
    RuleRegistry,
    UnavailableRule,
    normalise_value,
)

__all__ = [
    "DEFAULT_CAPABILITIES_CONFIG",
    "DEFAULT_MAPPINGS_CONFIG",
    "DEFAULT_RULES_CONFIG",
    "EXPECTATION_SATISFIED",
    "EXPECTATION_VIOLATED",
    "FINDING_STATUS",
    "NOT_APPLICABLE",
    "NOT_EVALUABLE",
    "Condition",
    "ExecutionGapCatalogue",
    "ExecutionGapRule",
    "RuleConfigError",
    "RuleEvaluation",
    "RuleRegistry",
    "UnavailableRule",
    "normalise_value",
]


class ExecutionGapCatalogue:
    """Implemented rules plus the explicitly unavailable expectations."""

    def __init__(
        self,
        config_file: str = DEFAULT_RULES_CONFIG,
        mappings_file: str = DEFAULT_MAPPINGS_CONFIG,
        capabilities_file: str = DEFAULT_CAPABILITIES_CONFIG,
    ) -> None:

        self.registry = RuleRegistry(
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

    def unavailable_for(self, capability: str):
        """Unavailable expectations aimed at one capability."""

        return [
            rule
            for rule in self.unavailable_rules
            if rule.capability == capability
        ]

    def to_dict(self):
        payload = self.registry.to_dict()

        payload["unavailable_capabilities"] = sorted(
            {
                rule.capability
                for rule in self.unavailable_rules
                if rule.capability
            }
        )

        return payload

    def __len__(self) -> int:
        return len(self.registry.rules)

    def __repr__(self) -> str:
        return (
            f"ExecutionGapCatalogue(available={len(self.registry.rules)}, "
            f"unavailable={len(self.unavailable_rules)})"
        )
