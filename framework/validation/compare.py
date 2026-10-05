"""Comparison of human review against SAT-SA output.

Comparison happens at indicator level, per family, per assessment scope. Free
text is never compared by string equality: a reviewer and the tool will never
phrase a reason the same way, and pretending otherwise would measure wording
rather than agreement.

Outcomes:

  MATCH        the same indicator was reported by both sides for the same scope
  MATCH_UNSUPPORTED
               the indicator agreed but the evidence check did not support it,
               so it is explicitly not counted as a validated match
  SCOPE_MISMATCH
               both sides reported the indicator, but for different scopes
  FALSE_POSITIVE
               SAT-SA reported an indicator the reviewer did not
  FALSE_NEGATIVE
               the reviewer reported an indicator SAT-SA did not

Scope is part of the identity of a signal. An indicator reported for the right
reason in the wrong entity is not a match, and treating it as one is the single
most flattering error a validation harness can make.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.validation.corpus import FAMILIES
from framework.validation.evidence import (
    SUPPORTED,
    check_evidence,
    check_traceability,
    read_rows,
    scope_row_indices,
)
from framework.validation.normalize import (
    NormalisedSignal,
    normalise_human_record,
    register_indicator_vocabulary,
    signal_positions,
)

MATCH = "MATCH"
MATCH_UNSUPPORTED = "MATCH_UNSUPPORTED"
SCOPE_MISMATCH = "SCOPE_MISMATCH"
FALSE_POSITIVE = "FALSE_POSITIVE"
FALSE_NEGATIVE = "FALSE_NEGATIVE"

OUTCOMES = (
    MATCH,
    MATCH_UNSUPPORTED,
    SCOPE_MISMATCH,
    FALSE_POSITIVE,
    FALSE_NEGATIVE,
)

#: Evidence states that count as a validated match.
SUPPORTING_EVIDENCE_STATES = ("SUPPORTED",)


class ComparisonRecord:
    """One compared signal, human side against tool side."""

    __slots__ = (
        "family",
        "indicator",
        "assessment_id",
        "dataset",
        "outcome",
        "human_evidence",
        "sat_sa_evidence",
        "capability",
        "record_positions",
        "explanation",
        "scope_mismatch",
        "notes",
    )

    def __init__(
        self,
        family: str,
        indicator: str,
        assessment_id: Optional[str],
        outcome: str,
        dataset: Optional[str] = None,
        human_evidence: Optional[Mapping[str, Any]] = None,
        sat_sa_evidence: Optional[Mapping[str, Any]] = None,
        capability: Optional[str] = None,
        record_positions: Optional[Sequence[int]] = None,
        explanation: Optional[str] = None,
        scope_mismatch: Optional[Mapping[str, Any]] = None,
        notes: Optional[Sequence[str]] = None,
    ) -> None:
        self.family = family
        self.indicator = indicator
        self.assessment_id = assessment_id
        self.dataset = dataset
        self.outcome = outcome
        self.human_evidence = human_evidence
        self.sat_sa_evidence = sat_sa_evidence
        self.capability = capability
        self.record_positions = list(record_positions or ())
        self.explanation = explanation
        self.scope_mismatch = scope_mismatch
        self.notes = list(notes or ())

    @property
    def scope_key(self) -> str:
        """Globally unique scope identity: an assessment id repeats across datasets."""

        return f"{self.dataset}::{self.assessment_id}"

    @property
    def is_validated_match(self) -> bool:
        return self.outcome == MATCH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family,
            "indicator": self.indicator,
            "assessment_id": self.assessment_id,
            "dataset": self.dataset,
            "outcome": self.outcome,
            "capability": self.capability,
            "record_positions": list(self.record_positions),
            "human_evidence": self.human_evidence,
            "sat_sa_evidence": self.sat_sa_evidence,
            "explanation": self.explanation,
            "scope_mismatch": self.scope_mismatch,
            "notes": list(self.notes),
        }


def _sat_signals_by_scope(
    reference: Mapping[str, Any]
) -> Dict[str, Dict[str, Dict[str, NormalisedSignal]]]:
    """Index the reference output by scope then family then indicator."""

    index: Dict[str, Dict[str, Dict[str, NormalisedSignal]]] = {}

    for record in reference.get("records", ()):

        # An assessment id repeats across datasets in this repository, so the
        # scope index is keyed on the dataset and the assessment id together.
        scope_id = f"{record.get('dataset')}::{record.get('assessment_id')}"
        scope = index.setdefault(scope_id, {})

        for family in FAMILIES:

            bucket = scope.setdefault(family, {})

            for finding in record.get(f"sat_sa_{family}_findings") or ():

                signal = NormalisedSignal(
                    family,
                    finding,
                    raw_positions=signal_positions(finding),
                )

                bucket[signal.indicator] = signal

    return index


def _dataclass_semantic_map(
    cases, pipelines: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Sequence[Mapping[str, Any]]]:
    """Semantic mapping per dataset, from the same run the reference used."""

    return {
        dataset: result.get("semantic_mapping") or []
        for dataset, result in pipelines.items()
    }


def compare(
    cases,
    review: Mapping[str, Any],
    reference: Mapping[str, Any],
    pipelines: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compare a human review against a SAT-SA reference output.

    ``pipelines`` optionally supplies the raw pipeline results so evidence
    checks can read the semantic mapping without re-running anything. When it is
    absent, evidence checks that need it report NOT_VERIFIABLE rather than
    guessing.
    """

    pipelines = pipelines or {}

    # Build the comparison vocabulary from what the tool actually emitted, so a
    # reviewer can never be scored against an invented indicator.
    vocabulary: Dict[str, List[str]] = {}

    for record in reference.get("records", ()):
        for family in FAMILIES:
            for finding in record.get(f"sat_sa_{family}_findings") or ():
                indicators = vocabulary.setdefault(family, [])
                indicator = finding.get("indicator")
                if indicator and indicator not in indicators:
                    indicators.append(indicator)

    from framework.validation import normalize

    previous = dict(normalize.KNOWN_INDICATOR_FAMILY)
    normalize.KNOWN_INDICATOR_FAMILY.clear()
    normalize.KNOWN_INDICATOR_FAMILY.update(vocabulary)

    try:
        return _compare(
            cases, review, reference, pipelines, vocabulary
        )
    finally:
        normalize.KNOWN_INDICATOR_FAMILY.clear()
        normalize.KNOWN_INDICATOR_FAMILY.update(previous)


