"""Evidence agreement for matched findings.

Phase 7 requires that a matched indicator is only counted as validated when
SAT-SA's evidence actually supports it. This module checks that against the
submitted source rows and the semantic mapping the system itself produced.

It deliberately does not re-run the detection logic. Re-deriving a verdict
would be new analytics, and a re-derivation that agreed with itself would prove
nothing. Instead it asks narrower questions:

  1. Traceability. Does the finding name the records it is about, and do those
     records exist inside its own assessment scope?
  2. Record-level support. For a concept the finding claims as evidence, do the
     cited source rows actually carry the claimed value?
  3. Arithmetic consistency. Do the finding's own stated numbers agree with
     each other and with the rows?

A finding that cites nothing checkable is reported as NOT_VERIFIABLE rather than
as supported. Silence is not agreement.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.supervision.execution_gap_detector import has_evidence
from framework.supervisory.rules.rule_engine import normalise_value
from framework.validation.corpus import dataset_path

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
NOT_VERIFIABLE = "NOT_VERIFIABLE"


class EvidenceReport:
    """The outcome of checking one finding's evidence."""

    __slots__ = (
        "status",
        "checks",
        "conflicts",
        "notes",
    )

    def __init__(
        self,
        status: str = NOT_VERIFIABLE,
        checks: Optional[List[Dict[str, Any]]] = None,
        conflicts: Optional[List[Dict[str, Any]]] = None,
        notes: Optional[List[str]] = None,
    ) -> None:
        self.status = status
        self.checks = checks or []
        self.conflicts = conflicts or []
        self.notes = notes or []

    @property
    def supports_finding(self) -> bool:
        """Only a fully supported finding counts as a validated match."""

        return self.status == SUPPORTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "checks": list(self.checks),
            "conflicts": list(self.conflicts),
            "notes": list(self.notes),
        }


