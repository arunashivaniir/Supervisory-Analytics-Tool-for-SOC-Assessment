"""Canonical package builder for SAT-SA Phase 1.

One call turns a submission into the Phase 1 foundation::

    SOURCE SCHEMA
        -> infer candidates once (schema level)
        -> decide mappings once (states, ambiguity, collisions)
        -> detect pipeline role
        -> summarize relationships
        -> validate
        -> package (schema, mapping, validation, relationships, provenance)

The package is plain JSON-serializable data. Per-record transformation
for compatibility still happens in ``SchemaMapper.map_record``; the
*decision* no longer depends on any record.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from framework.assessment.entity_context import build_column_name_index
from framework.canonical import decisions as mapping_decisions
from framework.canonical import roles as dataset_roles
from framework.canonical import relationships as joins
from framework.canonical import validate as package_validation
from framework.canonical.contract import MAPPING_STATES

PACKAGE_VERSION = "1"


def build_canonical_package(
    source_id: str,
    profile: Mapping[str, Any],
    semantic_engine: Any,
    mappings: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    explicit_role: Optional[str] = None,
    guard: Optional[Callable[[str, str, Any], bool]] = None,
) -> Dict[str, Any]:
    """Build the canonical package for one submission."""

    columns = list(profile.get("columns", []) or [])
    name_index = build_column_name_index(profile)

    candidates = semantic_engine.infer_with_candidates(profile)

    decided = mapping_decisions.decide_mappings(
        columns, candidates, mappings, name_index, guard
    )
    ordered = decided["decisions"]

    role = dataset_roles.detect_role(ordered, explicit_role=explicit_role)

    relationships = joins.summarize_relationships(records, ordered)

    validation = package_validation.validate_package(
        source_id,
        role["role"],
        ordered,
        records,
        relationships,
        decided["collisions"],
    )

    return _assemble(
        source_id, role, profile, ordered, decided["collisions"],
        relationships, validation, len(records), "small",
    )


def build_canonical_package_scan(
    source_id: str,
    profile: Mapping[str, Any],
    semantic_engine: Any,
    mappings: Mapping[str, Any],
    scan: Any,
    explicit_role: Optional[str] = None,
    guard: Optional[Callable[[str, str, Any], bool]] = None,
) -> Dict[str, Any]:
    """Build the canonical package by streaming a scan.

    Same package shape as :func:`build_canonical_package`. Joins and
    validation run as SQL aggregations plus bounded streaming, so full
    counts are exact without materializing rows. Provenance records the
    large-scan execution mode.
    """

    columns = list(profile.get("columns", []) or [])
    name_index = build_column_name_index(profile)

    candidates = semantic_engine.infer_with_candidates(profile)

    decided = mapping_decisions.decide_mappings(
        columns, candidates, mappings, name_index, guard
    )
    ordered = decided["decisions"]

    role = dataset_roles.detect_role(ordered, explicit_role=explicit_role)

    relationships = joins.summarize_scan(scan, ordered)

    validation = package_validation.validate_scan(
        source_id,
        role["role"],
        ordered,
        scan,
        relationships,
        decided["collisions"],
    )

    return _assemble(
        source_id, role, profile, ordered, decided["collisions"],
        relationships, validation, scan.count(), "large_scan",
        scan_metrics={
            "source_type": scan.source_type,
            "size_bytes": scan.size_bytes,
        },
    )


def _assemble(
    source_id: str,
    role: Dict[str, Any],
    profile: Mapping[str, Any],
    ordered: List[Dict[str, Any]],
    collisions: List[Dict[str, Any]],
    relationships: Dict[str, Any],
    validation: Dict[str, Any],
    record_count: int,
    execution_mode: str,
    scan_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    provenance: Dict[str, Any] = {
        "built_by": "framework.canonical.package",
        "mapping_thresholds": {
            "apply": 0.45,
            "mapped": 0.60,
            "ambiguity_margin": 0.10,
        },
        "naive_timestamp_policy": "assumed_utc",
        "record_count": record_count,
        "execution_mode": execution_mode,
    }

    if scan_metrics:
        provenance["scan"] = scan_metrics

    return {
        "package_version": PACKAGE_VERSION,
        "source_dataset": source_id,
        "detected_role": role,
        "schema": {
            "columns": [
                {
                    "column_name": column.get("column_name"),
                    "category": column.get("category"),
                }
                for column in list(profile.get("columns", []) or [])
            ],
        },
        "mapping_decisions": ordered,
        "mapping_collisions": collisions,
        "mapping_states": mapping_decisions.states_count(ordered),
        "validation": validation,
        "relationships": relationships,
        "provenance": provenance,
    }


def applied_decisions(
    package: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Legacy-shape applied entries from a built package."""

    return mapping_decisions.applied_mapping(
        package.get("mapping_decisions", [])
    )


def mapping_state_names() -> List[str]:
    """The closed mapping-state vocabulary."""

    return list(MAPPING_STATES)