def _compare(
    cases,
    review: Mapping[str, Any],
    reference: Mapping[str, Any],
    pipelines: Mapping[str, Mapping[str, Any]],
    vocabulary: Mapping[str, List[str]],
) -> Dict[str, Any]:
    sat_index = _sat_signals_by_scope(reference)
    records_by_case = {
        record["case_id"]: record
        for record in review.get("records", ())
    }
    reference_records = {
        record["case_id"]: record
        for record in reference.get("records", ())
    }

    # Global view: which scopes does each indicator appear on, per side.
    human_scopes: Dict[str, set] = {}
    sat_scopes: Dict[str, set] = {}

    human_by_case: Dict[str, Dict[str, List[str]]] = {}

    for case in cases:

        record = records_by_case.get(case.case_id, {})

        by_family = normalise_human_record(record)
        human_by_case[case.case_id] = by_family

        for family, indicators in by_family.items():
            for indicator in indicators:
                human_scopes.setdefault(
                    f"{family}:{indicator}", set()
                ).add(case.scope_key)

    for scope_id, families in sat_index.items():
        for family, bucket in families.items():
            for indicator in bucket:
                sat_scopes.setdefault(
                    f"{family}:{indicator}", set()
                ).add(scope_id)

    comparisons: List[ComparisonRecord] = []

    for case in cases:

        case_reference = reference_records.get(case.case_id, {})
        scope = sat_index.get(case.scope_key, {})
        human_by_family = human_by_case.get(case.case_id, {})

        dataset = case.dataset
        result = pipelines.get(dataset)
        semantic_mapping = (
            result.get("semantic_mapping") or () if result else ()
        )
        record_count = case_reference.get("sat_sa_record_count")

        for family in FAMILIES:

            human_indicators = list(human_by_family.get(family, []))
            sat_bucket = scope.get(family, {})
            sat_indicators = list(sat_bucket)

            for indicator in sorted(set(human_indicators) | set(sat_indicators)):

                key = f"{family}:{indicator}"
                signal = sat_bucket.get(indicator)
                human_has = indicator in human_indicators
                sat_has = indicator in sat_indicators

                if human_has and sat_has:
                    comparison = _compare_matched(
                        case, family, indicator, signal, semantic_mapping,
                    )
                elif sat_has:
                    comparison = _false_positive(case, family, indicator, signal)
                else:
                    comparison = _false_negative(
                        case, family, indicator, human_by_family
                    )

                comparisons.append(comparison)

    # A signal that both sides reported but on different scopes is a scope
    # mismatch, and must not also be reported as a match.
    comparisons = _reclassify_scope_mismatches(
        comparisons, human_scopes, sat_scopes
    )

    not_evaluable = _not_evaluable_summary(cases, reference)

    unrecognised = sorted(
        {
            indicator
            for by_family in human_by_case.values()
            for indicator in by_family.get("_unrecognised", ())
        }
    )

    expert_labelled = bool(
        review.get("label_source") == "EXPERT_REVIEW"
        and _has_human_input(review)
    )

    reviewer_ids = sorted(
        {
            record.get("reviewer_id")
            for record in review.get("records", ())
            if record.get("reviewer_id")
        }
    )

    return {
        "schema_version": 1,
        "artefact": "VALIDATION_COMPARISON",
        "case_count": len(cases),
        # The template declares the label source it is *meant* to collect. The
        # effective source is only EXPERT_REVIEW once a human has actually
        # entered something, so a blank template can never be reported as an
        # expert review that happened to agree with the tool.
        "declared_label_source": review.get("label_source"),
        "label_source": "EXPERT_REVIEW" if expert_labelled else "UNLABELLED",
        "expert_labelled": expert_labelled,
        # Provenance travels with the metrics so a report can name who reviewed
        # it. A review file is self-declared, so the only thing that makes it
        # checkable later is that the reviewer named themselves.
        "reviewer_ids": reviewer_ids,
        "indicator_vocabulary": {
            family: sorted(indicators)
            for family, indicators in vocabulary.items()
        },
        "unrecognised_human_indicators": unrecognised,
        "not_evaluable": not_evaluable,
        "comparisons": [item.to_dict() for item in comparisons],
    }