@lru_cache(maxsize=None)
def read_rows(dataset: str) -> List[Dict[str, str]]:
    """Submitted rows for a corpus dataset, read once per process.

    The comparison checks the same rows for several findings, so the file is
    read once and shared. The cache holds data that is already on disk and
    never mutated.
    """

    with open(dataset_path(dataset), "r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def concept_sources(
    semantic_mapping: Sequence[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    """Map each canonical concept to the source columns the mapping declares.

    Read from the system's own semantic mapping. When more than one column
    feeds one concept that is a collision, and the checker reports it rather
    than silently picking a winner.
    """

    sources: Dict[str, List[str]] = {}

    for entry in semantic_mapping or ():
        concept = entry.get("canonical_concept")
        column = entry.get("source_column")

        if not concept or not column:
            continue

        sources.setdefault(concept, []).append(column)

    return sources


def resolve_concept_sources(
    semantic_mapping: Sequence[Mapping[str, Any]],
    available_columns: Sequence[str],
    concepts: Sequence[str],
) -> Dict[str, List[str]]:
    """Source columns for specific concepts, with a declared-mapping fallback.

    A concept the published mapping does not declare is resolved by
    case-insensitive name match against the submitted header, and only if that
    also fails is the concept reported as unverifiable. Without the fallback the
    checker would reject findings whose evidence is plainly present in the file,
    because the mapping happens not to mention the column. The gap is not
    hidden: the caller records it in :func:`unmapped_concepts`, so the
    validator cannot be blamed for checking a concept the tool itself never
    said where it came from.
    """

    sources = concept_sources(semantic_mapping)

    by_name = {
        str(column).strip().lower(): column for column in available_columns
    }

    for concept in concepts:
        if concept in sources:
            continue

        match = by_name.get(str(concept).strip().lower())

        if match:
            sources[concept] = [match]

    return sources


def _concepts_referenced(signals) -> Sequence[str]:
    """Canonical concepts a finding declares it relies on.

    Read from ``evidence_concepts`` and the per-concept coverage figures, never
    from the raw ``evidence`` block. That block means different things per
    family: for the execution-gap layer it is a concept-to-value map, but for
    the operational-pattern layer it holds the finding's own statistics such as
    ``min_similarity_threshold``, which are not canonical concepts at all.
    """

    concepts = set()

    for signal in signals:
        concepts.update(signal.evidence_concepts or ())

        summary = signal.raw.get("evidence_summary") or {}
        concepts.update(summary.get("coverage_by_concept") or {})

    return sorted(concept for concept in concepts if concept)


def unmapped_concepts(
    semantic_mapping: Sequence[Mapping[str, Any]],
    signals: Sequence[Any],
    available_columns: Optional[Sequence[str]] = None,
) -> Dict[str, List[str]]:
    """Concepts findings rely on that the published mapping never declares.

    Only a concept that is actually present in the submitted header counts. A
    concept with no matching column is the absence the negative-space layer
    exists to report, not a traceability defect, and calling it one would
    bury the real gaps.

    This is a finding about the system's own reporting, not about the reviewer.
    """

    declared = concept_sources(semantic_mapping)

    if available_columns is not None:
        by_name = {
            str(column).strip().lower() for column in available_columns
        }
        candidates = [
            concept
            for concept in _concepts_referenced(signals)
            if concept not in declared
            and str(concept).strip().lower() in by_name
        ]
    else:
        candidates = [
            concept
            for concept in _concepts_referenced(signals)
            if concept not in declared
        ]

    return {concept: [] for concept in candidates}


def find_concept_collisions(
    semantic_mapping: Sequence[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    """Concepts fed by more than one source column.

    This is a property of the mapping, not of any finding, so it is safe to
    compute generically. It matters here because a collision can let a finding
    read a plausible-looking value from a column that means something else.
    """

    return {
        concept: columns
        for concept, columns in concept_sources(semantic_mapping).items()
        if len(columns) > 1
    }


def scope_row_indices(
    rows: Sequence[Mapping[str, str]],
    entity_id: Optional[str],
    period_label: Optional[str],
) -> List[int]:
    """Row positions belonging to one assessment scope in the raw file."""

    if not rows:
        return []

    entity_column = next(
        (
            column
            for column in ("cse", "entity", "cse_id")
            if column in rows[0]
        ),
        None,
    )
    period_column = next(
        (
            column
            for column in ("period", "month", "quarter")
            if column in rows[0]
        ),
        None,
    )

    indices = []

    for index, row in enumerate(rows):

        if entity_column and entity_id is not None:
            if row.get(entity_column) != entity_id:
                continue

        if period_column and period_label is not None:
            if row.get(period_column) != period_label:
                continue

        indices.append(index)

    return indices


def check_traceability(
    signal,
    scope_row_indices: Sequence[int],
) -> EvidenceReport:
    """Does the finding point at records that exist inside its own scope?

    Every family publishes either submitted-file offsets or scope-relative
    offsets, and the checker reads the one the finding actually used. Offsets
    from the other space are rejected rather than reinterpreted, because
    quietly reinterpreting them is how a finding ends up credited to the wrong
    record.
    """

    checks: List[Dict[str, Any]] = []
    notes: List[str] = []

    if signal.raw_positions:
        cited = list(signal.raw_positions)
        space = "submitted_file_rows"
        in_scope = set(scope_row_indices)
        detail = f"all {len(cited)} cited source rows are inside " \
                 f"{signal.assessment_id}"
    else:
        cited = list(signal.scope_positions)
        space = "scope_relative_positions"
        in_scope = set(range(len(scope_row_indices)))
        detail = f"all {len(cited)} cited scope positions are within the " \
                 f"{len(scope_row_indices)} records of the scope"

    if not cited:
        notes.append(
            "finding cites no record reference, so its evidence cannot be "
            "traced to submitted rows"
        )
        return EvidenceReport(NOT_VERIFIABLE, checks, notes=notes)

    out_of_scope = [
        position
        for position in cited
        if not isinstance(position, int) or position not in in_scope
    ]

    if out_of_scope:
        notes.append(
            f"cited {space} {out_of_scope} fall outside "
            f"{signal.assessment_id}"
        )
        return EvidenceReport(UNSUPPORTED, checks, notes=notes)

    checks.append(
        {
            "check": "records_within_scope",
            "position_space": space,
            "detail": detail,
            "passed": True,
        }
    )

    return EvidenceReport(SUPPORTED, checks, notes=notes)


def check_declared_evidence(
    signal,
    dataset: str,
    semantic_mapping: Sequence[Mapping[str, Any]],
) -> EvidenceReport:
    """Do the cited rows carry the values the finding claims as evidence?

    Applies to findings that publish a concept-to-value evidence map, which is
    what the execution-gap layer does.
    """

    evidence = signal.raw.get("evidence")

    if not isinstance(evidence, Mapping) or not evidence:
        return EvidenceReport(
            NOT_VERIFIABLE,
            notes=[
                f"{signal.family} findings do not publish a concept-to-value "
                "evidence map, so record-level support is checked by the "
                "arithmetic and coverage checks instead"
            ],
        )

    rows = read_rows(dataset)
    declared = concept_sources(semantic_mapping)
    sources = resolve_concept_sources(
        semantic_mapping, list(rows[0]) if rows else (), sorted(evidence)
    )
    checks: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    notes: List[str] = []

    cited = signal.raw_positions or signal.scope_positions

    for concept, claimed in sorted(evidence.items()):
        columns = sources.get(concept, [])

        if not columns:
            conflicts.append(
                {
                    "concept": concept,
                    "claimed": claimed,
                    "detail": "no source column is mapped to this concept",
                }
            )
            continue

        if concept not in declared:
            notes.append(
                f"the concept {concept} is not declared in the pipeline's own "
                f"semantic mapping; it was resolved to the submitted column "
                f"{columns[0]} by name"
            )

        matched: List[Dict[str, Any]] = []
        disagreeing: List[Dict[str, Any]] = []

        for position in cited:
            if position >= len(rows):
                continue

            row = rows[position]

            for column in columns:
                if column not in row:
                    continue

                submitted = row[column]

                if normalise_value(submitted) == normalise_value(claimed):
                    matched.append({"row": position, "column": column})
                elif has_evidence(submitted):
                    disagreeing.append(
                        {
                            "row": position,
                            "column": column,
                            "submitted": submitted,
                        }
                    )

        if matched:
            checks.append(
                {
                    "check": "evidence_value_present_in_cited_rows",
                    "concept": concept,
                    "claimed": claimed,
                    "matched_in": matched,
                    "passed": True,
                }
            )

        if disagreeing:
            conflicts.append(
                {
                    "concept": concept,
                    "claimed": claimed,
                    "detail": "a cited row supplies a different populated "
                    "value for this concept",
                    "rows": disagreeing,
                    "columns_supplying_concept": columns,
                }
            )

        if not matched:
            conflicts.append(
                {
                    "concept": concept,
                    "claimed": claimed,
                    "detail": "no cited row carries the claimed value",
                    "columns_supplying_concept": columns,
                }
            )

    if conflicts and not checks:
        return EvidenceReport(UNSUPPORTED, checks, conflicts, notes=notes)

    if conflicts:
        return EvidenceReport(PARTIALLY_SUPPORTED, checks, conflicts, notes=notes)

    if checks:
        return EvidenceReport(SUPPORTED, checks, conflicts, notes=notes)

    return EvidenceReport(
        NOT_VERIFIABLE, checks, conflicts, notes=notes + ["no evidence concepts checked"]
    )


def check_operational_evidence(
    signal,
    dataset: str,
    semantic_mapping: Sequence[Mapping[str, Any]],
) -> EvidenceReport:
    """Check a concentration or repetition finding against the submitted rows.

    Concentration is checked by confirming the cited positions really do carry
    the asset value the finding names, and that the stated share matches the
    stated counts. Repetition is checked by confirming the cited positions
    carry identical evidence text. The text itself is never copied into the
    report; only agreement is reported.
    """

    evidence = signal.raw.get("evidence") or {}
    rows = read_rows(dataset)
    declared = concept_sources(semantic_mapping)
    wanted = ["ASSET_IDENTIFIER"]

    if evidence.get("repeating_group_size") is not None:
        wanted.append("INVESTIGATION_EVIDENCE")

    sources = resolve_concept_sources(
        semantic_mapping, list(rows[0]) if rows else (), wanted
    )
    scope_positions = scope_row_indices(
        rows, signal.entity_id, signal.period_label
    )

    cited = evidence.get("group_record_positions")

    if not isinstance(cited, list) or not cited:
        cited = signal.scope_positions

    if not cited:
        return EvidenceReport(
            NOT_VERIFIABLE, notes=["no cited positions to check"]
        )

    scope_size = len(scope_positions)
    checks: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    notes: List[str] = []

    group_value = evidence.get("group_value")

    if group_value is not None:
        asset_columns = sources.get("ASSET_IDENTIFIER", [])

        if not asset_columns:
            conflicts.append(
                {
                    "concept": "ASSET_IDENTIFIER",
                    "detail": "no source column is mapped to this concept",
                }
            )
        else:
            if "ASSET_IDENTIFIER" not in declared:
                notes.append(
                    "ASSET_IDENTIFIER is not declared in the pipeline's own "
                    f"semantic mapping; resolved by name to {asset_columns[0]}"
                )

            agreeing = 0

            for position in cited:
                if position >= scope_size:
                    continue

                row = rows[scope_positions[position]]

                if any(
                    normalise_value(row.get(column)) == normalise_value(group_value)
                    for column in asset_columns
                    if column in row
                ):
                    agreeing += 1

            if agreeing == len(cited):
                checks.append(
                    {
                        "check": "cited_records_share_the_named_asset",
                        "detail": f"all {agreeing} cited records carry the "
                        "asset value the finding names",
                        "passed": True,
                    }
                )
            else:
                conflicts.append(
                    {
                        "concept": "ASSET_IDENTIFIER",
                        "claimed": group_value,
                        "detail": f"only {agreeing} of {len(cited)} cited "
                        "records carry the named asset value",
                    }
                )

    stated_count = evidence.get("group_record_count")
    stated_scope = evidence.get("scope_record_count")

    if isinstance(stated_count, int) and isinstance(stated_scope, int):
        if stated_scope > 0 and stated_count > stated_scope:
            conflicts.append(
                {
                    "concept": "population",
                    "detail": f"the finding counts {stated_count} records out "
                    f"of {stated_scope}, which cannot be true",
                }
            )
        elif stated_count != len(cited):
            notes.append(
                f"the finding states {stated_count} records in the group but "
                f"cites {len(cited)}"
            )
            checks.append(
                {
                    "check": "group_count_matches_cited_positions",
                    "detail": f"stated {stated_count}, cited {len(cited)}",
                    "passed": stated_count == len(cited),
                }
            )
        else:
            checks.append(
                {
                    "check": "group_count_matches_cited_positions",
                    "detail": f"stated count and cited positions agree at "
                    f"{stated_count}",
                    "passed": True,
                }
            )

    if stated_scope is not None and scope_size and stated_scope != scope_size:
        conflicts.append(
            {
                "concept": "population",
                "detail": f"the finding states a population of {stated_scope} "
                f"records but the scope contains {scope_size} submitted rows",
            }
        )

    repeating = evidence.get("repeating_group_size")

    if isinstance(repeating, int):
        note_columns = sources.get("INVESTIGATION_EVIDENCE", [])

        if not note_columns:
            conflicts.append(
                {
                    "concept": "INVESTIGATION_EVIDENCE",
                    "detail": "no source column is mapped to this concept",
                }
            )
        else:
            texts = set()

            for position in cited:
                if position >= scope_size:
                    continue

                row = rows[scope_positions[position]]

                for column in note_columns:
                    if column in row and has_evidence(row[column]):
                        texts.add(normalise_value(row[column]))
                        break

            if len(texts) == 1:
                checks.append(
                    {
                        "check": "cited_records_share_identical_evidence",
                        "detail": f"all {len(cited)} cited records carry "
                        "identical evidence wording; the wording itself is not "
                        "reproduced here",
                        "passed": True,
                    }
                )
            else:
                conflicts.append(
                    {
                        "concept": "INVESTIGATION_EVIDENCE",
                        "detail": f"cited records carry {len(texts)} distinct "
                        "writings, so the cited group is not uniform",
                    }
                )

    if conflicts and not checks:
        return EvidenceReport(UNSUPPORTED, checks, conflicts, notes)

    if conflicts:
        return EvidenceReport(PARTIALLY_SUPPORTED, checks, conflicts, notes)

    if checks:
        return EvidenceReport(SUPPORTED, checks, conflicts, notes)

    return EvidenceReport(
        NOT_VERIFIABLE, checks, conflicts, notes=["no operational check applied"]
    )


def check_negative_space_evidence(
    signal,
    dataset: str,
    semantic_mapping: Sequence[Mapping[str, Any]],
) -> EvidenceReport:
    """Check a negative-space finding's population figures against the rows.

    The finding reports a population: how many triggered records carried the
    expected evidence, how many did not, and how many of those were submitted
    but stated no usable outcome. Its cited positions are the absence
    witnesses, not the whole population, so the coverage figure is not
    recomputed from the cited rows. Doing that would silently compare a
    population count against a subset and manufacture a contradiction.

    What is checkable, without re-deriving the trigger or the rule's accepted
    values, is the finding's own arithmetic and the honesty of its witnesses:

      1. the three population figures add up to the trigger count, and the
         coverage ratio matches;
      2. the number of cited witnesses equals the number of records the finding
         says lack the expected evidence;
      3. every witness is inside the scope;
      4. every witness really does carry no usable evidence, judged by the
         shared evidence contract, unless the finding already classified that
         record as unusable.

    Check 4 is the one that catches over-claiming: a finding cannot point at a
    row that plainly contains escalation evidence and call it an absence.
    """

    summary = signal.raw.get("evidence_summary") or {}
    by_concept = summary.get("coverage_by_concept") or {}

    if not by_concept:
        return EvidenceReport(
            NOT_VERIFIABLE,
            notes=["no per-concept coverage is published to check"],
        )

    rows = read_rows(dataset)
    declared = concept_sources(semantic_mapping)
    sources = resolve_concept_sources(
        semantic_mapping,
        list(rows[0]) if rows else (),
        sorted(by_concept),
    )
    scope_positions = scope_row_indices(
        rows, signal.entity_id, signal.period_label
    )
    scope_size = len(scope_positions)

    reference = signal.raw.get("record_reference") or {}
    unusable_positions = set(reference.get("records_with_unusable_evidence") or ())
    witnesses = list(signal.scope_positions)

    checks: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    notes: List[str] = []

    trigger_records = summary.get("trigger_records")

    if isinstance(trigger_records, int) and trigger_records > scope_size:
        conflicts.append(
            {
                "concept": "population",
                "detail": f"the finding counts {trigger_records} triggered "
                f"records but {signal.assessment_id} contains only "
                f"{scope_size} submitted rows",
            }
        )

    for concept, figures in sorted(by_concept.items()):

        with_evidence = figures.get("records_with_expected_evidence")
        without_evidence = figures.get("records_without_expected_evidence")
        unusable = figures.get("records_with_unusable_evidence")
        coverage = figures.get("coverage")

        if concept not in declared:
            columns = sources.get(concept) or []

            if columns:
                notes.append(
                    f"the concept {concept} is not declared in the pipeline's "
                    f"own semantic mapping; it was resolved to the submitted "
                    f"column {columns[0]} by name"
                )

        if not all(
            isinstance(value, int)
            for value in (with_evidence, without_evidence, unusable)
        ):
            notes.append(
                f"the finding does not publish a full count for {concept}, so "
                "its arithmetic cannot be checked"
            )
            continue

        if with_evidence + without_evidence != (
            trigger_records if isinstance(trigger_records, int) else None
        ):
            conflicts.append(
                {
                    "concept": concept,
                    "detail": f"{with_evidence} records with evidence plus "
                    f"{without_evidence} without does not equal the "
                    f"{trigger_records} triggered records the finding claims",
                }
            )
        else:
            checks.append(
                {
                    "check": "population_figures_add_up",
                    "concept": concept,
                    "with_evidence": with_evidence,
                    "without_evidence": without_evidence,
                    "unusable": unusable,
                    "trigger_records": trigger_records,
                    "passed": True,
                }
            )

        if isinstance(coverage, (int, float)) and isinstance(
            trigger_records, int
        ):
            expected = (
                with_evidence / trigger_records if trigger_records else None
            )

            if expected is None or abs(coverage - expected) > 0.0001:
                conflicts.append(
                    {
                        "concept": concept,
                        "detail": f"the finding states coverage {coverage} but "
                        f"{with_evidence} of {trigger_records} is "
                        f"{expected}",
                    }
                )
            else:
                checks.append(
                    {
                        "check": "coverage_matches_its_own_counts",
                        "concept": concept,
                        "coverage": coverage,
                        "passed": True,
                    }
                )

        if witnesses and len(witnesses) != without_evidence:
            conflicts.append(
                {
                    "concept": concept,
                    "detail": f"the finding says {without_evidence} records "
                    f"lack the expected evidence but cites {len(witnesses)} "
                    "as the witnesses",
                }
            )
        elif witnesses:
            checks.append(
                {
                    "check": "witness_count_matches_absence_count",
                    "concept": concept,
                    "witnesses": len(witnesses),
                    "records_without_expected_evidence": without_evidence,
                    "passed": True,
                }
            )

        columns = sources.get(concept) or []
        contradicting = []

        for position in witnesses:

            if position >= scope_size:
                continue

            row = rows[scope_positions[position]]

            populated = any(
                column in row and has_evidence(row[column])
                for column in columns
            )

            if populated and position not in unusable_positions:
                contradicting.append(position)

        if contradicting:
            conflicts.append(
                {
                    "concept": concept,
                    "detail": "the finding cites records as lacking the "
                    "expected evidence while they carry a populated value it "
                    "did not classify as unusable",
                    "scope_positions": contradicting,
                }
            )
        elif witnesses and columns:
            checks.append(
                {
                    "check": "cited_absence_witnesses_carry_no_usable_evidence",
                    "concept": concept,
                    "witnesses_checked": len(witnesses),
                    "classified_unusable_by_the_finding": sorted(
                        unusable_positions
                    ),
                    "passed": True,
                }
            )

    if conflicts and not checks:
        return EvidenceReport(UNSUPPORTED, checks, conflicts, notes)

    if conflicts:
        return EvidenceReport(PARTIALLY_SUPPORTED, checks, conflicts, notes)

    if checks:
        return EvidenceReport(SUPPORTED, checks, conflicts, notes)

    return EvidenceReport(NOT_VERIFIABLE, checks, conflicts, notes)


def check_evidence(
    signal,
    dataset: str,
    semantic_mapping: Sequence[Mapping[str, Any]],
) -> EvidenceReport:
    """Run the applicable evidence checks for one finding."""

    if signal.family == "operational_pattern":
        report = check_operational_evidence(signal, dataset, semantic_mapping)
    elif signal.family == "negative_space":
        report = check_negative_space_evidence(signal, dataset, semantic_mapping)
    else:
        report = check_declared_evidence(signal, dataset, semantic_mapping)

    return report
