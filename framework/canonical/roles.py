"""Dataset role detection for SAT-SA Phase 1.

Classifies one submission schema as ALERTS, CASES, WORKFLOW_EVENTS,
ASSETS or UNKNOWN from the mapping decisions — which canonical concepts
the schema actually carries — never from the filename.

An explicit role, when the caller supplies one, is respected verbatim:
detection is a fallback, not an override. When the evidence is thin or
contradictory the answer is UNKNOWN (review required), never a forced
classification.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from framework.canonical.contract import (
    ROLE_ALERTS,
    ROLE_ASSETS,
    ROLE_CASES,
    ROLE_UNKNOWN,
    ROLE_WORKFLOW_EVENTS,
)

# Concept presence that argues for each role. The first element of each
# set is the anchor: without it the role cannot win no matter how many
# supporting concepts matched.
ROLE_SIGNALS: Dict[str, Dict[str, List[str]]] = {
    ROLE_WORKFLOW_EVENTS: {
        "anchor": ["WORKFLOW_CASE_ID"],
        "support": [
            "WORKFLOW_EVENT_AT",
            "WORKFLOW_EVENT_TYPE",
            "WORKFLOW_ACTOR",
            "WORKFLOW_TIER",
            "CASE_ID",
        ],
    },
    ROLE_CASES: {
        "anchor": ["CASE_ID"],
        "support": [
            "CLOSED_AT",
            "ACKNOWLEDGED_AT",
            "CLOSURE_DISPOSITION",
            "ANALYST_ID",
            "CASE_ALERT_ID",
            "ESCALATION_LEVEL",
            "ESCALATION_STATUS",
            "INVESTIGATION_NOTES",
            "INVESTIGATION_EVIDENCE",
        ],
    },
    ROLE_ALERTS: {
        "anchor": ["ALERT_ID"],
        "support": [
            "SECURITY_SEVERITY",
            "TRIGGERED_AT",
            "EVENT_TIMESTAMP",
            "THREAT_CATEGORY",
            "ALERT_NAME",
            "EVENT_ID",
            "SOURCE_SYSTEM",
        ],
    },
    ROLE_ASSETS: {
        "anchor": ["ASSET_IDENTIFIER"],
        "support": [
            "ASSET_CRITICALITY",
            "ASSET_TYPE",
            "EXPECTED_TELEMETRY",
            "NETWORK_ZONE",
        ],
    },
}

# Tie-break order when two roles score equally. Workflow events beat cases
# beat alerts beat assets: the more specific the grain, the more a wrong
# role would distort joins.
_TIE_BREAK = (
    ROLE_WORKFLOW_EVENTS,
    ROLE_CASES,
    ROLE_ALERTS,
    ROLE_ASSETS,
)


def detect_role(
    decisions: Sequence[Mapping[str, Any]],
    explicit_role: Optional[str] = None,
) -> Dict[str, Any]:
    """Detect the dataset role from applied mapping decisions."""

    if explicit_role is not None:
        if explicit_role in (
            ROLE_ALERTS,
            ROLE_CASES,
            ROLE_WORKFLOW_EVENTS,
            ROLE_ASSETS,
            ROLE_UNKNOWN,
        ):
            return {
                "role": explicit_role,
                "confidence": 1.0,
                "reason": "Explicit role supplied by the caller; "
                "detection did not override it.",
                "signals": [],
            }

        return {
            "role": ROLE_UNKNOWN,
            "confidence": 0.0,
            "reason": "Explicit role '%s' is not a known role; "
            "review required." % explicit_role,
            "signals": [],
        }

    applied: Set[str] = {
        item["canonical_concept"]
        for item in decisions
        if item.get("applied") and item.get("canonical_concept")
    }

    scored = []

    for role, signals in ROLE_SIGNALS.items():
        anchor_present = any(name in applied for name in signals["anchor"])
        support = sorted(name for name in signals["support"] if name in applied)

        if not anchor_present:
            continue

        # The anchor plus at least one supporting concept: an identifier
        # alone says nothing about what the rows are.
        if not support:
            continue

        total = 1 + len(signals["support"])
        score = round((1 + len(support)) / total, 2)
        scored.append((role, score, support))

    if not scored:
        return {
            "role": ROLE_UNKNOWN,
            "confidence": 0.0,
            "reason": "No role anchor with supporting concepts was found; "
            "review required rather than a forced classification.",
            "signals": [],
        }

    scored.sort(
        key=lambda entry: (-entry[1], _TIE_BREAK.index(entry[0])),
    )
    role, confidence, support = scored[0]

    return {
        "role": role,
        "confidence": confidence,
        "reason": "Anchor and supporting concepts matched: %s."
        % ", ".join([role] + support),
        "signals": support,
    }
