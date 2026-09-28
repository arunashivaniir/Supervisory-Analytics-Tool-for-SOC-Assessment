"""
SAT-SA assessment scope: entity (CSE) identity resolution.

This module answers one question: *which assessed entity does this record belong
to, and how confident are we?*

It is the entity-context half of the assessment scope layer. Period handling
lives in :mod:`framework.assessment.period`; the two are combined into
``AssessmentScope`` objects by :mod:`framework.assessment.scope`.

Design rules this module exists to enforce
------------------------------------------

* **No invented entities.** If a dataset carries no entity-identity field, the
  result is ``UNKNOWN_ENTITY`` with ``available=False`` and a recorded reason.
  A scope is never fabricated to fill a gap, and no value is ever guessed from
  unrelated data.
* **"Unavailable" is not "one entity".** A dataset with a single distinct
  entity value and a dataset with no entity field both produce exactly one
  scope, but they are distinguishable: ``available`` and ``method`` differ, and
  so does ``entity_resolution.distinct_entities``. Downstream analytics must be
  able to tell "this CSE contains everything" from "we do not know whose this
  is".
* **Discovery is semantic, not hardcoded.** Entity columns are identified by
  running the existing
  :class:`framework.intelligence.semantic_inference.SemanticInference` engine
  over the dataset profile using the pattern set in
  ``framework/config/assessment_scope_patterns.json``. No column name lives in
  Python, so a new customer export is supported by editing configuration.
* **Reuse of the existing resolver.** When semantic discovery finds nothing,
  the existing :class:`framework.entity.entity_resolver.EntityResolver` is
  consulted so SAT-SA keeps one notion of entity identity. Only its explicit
  entity tier is accepted: the organizational and asset tiers describe a
  record's position *inside* a CSE, and treating them as the CSE would invent
  one entity per department or per host.
* **Deterministic.** Candidate columns are ranked by confidence and then by
  name, so the same dataset always produces the same entity column even when
  several columns look plausible. Ambiguity is reported, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from framework.entity.entity_resolver import EntityResolver
from framework.intelligence.semantic_inference import SemanticInference

UNKNOWN_ENTITY = "UNKNOWN_ENTITY"

DEFAULT_CONFIG_FILE = "framework/config/assessment_scope_patterns.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "min_column_confidence": 0.45,
    "entity_identifier_concepts": ["ENTITY_IDENTITY"],
    "entity_name_concepts": ["ENTITY_NAME"],
    "accepted_entity_resolver_tiers": ["explicit"],
}


class PatternInference(SemanticInference):
    """The existing :class:`SemanticInference` scorer over an in-memory pattern set.

    ``SemanticInference`` reads its patterns from a config file, while the scope
    layer keeps its patterns in the same file as the resolution settings. This
    subclass supplies the patterns directly so there is exactly **one** scoring
    implementation in SAT-SA, and no existing intelligence module is modified.

    ``infer()`` and ``calculate_score()`` are inherited unchanged.
    """

    def __init__(self, patterns: Mapping[str, Any]) -> None:

        self.patterns = dict(patterns)


def load_scope_config(config_file: str = DEFAULT_CONFIG_FILE) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split the scope configuration into scoring axes and resolution settings.

    Returns ``(axes, settings)`` where ``axes`` maps an axis name to a pattern
    dict consumable by :class:`SemanticInference` and ``settings`` carries the
    resolution policy. The ``settings`` key is never treated as a scoring axis.
    """

    import json

    with open(config_file, "r") as handle:
        raw = json.load(handle)

    settings = dict(DEFAULT_SETTINGS)

    axes: Dict[str, Any] = {}

    for key, value in raw.items():

        if key == "settings":
            settings.update(value)
            continue

        if key.startswith("_"):
            continue

        if not isinstance(value, dict):
            continue

        axes[key] = value

    return axes, settings


def build_column_name_index(profile: Mapping[str, Any]) -> Dict[str, str]:
    """Map lowercased profile column names to their original spelling.

    ``SemanticInference`` lowercases ``source_column`` when it reports a match,
    so lookups against real records need this index to recover the original
    spelling.
    """

    index: Dict[str, str] = {}

    for column in profile.get("columns", []) or []:

        name = column.get("column_name")

        if not isinstance(name, str) or not name:
            continue

        index.setdefault(name.lower(), name)

    return index


def rank_candidates(mappings: Sequence[Mapping[str, Any]], name_index: Mapping[str, str]) -> List[Dict[str, Any]]:
    """Turn semantic mappings into a deterministic, deduplicated candidate list."""

    candidates: List[Dict[str, Any]] = []

    seen = set()

    for mapping in mappings:

        concept = mapping.get("canonical_concept")

        lowered = mapping.get("source_column")

        if not concept or not isinstance(lowered, str) or not lowered:
            continue

        original = name_index.get(lowered.lower(), lowered)

        if original in seen:
            continue

        seen.add(original)

        candidates.append(
            {
                "column": original,
                "concept": concept,
                "confidence": float(mapping.get("confidence", 0.0) or 0.0),
            }
        )

    candidates.sort(key=lambda item: (-item["confidence"], item["column"]))

    return candidates


