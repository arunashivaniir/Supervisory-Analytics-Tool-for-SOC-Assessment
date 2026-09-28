"""
SAT-SA assessment scope: the multi-CSE / multi-period data model.

This module is the foundation that lets one SAT-SA analytical engine run over
one or many Critical Sector Entities across one or many assessment periods,
without duplicating any analytical logic.

Why it exists
-------------

The problem statement requires analysis spanning multiple CSEs, multiple
entities, multiple time periods, and eventually peer benchmarking and trend
analysis. None of that is possible while a dataset is treated as one
undifferentiated bag of records. This module supplies the missing concept: an
**assessment scope** is the (entity, period) pair a set of records belongs to,
and a **collection** holds the scopes for a dataset and can be grouped or
filtered along either axis.

    Source Dataset -> Ingestion -> Dataset Understanding
                                        |
                        +---------------+---------------+
                        |                               |
                Entity / CSE identity            Assessment period
                        |                               |
                        +---------------+---------------+
                                        v
                                AssessmentScope
                                (CSE + period + records)
                                        |
                                        v
                              Existing SAT-SA analytics

Data contract
-------------

Every scope serialises to the structure below, mirroring the required contract.
Fields that cannot be established are explicit ``null`` / ``UNKNOWN`` /
``available: false`` values with a recorded ``unavailable_reason``; they are
never guessed.

.. code-block:: json

    {
      "assessment_id": "CSE-001::Period-1",
      "entity": {
        "id": "CSE-001",
        "name": null,
        "confidence": 0.75,
        "available": true,
        "source": "cse",
        "method": "semantic_mapping",
        "unavailable_reason": null
      },
      "period": {
        "label": "Period-1",
        "start": null,
        "end": null,
        "confidence": 0.75,
        "available": true,
        "granularity": "explicit",
        "source": "period",
        "method": "explicit_column",
        "label_precision": "opaque",
        "unavailable_reason": null
      },
      "source": {
        "id": "dataset_multi_cse.csv",
        "type": "csv",
        "evidence_id": null
      },
      "record_count": 2,
      "metadata": { "...": "..." }
    }

Records are not duplicated
--------------------------

A scope stores ``record_indices`` into the single shared record sequence and
resolves them on demand. The same ``dict`` objects produced once by ingestion
are referenced by every scope, so grouping a large multi-CSE dataset costs
indices, not copies.

Failure behaviour
-----------------

* No entity column -> entity ``UNKNOWN_ENTITY``, ``available: false``, reason
  recorded; the pipeline continues.
* No period evidence -> period ``UNKNOWN_PERIOD``, ``available: false``, reason
  recorded; the pipeline continues.
* A missing period never raises.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from framework.assessment.entity_context import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_SETTINGS,
    UNKNOWN_ENTITY,
    EntityColumnResolution,
    EntityContext,
    EntityContextResolver,
    load_scope_config,
)
from framework.assessment.period import (
    UNKNOWN_PERIOD,
    PeriodColumnResolution,
    PeriodContext,
    PeriodResolver,
)


class AssessmentScope:
    """The records of one dataset that belong to one (entity, period) pair."""

    def __init__(
        self,
        assessment_id: str,
        entity: EntityContext,
        period: PeriodContext,
        record_indices: Sequence[int],
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        evidence_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        records: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> None:

        self.assessment_id = assessment_id
        self.entity = entity
        self.period = period
        self.record_indices: List[int] = list(record_indices)
        self.source_id = source_id
        self.source_type = source_type
        self.evidence_id = evidence_id
        self.metadata: Dict[str, Any] = dict(metadata or {})
        self._records = records

    # Identity is the whole point of a scope, so it is readable directly.

    @property
    def entity_id(self) -> Optional[str]:
        return self.entity.entity_id

    @property
    def entity_name(self) -> Optional[str]:
        return self.entity.entity_name

    @property
    def period_label(self) -> str:
        return self.period.label

    @property
    def period_start(self) -> Optional[str]:
        return self.period.start

    @property
    def period_end(self) -> Optional[str]:
        return self.period.end

    @property
    def record_count(self) -> int:
        return len(self.record_indices)

    @property
    def entity_key(self) -> str:
        return self.entity.group_key

    @property
    def entity_available(self) -> bool:
        return self.entity.available

    @property
    def period_available(self) -> bool:
        return self.period.available

    @property
    def records(self) -> List[Mapping[str, Any]]:
        """The scope's records, resolved on demand from the shared sequence.

        The returned list is new, but the record ``dict`` objects are the very
        same objects ingestion produced: no record is ever copied or duplicated.
        """

        if self._records is None:
            return []

        return [
            self._records[index]
            for index in self.record_indices
            if 0 <= index < len(self._records)
        ]

    def to_dict(self) -> Dict[str, Any]:

        return {
            "assessment_id": self.assessment_id,
            "entity": self.entity.to_dict(),
            "period": self.period.to_dict(),
            "source": {
                "id": self.source_id,
                "type": self.source_type,
                "evidence_id": self.evidence_id,
            },
            "record_count": self.record_count,
            "metadata": dict(self.metadata),
        }

    def to_summary(self) -> Dict[str, Any]:

        return {
            "assessment_id": self.assessment_id,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_available": self.entity_available,
            "period_label": self.period_label,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "period_available": self.period_available,
            "record_count": self.record_count,
        }

    def __repr__(self) -> str:

        return (
            f"AssessmentScope(assessment_id={self.assessment_id!r}, "
            f"records={self.record_count})"
        )


class AssessmentCollection:
    """The full set of assessment scopes for one ingested source.

    Supports grouping and filtering along both axes, which is what later peer
    benchmarking (group by entity) and trend analysis (group by period) will
    consume. Nothing here performs analysis: it only partitions records.
    """

    def __init__(
        self,
        scopes: Sequence[AssessmentScope],
        records: Optional[Sequence[Mapping[str, Any]]] = None,
        entity_resolution: Optional[EntityColumnResolution] = None,
        period_resolution: Optional[PeriodColumnResolution] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:

        self.scopes: List[AssessmentScope] = list(scopes)
        self.records = records
        self.entity_resolution = entity_resolution
        self.period_resolution = period_resolution
        self.metadata: Dict[str, Any] = dict(metadata or {})

        self.by_entity: Dict[str, List[AssessmentScope]] = {}
        self.by_period: Dict[str, List[AssessmentScope]] = {}
        self.by_entity_period: Dict[Tuple[str, str], List[AssessmentScope]] = {}

        for scope in self.scopes:

            self.by_entity.setdefault(scope.entity_key, []).append(scope)
            self.by_period.setdefault(scope.period_label, []).append(scope)

            key = (scope.entity_key, scope.period_label)

            self.by_entity_period.setdefault(key, []).append(scope)

    # -- container protocol ----------------------------------------------

    def __len__(self) -> int:
        return len(self.scopes)

    def __iter__(self) -> Iterator[AssessmentScope]:
        return iter(self.scopes)

    def __getitem__(self, index: int) -> AssessmentScope:
        return self.scopes[index]

    def __repr__(self) -> str:

        return (
            f"AssessmentCollection(scopes={len(self.scopes)}, "
            f"entities={self.entity_count}, periods={self.period_count})"
        )

    # -- indexing --------------------------------------------------------

    @property
    def entity_keys(self) -> List[str]:
        return sorted(self.by_entity)

    @property
    def period_labels(self) -> List[str]:
        return sorted(self.by_period)

    @property
    def entity_count(self) -> int:
        return len(self.by_entity)

    @property
    def period_count(self) -> int:
        return len(self.by_period)

    @property
    def record_count(self) -> int:
        return sum(scope.record_count for scope in self.scopes)

    @property
    def distinct_entity_count(self) -> int:
        """Number of real entities, excluding the unresolved placeholder.

        ``0`` means the dataset carried no entity identity. This is what lets
        downstream code tell "one entity" apart from "entity unavailable" even
        though both yield a single scope.
        """

        return len([key for key in self.by_entity if key != UNKNOWN_ENTITY])

    @property
    def distinct_period_count(self) -> int:
        return len([key for key in self.by_period if key != UNKNOWN_PERIOD])

    @property
    def has_unresolved_entity(self) -> bool:
        return UNKNOWN_ENTITY in self.by_entity

    @property
    def has_unresolved_period(self) -> bool:
        return UNKNOWN_PERIOD in self.by_period

    # -- lookup and filtering --------------------------------------------

    def for_entity(self, entity: Optional[str] = None) -> List[AssessmentScope]:
        """Scopes for one entity. ``None`` selects the unresolved entity."""

        return list(self.by_entity.get(entity, []))

    def for_period(self, period: Optional[str] = None) -> List[AssessmentScope]:
        """Scopes for one period. ``None`` selects ``UNKNOWN_PERIOD``."""

        return list(self.by_period.get(period, []))

    def for_entity_period(
        self,
        entity: Optional[str],
        period: Optional[str],
    ) -> List[AssessmentScope]:

        return list(self.by_entity_period.get((entity, period), []))

    def filter(
        self,
        entity: Optional[str] = None,
        period: Optional[str] = None,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
    ) -> List[AssessmentScope]:
        """Filter scopes by entity, period, or an inclusive date window.

        Omitted arguments do not constrain the result, so
        ``filter(period="2026-Q1")`` returns that period across every entity.
        """

        selected = self.scopes

        if entity is not None:
            selected = [scope for scope in selected if scope.entity_key == entity]

        if period is not None:
            selected = [scope for scope in selected if scope.period_label == period]

        if period_start is not None:
            selected = [
                scope
                for scope in selected
                if scope.period_start is not None and scope.period_start >= period_start
            ]

        if period_end is not None:
            selected = [
                scope
                for scope in selected
                if scope.period_end is not None and scope.period_end <= period_end
            ]

        return list(selected)

    def records_for(self, scope: AssessmentScope) -> List[Mapping[str, Any]]:
        return scope.records

    def records_for_entity(self, entity: Optional[str] = None) -> List[Mapping[str, Any]]:
        return self._collect(self.for_entity(entity))

    def records_for_period(self, period: Optional[str] = None) -> List[Mapping[str, Any]]:
        return self._collect(self.for_period(period))

    def records_for_entity_period(
        self,
        entity: Optional[str],
        period: Optional[str],
    ) -> List[Mapping[str, Any]]:

        return self._collect(self.for_entity_period(entity, period))

    def _collect(self, scopes: Iterable[AssessmentScope]) -> List[Mapping[str, Any]]:

        if self.records is None:
            return []

        collected: List[Mapping[str, Any]] = []

        seen = set()

        for scope in scopes:

            for index in scope.record_indices:

                if index in seen or not (0 <= index < len(self.records)):
                    continue

                seen.add(index)

                collected.append(self.records[index])

        return collected

    # -- serialisation ----------------------------------------------------

    def _source_descriptor(self) -> Dict[str, Any]:

        if not self.scopes:
            return {
                "id": self.metadata.get("source_id"),
                "type": self.metadata.get("source_type"),
                "evidence_id": self.metadata.get("evidence_id"),
            }

        scope = self.scopes[0]

        return {
            "id": scope.source_id,
            "type": scope.source_type,
            "evidence_id": scope.evidence_id,
        }

    def to_dict(self, include_records: bool = False) -> Dict[str, Any]:

        payload: Dict[str, Any] = {
            "source": self._source_descriptor(),
            "scopes": [scope.to_dict() for scope in self.scopes],
            "scope_count": len(self.scopes),
            "record_count": self.record_count,
            "entity_resolution": {
                "available": not self.has_unresolved_entity,
                "distinct_entities": self.distinct_entity_count,
                "unresolved_scopes": len(self.for_entity(UNKNOWN_ENTITY)),
                "column_resolution": (
                    self.entity_resolution.to_dict()
                    if self.entity_resolution is not None
                    else None
                ),
            },
            "period_resolution": {
                "available": not self.has_unresolved_period,
                "distinct_periods": self.distinct_period_count,
                "unresolved_scopes": len(self.for_period(UNKNOWN_PERIOD)),
                "column_resolution": (
                    self.period_resolution.to_dict()
                    if self.period_resolution is not None
                    else None
                ),
            },
            "metadata": dict(self.metadata),
        }

        if include_records:

            payload["scope_records"] = [
                {
                    "assessment_id": scope.assessment_id,
                    "record_indices": list(scope.record_indices),
                }
                for scope in self.scopes
            ]

        return payload

    def to_summary(self) -> Dict[str, Any]:

        return {
            "scope_count": len(self.scopes),
            "entity_count": self.entity_count,
            "distinct_entities": self.distinct_entity_count,
            "period_count": self.period_count,
            "distinct_periods": self.distinct_period_count,
            "record_count": self.record_count,
            "entity_available": not self.has_unresolved_entity,
            "period_available": not self.has_unresolved_period,
            "scopes": [scope.to_summary() for scope in self.scopes],
        }


class AssessmentScopeBuilder:
    """Build the assessment scope collection for one ingested source.

    This is the only entry point later analytics need. It performs no analysis
    and imports no analytical module, so adding scope support cannot change an
    existing result: it only adds the ``assessment`` key.
    """

    def __init__(
        self,
        config_file: str = DEFAULT_CONFIG_FILE,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:

        self.config_file = config_file
        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)

        _, config_settings = load_scope_config(config_file)

        self.settings.update(config_settings)

        if settings:
            self.settings.update(settings)

        self.entity_resolver = EntityContextResolver(
            config_file=config_file,
            settings=self.settings,
        )

        self.period_resolver = PeriodResolver(
            config_file=config_file,
            settings=self.settings,
        )

    def build(
        self,
        records: Sequence[Mapping[str, Any]],
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        evidence_id: Optional[str] = None,
    ) -> AssessmentCollection:
        """Partition records into assessment scopes.

        ``records`` is the shared record sequence from ingestion. Scopes hold
        indices into it, so records are never copied.
        """

        records = list(records or [])

        entity_contexts, entity_resolution = self.entity_resolver.resolve_records(
            records,
            profile,
        )

        period_contexts, period_resolution = self.period_resolver.resolve_records(
            records,
            profile,
            semantic_results,
        )

        grouped: Dict[Tuple[str, str], List[int]] = {}

        for index, (entity_context, period_context) in enumerate(
            zip(entity_contexts, period_contexts)
        ):

            key = (entity_context.group_key, period_context.label)

            grouped.setdefault(key, []).append(index)

        shared = {
            "entity_resolution": entity_resolution,
            "period_resolution": period_resolution,
            "source_id": source_id,
            "source_type": source_type,
            "evidence_id": evidence_id,
        }

        scopes: List[AssessmentScope] = []

        for (entity_key, period_label), indices in sorted(
            grouped.items(),
            key=lambda item: (item[0][0], item[0][1]),
        ):

            entity_context = entity_contexts[indices[0]]
            period_context = period_contexts[indices[0]]

            if len(indices) == len(records):

                note = "all records in this dataset share this entity and period"

            else:

                note = None

            metadata = {
                "entity": {
                    "method": entity_context.method,
                    "source": entity_context.source,
                    "available": entity_context.available,
                    "unavailable_reason": entity_context.unavailable_reason,
                    "ambiguous": entity_resolution.ambiguous,
                    "candidate_columns": [
                        candidate["column"] for candidate in entity_resolution.candidates
                    ],
                },
                "period": {
                    "method": period_context.method,
                    "source": period_context.source,
                    "available": period_context.available,
                    "unavailable_reason": period_context.unavailable_reason,
                    "granularity": period_context.granularity,
                    "ambiguous": period_resolution.ambiguous,
                    "candidate_columns": [
                        candidate["column"] for candidate in period_resolution.period_candidates
                    ] + [
                        candidate["column"] for candidate in period_resolution.timestamp_candidates
                    ],
                },
                "note": note,
            }

            assessment_id = f"{entity_key}::{period_label}"

            scopes.append(
                AssessmentScope(
                    assessment_id=assessment_id,
                    entity=entity_context,
                    period=period_context,
                    record_indices=indices,
                    source_id=source_id,
                    source_type=source_type,
                    evidence_id=evidence_id,
                    metadata=metadata,
                    records=records,
                )
            )

        return AssessmentCollection(
            scopes=scopes,
            records=records,
            entity_resolution=entity_resolution,
            period_resolution=period_resolution,
            metadata={
                "source_id": source_id,
                "source_type": source_type,
                "evidence_id": evidence_id,
                "period_granularity": self.period_resolver.granularity,
                "derive_period_from_timestamps": self.period_resolver.derive_from_timestamps,
            },
        )
