"""Validation report generation.

The report's first job is honesty about what kind of validation has actually
happened. If no human reviewer has entered labels, it says "Expert validation
pending." in those words, and controlled design intent is never described as
expert ground truth.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.validation.compare import (
    FALSE_NEGATIVE,
    FALSE_POSITIVE,
    MATCH,
    MATCH_UNSUPPORTED,
    SCOPE_MISMATCH,
)
from framework.validation.corpus import (
    FAMILIES,
    FORBIDDEN_LABEL_PHRASES,
    LABEL_SOURCE_CONTROLLED,
    LABEL_SOURCE_EXPERT,
    ValidationCase,
)

EXPERT_PENDING = "Expert validation pending."

FAMILY_TITLES = {
    "execution_gap": "Execution Gap",
    "negative_space": "Negative Space",
    "operational_pattern": "Operational Pattern",
}


def _rule(char: str = "-", width: int = 78) -> str:
    return char * width


def _header(number: int, title: str) -> str:
    return f"{number}. {title.upper()}\n{_rule()}"


def _family_section(
    number: int, family: str, metrics: Mapping[str, Any]
) -> str:
    block = metrics.get("per_family", {}).get(family, {})

    lines = [_header(number, FAMILY_TITLES.get(family, family))]

    computable = block.get("agreement_metrics_computable", True)

    if not computable:
        lines.append(
            "  agreement not computable: no human review labels exist yet."
        )
        lines.append(
            "  The counts below are SAT-SA output, not errors. An indicator"
        )
        lines.append(
            "  counted here as a false positive means only that no reviewer"
        )
        lines.append(
            "  has yet to confirm it, which is a gap in the evidence for this"
        )
        lines.append(
            "  study and not a demonstrated mistake by SAT-SA."
        )
        lines.append("")

    # The outcome words are only true once a human has actually reviewed. With
    # no review the same lines are relabelled as tool output, so the report
    # cannot be read as accusing the tool of errors nobody has established.
    if computable:
        positive_label = "false positive"
        negative_label = "false negative"
    else:
        positive_label = "reported, unreviewed"
        negative_label = "reviewer-only, would be a miss"

    lines.append(f"  true positives ................ {block.get('true_positives')}")
    lines.append(f"  false positives ............... {block.get('false_positives')}")
    lines.append(f"  false negatives ............... {block.get('false_negatives')}")
    lines.append(
        f"  matches with unsupported evidence "
        f"{block.get('matches_with_unsupported_evidence')}"
    )
    lines.append(f"  scope mismatches .............. {block.get('scope_mismatches')}")
    lines.append(
        f"  precision ..................... "
        f"{_format_ratio(block.get('precision'), computable)}"
    )
    lines.append(
        f"  recall ........................ "
        f"{_format_ratio(block.get('recall'), computable)}"
    )

    for detail in block.get("false_positive_details") or ():
        lines.append(
            f"    {positive_label}: {detail.get('indicator')} "
            f"at {detail.get('assessment_id')}"
        )

    for detail in block.get("false_negative_details") or ():
        lines.append(
            f"    {negative_label}: {detail.get('indicator')} "
            f"at {detail.get('assessment_id')}"
        )

    for detail in block.get("scope_mismatch_details") or ():
        lines.append(
            f"    scope mismatch: {detail.get('indicator')} "
            f"at {detail.get('assessment_id')}"
        )

    lines.append("")

    return "\n".join(lines)


def _format_ratio(value: Any, computable: bool = True) -> str:
    if value is None:
        if not computable:
            return "not computable (no human review labels exist yet)"

        return "not defined (no positive or no negative case present)"

    return f"{value:.4f}"


def build_report(
    cases: Sequence[ValidationCase],
    comparison: Mapping[str, Any],
    metrics: Mapping[str, Any],
    reference: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render the validation report."""

    expert_labelled = bool(metrics.get("expert_labelled"))
    label_source = metrics.get("label_source")

    lines: List[str] = []

    lines.append(_rule("="))
    lines.append("SAT-SA SMALL EXPERT VALIDATION STUDY")
    lines.append(_rule("="))
    lines.append("")

    # 1
    lines.append(_header(1, "Objective"))
    lines.append(
        "  Compare human manual review against SAT-SA output for the three"
    )
    lines.append(
        "  existing supervisory signal families, and establish whether those"
    )
    lines.append(
        "  signals are useful, explainable and aligned with manual review."
    )
    lines.append(
        "  No new analytics were added. The framework observes the existing"
    )
    lines.append(
        "  pipeline result and adds no rule, threshold, score or output key."
    )
    lines.append("")

    # 2
    lines.append(_header(2, "Dataset description"))
    datasets = sorted({case.dataset for case in cases})
    lines.append(
        f"  {len(cases)} assessment cases drawn from {len(datasets)} datasets"
    )
    lines.append("  that already exist in the repository. No new dataset was created.")
    for dataset in datasets:
        count = sum(1 for case in cases if case.dataset == dataset)
        lines.append(f"    {dataset} ({count} cases)")
    lines.append("")

    # 3
    lines.append(_header(3, "Number of assessment cases"))
    lines.append(f"  {len(cases)}")
    lines.append("")

    # 4
    lines.append(_header(4, "Manual-review methodology"))
    lines.append(
        "  A reviewer is given each case's assessment scope and the raw"
    )
    lines.append(
        "  submitted rows behind it. They record, per signal family, the"
    )
    lines.append(
        "  indicators they observed, the records that support them, their"
    )
    lines.append("  reasoning, and their confidence.")
    lines.append(
        "  The template ships with every human field empty, so no review is"
    )
    lines.append(
        "  implied before one happens. Free text is kept separate from"
    )
    lines.append(
        "  indicator comparison and is never matched by string equality."
    )
    lines.append("")

    # 5
    lines.append(_header(5, "SAT-SA methodology"))
    lines.append(
        "  The existing pipeline is run over each corpus dataset. The"
    )
    lines.append(
        "  reference output is a verbatim slice of the existing per-scope"
    )
    lines.append(
        "  payloads under execution_gap_findings, negative_space_findings and"
    )
    lines.append(
        "  operational_pattern_findings. No result schema was modified."
    )
    lines.append("")

    # 6
    lines.append(_header(6, "Comparison methodology"))
    lines.append("  Comparison is per indicator, per family, per assessment scope.")
    lines.append(
        "  Scope is part of a signal's identity, so an indicator reported for"
    )
    lines.append(
        "  the right reason against the wrong entity is recorded as a scope"
    )
    lines.append("  mismatch rather than as a match.")
    lines.append("  Outcomes: MATCH, MATCH_UNSUPPORTED, SCOPE_MISMATCH,")
    lines.append("  FALSE_POSITIVE, FALSE_NEGATIVE.")
    lines.append("")

    # 7-9
    lines.append(_family_section(7, "execution_gap", metrics))
    lines.append(_family_section(8, "negative_space", metrics))
    lines.append(_family_section(9, "operational_pattern", metrics))

    # 10
    lines.append(_header(10, "Precision and recall per family"))
    computable = metrics.get("agreement_metrics_computable", True)
    for family in FAMILIES:
        block = metrics.get("per_family", {}).get(family, {})
        lines.append(
            f"  {FAMILY_TITLES.get(family, family):22} "
            f"precision={_format_ratio(block.get('precision'), computable)}  "
            f"recall={_format_ratio(block.get('recall'), computable)}"
        )
    lines.append("")
    if not metrics.get("agreement_metrics_computable"):
        lines.append(
            f"  {metrics.get('agreement_metrics_blocked_because')}"
        )
        lines.append("")
    lines.append(f"  {metrics.get('no_grand_accuracy_score')}")
    lines.append("")

    # 11
    computable = bool(metrics.get("agreement_metrics_computable"))

    lines.append(_header(11, "False positives"))
    any_fp = False
    for family in FAMILIES:
        for detail in metrics["per_family"][family].get("false_positive_details") or ():
            any_fp = True
            lines.append(
                f"  {family}: {detail.get('indicator')} at "
                f"{detail.get('assessment_id')} in {detail.get('dataset')}"
            )
    if not any_fp:
        lines.append("  none")
    if not computable and any_fp:
        lines.append("")
        lines.append(
            "  These are not false positives. No human review exists yet, so"
        )
        lines.append(
            "  nothing has confirmed or contradicted them. They are listed as"
        )
        lines.append("  SAT-SA output awaiting review.")
    lines.append("")

    # 12
    lines.append(_header(12, "False negatives"))
    any_fn = False
    for family in FAMILIES:
        for detail in metrics["per_family"][family].get("false_negative_details") or ():
            any_fn = True
            lines.append(
                f"  {family}: {detail.get('indicator')} at "
                f"{detail.get('assessment_id')} in {detail.get('dataset')}"
            )
    if not any_fn:
        lines.append(
            "  none, and none can exist yet: a false negative requires a"
        )
        lines.append(
            "  human label that SAT-SA did not reproduce."
        )
    lines.append("")

    # 13
    lines.append(_header(13, "NOT_EVALUABLE cases"))
    not_evaluable = metrics.get("not_evaluable", {})
    lines.append(
        f"  cases where SAT-SA declined to judge at least one pattern: "
        f"{not_evaluable.get('cases_where_sat_sa_declined')} of "
        f"{not_evaluable.get('case_count')}"
    )
    lines.append(
        "  Declining to judge is a distinct outcome from judging and finding"
    )
    lines.append(
        "  nothing, and is counted separately so it cannot be scored as agreement."
    )
    for entry in not_evaluable.get("entries") or ():
        if entry.get("sat_sa_not_evaluable_patterns"):
            lines.append(
                f"    {entry.get('case_id')} "
                f"{entry.get('assessment_id')}: "
                f"{', '.join(entry['sat_sa_not_evaluable_patterns'])}"
            )
    lines.append("")

    # 14
    lines.append(_header(14, "Evidence traceability"))
    traceability = metrics.get("traceability", {})
    for status, count in sorted(
        (traceability.get("evidence_status_counts") or {}).items()
    ):
        lines.append(f"  evidence {status:24} {count}")
    lines.append(
        f"  explanations present "
        f"{traceability.get('explanations_present')} of "
        f"{traceability.get('comparable_comparisons')} comparable signals"
    )
    lines.append(
        f"  record references present "
        f"{traceability.get('record_references_present')} of "
        f"{traceability.get('comparable_comparisons')}"
    )
    lines.append(f"  {traceability.get('note')}")
    lines.append("")

    # 15
    lines.append(_header(15, "Human assessment of supervisory usefulness"))
    supervisory = metrics.get("supervisory_value", {})
    lines.append(f"  question: {supervisory.get('question')}")
    lines.append(
        f"  allowed answers: {', '.join(supervisory.get('allowed_answers', []))}"
    )
    responses = supervisory.get("responses") or {}
    if responses:
        for answer, count in sorted(responses.items()):
            lines.append(f"    {answer}: {count}")
    else:
        lines.append("  no responses recorded")
    lines.append(f"  {supervisory.get('treated_as')}")
    lines.append(f"  not used as: {supervisory.get('not_used_as')}")
    lines.append("")

    # 16
    lines.append(_header(16, "Validation status"))
    lines.append("")
    if expert_labelled:
        lines.append("  EXPERT VALIDATION")
        lines.append(
            f"  A real human reviewer entered labels (label_source="
            f"{label_source})."
        )
        lines.append(
            "  Metrics above are computed against those expert labels."
        )
        reviewers = metrics.get("reviewer_ids") or []
        if reviewers:
            lines.append(
                f"  reviewers of record: {', '.join(sorted(reviewers))}"
            )
        else:
            lines.append(
                "  no reviewer id was supplied, so the provenance of these "
                "labels cannot be checked from this report"
            )
    else:
        lines.append("  CONTROLLED VALIDATION")
        lines.append(f"  {EXPERT_PENDING}")
        lines.append(
            "  No human reviewer has entered any label, so the metrics above"
        )
        lines.append(
            "  are a self-consistency check of SAT-SA against controlled"
        )
        lines.append(
            "  design intent, not expert validation, and must not be quoted as"
        )
        lines.append(
            "  evidence that the signals match expert judgement."
        )
    lines.append("")

    # 17
    lines.append(_header(17, "Limitations"))
    for limitation in _limitations(cases, metrics, reference, expert_labelled):
        lines.append(f"  - {limitation}")
    lines.append("")

    lines.append(_rule("="))
    lines.append("END OF REPORT")
    lines.append(_rule("="))

    report = "\n".join(lines)

    return report


