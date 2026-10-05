"""Per-family metrics for the validation comparison.

Precision and recall are reported per signal family, because a single number
across three families with different vocabularies would be meaningless. There is
deliberately no grand accuracy score: the corpus is small and controlled, and a
headline number over it would invite more confidence than 20 cases can carry.

The ``label_source`` travels with every metric block. Metrics computed from
controlled design intent describe whether the comparison machinery and the
system agree with each other. They are not expert validation, and they are
labelled as such wherever they appear.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from framework.validation.compare import (
    FALSE_NEGATIVE,
    FALSE_POSITIVE,
    MATCH,
    MATCH_UNSUPPORTED,
    SCOPE_MISMATCH,
)
from framework.validation.corpus import FAMILIES


def _ratio(numerator: int, denominator: int) -> Any:
    if not denominator:
        return None

    return round(numerator / denominator, 4)


def family_metrics(comparisons: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Metrics for one family, derived only from that family's comparisons."""

    counts = {
        MATCH: 0,
        MATCH_UNSUPPORTED: 0,
        SCOPE_MISMATCH: 0,
        FALSE_POSITIVE: 0,
        FALSE_NEGATIVE: 0,
    }

    indicator_vocabulary: Dict[str, str] = {}

    for item in comparisons:
        outcome = item.get("outcome")
        if outcome in counts:
            counts[outcome] += 1
        indicator_vocabulary.setdefault(
            item.get("indicator", ""), item.get("outcome", "")
        )

    true_positives = counts[MATCH]
    false_positives = counts[FALSE_POSITIVE]
    false_negatives = counts[FALSE_NEGATIVE]

    # Precision and recall are defined against indicator agreements only. A
    # matched indicator whose evidence did not check out is excluded from true
    # positives, because the brief is explicit that an unsupported match is not
    # a successful validation.
    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(true_positives, true_positives + false_negatives)

    return {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "matches_with_unsupported_evidence": counts[MATCH_UNSUPPORTED],
        "scope_mismatches": counts[SCOPE_MISMATCH],
        "precision": precision,
        "recall": recall,
        "outcome_counts": counts,
        "false_positive_details": [
            {
                "indicator": item.get("indicator"),
                "assessment_id": item.get("assessment_id"),
                "dataset": item.get("dataset"),
            }
            for item in comparisons
            if item.get("outcome") == FALSE_POSITIVE
        ],
        "false_negative_details": [
            {
                "indicator": item.get("indicator"),
                "assessment_id": item.get("assessment_id"),
                "dataset": item.get("dataset"),
            }
            for item in comparisons
            if item.get("outcome") == FALSE_NEGATIVE
        ],
        "scope_mismatch_details": [
            {
                "indicator": item.get("indicator"),
                "assessment_id": item.get("assessment_id"),
                "dataset": item.get("dataset"),
                "notes": item.get("notes", []),
            }
            for item in comparisons
            if item.get("outcome") == SCOPE_MISMATCH
        ],
    }


def compute_metrics(comparison: Mapping[str, Any]) -> Dict[str, Any]:
    """Metrics across the whole comparison, broken out by family."""

    comparisons = list(comparison.get("comparisons") or ())

    # Agreement metrics only mean something once a human has labelled
    # something. With an empty review every tool signal is trivially
    # "unmatched", and reporting precision 0.0 from that would be a false
    # statement about SAT-SA rather than a statement about the missing labels.
    human_labelled = any(
        item.get("outcome") == FALSE_NEGATIVE or item.get("human_evidence")
        for item in comparisons
    ) or comparison.get("expert_labelled", False)

    per_family: Dict[str, Any] = {}

    for family in FAMILIES:

        subset = [
            item for item in comparisons if item.get("family") == family
        ]

        block = family_metrics(subset)

        if not human_labelled:
            block["precision"] = None
            block["recall"] = None
            block["agreement_metrics_computable"] = False
            block["agreement_metrics_blocked_because"] = (
                "no human review labels exist, so agreement cannot be "
                "measured. These counts are SAT-SA output, not errors."
            )

        per_family[family] = block

    evidence_states: Dict[str, int] = {}

    for item in comparisons:

        evidence = item.get("sat_sa_evidence") or {}
        status = evidence.get("status")

        if status:
            evidence_states[status] = evidence_states.get(status, 0) + 1

    traceability = {
        "agreement_metrics_computable": bool(human_labelled),
        "evidence_status_counts": evidence_states,
        "explanations_present": sum(
            1 for item in comparisons if item.get("explanation")
        ),
        "record_references_present": sum(
            1 for item in comparisons if item.get("record_positions")
        ),
        "comparable_comparisons": len(comparisons),
        "note": "traceability counts only comparable signals. Free text is "
                "never compared by string equality, so an explanation is "
                "recorded as present or absent, never as equal or different.",
    }

    supervisory = _supervisory_summary(comparison)

    return {
        "schema_version": 1,
        "artefact": "VALIDATION_METRICS",
        "label_source": comparison.get("label_source"),
        "declared_label_source": comparison.get("declared_label_source"),
        "expert_labelled": comparison.get("expert_labelled", False),
        "reviewer_ids": comparison.get("reviewer_ids", []),
        "agreement_metrics_computable": bool(human_labelled),
        "agreement_metrics_blocked_because": (
            None
            if human_labelled
            else "no human review labels exist; SAT-SA output is reported "
                 "but agreement is not measurable"
        ),
        "case_count": comparison.get("case_count"),
        "per_family": per_family,
        "not_evaluable": comparison.get("not_evaluable", {}),
        "traceability": traceability,
        "supervisory_value": supervisory,
        "unrecognised_human_indicators": comparison.get(
            "unrecognised_human_indicators", []
        ),
        "no_grand_accuracy_score": (
            "Precision and recall are reported per signal family only. No "
            "single accuracy figure is produced: the corpus is small and "
            "controlled, and one number would hide which family it describes."
        ),
    }


def _supervisory_summary(comparison: Mapping[str, Any]) -> Dict[str, Any]:
    """The supervisory-value question, counted but never scored.

    A YES here is an argument that the signal is not obvious from a
    conventional dashboard. It is not an accuracy measure and is not turned
    into a novelty index.
    """

    # The comparison carries the review verbatim for the report to render.
    return {
        "question": "Would this signal be difficult to identify from a "
                    "conventional SOC dashboard?",
        "allowed_answers": ["YES", "NO", "UNCERTAIN"],
        "treated_as": "supporting evidence for a supervisory-value argument",
        "not_used_as": "an accuracy metric or a novelty score",
        "responses": comparison.get("supervisory_responses", {}),
    }