class EntityColumnResolution:
    """Which source columns were chosen to identify an entity, and why."""

    def __init__(self) -> None:

        self.identifier_column: Optional[str] = None
        self.identifier_concept: Optional[str] = None
        self.identifier_confidence: float = 0.0

        self.name_column: Optional[str] = None
        self.name_concept: Optional[str] = None
        self.name_confidence: float = 0.0

        self.candidates: List[Dict[str, Any]] = []
        self.ambiguous: bool = False
        self.method: str = "unavailable"
        self.reason: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.identifier_column is not None or self.name_column is not None

    def to_dict(self) -> Dict[str, Any]:

        return {
            "identifier_column": self.identifier_column,
            "identifier_concept": self.identifier_concept,
            "identifier_confidence": self.identifier_confidence,
            "name_column": self.name_column,
            "name_concept": self.name_concept,
            "name_confidence": self.name_confidence,
            "candidates": list(self.candidates),
            "ambiguous": self.ambiguous,
            "method": self.method,
            "reason": self.reason,
        }


@dataclass
class EntityContext:
    """Resolved entity identity for a single record or a whole scope."""

    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    confidence: float = 0.0
    available: bool = False
    source: Optional[str] = None
    method: str = "unavailable"
    unavailable_reason: Optional[str] = None

    @property
    def group_key(self) -> str:
        """Stable grouping key for assessment scopes.

        Prefers an identifier, falls back to a name, and only then to
        ``UNKNOWN_ENTITY``. Never returns ``None``, so a scope is always
        groupable even when the entity is unavailable.
        """

        if self.entity_id:
            return str(self.entity_id)

        if self.entity_name:
            return str(self.entity_name)

        return UNKNOWN_ENTITY

    def to_dict(self) -> Dict[str, Any]:

        return {
            "id": self.entity_id if self.entity_id is not None else UNKNOWN_ENTITY,
            "name": self.entity_name,
            "confidence": round(float(self.confidence), 4),
            "available": self.available,
            "source": self.source,
            "method": self.method,
            "unavailable_reason": self.unavailable_reason,
        }


