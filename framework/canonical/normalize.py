"""Value and timestamp normalization for SAT-SA Phase 1.

Explicit, configurable vocabularies — no hidden magic. Every function
returns the original value untouched beside the canonical one, so
evidence and provenance always keep what the submission actually said.

Unknown values are never guessed: the canonical slot stays empty and the
caller records a validation issue. A normalization that cannot decide is
reported, not averaged away.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Categorical vocabularies.
#
# Keys are compared case-insensitively after stripping. Anything absent
# maps to None: an organisation vocabulary this table does not know is an
# unknown value, not a low one.
# ---------------------------------------------------------------------------

SEVERITY_TABLE = {
    "critical": "CRITICAL",
    "crit": "CRITICAL",
    "sev1": "CRITICAL",
    "sev-1": "CRITICAL",
    "sev 1": "CRITICAL",
    "p1": "CRITICAL",
    "s1": "CRITICAL",
    "high": "HIGH",
    "sev2": "HIGH",
    "sev-2": "HIGH",
    "sev 2": "HIGH",
    "p2": "HIGH",
    "s2": "HIGH",
    "medium": "MEDIUM",
    "med": "MEDIUM",
    "moderate": "MEDIUM",
    "sev3": "MEDIUM",
    "sev-3": "MEDIUM",
    "sev 3": "MEDIUM",
    "p3": "MEDIUM",
    "s3": "MEDIUM",
    "low": "LOW",
    "sev4": "LOW",
    "sev-4": "LOW",
    "sev 4": "LOW",
    "p4": "LOW",
    "s4": "LOW",
    "info": "LOW",
    "informational": "LOW",
}

ESCALATION_STATUS_TABLE = {
    "escalated": "ESCALATED",
    "yes": "ESCALATED",
    "y": "ESCALATED",
    "true": "ESCALATED",
    "escalate": "ESCALATED",
    "not_escalated": "NOT_ESCALATED",
    "not escalated": "NOT_ESCALATED",
    "no": "NOT_ESCALATED",
    "n": "NOT_ESCALATED",
    "false": "NOT_ESCALATED",
    "none": "NOT_ESCALATED",
    "pending": "PENDING",
    "requested": "PENDING",
}

CLOSURE_DISPOSITION_TABLE = {
    "closed": "CLOSED",
    "resolved": "CLOSED",
    "fixed": "CLOSED",
    "completed": "CLOSED",
    "done": "CLOSED",
    "false_positive": "FALSE_POSITIVE",
    "false positive": "FALSE_POSITIVE",
    "fp": "FALSE_POSITIVE",
    "benign": "FALSE_POSITIVE",
    "duplicate": "DUPLICATE",
    "dup": "DUPLICATE",
    "wont_fix": "WONT_FIX",
    "won't fix": "WONT_FIX",
    "wont fix": "WONT_FIX",
    "deferred": "WONT_FIX",
    "open": "OPEN",
    "reopened": "OPEN",
    "re-opened": "OPEN",
    "in_progress": "OPEN",
    "in progress": "OPEN",
}

# Policy for timezone-naive timestamps: assumed UTC, and flagged.
# The assumption is documented on every parsed value (naive_assumed_utc)
# so no consumer can mistake an assumed zone for a stated one.
NAIVE_TIMEZONE_POLICY = "assumed_utc"

_EXTRA_STRPTIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)


def _lookup(table: Mapping[str, str], value: Any) -> Tuple[Optional[str], Any]:
    """Canonical value for a raw categorical, with the original kept."""

    original = value

    if value is None:
        return None, original

    if isinstance(value, bool):
        return None, original

    key = str(value).strip().lower()

    if not key or key in ("nan", "nat", "none", "null", "-", "unknown", "n/a"):
        return None, original

    return table.get(key), original


def normalize_severity(value: Any) -> Dict[str, Any]:
    """Map a submitted severity onto CRITICAL/HIGH/MEDIUM/LOW."""

    canonical, original = _lookup(SEVERITY_TABLE, value)

    return {
        "canonical": canonical,
        "original": original,
        "known": canonical is not None,
    }


def normalize_escalation_status(value: Any) -> Dict[str, Any]:
    """Map a submitted escalation state onto ESCALATED/NOT_ESCALATED/PENDING."""

    canonical, original = _lookup(ESCALATION_STATUS_TABLE, value)

    return {
        "canonical": canonical,
        "original": original,
        "known": canonical is not None,
    }


def normalize_closure_disposition(value: Any) -> Dict[str, Any]:
    """Map a submitted closure onto CLOSED/FALSE_POSITIVE/DUPLICATE/..."""

    canonical, original = _lookup(CLOSURE_DISPOSITION_TABLE, value)

    return {
        "canonical": canonical,
        "original": original,
        "known": canonical is not None,
    }


def parse_timestamp(value: Any) -> Dict[str, Any]:
    """Parse a submitted timestamp without ever fixing it.

    Returns the ISO-8601 instant (always timezone-aware; naive inputs are
    assumed UTC per ``NAIVE_TIMEZONE_POLICY`` and flagged), the original
    value, and whether parsing failed. Unparseable input yields
    ``canonical None`` plus ``parse_error True`` — never a guessed date.
    """

    result: Dict[str, Any] = {
        "canonical": None,
        "original": value,
        "tz_aware": None,
        "naive_assumed_utc": False,
        "parse_error": False,
    }

    if value is None or isinstance(value, bool):
        result["parse_error"] = True
        return result

    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        result["parse_error"] = True
        return result
    else:
        text = str(value).strip()

        if not text or text.lower() in ("nan", "nat", "none", "null", "n/a", "-"):
            result["parse_error"] = True
            return result

        moment = _parse_text(text)

        if moment is None:
            result["parse_error"] = True
            return result

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
        result["naive_assumed_utc"] = True
        result["tz_aware"] = False
    else:
        result["tz_aware"] = True

    result["canonical"] = moment.isoformat()

    return result


def _parse_text(text: str) -> Optional[datetime]:
    candidate = text

    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass

    for format_string in _EXTRA_STRPTIME_FORMATS:
        try:
            return datetime.strptime(candidate, format_string)
        except ValueError:
            continue

    return None


def check_chronology(
    triggered: Optional[str],
    acknowledged: Optional[str],
    closed: Optional[str],
) -> List[Dict[str, str]]:
    """Flag impossible orderings between parsed instants.

    Inputs are ISO-8601 strings (or None when unparsed). Returns terse
    violation records; an empty list means nothing impossible was seen —
    not that the timeline is correct.
    """

    moments: Dict[str, Optional[datetime]] = {}

    for label, raw in (
        ("triggered_at", triggered),
        ("acknowledged_at", acknowledged),
        ("closed_at", closed),
    ):
        if not raw:
            moments[label] = None
            continue

        try:
            moments[label] = datetime.fromisoformat(raw)
        except ValueError:
            moments[label] = None

    violations = []

    trigger = moments["triggered_at"]
    ack = moments["acknowledged_at"]
    close = moments["closed_at"]

    if trigger is not None and ack is not None and ack < trigger:
        violations.append(
            {
                "pair": "acknowledged_at < triggered_at",
                "detail": "acknowledged %s precedes triggered %s"
                % (acknowledged, triggered),
            }
        )

    if ack is not None and close is not None and close < ack:
        violations.append(
            {
                "pair": "closed_at < acknowledged_at",
                "detail": "closed %s precedes acknowledged %s"
                % (closed, acknowledged),
            }
        )

    if (
        trigger is not None
        and close is not None
        and ack is None
        and close < trigger
    ):
        violations.append(
            {
                "pair": "closed_at < triggered_at",
                "detail": "closed %s precedes triggered %s with no "
                "acknowledgement recorded" % (closed, triggered),
            }
        )

    return violations


def normalize_record_values(
    record: Mapping[str, Any],
    severity_column: Optional[str] = None,
    escalation_column: Optional[str] = None,
    disposition_column: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize the categorical slots of one record, originals kept.

    Returns ``{slot: {canonical, original, known}}`` for each column that
    was provided. Columns absent from the record are skipped, not nulled.
    """

    slots: Dict[str, Any] = {}
    columns = (
        (severity_column, normalize_severity),
        (escalation_column, normalize_escalation_status),
        (disposition_column, normalize_closure_disposition),
    )

    for column, normalizer in columns:
        if column and column in record:
            slots[column] = normalizer(record[column])

    return slots