def _limitations(
    cases, metrics, reference, expert_labelled
) -> List[str]:
    limitations = [
        "The corpus is small and controlled. It is designed to exercise the "
        "comparison machinery across the signal families and the scope "
        "isolation rules. It cannot estimate how the signals perform on real "
        "operational data.",
    ]

    if not expert_labelled:
        limitations.append(
            "No expert labels exist yet, so no claim about agreement with a "
            "human reviewer is supported by this report."
        )

    limitations.append(
        "Controlled expectations were written by the framework author from "
        "the raw source rows. They are design intent. They are not independent "
        "of the system's authors and must not be read as external validation."
    )

    for family in FAMILIES:

        block = metrics.get("per_family", {}).get(family, {})

        if block.get("false_positives") and not block.get("true_positives"):
            limitations.append(
                f"{family}: no case in this corpus pairs a human-reported "
                "indicator with a matching SAT-SA indicator, so precision is "
                "not defined for this family."
            )

    if any(
        observation.get("collisions")
        for observation in (reference or {}).get("concept_collisions", ())
    ):
        collisions = []
        for observation in reference.get("concept_collisions", ()):
            for concept, columns in sorted(
                observation.get("collisions", {}).items()
            ):
                collisions.append(
                    f"{observation.get('dataset')}: {concept} is fed by "
                    f"{', '.join(columns)}"
                )
        limitations.append(
            "Concept collisions were observed, meaning more than one source "
            "column feeds a single canonical concept: "
            + "; ".join(collisions)
            + ". A finding's evidence value for such a concept is ambiguous "
            "unless the columns agree, so those findings need human reading "
            "rather than automatic acceptance."
        )

    limitations.append(
        "Precision and recall are undefined wherever a family has no positive "
        "or no negative case in the corpus. Undefined is reported as undefined "
        "rather than as zero or one."
    )

    limitations.append(
        "Explanations are recorded as present or absent. Human and tool "
        "reasoning is never compared by string equality, so this report cannot "
        "and does not measure whether the wording of an explanation is good."
    )

    limitations.append(
        "The supervisory-value question is a novelty signal about dashboard "
        "visibility, not an accuracy measure, and is not scored numerically."
    )

    return limitations


