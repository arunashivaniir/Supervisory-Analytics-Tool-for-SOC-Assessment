"""Alert / case / workflow / asset relationship summary, Phase 1.

Joins submitted rows on their normalized identifiers and reports what
linked and what did not. Supported patterns:

* one alert -> one case
* one alert -> many related records
* one case -> many workflow events
* many alerts -> related cases where the schema supports it

No one-to-one assumption anywhere: every side is a set, links are pairs,
and each of unmatched alerts, orphan cases and orphan workflow events is
counted explicitly.

A join is only assessed where both sides are mapped. A relationship that
cannot be evaluated — because a join key never mapped — is reported as
not assessable, never as zero.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


def normalize_id(value: Any) -> Optional[str]:
    """A join key as a stripped string, or None when absent."""

    if value is None or isinstance(value, bool):
        return None

    text = str(value).strip()

    if not text or text.lower() in ("nan", "nat", "none", "null", "n/a", "-"):
        return None

    return text


def find_id_field(
    decisions: Sequence[Mapping[str, Any]],
    *concepts: str,
) -> Optional[str]:
    """Original-spelling source field of the first applied concept."""

    for concept in concepts:
        for item in decisions:
            if item.get("applied") and item.get("canonical_concept") == concept:
                return item["source_field"]

    return None


def summarize_relationships(
    records: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize alert/case/workflow joins over submitted rows."""

    fields = _join_fields(decisions)
    state = _new_state()

    for record in records:
        _feed_record(
            state,
            fields,
            {name: normalize_id(record.get(field)) for name, field in fields.items()},
        )

    return _finalize(state, fields)


