"""
SAT-SA capability evaluator.

Answers, for each assessment scope, which of the eight SOC capabilities can be
assessed from the evidence that scope actually submitted.

Inputs are **canonical concepts**, never raw source-column names:

* the concepts the existing semantic mapping pass already resolved for the
  dataset, and
* the concepts the capability pattern file resolves for the few existing
  concepts that the main pass cannot reach (see
  ``framework/config/capability_evidence_patterns.json``).

Per-scope, and never pooled across scopes
-----------------------------------------

The evaluator runs once per :class:`framework.assessment.scope.AssessmentScope`.
A multi-CSE, multi-period dataset therefore yields one independent set of eight
capability contexts per scope. Records are read through the scope's shared
record sequence; nothing is copied, and capabilities are never combined across
CSEs or periods.

Status computation
------------------

Given the satisfied primary (``p``) and supporting (``s``) counts, and the
configured minimums::

    if p + s == 0                       -> NOT_ASSESSED
    elif p >= minimum.primary
         and p + s >= minimum.total     -> AVAILABLE
    else                                -> INSUFFICIENT_EVIDENCE

Every threshold comes from ``framework/config/capabilities.json``. Nothing is
hardcoded per dataset.

This layer produces no findings, no severity and no score. Absence of evidence
is reported as a status, never as a risk.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from framework.assessment.entity_context import (
    PatternInference,
    build_column_name_index,
    rank_candidates,
)
from framework.assessment.scope import AssessmentCollection, AssessmentScope

from framework.capability.capability_context import (
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_NOT_ASSESSED,
    STATUS_ORDER,
    CapabilityContext,
)
from framework.capability.capability_registry import (
    CapabilityDefinition,
    CapabilityRegistry,
)

DEFAULT_CAPABILITY_PATTERNS = "framework/config/capability_evidence_patterns.json"

BLANK_VALUES = {"", "nan", "nat", "none", "null"}


def is_populated(value: Any) -> bool:
    """True when a source cell carries real information."""

    if value is None:
        return False

    if isinstance(value, float) and value != value:
        return False

    if isinstance(value, bool):
        return True

    if isinstance(value, str):
        return value.strip().lower() not in BLANK_VALUES

    return True


def _tagged(
    candidates: Sequence[Mapping[str, Any]], origin: str
) -> List[Dict[str, Any]]:
    """Record which pass resolved a concept, without altering the ranking.

    Kept separate from ``rank_candidates`` so the ranking stays owned by the
    existing semantic inference code and is not re-implemented here.
    """

    tagged = []

    for candidate in candidates:

        item = dict(candidate)
        item["resolution"] = origin
        tagged.append(item)

    return tagged


class EvidenceIndex:
    """The canonical concepts resolvable inside one assessment scope.

    A concept counts as available only when its source column is present *and*
    at least one record in the scope carries a populated value for it. A mapped
    column that is empty throughout the scope is not evidence.
    """

    def __init__(
        self,
        concepts: Mapping[str, Dict[str, Any]],
        columns: Sequence[str],
    ) -> None:

        self.concepts: Dict[str, Dict[str, Any]] = dict(concepts)
        self.columns: List[str] = list(columns)

    @property
    def available_concepts(self) -> List[str]:
        return sorted(self.concepts)

    def entries_for(self, concept: Optional[str]) -> Optional[Dict[str, Any]]:
        if not concept:
            return None

        return self.concepts.get(concept)

    def concept_values(
        self, records: Sequence[Mapping[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Project records onto their canonical concepts, one mapping per record.

        This is the single place source column names are translated into
        concept values, so every downstream consumer -- the capability layer,
        the execution-gap engine and the negative-space engine -- reads
        evidence by concept and inherits column-name independence for free.

        A concept absent from a record's mapping was not observed for that
        record, which is what lets consumers tell "not submitted" apart from
        "submitted as empty".
        """

        projected: List[Dict[str, Any]] = []

        for record in records:

            values: Dict[str, Any] = {}

            for concept, entry in self.concepts.items():

                column = entry.get("column")

                if not column or not isinstance(record, Mapping):
                    continue

                if column in record:
                    values[concept] = record[column]

            projected.append(values)

        return projected

    def to_dict(self) -> Dict[str, Any]:

        return {
            "available_concepts": self.available_concepts,
            "columns": list(self.columns),
        }

    def __repr__(self) -> str:

        return f"EvidenceIndex(concepts={self.available_concepts})"


