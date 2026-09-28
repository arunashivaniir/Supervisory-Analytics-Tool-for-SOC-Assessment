"""Canonical domain contract for SAT-SA Phase 1.

This module declares the supervisory data model: which canonical concepts
exist, which pipeline they belong to, what shape they have, and which
aliases may name them in a submission. It is metadata only — no I/O, no
inference, no transformation.

Two vocabulary sources already exist and are reused, not duplicated:

* ``framework/config/mappings.json`` maps concept -> canonical_path.
  Every concept declared here must resolve to a path there.
* ``framework/config/semantic_patterns.json`` carries the inference
  evidence (keywords, negatives, categories, value patterns).

``CONCEPTS`` adds what neither file states: the domain category, the
source pipeline, the datatype, whether the field is required for its
pipeline role, and cardinality. Required here means "expected when the
dataset plays the matching pipeline role" — it drives validation, never
a silent default.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# ---------------------------------------------------------------------------
# Mapping states.
#
# A mapping decision is made once per source field, at the schema level.
# WRONG MAPPING IS WORSE THAN UNMAPPED: ambiguous candidates must never
# silently become MAPPED.
# ---------------------------------------------------------------------------

MAPPED = "MAPPED"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
AMBIGUOUS = "AMBIGUOUS"
UNMAPPED = "UNMAPPED"
INVALID = "INVALID"

MAPPING_STATES = (MAPPED, LOW_CONFIDENCE, AMBIGUOUS, UNMAPPED, INVALID)

# Score at or above which the existing pipeline applies a mapping.
# Unchanged from the v4 behaviour (SemanticInference threshold and
# SchemaMapper threshold both 0.45).
APPLY_THRESHOLD = 0.45

# Score at or above which a mapping is reported as MAPPED rather than
# LOW_CONFIDENCE. Between APPLY_THRESHOLD and this value the mapping is
# applied exactly as v4 applied it, but flagged so downstream consumers
# can see it was a weak match.
MAPPED_MIN_CONFIDENCE = 0.60

# Minimum margin between the best and second-best candidate for the best
# to be applied. Below this margin the field is AMBIGUOUS and neither
# candidate is applied — a slightly higher score is not evidence when two
# concepts both plausibly explain a name.
AMBIGUITY_MARGIN = 0.10

# ---------------------------------------------------------------------------
# Dataset roles (Pipeline 1 / Pipeline 2).
# ---------------------------------------------------------------------------

ROLE_ALERTS = "ALERTS"
ROLE_CASES = "CASES"
ROLE_WORKFLOW_EVENTS = "WORKFLOW_EVENTS"
ROLE_ASSETS = "ASSETS"
ROLE_UNKNOWN = "UNKNOWN"

DATASET_ROLES = (
    ROLE_ALERTS,
    ROLE_CASES,
    ROLE_WORKFLOW_EVENTS,
    ROLE_ASSETS,
    ROLE_UNKNOWN,
)

# ---------------------------------------------------------------------------
# Concept declarations.
#
# category:  ALERT | CASE | WORKFLOW_EVENT | ASSET | SHARED
# pipeline:  PIPELINE_1 | PIPELINE_2 | WORKFLOW | ASSET | SHARED
# datatype:  identifier | timestamp | categorical | text | numeric | boolean
# required:  expected when the dataset plays the concept's pipeline role.
# cardinality: ONE per record for scalar slots; MANY where a record may
#   legitimately carry several values (currently informational).
# ---------------------------------------------------------------------------


def _concept(
    canonical_path: str,
    category: str,
    pipeline: str,
    datatype: str,
    required: bool = False,
    cardinality: str = "ONE",
    aliases: Optional[List[str]] = None,
    note: str = "",
) -> Dict[str, Any]:
    return {
        "canonical_path": canonical_path,
        "category": category,
        "pipeline": pipeline,
        "datatype": datatype,
        "required": required,
        "cardinality": cardinality,
        "aliases": list(aliases or []),
        "note": note,
    }


CONCEPTS: Dict[str, Dict[str, Any]] = {
    # -- Pre-existing v4 concepts (paths unchanged) -------------------------
    "SECURITY_SEVERITY": _concept(
        "alert_context.severity", "ALERT", "PIPELINE_1", "categorical",
        required=True,
        aliases=["severity", "priority", "sev", "risk_rating"],
    ),
    "ASSET_IDENTIFIER": _concept(
        "asset_context.asset_id", "ASSET", "SHARED", "identifier",
        aliases=["asset_id", "assetid", "host", "hostname"],
    ),
    "ASSET_CRITICALITY": _concept(
        "asset_context.criticality", "ASSET", "ASSET", "categorical",
        aliases=["criticality", "asset_criticality", "business_impact"],
        note="Importance of the asset, never alert severity.",
    ),
    "ASSET_TYPE": _concept(
        "asset_context.asset_type", "ASSET", "SHARED", "categorical",
        aliases=["asset_type", "host_type", "device_type"],
    ),
    "RESOLUTION_TIME": _concept(
        "response_context.resolution_time", "CASE", "PIPELINE_2", "timestamp",
        aliases=["resolution_time", "resolved_at"],
    ),
    "EVENT_TIMESTAMP": _concept(
        "alert_context.timestamp", "ALERT", "PIPELINE_1", "timestamp",
        aliases=["event_timestamp", "event_time"],
    ),
    "USER_IDENTIFIER": _concept(
        "entity_context.entity_name", "SHARED", "SHARED", "identifier",
    ),
    "THREAT_CATEGORY": _concept(
        "alert_context.category", "ALERT", "PIPELINE_1", "categorical",
        aliases=["category", "threat_type", "attack_type"],
    ),
    "INVESTIGATION_EVIDENCE": _concept(
        "investigation_context.notes", "CASE", "PIPELINE_2", "text",
        aliases=["investigation_notes", "notes", "comments"],
    ),
    "ESCALATION_STATUS": _concept(
        "response_context.escalation_status", "CASE", "PIPELINE_2",
        "categorical",
        aliases=["escalation_status", "escalated"],
    ),
    # -- Pipeline 1: alert / SIEM-like submission ---------------------------
    "ALERT_ID": _concept(
        "alert_context.alert_id", "ALERT", "PIPELINE_1", "identifier",
        required=True,
        aliases=["alert_id", "alertid", "alert_number", "alert_key"],
    ),
    "EVENT_ID": _concept(
        "alert_context.event_id", "ALERT", "PIPELINE_1", "identifier",
        aliases=["event_id", "eventid"],
    ),
    "TRIGGERED_AT": _concept(
        "alert_context.timestamp", "ALERT", "PIPELINE_1", "timestamp",
        required=True,
        aliases=["triggered_at", "detected_at", "event_time", "alert_time"],
        note="Pipeline 1 name for the EVENT_TIMESTAMP slot.",
    ),
    "ALERT_NAME": _concept(
        "alert_context.alert_name", "ALERT", "PIPELINE_1", "categorical",
        aliases=["alert_name", "rule_name", "detection_name"],
    ),
    "NETWORK_ZONE": _concept(
        "asset_context.network_zone", "ASSET", "SHARED", "categorical",
        aliases=["network_zone", "zone", "segment"],
    ),
    "SOURCE_SYSTEM": _concept(
        "alert_context.source_system", "ALERT", "PIPELINE_1", "categorical",
        aliases=["source_system", "sensor", "collector"],
    ),
    # -- Pipeline 2: case / workflow / SOAR / ITSM submission ---------------
    "CASE_ID": _concept(
        "case_context.case_id", "CASE", "PIPELINE_2", "identifier",
        required=True,
        aliases=["case_id", "caseid", "ticket_id", "incident_id"],
    ),
    "CASE_ALERT_ID": _concept(
        "case_context.alert_id", "CASE", "PIPELINE_2", "identifier",
        note="Join key to Pipeline 1. Only case-qualified spellings.",
    ),
    "ACKNOWLEDGED_AT": _concept(
        "case_context.acknowledged_at", "CASE", "PIPELINE_2", "timestamp",
        aliases=["acknowledged_at", "ack_time"],
    ),
    "CLOSED_AT": _concept(
        "case_context.closed_at", "CASE", "PIPELINE_2", "timestamp",
        aliases=["closed_at", "close_time", "resolved_at"],
    ),
    "ANALYST_ID": _concept(
        "case_context.analyst_id", "CASE", "PIPELINE_2", "identifier",
        aliases=["analyst_id", "analyst", "assigned_to"],
    ),
    "ESCALATION_LEVEL": _concept(
        "case_context.escalation_level", "CASE", "PIPELINE_2", "categorical",
        aliases=["escalation_level", "esc_level", "tier"],
        note="The level reached, never the escalation state.",
    ),
    "CLOSURE_DISPOSITION": _concept(
        "case_context.closure_disposition", "CASE", "PIPELINE_2",
        "categorical",
        aliases=["disposition", "closure", "outcome"],
    ),
    "INVESTIGATION_NOTES": _concept(
        "case_context.investigation_notes", "CASE", "PIPELINE_2", "text",
        aliases=["case_notes", "analyst_notes"],
        note="Case-qualified note spellings; bare investigation_notes "
        "stays with INVESTIGATION_EVIDENCE.",
    ),
    # -- Workflow events -----------------------------------------------------
    "WORKFLOW_CASE_ID": _concept(
        "workflow_context.case_id", "WORKFLOW_EVENT", "WORKFLOW",
        "identifier", required=True,
        note="Join key to cases. Only workflow-qualified spellings.",
    ),
    "WORKFLOW_EVENT_AT": _concept(
        "workflow_context.event_at", "WORKFLOW_EVENT", "WORKFLOW",
        "timestamp",
        aliases=["event_at"],
    ),
    "WORKFLOW_EVENT_TYPE": _concept(
        "workflow_context.event_type", "WORKFLOW_EVENT", "WORKFLOW",
        "categorical",
        aliases=["event_type", "transition"],
    ),
    "WORKFLOW_ACTOR": _concept(
        "workflow_context.actor", "WORKFLOW_EVENT", "WORKFLOW", "identifier",
        aliases=["actor", "performed_by"],
    ),
    "WORKFLOW_TIER": _concept(
        "workflow_context.tier", "WORKFLOW_EVENT", "WORKFLOW", "categorical",
    ),
    # -- Asset / inventory ---------------------------------------------------
    "EXPECTED_TELEMETRY": _concept(
        "monitoring_context.expected_telemetry", "ASSET", "ASSET",
        "categorical",
        aliases=["expected_telemetry", "expected_coverage"],
    ),
}


def concept_names() -> List[str]:
    """Every canonical concept the contract declares."""

    return list(CONCEPTS)


def get_concept(name: str) -> Optional[Dict[str, Any]]:
    """The contract entry for a concept, or None when undeclared."""

    entry = CONCEPTS.get(name)

    if entry is None:
        return None

    return dict(entry, aliases=list(entry["aliases"]))


def concepts_for_pipeline(pipeline: str) -> List[str]:
    """Concept names belonging to a pipeline (or SHARED for any)."""

    return [
        name
        for name, entry in CONCEPTS.items()
        if entry["pipeline"] == pipeline or entry["pipeline"] == "SHARED"
    ]


def required_for_role(role: str) -> List[str]:
    """Concepts expected when a dataset plays a role.

    ALERTS -> required PIPELINE_1 concepts, CASES -> required PIPELINE_2,
    WORKFLOW_EVENTS -> required WORKFLOW, ASSETS -> required ASSET.
    UNKNOWN declares nothing required: an unclassified dataset cannot
    fail a requirement it was never shown to have.
    """

    wanted = {
        ROLE_ALERTS: "PIPELINE_1",
        ROLE_CASES: "PIPELINE_2",
        ROLE_WORKFLOW_EVENTS: "WORKFLOW",
        ROLE_ASSETS: "ASSET",
    }.get(role)

    if wanted is None:
        return []

    return [
        name
        for name, entry in CONCEPTS.items()
        if entry["pipeline"] == wanted and entry["required"]
    ]


def check_against_mappings(mappings: Mapping[str, Any]) -> List[str]:
    """Contract concepts with no canonical_path in mappings.json.

    A non-empty return is a configuration error: inference could name a
    concept the mapper cannot write.
    """

    missing = []

    for name in CONCEPTS:
        entry = mappings.get(name)

        if not isinstance(entry, dict) or not entry.get("canonical_path"):
            missing.append(name)

    return missing