def summarize_scan(
    scan: Any,
    decisions: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize joins as SQL over the scan, same shape as records.

    Counts, links and samples are all computed inside the engine:
    Python holds only capped samples, so memory stays flat while rows
    grow. No Python-side ID sets exist on this path at all.
    """

    from framework.ingestion.scan import quote_identifier

    fields = _join_fields(decisions)
    relation = scan._relation  # noqa: SLF001 - same package family

    def distinct(field: Optional[str], extra: str = "") -> str:
        return (
            "(SELECT DISTINCT %s AS _k FROM %s WHERE %s IS NOT NULL %s)"
            % (quote_identifier(field or ""), relation,
               quote_identifier(field or ""), extra)
        )

    alert_field = fields["alert"]
    case_field = fields["case"]
    case_alert_field = fields["case_alert"]
    workflow_case_field = fields["workflow_case"]

    summary: Dict[str, Any] = {
        "alerts": 0,
        "cases": 0,
        "workflow_events": 0,
        "assets": 0,
        "linked_cases": _capped([]),
        "orphan_cases": _capped([]),
        "cases_without_link_info": _capped([]),
        "alerts_without_case": _capped([]),
        "orphan_workflow_cases": _capped([]),
        "rows_with_case_but_no_alert_key": 0,
        "event_rows_without_case_key": 0,
        "alert_case_assessable": False,
        "workflow_assessable": False,
        "join_fields": {
            "alert_id": alert_field,
            "case_id": case_field,
            "case_alert_id": case_alert_field,
            "workflow_case_id": workflow_case_field,
        },
    }

    query = scan._query  # noqa: SLF001 - same package family

    def count(sql: str) -> int:
        return int(query(sql)[0][0])

    def capped_list(sql: str, limit: int = 50) -> Dict[str, Any]:
        rows = query("%s LIMIT %d" % (sql, limit + 1))
        items = [str(row[0]) for row in rows[:limit]]
        total = count(
            "SELECT COUNT(*) FROM (%s) AS _t" % sql
        )
        return {
            "count": total,
            "sample": items,
            "truncated": len(rows) > limit,
        }

    if fields["asset"]:
        summary["assets"] = count(
            "SELECT COUNT(DISTINCT %s) FROM %s WHERE %s IS NOT NULL"
            % (
                quote_identifier(fields["asset"]), relation,
                quote_identifier(fields["asset"]),
            )
        )

    alert_case_assessable = alert_field is not None and (
        case_field is not None or case_alert_field is not None
    )
    summary["alert_case_assessable"] = bool(alert_case_assessable)

    if alert_field:
        summary["alerts"] = count(
            "SELECT COUNT(DISTINCT %s) FROM %s WHERE %s IS NOT NULL"
            % (
                quote_identifier(alert_field), relation,
                quote_identifier(alert_field),
            )
        )

    if case_field:
        summary["cases"] = count(
            "SELECT COUNT(DISTINCT %s) FROM %s WHERE %s IS NOT NULL"
            % (
                quote_identifier(case_field), relation,
                quote_identifier(case_field),
            )
        )

    if alert_case_assessable:
        # Alert/case joins need both sides mapped. Workflow linkage
        # below is independent of that.
        aq = quote_identifier(alert_field or "")

        if case_field and case_alert_field:
            cq = quote_identifier(case_field)
            lq = quote_identifier(case_alert_field)

            # Case -> alert pairs as named on case rows.
            pairs = (
                "(SELECT DISTINCT %s AS _c, %s AS _l FROM %s "
                "WHERE %s IS NOT NULL AND %s IS NOT NULL)"
                % (cq, lq, relation, cq, lq)
            )
            known_alerts = (
                "(SELECT DISTINCT %s AS _a FROM %s WHERE %s IS NOT NULL)"
                % (aq, relation, aq)
            )

            summary["linked_cases"] = capped_list(
                "SELECT DISTINCT _p._c FROM %s AS _p JOIN %s AS _a "
                "ON _p._l = _a._a ORDER BY _p._c" % (pairs, known_alerts)
            )
            summary["orphan_cases"] = capped_list(
                "SELECT DISTINCT _p._c FROM %s AS _p LEFT JOIN %s AS _a "
                "ON _p._l = _a._a WHERE _a._a IS NULL ORDER BY _p._c"
                % (pairs, known_alerts)
            )
            summary["alerts_without_case"] = capped_list(
                "SELECT _a._a FROM %s AS _a LEFT JOIN "
                "(SELECT DISTINCT _l FROM %s) AS _p ON _a._a = _p._l "
                "WHERE _p._l IS NULL ORDER BY _a._a"
                % (known_alerts, pairs)
            )

            named_cases = count(
                "SELECT COUNT(DISTINCT _c) FROM %s" % pairs
            )
            summary["cases_without_link_info"] = {
                "count": max(0, summary["cases"] - named_cases),
                "sample": [],
                "truncated": False,
            }

            if case_alert_field and case_field:
                summary["rows_with_case_but_no_alert_key"] = count(
                    "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL "
                    "AND %s IS NULL" % (relation, cq, lq)
                )
        else:
            # Alerts exist but no case side names links: every alert is
            # unmatched and no case can be classified.
            summary["alerts_without_case"] = capped_list(
                "SELECT DISTINCT %s AS _a FROM %s WHERE %s IS NOT NULL "
                "ORDER BY _a" % (aq, relation, aq)
            )

    # Workflow event rows: the workflow key on its own slot, or any
    # workflow event attribute present.
    event_attrs = [
        fields[name]
        for name in ("event_type", "event_at", "event_actor", "event_tier")
        if fields[name]
    ]

    if workflow_case_field:
        wq = quote_identifier(workflow_case_field)
        conditions = ["%s IS NOT NULL" % wq]

        if workflow_case_field != case_field:
            summary["workflow_events"] = count(
                "SELECT COUNT(*) FROM %s WHERE %s" % (
                    relation, " AND ".join(conditions),
                )
            )
        elif event_attrs:
            attr_checks = " OR ".join(
                "%s IS NOT NULL" % quote_identifier(name)
                for name in event_attrs
            )
            summary["workflow_events"] = count(
                "SELECT COUNT(*) FROM %s WHERE %s AND (%s)"
                % (relation, " AND ".join(conditions), attr_checks)
            )
        else:
            summary["workflow_events"] = 0

        # Rows carrying neither key are joinable to nothing. Mirrors the
        # record path: workflow key absent with no alert or case anchor.
        missing = ["%s IS NULL" % wq]

        if case_field and workflow_case_field != case_field:
            missing.append("%s IS NULL" % quote_identifier(case_field))

        if alert_field:
            missing.append("%s IS NULL" % quote_identifier(alert_field))

        summary["event_rows_without_case_key"] = count(
            "SELECT COUNT(*) FROM %s WHERE %s"
            % (relation, " AND ".join(missing))
        )

    workflow_assessable = (
        workflow_case_field is not None and case_field is not None
    )
    summary["workflow_assessable"] = bool(workflow_assessable)

    if workflow_assessable:
        wq = quote_identifier(workflow_case_field or "")
        summary["orphan_workflow_cases"] = capped_list(
            "SELECT DISTINCT _w FROM "
            "(SELECT DISTINCT %s AS _w FROM %s WHERE %s IS NOT NULL) AS _e "
            "LEFT JOIN (SELECT DISTINCT %s AS _c FROM %s "
            "WHERE %s IS NOT NULL) AS _c ON _e._w = _c._c "
            "WHERE _c._c IS NULL ORDER BY _w"
            % (wq, relation, wq, cq, relation, cq)
        )

    return summary


def _join_fields(
    decisions: Sequence[Mapping[str, Any]],
) -> Dict[str, Optional[str]]:
    """Link-key source fields (original spelling) for each join slot."""

    return {
        "alert": find_id_field(decisions, "ALERT_ID"),
        "case": find_id_field(decisions, "CASE_ID"),
        "case_alert": find_id_field(decisions, "CASE_ALERT_ID", "ALERT_ID"),
        "workflow_case": find_id_field(
            decisions, "WORKFLOW_CASE_ID", "CASE_ID"
        ),
        "event_type": find_id_field(decisions, "WORKFLOW_EVENT_TYPE"),
        "event_at": find_id_field(decisions, "WORKFLOW_EVENT_AT"),
        "event_actor": find_id_field(decisions, "WORKFLOW_ACTOR"),
        "event_tier": find_id_field(decisions, "WORKFLOW_TIER"),
        "asset": find_id_field(decisions, "ASSET_IDENTIFIER"),
    }


def _new_state(id_cap: Optional[int] = None) -> Dict[str, Any]:
    return {
        "alert_ids": set(),
        "case_ids": set(),
        "workflow_case_ids": set(),
        "case_to_alerts": {},
        "alert_to_cases": {},
        "workflow_events": 0,
        "asset_ids": set(),
        "rows_with_case_but_no_alert_key": 0,
        "event_rows_without_case_key": 0,
        "id_cap": id_cap,
        "overflow": False,
    }


def _feed_record(
    state: Dict[str, Any],
    fields: Mapping[str, Optional[str]],
    values: Mapping[str, Optional[str]],
) -> None:
    alert = values.get("alert")
    case = values.get("case")
    case_alert = values.get("case_alert")
    workflow_case = values.get("workflow_case")

    if alert is not None:
        state["alert_ids"].add(alert)

    if case is not None:
        state["case_ids"].add(case)

    asset = values.get("asset")

    if asset is not None:
        state["asset_ids"].add(asset)

    if fields["case_alert"] and case is not None and case_alert is None:
        state["rows_with_case_but_no_alert_key"] += 1

    if case_alert is not None and case is not None:
        state["case_to_alerts"].setdefault(case, set()).add(case_alert)
        state["alert_to_cases"].setdefault(case_alert, set()).add(case)

    event_attributes = ("event_type", "event_at", "event_actor", "event_tier")

    # A row is a workflow event row when it carries the workflow case
    # key on a slot of its own, or when it carries workflow event
    # attributes. A case row that merely shares the CASE_ID slot is
    # not an event.
    if fields["workflow_case"] and workflow_case is not None and (
        fields["workflow_case"] != fields["case"]
        or any(values.get(name) is not None for name in event_attributes)
    ):
        state["workflow_events"] += 1
        state["workflow_case_ids"].add(workflow_case)
    elif fields["workflow_case"] and workflow_case is None:
        if alert is None and case is None:
            state["event_rows_without_case_key"] += 1

    cap = state["id_cap"]

    if cap is not None and (
        len(state["alert_ids"]) > cap
        or len(state["case_ids"]) > cap
        or len(state["workflow_case_ids"]) > cap
    ):
        state["overflow"] = True

def _finalize(
    state: Dict[str, Any],
    fields: Mapping[str, Optional[str]],
) -> Dict[str, Any]:
    alert_ids = state["alert_ids"]
    case_ids = state["case_ids"]
    workflow_case_ids = state["workflow_case_ids"]
    case_to_alerts = state["case_to_alerts"]
    alert_to_cases = state["alert_to_cases"]

    alert_field = fields["alert"]
    case_field = fields["case"]
    case_alert_field = fields["case_alert"]
    workflow_case_field = fields["workflow_case"]

    linked_cases: List[str] = []
    orphan_cases: List[str] = []
    cases_without_link_info: List[str] = []
    alerts_without_case: List[str] = []

    alert_case_assessable = alert_field is not None and (
        case_field is not None or case_alert_field is not None
    ) and not state["overflow"]

    if alert_case_assessable:
        for case in sorted(case_ids):
            named = case_to_alerts.get(case, set())
            known = named & alert_ids

            if known:
                linked_cases.append(case)
            elif named:
                # Names an alert absent from the alerts side: orphan.
                orphan_cases.append(case)
            else:
                cases_without_link_info.append(case)

        linked_alerts = set(alert_to_cases)
        alerts_without_case = sorted(
            alert for alert in alert_ids if alert not in linked_alerts
        )


    workflow_assessable = (
        workflow_case_field is not None
        and case_field is not None
        and not state["overflow"]
    )
    orphan_workflow_cases: List[str] = []

    if workflow_assessable:
        orphan_workflow_cases = sorted(
            case for case in workflow_case_ids if case not in case_ids
        )

    if state["overflow"]:
        # Bounded memory won over complete joins. The counts above are
        # partial and the joins are reported not assessable with the
        # reason, never as zero. Validation adds the overflow issue.
        alert_case_assessable = False
        workflow_assessable = False

    return {
        "alerts": len(alert_ids),
        "cases": len(case_ids),
        "workflow_events": state["workflow_events"],
        "assets": len(state["asset_ids"]),
        "linked_cases": _capped(linked_cases),
        "orphan_cases": _capped(orphan_cases),
        "cases_without_link_info": _capped(cases_without_link_info),
        "alerts_without_case": _capped(alerts_without_case),
        "orphan_workflow_cases": _capped(orphan_workflow_cases),
        "rows_with_case_but_no_alert_key": state[
            "rows_with_case_but_no_alert_key"
        ],
        "event_rows_without_case_key": state["event_rows_without_case_key"],
        "alert_case_assessable": alert_case_assessable,
        "workflow_assessable": workflow_assessable,
        "join_fields": {
            "alert_id": alert_field,
            "case_id": case_field,
            "case_alert_id": case_alert_field,
            "workflow_case_id": workflow_case_field,
        },
    }


# Samples are evidence pointers, not the evidence: exact counts travel
# with a capped sample so a large submission cannot bloat the package.
_SAMPLE_LIMIT = 50


def _capped(items: List[str]) -> Dict[str, Any]:
    return {
        "count": len(items),
        "sample": items[:_SAMPLE_LIMIT],
        "truncated": len(items) > _SAMPLE_LIMIT,
    }


def _case_links_known_alert(
    case: str,
    case_to_alerts: Mapping[str, Set[str]],
    alert_ids: Set[str],
) -> bool:
    return bool(case_to_alerts.get(case, set()) & alert_ids)


def case_variant_conflicts(ids: Set[str]) -> List[Tuple[str, str]]:
    """Identifier pairs differing only by case or whitespace handling.

    Such pairs join differently depending on normalization, so they are
    conflicting identifiers rather than distinct entities.
    """

    lowered: Dict[str, str] = {}
    conflicts = []

    for identifier in sorted(ids):
        key = identifier.lower()

        if key in lowered and lowered[key] != identifier:
            conflicts.append((lowered[key], identifier))
        else:
            lowered.setdefault(key, identifier)

    return conflicts
