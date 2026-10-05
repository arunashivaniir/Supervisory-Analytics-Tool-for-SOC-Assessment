"""Pre-run dataset preview for the New Assessment wizard (Batch D).

``preview_dataset`` answers "what does SAT-SA understand about this
submission" without running any analytics layer: profile, canonical
package (decisions, role, relationships, validation) and a bounded
schema view. Small files use the record flow; large files use the
Phase 2 scan flow, so previewing never materializes millions of rows
to decide it does not need them.

Reviewer input is recomputed, never pasted: an explicit role goes
through ``detect_role`` (which re-derives required-field validation),
and mapping overrides go through the mapper guard, the
unknown-concept check and collision detection before they replace an
automatic decision. Rejected overrides are reported, never applied.
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Mapping, Optional

from framework.canonical import decisions as mapping_decisions
from framework.canonical import relationships as joins
from framework.canonical import validate as package_validation
from framework.canonical.contract import (
    CONCEPTS,
    INVALID,
    MAPPED,
    UNMAPPED,
)
from framework.canonical.package import (
    build_canonical_package,
    build_canonical_package_scan,
)

REVIEWER_SOURCE = "REVIEWER_OVERRIDE"


def preview_dataset(
    dataset_file: str,
    pipeline: Any,
    explicit_role: Optional[str] = None,
    mapping_overrides: Optional[Mapping[str, Any]] = None,
    execution_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the bounded pre-run preview for one dataset file."""

    from framework.ingestion.paths import resolve_source, select_execution_mode

    source_path = resolve_source(dataset_file)
    mode = select_execution_mode(source_path, override=execution_mode)

    if mode == "large":
        return _preview_large(dataset_file, source_path, pipeline, explicit_role, mapping_overrides)

    return _preview_small(dataset_file, source_path, pipeline, explicit_role, mapping_overrides)