class EntityContextResolver:
    """Resolve entity identity per record using semantic discovery.

    Resolution order, strongest evidence first:

    1. a column the scope pattern set identified as an entity identifier;
    2. a column the scope pattern set identified as an entity name;
    3. the existing :class:`EntityResolver`, accepted only if it reports its
       explicit entity tier;
    4. ``UNKNOWN_ENTITY``, with the reason recorded.
    """

    def __init__(
        self,
        config_file: str = DEFAULT_CONFIG_FILE,
        settings: Optional[Mapping[str, Any]] = None,
        entity_resolver: Optional[EntityResolver] = None,
    ) -> None:

        axes, config_settings = load_scope_config(config_file)

        self.settings: Dict[str, Any] = dict(config_settings)

        if settings:
            self.settings.update(settings)

        self.min_confidence = float(self.settings.get("min_column_confidence", 0.45))

        self.identifier_concepts = list(self.settings.get("entity_identifier_concepts", ["ENTITY_IDENTITY"]))
        self.name_concepts = list(self.settings.get("entity_name_concepts", ["ENTITY_NAME"]))

        self.accepted_tiers = list(self.settings.get("accepted_entity_resolver_tiers", ["explicit"]))

        self._identifier_engine = self._build_engine(axes.get("entity_identifier"))
        self._name_engine = self._build_engine(axes.get("entity_display_name"))

        self.entity_resolver = entity_resolver or EntityResolver()

    @staticmethod
    def _build_engine(patterns: Optional[Mapping[str, Any]]) -> Optional[PatternInference]:

        if not patterns:
            return None

        return PatternInference(patterns=patterns)

    def _candidates_for(
        self,
        engine: Optional[PatternInference],
        concepts: Sequence[str],
        profile: Mapping[str, Any],
        name_index: Mapping[str, str],
    ) -> List[Dict[str, Any]]:

        if engine is None:
            return []

        wanted = set(concepts)

        mappings = [
            mapping
            for mapping in engine.infer(profile)
            if mapping.get("canonical_concept") in wanted
            and float(mapping.get("confidence", 0.0) or 0.0) >= self.min_confidence
        ]

        return rank_candidates(mappings, name_index)

    def resolve_columns(self, profile: Mapping[str, Any]) -> EntityColumnResolution:
        """Choose the entity identifier / name columns for a dataset profile."""

        resolution = EntityColumnResolution()

        name_index = build_column_name_index(profile)

        identifier_candidates = self._candidates_for(
            self._identifier_engine, self.identifier_concepts, profile, name_index
        )

        name_candidates = self._candidates_for(
            self._name_engine, self.name_concepts, profile, name_index
        )

        resolution.candidates = identifier_candidates + name_candidates

        if identifier_candidates and name_candidates:

            identifier = identifier_candidates[0]
            name = name_candidates[0]

            if identifier["column"] == name["column"]:

                # One column claimed by both axes, e.g. "customer_name" which
                # contains the identifier keyword "customer" and the name
                # keyword "customer_name". The more specific axis wins, so a
                # name column is never reported as an entity id.
                if name["confidence"] >= identifier["confidence"]:

                    identifier_candidates = []

                else:

                    name_candidates = []

        if identifier_candidates:

            chosen = identifier_candidates[0]

            resolution.identifier_column = chosen["column"]
            resolution.identifier_concept = chosen["concept"]
            resolution.identifier_confidence = chosen["confidence"]

        if name_candidates:

            chosen = name_candidates[0]

            resolution.name_column = chosen["column"]
            resolution.name_concept = chosen["concept"]
            resolution.name_confidence = chosen["confidence"]

        if resolution.resolved:

            resolution.method = "semantic_mapping"

            distinct_columns = {
                candidate["column"]
                for candidate in resolution.candidates
            }

            resolution.ambiguous = len(distinct_columns) > 1

            if resolution.ambiguous:

                resolution.reason = (
                    "several columns matched entity patterns "
                    f"({', '.join(sorted(distinct_columns))}); "
                    f"selected {resolution.identifier_column or resolution.name_column} "
                    "by confidence then name"
                )

            return resolution

        resolution.method = "unavailable"

        resolution.reason = (
            "no column matched the entity identification patterns in "
            "assessment_scope_patterns.json"
        )

        return resolution

    def _read(self, record: Mapping[str, Any], column: Optional[str]) -> Optional[str]:

        if not column or not isinstance(record, Mapping):
            return None

        if column in record:
            return record[column]

        lowered = column.lower()

        for key, value in record.items():

            if isinstance(key, str) and key.lower() == lowered:
                return value

        return None

    def _resolver_value(self, value: Any) -> Optional[str]:

        if value is None:
            return None

        if isinstance(value, float) and value != value:
            return None

        text = str(value).strip()

        if not text or text.lower() in {"nan", "nat", "none", "null"}:
            return None

        return text

    def resolve(
        self,
        record: Mapping[str, Any],
        resolution: EntityColumnResolution,
    ) -> EntityContext:
        """Resolve the entity for a single record."""

        identifier = self._resolver_value(
            self._read(record, resolution.identifier_column)
        )

        name = self._resolver_value(
            self._read(record, resolution.name_column)
        )

        if identifier or name:

            confidence = 0.0

            if identifier and resolution.identifier_column:
                confidence = max(confidence, resolution.identifier_confidence)

            if name and resolution.name_column:
                confidence = max(confidence, resolution.name_confidence)

            return EntityContext(
                entity_id=identifier,
                entity_name=name,
                confidence=confidence,
                available=True,
                source=resolution.identifier_column or resolution.name_column,
                method=resolution.method,
            )

        if resolution.resolved:

            return EntityContext(
                available=False,
                method="semantic_mapping",
                unavailable_reason=(
                    f"entity column(s) "
                    f"{resolution.identifier_column or resolution.name_column} "
                    "present but empty for this record"
                ),
            )

        if "explicit" in self.accepted_tiers:

            legacy = self.entity_resolver.resolve(dict(record))

            legacy_entity = str(legacy.get("entity", UNKNOWN_ENTITY))
            legacy_source = str(legacy.get("source", "none"))

            explicit_fields = {
                str(field_name).lower()
                for field_name in getattr(self.entity_resolver, "ENTITY_FIELDS", [])
            }

            if (
                legacy_entity != UNKNOWN_ENTITY
                and legacy_source.lower() in explicit_fields
            ):

                return EntityContext(
                    entity_id=legacy_entity,
                    confidence=float(legacy.get("confidence", 0.0) or 0.0),
                    available=True,
                    source=legacy_source,
                    method="entity_resolver",
                )

            rejected = self._rejection_reason(legacy_entity, legacy_source)

        else:

            rejected = "entity resolver tiers disabled by configuration"

        return EntityContext(
            available=False,
            method="unavailable",
            unavailable_reason=self._combine_reasons(
                resolution.reason,
                rejected,
            ),
        )

    @staticmethod
    def _combine_reasons(*reasons: Optional[str]) -> str:

        parts = [str(reason).strip() for reason in reasons if reason]

        seen: List[str] = []

        for part in parts:

            if part not in seen:
                seen.append(part)

        return "; ".join(seen)

    def _rejection_reason(self, entity: str, source: str) -> str:

        if entity == UNKNOWN_ENTITY:

            return (
                "no entity-identity column found; the existing EntityResolver "
                f"reported no entity (source={source})"
            )

        return (
            f"no entity-identity column found; the existing EntityResolver "
            f"reported a non-entity field (source={source}) which was rejected "
            "because it identifies a location inside a CSE, not the CSE itself"
        )

    def resolve_records(
        self,
        records: Sequence[Mapping[str, Any]],
        profile: Mapping[str, Any],
        resolution: Optional[EntityColumnResolution] = None,
    ) -> Tuple[List[EntityContext], EntityColumnResolution]:
        """Resolve entity identity for every record in a dataset."""

        if resolution is None:
            resolution = self.resolve_columns(profile)

        contexts = [
            self.resolve(record, resolution)
            for record in records
        ]

        return contexts, resolution
