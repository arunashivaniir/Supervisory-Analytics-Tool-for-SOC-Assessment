"""Canonical validation for SAT-SA Phase 1.

Structured data-quality issues over the canonical package. Every issue is
a plain record::

    {
        "code": "...",        # stable machine key, e.g. ORPHAN_CASE
        "severity": "...",    # error | warning | info
        "entity": "...",      # dataset under assessment
        "field": "...",       # source field, when the issue has one
        "source": "...",      # where the issue was observed
        "message": "...",     # human sentence, no jargon
    }

Severity policy, documented so it cannot drift silently:

* error   — the evidence contradicts itself (impossible chronology,
  conflicting identifiers). Something must be resolved before the
  timeline or the join can be trusted.
* warning — the evidence is incomplete or ambiguous in a way that limits
  analysis (orphans, missing keys, unknown values, collisions,
  duplicates where uniqueness is expected). Analysis continues; the
  limitation is stated.
* info    — a relationship that could not be assessed because a join key
  never mapped. Not a failure — a boundary of what was checkable.

Nothing here corrects data. A broken timestamp is flagged, never fixed;
an unknown severity is reported, never defaulted.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from framework.canonical import normalize as values
from framework.canonical.contract import required_for_role
from framework.canonical.relationships import (
    case_variant_conflicts,
    find_id_field,
    normalize_id,
)

ERROR = "error"
WARNING = "warning"
INFO = "info"

# Per-check issue cap. Counts stay exact; only the listed samples are
# capped, so a pathological file cannot bloat the package.
MAX_ISSUES_PER_CHECK = 25


def make_issue(
    code: str,
    severity: str,
    message: str,
    entity: str = "",
    field: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """One structured validation issue."""

    return {
        "code": code,
        "severity": severity,
        "entity": entity,
        "field": field,
        "source": source,
        "message": message,
    }


def validate_package(
    source_id: str,
    role: str,
    decisions: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    relationships: Mapping[str, Any],
    collisions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate the canonical package, returning issues plus counts."""

    issues: List[Dict[str, Any]] = []

    issues.extend(_check_required(source_id, role, decisions))
    issues.extend(_check_duplicates(source_id, role, decisions, records))
    issues.extend(_check_identifier_conflicts(source_id, decisions, records))
    issues.extend(_check_joins(source_id, relationships))
    issues.extend(
        _check_values(source_id, decisions, records)
    )
    issues.extend(_check_collisions(source_id, collisions))
    counts: Dict[str, int] = {}

    for issue in issues:
        counts[issue["code"]] = counts.get(issue["code"], 0) + 1

    return {
        "issues": issues,
        "issue_counts": counts,
        "error_count": sum(1 for item in issues if item["severity"] == ERROR),
        "warning_count": sum(
            1 for item in issues if item["severity"] == WARNING
        ),
    }


