"""
SAT-SA capability registry.

Loads and validates the eight SOC capability definitions from
``framework/config/capabilities.json``.

The registry exists to make one guarantee: **a capability definition can only
refer to evidence that already exists in SAT-SA.** Every declared evidence item
must name either an existing canonical path in
``framework/canonical/canonical_schema.json`` or a concept already present in
``framework/config/mappings.json``. A definition that names an unknown field or
an invented concept is rejected when the registry loads, not silently ignored.

That guarantee is what allows the capability layer to be evidence-aware without
becoming a second source of truth. The canonical schema remains the only
definition of what evidence SAT-SA understands.

What a definition contains
--------------------------

``capability_id``
    Stable identifier, e.g. ``INVESTIGATION``.
``name`` / ``description``
    Human-facing identity and intent.
``primary_evidence``
    Evidence without which the capability cannot be assessed.
``supporting_evidence``
    Evidence that enriches the assessment. Not mandatory.
``minimum_evidence``
    ``{"primary": n, "total": m}`` -- the explicit, configurable thresholds that
    decide ``AVAILABLE``. No status is hardcoded per dataset.
``indicator_categories``
    Names from the existing ``framework.features.feature_registry``, establishing
    the relationship between a capability and indicators that existing detectors
    already emit. The registry declares the relationship and never generates a
    finding.
``indicator_emitted_by``
    For each indicator, which existing detector emits it, or ``"declared"`` when
    the relationship is registered but no detector produces it yet.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

DEFAULT_CAPABILITY_CONFIG = "framework/config/capabilities.json"
DEFAULT_MAPPINGS_CONFIG = "framework/config/mappings.json"
DEFAULT_SCHEMA_CONFIG = "framework/canonical/canonical_schema.json"

REQUIRED_CAPABILITIES = (
    "THREAT_DETECTION",
    "INVESTIGATION",
    "ESCALATION",
    "INCIDENT_RESPONSE",
    "SECURITY_OPERATIONS",
    "GOVERNANCE_OVERSIGHT",
    "OPERATIONAL_DISCIPLINE",
    "CYBER_RESILIENCE",
)


class CapabilityRegistryError(Exception):
    """Raised when a capability definition refers to unknown SAT-SA evidence."""


def _load_json(path: str) -> Dict[str, Any]:

    with open(path, "r") as handle:

        return json.load(handle)


def _canonical_paths(schema: Mapping[str, Any], prefix: str = "") -> List[str]:
    """Flatten the canonical schema into dotted paths of leaf fields."""

    paths: List[str] = []

    for key, value in schema.items():

        path = f"{prefix}.{key}" if prefix else key

        if isinstance(value, Mapping):
            paths.extend(_canonical_paths(value, path))
        else:
            paths.append(path)

    return paths


class EvidenceRequirement:
    """One declared piece of evidence a capability needs."""

    def __init__(
        self,
        canonical_path: str,
        concept: Optional[str],
        role: str,
        discoverable: bool,
    ) -> None:

        self.canonical_path = canonical_path
        self.concept = concept
        self.role = role
        self.discoverable = discoverable

    def to_dict(self) -> Dict[str, Any]:

        return {
            "canonical_path": self.canonical_path,
            "concept": self.concept,
            "role": self.role,
            "discoverable": self.discoverable,
        }

    def __repr__(self) -> str:

        return f"EvidenceRequirement({self.canonical_path!r}, concept={self.concept!r})"


class CapabilityDefinition:
    """One of the eight SOC capabilities, with its evidence requirements."""

    def __init__(
        self,
        capability_id: str,
        name: str,
        description: str,
        primary_evidence: Sequence[EvidenceRequirement],
        supporting_evidence: Sequence[EvidenceRequirement],
        minimum_evidence: Mapping[str, int],
        indicator_categories: Sequence[str],
        indicator_emitted_by: Mapping[str, str],
        note: Optional[str] = None,
    ) -> None:

        self.capability_id = capability_id
        self.name = name
        self.description = description
        self.primary_evidence: List[EvidenceRequirement] = list(primary_evidence)
        self.supporting_evidence: List[EvidenceRequirement] = list(supporting_evidence)
        self.minimum_evidence = {
            "primary": int(minimum_evidence.get("primary", 1)),
            "total": int(minimum_evidence.get("total", 1)),
        }
        self.indicator_categories: List[str] = list(indicator_categories)
        self.indicator_emitted_by: Dict[str, str] = dict(indicator_emitted_by)
        self.note = note

    @property
    def all_evidence(self) -> List[EvidenceRequirement]:
        return list(self.primary_evidence) + list(self.supporting_evidence)

    @property
    def declared_evidence_count(self) -> int:
        return len(self.primary_evidence) + len(self.supporting_evidence)

    @property
    def undiscoverable_evidence(self) -> List[str]:
        """Canonical fields this capability needs that no source column can fill.

        These are real requirements with no path from a source column today,
        because the canonical field has no concept in ``mappings.json``. They are
        reported rather than worked around.
        """

        return [
            requirement.canonical_path
            for requirement in self.all_evidence
            if not requirement.discoverable
        ]

    def to_dict(self) -> Dict[str, Any]:

        payload: Dict[str, Any] = {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "primary_evidence": [item.to_dict() for item in self.primary_evidence],
            "supporting_evidence": [item.to_dict() for item in self.supporting_evidence],
            "minimum_evidence": dict(self.minimum_evidence),
            "indicator_categories": list(self.indicator_categories),
            "indicator_emitted_by": dict(self.indicator_emitted_by),
            "undiscoverable_evidence": list(self.undiscoverable_evidence),
            "undiscoverable_evidence_count": len(self.undiscoverable_evidence),
        }

        if self.note:
            payload["note"] = self.note

        return payload

    def __repr__(self) -> str:

        return f"CapabilityDefinition({self.capability_id!r})"


class CapabilityRegistry:
    """The validated set of capability definitions.

    Loading validates every reference, so a capability can never claim evidence
    SAT-SA does not actually have.
    """

    def __init__(
        self,
        config_file: str = DEFAULT_CAPABILITY_CONFIG,
        mappings_file: str = DEFAULT_MAPPINGS_CONFIG,
        schema_file: str = DEFAULT_SCHEMA_CONFIG,
    ) -> None:

        self.config_file = config_file
        self.mappings_file = mappings_file
        self.schema_file = schema_file

        raw = _load_json(config_file)
        self.mappings: Dict[str, Any] = _load_json(mappings_file)
        self.schema: Dict[str, Any] = _load_json(schema_file)

        self.known_paths = set(_canonical_paths(self.schema))
        self.known_concepts = set(self.mappings)
        self.concept_to_path = {
            concept: entry["canonical_path"]
            for concept, entry in self.mappings.items()
            if isinstance(entry, Mapping) and entry.get("canonical_path")
        }

        definitions = raw.get("capabilities", raw)

        self.capabilities: Dict[str, CapabilityDefinition] = {
            capability_id: self._build(capability_id, payload)
            for capability_id, payload in definitions.items()
        }

        self._validate()

    def _build_evidence(
        self,
        capability_id: str,
        items: Sequence[Mapping[str, Any]],
    ) -> List[EvidenceRequirement]:

        requirements: List[EvidenceRequirement] = []

        for item in items:

            path = item.get("canonical_path")
            concept = item.get("concept")

            if not path:
                raise CapabilityRegistryError(
                    f"{capability_id}: evidence item without canonical_path"
                )

            if path not in self.known_paths:
                raise CapabilityRegistryError(
                    f"{capability_id}: canonical path {path!r} does not exist in "
                    f"{self.schema_file}. Capability definitions may not invent "
                    "canonical fields."
                )

            if concept is not None and concept not in self.known_concepts:
                raise CapabilityRegistryError(
                    f"{capability_id}: concept {concept!r} does not exist in "
                    f"{self.mappings_file}. Capability definitions may not invent "
                    "canonical concepts."
                )

            if concept is not None:

                mapped_path = self.concept_to_path.get(concept)

                if mapped_path != path:
                    raise CapabilityRegistryError(
                        f"{capability_id}: concept {concept!r} maps to "
                        f"{mapped_path!r} but is declared against {path!r}"
                    )

            requirements.append(
                EvidenceRequirement(
                    canonical_path=path,
                    concept=concept,
                    role=item.get("role", ""),
                    discoverable=concept is not None,
                )
            )

        return requirements

    def _build(
        self,
        capability_id: str,
        payload: Mapping[str, Any],
    ) -> CapabilityDefinition:

        minimum = payload.get("minimum_evidence", {})

        if not isinstance(minimum, Mapping):
            raise CapabilityRegistryError(
                f"{capability_id}: minimum_evidence must be an object"
            )

        primary = self._build_evidence(
            capability_id, payload.get("primary_evidence", [])
        )

        supporting = self._build_evidence(
            capability_id, payload.get("supporting_evidence", [])
        )

        if not primary and int(minimum.get("primary", 0)) > 0:
            raise CapabilityRegistryError(
                f"{capability_id}: minimum_evidence.primary is "
                f"{minimum.get('primary')} but no primary evidence is declared"
            )

        return CapabilityDefinition(
            capability_id=capability_id,
            name=payload.get("name", capability_id),
            description=payload.get("description", ""),
            primary_evidence=primary,
            supporting_evidence=supporting,
            minimum_evidence=minimum,
            indicator_categories=payload.get("indicator_categories", []),
            indicator_emitted_by=payload.get("indicator_emitted_by", {}),
            note=payload.get("_note"),
        )

    def _validate(self) -> None:

        missing = [
            capability_id
            for capability_id in REQUIRED_CAPABILITIES
            if capability_id not in self.capabilities
        ]

        if missing:
            raise CapabilityRegistryError(
                f"registry is missing required capabilities: {', '.join(missing)}"
            )

        unexpected = [
            capability_id
            for capability_id in self.capabilities
            if capability_id not in REQUIRED_CAPABILITIES
        ]

        if unexpected:
            raise CapabilityRegistryError(
                f"registry defines unexpected capabilities: {', '.join(unexpected)}"
            )

        for capability_id, definition in self.capabilities.items():

            declared = {
                requirement.canonical_path
                for requirement in definition.all_evidence
            }

            if len(declared) != len(definition.all_evidence):
                raise CapabilityRegistryError(
                    f"{capability_id}: duplicate canonical_path in evidence "
                    "requirements"
                )

            if definition.minimum_evidence["total"] < definition.minimum_evidence["primary"]:
                raise CapabilityRegistryError(
                    f"{capability_id}: minimum_evidence.total is lower than "
                    "minimum_evidence.primary"
                )

            if definition.minimum_evidence["total"] > definition.declared_evidence_count:
                raise CapabilityRegistryError(
                    f"{capability_id}: minimum_evidence.total "
                    f"({definition.minimum_evidence['total']}) exceeds the "
                    f"declared evidence count "
                    f"({definition.declared_evidence_count})"
                )

            if definition.minimum_evidence["primary"] > len(definition.primary_evidence):
                raise CapabilityRegistryError(
                    f"{capability_id}: minimum_evidence.primary "
                    f"({definition.minimum_evidence['primary']}) exceeds the "
                    f"declared primary evidence count "
                    f"({len(definition.primary_evidence)})"
                )

    # -- accessors ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self.capabilities)

    def __iter__(self):
        return iter(self.capabilities.values())

    def __contains__(self, capability_id: object) -> bool:
        return capability_id in self.capabilities

    def get(self, capability_id: str) -> CapabilityDefinition:
        return self.capabilities[capability_id]

    @property
    def capability_ids(self) -> List[str]:
        """Capability ids in the SIH order, not dictionary order."""

        return [
            capability_id
            for capability_id in REQUIRED_CAPABILITIES
            if capability_id in self.capabilities
        ]

    def concepts_used(self) -> List[str]:
        """Every existing canonical concept any capability depends on."""

        concepts = set()

        for definition in self.capabilities.values():

            for requirement in definition.all_evidence:

                if requirement.concept:
                    concepts.add(requirement.concept)

        return sorted(concepts)