def write_report(report: str, path: str) -> str:
    directory = os.path.dirname(os.path.abspath(path))

    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(report)
        handle.write("\n")

    return path


#: Words that turn a mention into a prohibition. A report has to be able to say
#: "this is not ground truth" without tripping its own audit, so an occurrence
#: is only a finding when it is not already being denied.
_NEGATIONS = (
    "not",
    "never",
    "no",
    "non",
    "cannot",
    "without",
    "rather than",
    "instead of",
    "is not",
    "are not",
)


def _is_denied(text: str, index: int, window: int = 48) -> bool:
    """Is this occurrence of a phrase inside a denial of it?"""

    preceding = text[max(0, index - window):index].lower()

    return any(
        negation in preceding
        for negation in _NEGATIONS
    )


def assert_no_ground_truth_claims(text: str) -> List[str]:
    """Return any phrase in the report that overstates label authority.

    Only affirmative uses count. A report that states the controlled
    expectations are *not* ground truth is doing exactly the right thing, and
    flagging it would push the wording towards silence instead of clarity.
    """

    lowered = text.lower()
    claims = []

    for phrase in FORBIDDEN_LABEL_PHRASES:

        start = lowered.find(phrase)

        while start != -1:

            if not _is_denied(lowered, start) and phrase not in claims:
                claims.append(phrase)

            start = lowered.find(phrase, start + 1)

    return claims
