"""Schema for the human manual-review template.

The template is what a real reviewer fills in. It is generated from the corpus
so that every case appears exactly once, and it is generated with every human
field empty on purpose: shipping a template with a finding already filled in
would be fabricating a review that never happened.

Two rules are enforced here rather than left to convention:

* the template must contain no human judgement at the moment it is written;
* the template must not contain any SAT-SA output, because the reviewer has to
  reach their own conclusion first.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from framework.validation.corpus import (
    LABEL_SOURCE_EXPERT,
    ValidationCase,
    dataset_path,
)

#: Where ``python -m framework.validation template`` writes the review file and
#: where ``compare`` reads it from by default. The template is a generated
#: artefact rather than a source file, so it lives beside the other generated
#: validation outputs instead of at the top of the package.
REVIEW_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "output",
    "human_review_template.json",
)

#: Every field a reviewer supplies. All of these are empty in the shipped
#: template. None of them is pre-populated from SAT-SA output or from the
#: controlled expectations in the corpus.
HUMAN_FIELDS: List[str] = [
    "human_execution_gap",
    "human_negative_space",
    "human_operational_pattern",
    "human_indicators",
    "human_evidence_reference",
    "human_reason",
    "human_confidence",
    "supervisory_dashboard_difficulty",
    "supervisory_review_rationale",
    "reviewer_id",
    "review_timestamp",
]

#: Fields that identify the case rather than record a judgement. These are
#: filled in by the generator because they are facts about the corpus, not
#: opinions about it.
IDENTITY_FIELDS: List[str] = [
    "case_id",
    "assessment_id",
    "entity",
    "period",
]

#: Allowed answers for the supervisory-value question. Deliberately not a
#: number: this supports an argument about novelty, it does not score it.
DASHBOARD_DIFFICULTY_VALUES = ("YES", "NO", "UNCERTAIN")

CONFIDENCE_VALUES = ("HIGH", "MEDIUM", "LOW", "UNSURE")


class ReviewTemplateError(ValueError):
    """The human review template cannot be trusted."""


def _empty_record(case: ValidationCase) -> Dict[str, Any]:
    """One review row: identity filled in, every human field empty."""

    return {
        "case_id": case.case_id,
        "assessment_id": case.assessment_id,
        "entity": case.entity_id,
        "period": case.period_label,
        "dataset": case.dataset,
        "case_type": case.case_type,
        "human_execution_gap": None,
        "human_negative_space": None,
        "human_operational_pattern": None,
        "human_indicators": None,
        "human_evidence_reference": None,
        "human_reason": None,
        "human_confidence": None,
        "supervisory_dashboard_difficulty": None,
        "supervisory_review_rationale": None,
        "reviewer_id": None,
        "review_timestamp": None,
    }


def build_review_template(cases: List[ValidationCase]) -> Dict[str, Any]:
    """Build an empty review template for the given cases."""

    return {
        "schema_version": 1,
        "artefact": "HUMAN_REVIEW_TEMPLATE",
        "label_source": LABEL_SOURCE_EXPERT,
        "instructions": [
            "Complete this file BEFORE seeing any SAT-SA output.",
            "Inspect only the submitted source data named in the dataset column.",
            "Record what you concluded, not what you expect the tool to say.",
            "Leave a field empty if you did not assess it. An empty field is",
            "not a negative finding.",
        ],
        "field_definitions": {
            "human_execution_gap": "Indicator observed for the execution-gap family, or an empty list for none observed.",
            "human_negative_space": "Indicator observed for the negative-space family, or an empty list for none observed.",
            "human_operational_pattern": "Indicator observed for the operational-pattern family, or an empty list for none observed.",
            "human_indicators": "Every indicator observed across all three families, as a list of indicator codes.",
            "human_evidence_reference": "Which submitted records support your conclusion, as record ids or positions.",
            "human_reason": "Your reasoning, in your own words.",
            "human_confidence": "One of HIGH, MEDIUM, LOW, UNSURE.",
            "supervisory_dashboard_difficulty": "Would this signal be difficult to identify from a conventional SOC dashboard? One of YES, NO, UNCERTAIN.",
            "supervisory_review_rationale": "Why would a supervisor review this?",
            "reviewer_id": "Your identifier.",
            "review_timestamp": "When you completed the review, ISO 8601.",
        },
        "allowed_values": {
            "human_confidence": list(CONFIDENCE_VALUES),
            "supervisory_dashboard_difficulty": list(
                DASHBOARD_DIFFICULTY_VALUES
            ),
        },
        "case_count": len(cases),
        "completed_case_count": 0,
        "records": [_empty_record(case) for case in cases],
    }


def is_template_blank(template: Dict[str, Any]) -> bool:
    """True when no human judgement has been recorded.

    A reviewer who inspected a case and found nothing still records an empty
    list and a confidence value, so a completed record is never identical to a
    blank one. This is what makes "no expert labels yet" a checkable fact
    rather than an assumption.
    """

    for record in template.get("records", ()):
        for field in HUMAN_FIELDS:
            if record.get(field) not in (None, "", []):
                return False

    return True


def has_any_expert_label(template: Dict[str, Any]) -> bool:
    """True when at least one human field carries a reviewer's judgement."""

    return not is_template_blank(template)