def _preview_small(
    dataset_file: str,
    source_path: Any,
    pipeline: Any,
    explicit_role: Optional[str],
    mapping_overrides: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    ingestion = pipeline.ingestion.load(source_path)
    profile = pipeline.profiler.profile(ingestion.profiling_target)
    package = build_canonical_package(
        dataset_file,
        profile,
        pipeline.semantic_engine,
        pipeline.mapper.mappings,
        ingestion.records,
        explicit_role=explicit_role,
        guard=pipeline.mapper.validate_mapping,
    )
    record_count = len(ingestion.records)

    return _finalize(
        dataset_file, package, profile, record_count, "small",
        _refresh_small, {
            "records": ingestion.records,
            "role": package["detected_role"]["role"],
        },
        mapping_overrides,
    )


def _preview_large(
    dataset_file: str,
    source_path: Any,
    pipeline: Any,
    explicit_role: Optional[str],
    mapping_overrides: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    from framework.ingestion.scan import open_scan
    from framework.profiling.scan_profiler import profile_scan

    scan = open_scan(source_path)

    try:
        profile = profile_scan(scan)
        package = build_canonical_package_scan(
            dataset_file,
            profile,
            pipeline.semantic_engine,
            pipeline.mapper.mappings,
            scan,
            explicit_role=explicit_role,
            guard=pipeline.mapper.validate_mapping,
        )
        record_count = scan.count()

        return _finalize(
            dataset_file, package, profile, record_count, "large_scan",
            _refresh_large, {"scan": scan, "role": package["detected_role"]["role"]},
            mapping_overrides,
        )
    finally:
        close = getattr(scan, "close", None)

        if callable(close):
            try:
                close()
            except Exception:
                pass


def _refresh_small(context: Dict[str, Any], decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    relationships = joins.summarize_relationships(context["records"], decisions)
    validation = package_validation.validate_package(
        context["source_id"], context["role"], decisions,
        context["records"], relationships, context["collisions"],
    )

    return {"relationships": relationships, "validation": validation}


def _refresh_large(context: Dict[str, Any], decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    relationships = joins.summarize_scan(context["scan"], decisions)
    validation = package_validation.validate_scan(
        context["source_id"], context["role"], decisions,
        context["scan"], relationships, context["collisions"],
    )

    return {"relationships": relationships, "validation": validation}


def _finalize(
    dataset_file: str,
    package: Mapping[str, Any],
    profile: Mapping[str, Any],
    record_count: int,
    execution_mode: str,
    refresh: Any,
    refresh_context: Dict[str, Any],
    mapping_overrides: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    decisions = [dict(item) for item in package["mapping_decisions"]]
    rejected: List[Dict[str, Any]] = []

    refresh_context = dict(
        refresh_context,
        source_id=dataset_file,
        collisions=list(package["mapping_collisions"]),
    )

    if mapping_overrides:
        decisions, rejected = apply_reviewer_overrides(
            decisions, mapping_overrides, package.get("canonical_contract", {}),
        )
        refreshed = refresh(refresh_context, decisions)
        relationships: Mapping[str, Any] = refreshed["relationships"]
        validation: Mapping[str, Any] = refreshed["validation"]
    else:
        relationships = package["relationships"]
        validation = package["validation"]

    profile_columns = {
        str(column.get("column_name", "")).lower(): column
        for column in (profile.get("columns", []) or [])
        if isinstance(column.get("column_name"), str)
    }

    schema_columns = []

    for column in package["schema"]["columns"]:
        name = column.get("column_name")
        source = profile_columns.get(str(name).lower(), {}) if isinstance(name, str) else {}

        schema_columns.append(
            {
                "column_name": name,
                "category": column.get("category"),
                "sample_values": list(source.get("sample_values", []) or [])[:10],
            }
        )

    return {
        "dataset": dataset_file,
        "record_count": record_count,
        "execution_mode": execution_mode,
        "detected_role": package["detected_role"],
        "schema": {"columns": schema_columns},
        "mapping_decisions": decisions,
        "mapping_states": mapping_decisions.states_count(decisions),
        "mapping_collisions": package["mapping_collisions"],
        "mapping_overrides_rejected": rejected,
        "validation": {
            "error_count": validation.get("error_count", 0),
            "warning_count": validation.get("warning_count", 0),
            "issues": validation.get("issues", []),
        },
        "relationships": relationships,
        "canonical_contract": package["canonical_contract"],
        "previewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def apply_reviewer_overrides(
    decisions: List[Dict[str, Any]],
    overrides: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> Any:
    """Apply reviewer mapping choices onto automatic decisions.

    Returns ``(new_decisions, rejected)``. A choice is applied only when
    the concept is known, has a canonical path, passes the actor guard
    and collides with nothing already claimed; otherwise it is reported
    in ``rejected`` and the automatic decision stands. The original
    automatic concept/state is always preserved beside the reviewer
    choice. Pure function: the input list is never mutated.
    """

    from framework.mapping.schema_mapper import TIMESTAMP_CONCEPTS

    fresh = [dict(item) for item in decisions]
    by_field = {item["source_field"]: item for item in fresh}
    rejected: List[Dict[str, Any]] = []

    claimed: Dict[str, str] = {}

    for item in fresh:
        concept = item.get("canonical_concept")

        if item.get("applied") and concept:
            path = (contract.get(concept, {}) or {}).get("canonical_path")

            if path:
                claimed.setdefault(path, item["source_field"])

    for field, wanted in dict(overrides or {}).items():
        decision = by_field.get(field)

        if decision is None:
            rejected.append(
                {"source_field": field, "reason": "Unknown source field."}
            )
            continue

        previous_concept = decision.get("canonical_concept")
        previous_state = decision.get("mapping_state")

        if wanted is None:
            decision["reviewer_override"] = {
                "concept": None,
                "previous_concept": previous_concept,
                "previous_state": previous_state,
                "source": REVIEWER_SOURCE,
            }
            decision["canonical_concept"] = None
            decision["canonical_path"] = None
            decision["confidence"] = 0.0
            decision["mapping_state"] = UNMAPPED
            decision["applied"] = False
            continue

        entry = contract.get(wanted) or CONCEPTS.get(wanted)

        if entry is None:
            rejected.append(
                {
                    "source_field": field,
                    "concept": wanted,
                    "reason": "'%s' is not a known canonical concept." % wanted,
                }
            )
            continue

        path = entry.get("canonical_path")

        if not path:
            rejected.append(
                {
                    "source_field": field,
                    "concept": wanted,
                    "reason": "'%s' has nowhere to be written." % wanted,
                }
            )
            continue

        if wanted in TIMESTAMP_CONCEPTS and field.lower().endswith("_by"):
            rejected.append(
                {
                    "source_field": field,
                    "concept": wanted,
                    "reason": (
                        "Actor-like field '%s' cannot map to timestamp "
                        "concept '%s'." % (field, wanted)
                    ),
                }
            )
            continue

        owner = claimed.get(path)

        if owner is not None and owner != field:
            rejected.append(
                {
                    "source_field": field,
                    "concept": wanted,
                    "reason": (
                        "Collision on '%s': '%s' already claims it."
                        % (path, owner)
                    ),
                }
            )
            continue

        old_path = decision.get("canonical_path")

        if old_path and claimed.get(old_path) == field:
            del claimed[old_path]

        claimed[path] = field
        decision["reviewer_override"] = {
            "concept": wanted,
            "previous_concept": previous_concept,
            "previous_state": previous_state,
            "source": REVIEWER_SOURCE,
        }
        decision["canonical_concept"] = wanted
        decision["canonical_path"] = path
        decision["mapping_state"] = MAPPED
        decision["applied"] = True
        decision["reason"] = (
            "Reviewer override of automatic %s; guards and collision "
            "checks passed." % previous_state
        )

    # A rejected best candidate invalidates the same way Phase 1 does, so
    # mark anything the guard would refuse that slipped through as INVALID.
    for item in fresh:
        concept = item.get("canonical_concept")

        if (
            item.get("applied")
            and concept in TIMESTAMP_CONCEPTS
            and item["source_field"].lower().endswith("_by")
        ):
            item["mapping_state"] = INVALID
            item["applied"] = False

    return fresh, rejected