def _check_required(
    source_id: str,
    role: str,
    decisions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    applied = {
        item["canonical_concept"] for item in decisions if item.get("applied")
    }
    issues = []

    for concept in required_for_role(role):
        if concept not in applied:
            issues.append(
                make_issue(
                    "MISSING_REQUIRED_FIELD",
                    WARNING,
                    "Role %s expects '%s' but no source field mapped to "
                    "it. Checks needing it are not assessable."
                    % (role, concept),
                    entity=source_id,
                    field=None,
                    source="role:%s" % role,
                )
            )

    return issues


def _check_duplicates(
    source_id: str,
    role: str,
    decisions: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    issues = []

    for concept, code in (
        ("ALERT_ID", "DUPLICATE_ALERT_ID"),
        ("CASE_ID", "DUPLICATE_CASE_ID"),
    ):
        field = find_id_field(decisions, concept)

        if field is None:
            continue

        seen: Counter = Counter()
        total = 0

        for record in records:
            identifier = normalize_id(record.get(field))

            if identifier is None:
                continue

            total += 1
            seen[identifier] += 1

        duplicates = sorted(
            identifier
            for identifier, count in seen.items()
            if count > 1
        )

        if not duplicates:
            continue

        # Alert identifiers are expected unique per alert row; case rows
        # legitimately repeat a case across event-style rows, so the same
        # observation is an error in one role and a warning in the other.
        severity = (
            ERROR
            if (concept == "ALERT_ID" and role == "ALERTS")
            or (concept == "CASE_ID" and role == "CASES")
            else WARNING
        )

        issues.append(
            make_issue(
                code,
                severity,
                "'%s' repeats %d of %d distinct values %d times in "
                "total. Joins on this key treat repeats as one entity."
                % (
                    field,
                    len(duplicates),
                    len(seen),
                    sum(seen[item] - 1 for item in duplicates),
                ),
                entity=source_id,
                field=field,
                source="records:%d" % total,
            )
        )

    return issues[:MAX_ISSUES_PER_CHECK]


def _check_identifier_conflicts(
    source_id: str,
    decisions: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    issues = []

    for concept in ("ALERT_ID", "CASE_ID", "WORKFLOW_CASE_ID"):
        field = find_id_field(decisions, concept)

        if field is None:
            continue

        ids = {
            normalize_id(record.get(field))
            for record in records
        }
        ids.discard(None)

        for first, second in case_variant_conflicts(ids)[:5]:
            issues.append(
                make_issue(
                    "CONFLICTING_IDENTIFIERS",
                    ERROR,
                    "'%s' and '%s' differ only by case. They join as "
                    "distinct keys but may name one entity; the join "
                    "cannot be trusted until resolved." % (first, second),
                    entity=source_id,
                    field=field,
                    source="records",
                )
            )

    return issues[:MAX_ISSUES_PER_CHECK]


def _check_joins(
    source_id: str,
    relationships: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    issues = []

    if not relationships.get("alert_case_assessable"):
        issues.append(
            make_issue(
                "JOIN_NOT_ASSESSABLE",
                INFO,
                "Alert/case linkage could not be assessed: a join key "
                "never mapped. This is a boundary of what was checkable, "
                "not a finding.",
                entity=source_id,
                source="relationships",
            )
        )
    else:
        orphans = relationships.get("orphan_cases", {})
        alerts_without = relationships.get("alerts_without_case", {})

        if orphans.get("count"):
            issues.append(
                make_issue(
                    "ORPHAN_CASE",
                    WARNING,
                    "%d case(s) name alerts absent from the alerts side "
                    "(e.g. %s). They cannot be corroborated."
                    % (
                        orphans["count"],
                        ", ".join(orphans["sample"][:3]) or "—",
                    ),
                    entity=source_id,
                    source="relationships",
                )
            )

        if alerts_without.get("count"):
            issues.append(
                make_issue(
                    "UNMATCHED_ALERT",
                    INFO,
                    "%d alert(s) have no linked case. Unmatched alerts "
                    "are normal where case coverage is partial; they are "
                    "counted, not judged." % alerts_without["count"],
                    entity=source_id,
                    source="relationships",
                )
            )

    if not relationships.get("workflow_assessable"):
        if relationships.get("join_fields", {}).get("workflow_case_id"):
            issues.append(
                make_issue(
                    "JOIN_NOT_ASSESSABLE",
                    INFO,
                    "Workflow/case linkage could not be assessed: the "
                    "case side never mapped.",
                    entity=source_id,
                    source="relationships",
                )
            )
    else:
        orphan_events = relationships.get("orphan_workflow_cases", {})

        if orphan_events.get("count"):
            issues.append(
                make_issue(
                    "ORPHAN_WORKFLOW_EVENT",
                    WARNING,
                    "%d workflow event case(s) name cases absent from "
                    "the case side (e.g. %s)."
                    % (
                        orphan_events["count"],
                        ", ".join(orphan_events["sample"][:3]) or "—",
                    ),
                    entity=source_id,
                    source="relationships",
                )
            )

    missing_keys = relationships.get("rows_with_case_but_no_alert_key", 0)

    if missing_keys:
        issues.append(
            make_issue(
                "MISSING_JOIN_KEY",
                WARNING,
                "%d case row(s) carry no alert join key. They cannot be "
                "linked to Pipeline 1." % missing_keys,
                entity=source_id,
                source="relationships",
            )
        )

    return issues


def _check_values(
    source_id: str,
    decisions: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []

    severity_field = find_id_field(decisions, "SECURITY_SEVERITY")
    unknown_severities: Set[str] = set()

    if severity_field:
        for record in records:
            raw = record.get(severity_field)

            if normalize_id(raw) is None:
                continue

            if not values.normalize_severity(raw)["known"]:
                unknown_severities.add(str(raw).strip())

                if len(unknown_severities) >= MAX_ISSUES_PER_CHECK:
                    break

        for raw in sorted(unknown_severities):
            issues.append(
                make_issue(
                    "INVALID_SEVERITY",
                    WARNING,
                    "Severity value '%s' is outside the known vocabulary. "
                    "Kept as submitted; not defaulted." % raw,
                    entity=source_id,
                    field=severity_field,
                    source="records",
                )
            )

    trigger_field = find_id_field(
        decisions, "TRIGGERED_AT", "EVENT_TIMESTAMP"
    )
    ack_field = find_id_field(decisions, "ACKNOWLEDGED_AT")
    close_field = find_id_field(
        decisions, "CLOSED_AT", "RESOLUTION_TIME"
    )

    if trigger_field or ack_field or close_field:
        bad_timestamps = 0
        chronology: Dict[str, int] = {}

        for record in records:
            parsed = {}

            for label, field in (
                ("triggered", trigger_field),
                ("acknowledged", ack_field),
                ("closed", close_field),
            ):
                if not field:
                    parsed[label] = None
                    continue

                outcome = values.parse_timestamp(record.get(field))

                if outcome["canonical"] is None and normalize_id(
                    record.get(field)
                ) is not None:
                    bad_timestamps += 1

                parsed[label] = outcome["canonical"]

            for violation in values.check_chronology(
                parsed["triggered"], parsed["acknowledged"], parsed["closed"]
            ):
                chronology[violation["pair"]] = (
                    chronology.get(violation["pair"], 0) + 1
                )

        if bad_timestamps:
            issues.append(
                make_issue(
                    "INVALID_TIMESTAMP",
                    WARNING,
                    "%d timestamp value(s) could not be parsed. Flagged, "
                    "never reinterpreted." % bad_timestamps,
                    entity=source_id,
                    source="records",
                )
            )

        for pair, count in sorted(chronology.items()):
            issues.append(
                make_issue(
                    "IMPOSSIBLE_CHRONOLOGY",
                    ERROR,
                    "%d record(s) show '%s'. The timeline contradicts "
                    "itself; it was flagged, not corrected."
                    % (count, pair),
                    entity=source_id,
                    source="records",
                )
            )

    return issues

def _check_collisions(
    source_id: str,
    collisions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    issues = []

    for collision in collisions:
        issues.append(
            make_issue(
                "MAPPING_COLLISION",
                WARNING,
                "Fields %s all claimed '%s'; '%s' won and the rest "
                "were left unmapped rather than merged."
                % (
                    ", ".join(
                        [collision["winner"]] + collision["losers"]
                    ),
                    collision["canonical_path"],
                    collision["winner"],
                ),
                entity=source_id,
                field=collision["winner"],
                source="mapping_decisions",
            )
        )

    return issues


def issue_codes(issues: Sequence[Mapping[str, Any]]) -> Counter:
    """Count issues by code (for reports and tests)."""

    return Counter(item["code"] for item in issues)


def validate_scan(
    source_id: str,
    role: str,
    decisions: Sequence[Mapping[str, Any]],
    scan: Any,
    relationships: Mapping[str, Any],
    collisions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate over a scan without materializing rows.

    Same issue shapes as :func:`validate_package`. Counts come from SQL
    aggregations; only distinct vocabularies and chronology triples
    stream through Python, both bounded. A truncated vocabulary skips
    its check with an info note rather than guessing from a sample.
    """

    issues: List[Dict[str, Any]] = []

    issues.extend(_check_required(source_id, role, decisions))
    issues.extend(_check_scan_duplicates(source_id, role, decisions, scan))
    issues.extend(_check_scan_conflicts(source_id, decisions, scan))
    issues.extend(_check_joins(source_id, relationships))
    issues.extend(_check_scan_values(source_id, decisions, scan))
    issues.extend(_check_collisions(source_id, collisions))

    counts: Dict[str, int] = {}

    for issue in issues:
        counts[issue["code"]] = counts.get(issue["code"], 0) + 1

    return {
        "issues": issues,
        "issue_counts": counts,
        "error_count": sum(1 for item in issues if item["severity"] == ERROR),
        "warning_count": sum(
            1 for item in issues if item["severity"] == WARNING
        ),
    }


def _check_scan_duplicates(
    source_id: str,
    role: str,
    decisions: Sequence[Mapping[str, Any]],
    scan: Any,
) -> List[Dict[str, Any]]:
    issues = []

    for concept, code in (
        ("ALERT_ID", "DUPLICATE_ALERT_ID"),
        ("CASE_ID", "DUPLICATE_CASE_ID"),
    ):
        field = find_id_field(decisions, concept)

        if field is None:
            continue

        total = scan.count_where([ (field, "notnull", None) ])
        distinct = scan.distinct_count(field)
        dups = scan.duplicate_values(field)

        if distinct == total:
            continue

        severity = (
            ERROR
            if (concept == "ALERT_ID" and role == "ALERTS")
            or (concept == "CASE_ID" and role == "CASES")
            else WARNING
        )
        repeated = sum(count - 1 for _, count in dups["items"])

        issues.append(
            make_issue(
                code,
                severity,
                "'%s' repeats values %d times in total across %d "
                "distinct keys%s. Joins on this key treat repeats as "
                "one entity."
                % (
                    field,
                    repeated,
                    distinct,
                    " (duplicate list truncated)" if dups["truncated"]
                    else "",
                ),
                entity=source_id,
                field=field,
                source="scan:%d rows" % scan.count(),
            )
        )

    return issues[:MAX_ISSUES_PER_CHECK]


def _check_scan_conflicts(
    source_id: str,
    decisions: Sequence[Mapping[str, Any]],
    scan: Any,
) -> List[Dict[str, Any]]:
    issues = []

    for concept in ("ALERT_ID", "CASE_ID", "WORKFLOW_CASE_ID"):
        field = find_id_field(decisions, concept)

        if field is None:
            continue

        distinct = scan.distinct_values(field, limit=200000)
        ids = set(distinct["values"])

        for first, second in case_variant_conflicts(ids)[:5]:
            issues.append(
                make_issue(
                    "CONFLICTING_IDENTIFIERS",
                    ERROR,
                    "'%s' and '%s' differ only by case. They join as "
                    "distinct keys but may name one entity; the join "
                    "cannot be trusted until resolved." % (first, second),
                    entity=source_id,
                    field=field,
                    source="scan",
                )
            )

        if distinct["truncated"]:
            issues.append(
                make_issue(
                    "IDENTIFIER_REVIEW_TRUNCATED",
                    INFO,
                    "'%s' has more distinct values than the conflict "
                    "review bound; case-variant review covered the "
                    "first entries only." % field,
                    entity=source_id,
                    field=field,
                    source="scan",
                )
            )

    return issues[:MAX_ISSUES_PER_CHECK]


def _check_scan_values(
    source_id: str,
    decisions: Sequence[Mapping[str, Any]],
    scan: Any,
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []

    severity_field = find_id_field(decisions, "SECURITY_SEVERITY")

    if severity_field:
        distinct = scan.distinct_values(severity_field, limit=1000)
        unknown = sorted(
            value
            for value in distinct["values"]
            if normalize_id(value) is not None
            and not values.normalize_severity(value)["known"]
        )

        for raw in unknown[:MAX_ISSUES_PER_CHECK]:
            issues.append(
                make_issue(
                    "INVALID_SEVERITY",
                    WARNING,
                    "Severity value '%s' is outside the known vocabulary. "
                    "Kept as submitted; not defaulted." % raw,
                    entity=source_id,
                    field=severity_field,
                    source="scan",
                )
            )

        if distinct["truncated"]:
            issues.append(
                make_issue(
                    "VOCABULARY_REVIEW_TRUNCATED",
                    INFO,
                    "Severity vocabulary exceeded the review bound; "
                    "values beyond the first entries were not checked.",
                    entity=source_id,
                    field=severity_field,
                    source="scan",
                )
            )

    trigger_field = find_id_field(
        decisions, "TRIGGERED_AT", "EVENT_TIMESTAMP"
    )
    ack_field = find_id_field(decisions, "ACKNOWLEDGED_AT")
    close_field = find_id_field(
        decisions, "CLOSED_AT", "RESOLUTION_TIME"
    )
    wanted = [f for f in (trigger_field, ack_field, close_field) if f]

    if wanted:
        bad_timestamps = 0
        chronology: Dict[str, int] = {}
        rows_seen = 0

        for row in scan.iter_rows(wanted):
            rows_seen += 1
            parsed = {}

            for label, field in (
                ("triggered", trigger_field),
                ("acknowledged", ack_field),
                ("closed", close_field),
            ):
                if not field:
                    parsed[label] = None
                    continue

                raw = row.get(field)
                outcome = values.parse_timestamp(raw)

                if outcome["canonical"] is None and normalize_id(raw) is not None:
                    bad_timestamps += 1

                parsed[label] = outcome["canonical"]

            for violation in values.check_chronology(
                parsed["triggered"], parsed["acknowledged"], parsed["closed"]
            ):
                chronology[violation["pair"]] = (
                    chronology.get(violation["pair"], 0) + 1
                )

        if bad_timestamps:
            issues.append(
                make_issue(
                    "INVALID_TIMESTAMP",
                    WARNING,
                    "%d timestamp value(s) in %d streamed row(s) could "
                    "not be parsed. Flagged, never reinterpreted."
                    % (bad_timestamps, rows_seen),
                    entity=source_id,
                    source="scan",
                )
            )

        for pair, count in sorted(chronology.items()):
            issues.append(
                make_issue(
                    "IMPOSSIBLE_CHRONOLOGY",
                    ERROR,
                    "%d record(s) show '%s'. The timeline contradicts "
                    "itself; it was flagged, not corrected."
                    % (count, pair),
                    entity=source_id,
                    source="scan",
                )
            )

    return issues