def _has_human_input(review: Mapping[str, Any]) -> bool:
    from framework.validation.schema import has_any_expert_label

    return has_any_expert_label(review)


def _compare_matched(
    case,
    family: str,
    indicator: str,
    signal: Optional[NormalisedSignal],
    semantic_mapping,
) -> ComparisonRecord:
    """Both sides reported the indicator. Now judge whether evidence supports it.

    A validated match needs two independent things: the finding must point at
    records inside its own scope, and the rows at those records must carry the
    evidence it claims. Either one failing is enough to withhold the match,
    because an indicator that agrees with the reviewer but cannot be traced is
    not a validated agreement.
    """

    if signal is None:
        return ComparisonRecord(
            family,
            indicator,
            case.assessment_id,
            FALSE_POSITIVE,
            notes=["the tool reported this indicator on a different scope"],
        )

    rows = read_rows(case.dataset)
    traceability = check_traceability(
        signal,
        scope_row_indices(rows, signal.entity_id, signal.period_label),
    )
    support = check_evidence(signal, case.dataset, semantic_mapping)

    if (
        traceability.status == SUPPORTED
        and support.status in SUPPORTING_EVIDENCE_STATES
    ):
        outcome = MATCH
    else:
        outcome = MATCH_UNSUPPORTED

    return ComparisonRecord(
        family,
        indicator,
        case.assessment_id,
        outcome,
        dataset=case.dataset,
        sat_sa_evidence=support.to_dict(),
        capability=signal.capability,
        record_positions=signal.record_positions,
        explanation=signal.explanation,
        notes=[
            f"traceability: {traceability.status}",
            f"evidence: {support.status}",
        ],
    )


def _false_positive(case, family, indicator, signal) -> ComparisonRecord:
    return ComparisonRecord(
        family,
        indicator,
        case.assessment_id,
        FALSE_POSITIVE,
        dataset=case.dataset,
        sat_sa_evidence={
            "status": "NOT_EVALUATED",
            "detail": "a signal the reviewer did not report is not evidence "
                      "agreement",
        },
        capability=signal.capability if signal else None,
        record_positions=signal.record_positions if signal else [],
        explanation=signal.explanation if signal else None,
        notes=["SAT-SA reported an indicator the reviewer did not"],
    )