class CapabilityEvaluator:
    """Assess which of the eight capabilities each scope's evidence supports."""

    def __init__(
        self,
        registry: Optional[CapabilityRegistry] = None,
        patterns_file: str = DEFAULT_CAPABILITY_PATTERNS,
    ) -> None:

        self.registry = registry or CapabilityRegistry()
        self.patterns_file = patterns_file

        self.patterns = self._load_patterns(patterns_file)

        self._engine = PatternInference(patterns=self.patterns) if self.patterns else None

        self.concept_to_path = dict(self.registry.concept_to_path)

    @staticmethod
    def _load_patterns(patterns_file: str) -> Dict[str, Any]:

        import json

        if not patterns_file:
            return {}

        try:

            with open(patterns_file, "r") as handle:
                raw = json.load(handle)

        except FileNotFoundError:
            return {}

        return {
            key: value
            for key, value in raw.items()
            if isinstance(value, Mapping)
        }

    # -- concept discovery -------------------------------------------------

    def _existing_concepts(
        self,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Concepts the main semantic pass already resolved."""

        name_index = build_column_name_index(profile)

        relevant = [
            mapping
            for mapping in (semantic_results or [])
            if mapping.get("canonical_concept") in self.concept_to_path
        ]

        return _tagged(rank_candidates(relevant, name_index), "semantic_mapping")

    def _capability_pattern_concepts(
        self,
        profile: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        """Concepts only the capability pattern file can reach."""

        if self._engine is None:
            return []

        name_index = build_column_name_index(profile)

        mappings = [
            mapping
            for mapping in self._engine.infer(profile)
            if mapping.get("canonical_concept") in self.concept_to_path
        ]

        return _tagged(rank_candidates(mappings, name_index), "capability_patterns")

    def build_evidence_index(
        self,
        records: Sequence[Mapping[str, Any]],
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> EvidenceIndex:
        """Resolve which canonical concepts this record set actually carries."""

        candidates: Dict[str, Dict[str, Any]] = {}

        for candidate in self._existing_concepts(profile, semantic_results):

            candidates.setdefault(candidate["concept"], candidate)

        for candidate in self._capability_pattern_concepts(profile):

            candidates.setdefault(candidate["concept"], candidate)

        concepts: Dict[str, Dict[str, Any]] = {}

        columns: List[str] = []

        for concept, candidate in candidates.items():

            column = candidate["column"]

            if column not in columns:
                columns.append(column)

            entry = {
                "column": column,
                "confidence": candidate["confidence"],
                "canonical_path": self.concept_to_path.get(concept),
                "resolution": "semantic_mapping"
                if candidate.get("resolution") == "semantic_mapping"
                else "capability_patterns",
            }

            for record in records:

                value = self._read(record, column)

                if is_populated(value):

                    entry["populated_records"] = entry.get("populated_records", 0) + 1
                    entry["example"] = value

            if entry.get("populated_records", 0) > 0:

                concepts[concept] = entry

        return EvidenceIndex(concepts=concepts, columns=columns)

    @staticmethod
    def _read(record: Mapping[str, Any], column: str) -> Any:

        if column in record:
            return record[column]

        lowered = column.lower()

        for key, value in record.items():

            if isinstance(key, str) and key.lower() == lowered:
                return value

        return None

    # -- per-capability evaluation ----------------------------------------

    def _evaluate_definition(
        self,
        definition: CapabilityDefinition,
        index: EvidenceIndex,
        scope: Optional[AssessmentScope] = None,
    ) -> CapabilityContext:
        available: List[str] = []
        missing: List[str] = []
        detail: List[Dict[str, Any]] = []

        primary_hits = 0
        supporting_hits = 0
        confidences: List[float] = []

        for tier, requirements in (
            ("primary", definition.primary_evidence),
            ("supporting", definition.supporting_evidence),
        ):

            for requirement in requirements:

                entry = index.entries_for(requirement.concept)

                satisfied = entry is not None

                detail.append(
                    {
                        "canonical_path": requirement.canonical_path,
                        "concept": requirement.concept,
                        "tier": tier,
                        "role": requirement.role,
                        "discoverable": requirement.discoverable,
                        "satisfied": satisfied,
                        "source_column": entry["column"] if entry else None,
                        "resolution": entry.get("resolution")
                        if entry
                        else None,
                        "mapping_confidence": round(entry["confidence"], 4)
                        if entry
                        else None,
                        "populated_records": entry.get("populated_records")
                        if entry
                        else 0,
                    }
                )

                if satisfied:

                    if tier == "primary":
                        primary_hits += 1
                    else:
                        supporting_hits += 1

                    available.append(
                        requirement.concept
                        if requirement.concept
                        else requirement.canonical_path
                    )

                    confidences.append(entry["confidence"])

                else:

                    missing.append(
                        requirement.concept
                        if requirement.concept
                        else requirement.canonical_path
                    )

        total_hits = primary_hits + supporting_hits

        minimum = definition.minimum_evidence

        # NOT_ASSESSED is decided by primary evidence alone. Primary evidence is
        # what makes a capability meaningful at all; supporting evidence only
        # enriches an assessment that can already begin. Without it, a
        # precondition such as alert severity would drag ESCALATION out of
        # NOT_ASSESSED purely because severity happens to be present, which
        # would claim more about the submission than the evidence supports.
        if primary_hits == 0:

            status = STATUS_NOT_ASSESSED

        elif (
            primary_hits >= minimum["primary"]
            and total_hits >= minimum["total"]
        ):

            status = STATUS_AVAILABLE

        else:

            status = STATUS_INSUFFICIENT_EVIDENCE

        declared = definition.declared_evidence_count

        coverage = round(total_hits / declared, 4) if declared else 0.0

        confidence = round(
            sum(confidences) / len(confidences),
            4,
        ) if confidences else 0.0

        return CapabilityContext(
            capability_id=definition.capability_id,
            name=definition.name,
            status=status,
            confidence=confidence,
            coverage=coverage,
            evidence_available=available,
            evidence_missing=missing,
            indicator_categories=list(definition.indicator_categories),
            explanation=self._explain(
                definition,
                status,
                primary_hits,
                supporting_hits,
                minimum,
            ),
            evidence_detail=detail,
            undiscoverable_evidence=definition.undiscoverable_evidence,
            minimum_evidence=dict(minimum),
            assessment_id=scope.assessment_id if scope is not None else None,
            entity=(
                scope.entity.to_dict() if scope is not None else {}
            ),
            period=(
                scope.period.to_dict() if scope is not None else {}
            ),
        )

    def _explain(
        self,
        definition: CapabilityDefinition,
        status: str,
        primary_hits: int,
        supporting_hits: int,
        minimum: Mapping[str, int],
    ) -> str:
        """A statement about evidence, never about risk."""

        total = primary_hits + supporting_hits

        if status == STATUS_NOT_ASSESSED:

            return (
                f"No primary evidence for {definition.name} was submitted, so "
                "this capability cannot be assessed from this submission. "
                f"{supporting_hits} supporting item(s) may be present, but "
                "supporting evidence enriches an assessment and cannot begin "
                "one. This is a statement about the evidence provided, not a "
                "statement about risk."
            )

        if status == STATUS_AVAILABLE:

            return (
                f"{definition.name} evidence requirements are met: "
                f"{primary_hits}/{minimum['primary']} required primary and "
                f"{total}/{minimum['total']} total declared evidence items are "
                "present, so this capability can be assessed. The capability is "
                "assessable; this says nothing yet about how well it performs."
            )

        shortfall = []

        if primary_hits < minimum["primary"]:
            shortfall.append(
                f"{primary_hits} of {minimum['primary']} required primary "
                "evidence items"
            )

        if total < minimum["total"]:
            shortfall.append(
                f"{total} of {minimum['total']} total evidence items"
            )

        return (
            f"{definition.name} is partially evidenced but incomplete: "
            f"{'; '.join(shortfall)} are present. The submission needs more "
            "evidence before this capability can be assessed meaningfully. "
            "Incomplete evidence is not a negative finding."
        )

    # -- scope and collection entry points --------------------------------

    def evaluate_scope(
        self,
        scope: AssessmentScope,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
        index: Optional[EvidenceIndex] = None,
    ) -> List[CapabilityContext]:
        """Assess all eight capabilities for a single assessment scope.

        Records come from the scope's shared sequence, so a multi-CSE dataset is
        never pooled and no record is duplicated.
        """

        if index is None:
            index = self.build_evidence_index(
                scope.records, profile, semantic_results
            )

        return [
            self._evaluate_definition(definition, index, scope)
            for definition in (
                self.registry.get(capability_id)
                for capability_id in self.registry.capability_ids
            )
        ]

    def evaluate_collection(
        self,
        collection: AssessmentCollection,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Assess every scope independently and summarise across them.

        The per-scope results are authoritative. The collection summary only
        counts statuses; it never averages a coverage or confidence value into a
        capability-level judgement about a CSE.
        """

        scope_payloads: List[Dict[str, Any]] = []

        for scope in collection:

            contexts = self.evaluate_scope(
                scope, profile, semantic_results
            )

            scope_payloads.append(
                {
                    "assessment_id": scope.assessment_id,
                    "entity": scope.entity.to_dict(),
                    "period": scope.period.to_dict(),
                    "record_count": scope.record_count,
                    "capabilities": [
                        context.to_dict() for context in contexts
                    ],
                    "status_counts": {
                        status: len(
                            [
                                context
                                for context in contexts
                                if context.status == status
                            ]
                        )
                        for status in (
                            STATUS_AVAILABLE,
                            STATUS_INSUFFICIENT_EVIDENCE,
                            STATUS_NOT_ASSESSED,
                        )
                    },
                }
            )

        per_capability: List[Dict[str, Any]] = []

        for capability_id in self.registry.capability_ids:

            counts = {status: 0 for status in STATUS_ORDER}

            for payload in scope_payloads:

                for context in payload["capabilities"]:

                    if context["capability_id"] == capability_id:
                        counts[context["status"]] += 1

            per_capability.append(
                {
                    "capability_id": capability_id,
                    "available_scopes": counts[STATUS_AVAILABLE],
                    "insufficient_evidence_scopes": counts[
                        STATUS_INSUFFICIENT_EVIDENCE
                    ],
                    "not_assessed_scopes": counts[STATUS_NOT_ASSESSED],
                }
            )

        return {
            "capability_ids": self.registry.capability_ids,
            "scope_count": len(scope_payloads),
            "scopes": scope_payloads,
            "summary": {
                "scope_count": len(scope_payloads),
                "assessable_capability_instances": sum(
                    payload["status_counts"][STATUS_AVAILABLE]
                    for payload in scope_payloads
                ),
                "capabilities": per_capability,
            },
        }

    def evaluate_dataset(
        self,
        records: Sequence[Mapping[str, Any]],
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[CapabilityContext]:
        """Assess all eight capabilities for a single flat record set.

        Used when no assessment scope exists. Equivalent to a dataset that
        forms one scope.
        """

        index = self.build_evidence_index(records, profile, semantic_results)

        return [
            self._evaluate_definition(definition, index, None)
            for definition in (
                self.registry.get(capability_id)
                for capability_id in self.registry.capability_ids
            )
        ]