def _validate_indicator_list(value: Any, field: str, case_id: str) -> None:
    if value is None:
        return

    if not isinstance(value, list):
        raise ReviewTemplateError(
            f"{case_id}: {field} must be a list or null, got "
            f"{type(value).__name__}"
        )

    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ReviewTemplateError(
                f"{case_id}: {field} must contain non-empty strings"
            )


def validate_review(template: Dict[str, Any]) -> List[str]:
    """Validate a completed template. Returns a list of problems.

    Structural problems raise; content problems are returned so the reviewer
    gets every issue at once rather than one per run.
    """

    if template.get("schema_version") != 1:
        raise ReviewTemplateError("unsupported review schema_version")

    records = template.get("records")

    if not isinstance(records, list) or not records:
        raise ReviewTemplateError("review template declares no records")

    problems: List[str] = []

    seen = set()

    for record in records:
        case_id = record.get("case_id", "<missing>")

        if case_id in seen:
            raise ReviewTemplateError(f"duplicate case_id: {case_id}")

        seen.add(case_id)

        for field in IDENTITY_FIELDS:
            if not record.get(field):
                raise ReviewTemplateError(
                    f"{case_id}: identity field {field} is missing"
                )

        for field in (
            "human_execution_gap",
            "human_negative_space",
            "human_operational_pattern",
            "human_indicators",
        ):
            _validate_indicator_list(record.get(field), field, case_id)

        confidence = record.get("human_confidence")

        if confidence is not None and confidence not in CONFIDENCE_VALUES:
            problems.append(
                f"{case_id}: human_confidence {confidence!r} is not one of "
                f"{list(CONFIDENCE_VALUES)}"
            )

        difficulty = record.get("supervisory_dashboard_difficulty")

        if difficulty is not None and difficulty not in DASHBOARD_DIFFICULTY_VALUES:
            problems.append(
                f"{case_id}: supervisory_dashboard_difficulty {difficulty!r} "
                f"is not one of {list(DASHBOARD_DIFFICULTY_VALUES)}"
            )

        indicators = record.get("human_indicators")

        if indicators:
            for family_field in (
                "human_execution_gap",
                "human_negative_space",
                "human_operational_pattern",
            ):
                for indicator in record.get(family_field) or ():
                    if indicator not in indicators:
                        problems.append(
                            f"{case_id}: {indicator} appears in "
                            f"{family_field} but not in human_indicators"
                        )

    return problems


def write_review_template(
    path: str, cases: List[ValidationCase]
) -> str:
    """Write an empty review template, refusing to overwrite a real review."""

    if os.path.exists(path):
        existing = load_review(path)

        if not is_template_blank(existing):
            raise ReviewTemplateError(
                f"{path} already contains reviewer input and will not be "
                "overwritten"
            )

    template = build_review_template(cases)

    directory = os.path.dirname(os.path.abspath(path))

    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(template, handle, indent=2, sort_keys=True)
        handle.write("\n")

    return path


def load_review(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or REVIEW_TEMPLATE_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def review_by_case(template: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {record["case_id"]: record for record in template.get("records", ())}


def load_source_rows(case: ValidationCase) -> List[Dict[str, str]]:
    """Read the raw submitted rows for a case.

    The reviewer inspects these, and the evidence checks read the same rows, so
    both sides of the comparison start from the submitted data.
    """

    import csv

    with open(dataset_path(case.dataset), "r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    entity_column = None
    period_column = None

    for candidate in ("cse", "entity", "cse_id", "department"):
        if rows and candidate in rows[0]:
            entity_column = candidate
            break

    for candidate in ("period", "month", "quarter", "created_time"):
        if rows and candidate in rows[0]:
            period_column = candidate
            break

    selected = []

    for row in rows:
        if entity_column and row.get(entity_column) != case.entity_id:
            continue

        if period_column and row.get(period_column) != case.period_label:
            continue

        selected.append(row)

    return selected