def _false_negative(case, family, indicator, human_by_family) -> ComparisonRecord:
    return ComparisonRecord(
        family,
        indicator,
        case.assessment_id,
        FALSE_NEGATIVE,
        dataset=case.dataset,
        human_evidence={
            "status": "REVIEWER_REPORTED",
            "detail": "the reviewer reported an indicator SAT-SA did not",
        },
        notes=["the reviewer reported an indicator SAT-SA did not"],
    )


def _reclassify_scope_mismatches(
    comparisons: List[ComparisonRecord],
    human_scopes: Mapping[str, set],
    sat_scopes: Mapping[str, set],
) -> List[ComparisonRecord]:
    """Downgrade any agreement whose indicator sits on different scopes.

    Compares across the whole corpus rather than case by case, so a signal that
    moved between entities or periods is caught even when both individual cases
    look right. A pairing is only claimed when both sides reported the indicator
    somewhere: an indicator the tool never emitted at all is a plain false
    negative, and calling it a scope mismatch would let a missed signal leave
    the recall count.
    """

    for comparison in comparisons:

        if comparison.outcome not in (MATCH, MATCH_UNSUPPORTED, FALSE_POSITIVE,
                                     FALSE_NEGATIVE):
            continue

        key = f"{comparison.family}:{comparison.indicator}"

        human_set = human_scopes.get(key, set())
        sat_set = sat_scopes.get(key, set())

        if not human_set or not sat_set:
            continue

        if human_set == sat_set:
            continue

        # The indicator exists on both sides, but not on the same scopes. Only
        # the portion that overlaps stays a match.
        overlapping = human_set & sat_set

        comparison.scope_mismatch = {
            "human_scopes": sorted(human_set),
            "sat_sa_scopes": sorted(sat_set),
            "agreeing_scopes": sorted(overlapping),
        }

        comparison.notes.append(
            "scope mismatch: reviewer reported this indicator on "
            f"{sorted(human_set)} while SAT-SA reported it on "
            f"{sorted(sat_set)}"
        )

        if comparison.scope_key not in overlapping:
            comparison.outcome = SCOPE_MISMATCH
            # The note written when the outcome was first assigned now
            # contradicts it, so it is replaced rather than left to mislead.
            comparison.notes = [
                note
                for note in comparison.notes
                if not note.startswith("the reviewer reported an indicator")
                and not note.startswith("SAT-SA reported an indicator")
            ]
        else:
            comparison.notes.append(
                f"overlapping scopes where both agree: "
                f"{sorted(overlapping)}"
            )

    return comparisons


def _not_evaluable_summary(cases, reference) -> Dict[str, Any]:
    """Where SAT-SA declined to judge, and where the case expected that.

    Counting NOT_EVALUABLE matters because a layer that silently returns nothing
    on a small scope would otherwise be scored as agreeing with a reviewer who
    also saw nothing.
    """

    reference_records = {
        record["case_id"]: record for record in reference.get("records", ())
    }

    entries = []

    for case in cases:

        record = reference_records.get(case.case_id, {})

        states = record.get("sat_sa_operational_pattern_states") or []

        actual = {
            state.get("pattern_id")
            for state in states
            if state.get("pattern_status") == "NOT_EVALUABLE"
        }

        expected = set(case.expected_not_evaluable())

        entries.append(
            {
                "case_id": case.case_id,
                "assessment_id": case.assessment_id,
                "sat_sa_not_evaluable_patterns": sorted(
                    pattern for pattern in actual if pattern
                ),
                "controlled_expectation_not_evaluable": sorted(expected),
                "agrees": actual == expected if expected else None,
                "note": "expectation is controlled design intent, not an "
                        "expert judgement",
            }
        )

    return {
        "case_count": len(entries),
        "cases_where_sat_sa_declined": sum(
            1 for entry in entries if entry["sat_sa_not_evaluable_patterns"]
        ),
        "cases_matching_controlled_expectation": sum(
            1
            for entry in entries
            if entry["agrees"] is True
        ),
        "entries": entries,
    }
