"""Loader for the controlled validation corpus.

The corpus is a list of assessment cases. Each case points at a dataset that
already exists in the repository and names one ``AssessmentScope`` inside it, so
the validation framework never creates a second copy of data that is already
there.

A case may carry a ``controlled_expectation``. That is design intent written by
the framework author from the raw source rows, and it exists so the comparison
machinery can be exercised in software tests. It is explicitly *not* expert
ground truth, and every consumer of this module has to carry that distinction
through to its output.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

CORPUS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "corpus.json"
)

#: The three intelligence families under validation, mapped to the existing
#: pipeline result key that already holds them.
FAMILY_RESULT_KEYS: Dict[str, str] = {
    "execution_gap": "execution_gap_findings",
    "negative_space": "negative_space_findings",
    "operational_pattern": "operational_pattern_findings",
}

FAMILIES: List[str] = list(FAMILY_RESULT_KEYS)

#: A label may only ever be described as one of these.
LABEL_SOURCE_CONTROLLED = "CONTROLLED_EXPECTATION"
LABEL_SOURCE_EXPERT = "EXPERT_REVIEW"
LABEL_SOURCE_UNLABELLED = "UNLABELLED"

LABEL_SOURCES = (
    LABEL_SOURCE_CONTROLLED,
    LABEL_SOURCE_EXPERT,
    LABEL_SOURCE_UNLABELLED,
)

#: Phrases that would turn design intent into a claim of expert authority. The
#: corpus and every artefact derived from it are checked against this list.
FORBIDDEN_LABEL_PHRASES = (
    "ground truth",
    "ground_truth",
    "groundtruth",
    "expert ground truth",
    "expert-reviewed label",
)


class CorpusError(ValueError):
    """The corpus cannot be trusted."""


def _repo_root() -> str:
    """Locate the repository root from this file, independent of the CWD.

    The rest of the framework resolves its configuration relative to the working
    directory, so the pipeline still has to be invoked from the repository root.
    Resolving the corpus independently only means the corpus file itself can be
    located reliably.
    """

    here = os.path.dirname(os.path.abspath(__file__))

    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))


def repo_root() -> str:
    """Public accessor for the repository root."""

    return _repo_root()


def dataset_path(dataset: str) -> str:
    """Resolve a corpus dataset name to a readable path."""

    return os.path.join(_repo_root(), dataset)


class ValidationCase:
    """One assessment case in the corpus.

    Attributes mirror the corpus file. Nothing here is inferred from SAT-SA
    output; ``controlled_expectation`` comes from the corpus file and its
    ``label_source`` records who wrote it.
    """

    __slots__ = (
        "case_id",
        "dataset",
        "assessment_id",
        "case_type",
        "covers",
        "design_intent",
        "raw_observations",
        "controlled_expectation",
        "expectation_label_source",
    )

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.case_id = payload["case_id"]
        self.dataset = payload["dataset"]
        self.assessment_id = payload["assessment_id"]
        self.case_type = payload.get("case_type", "UNCLASSIFIED")
        self.covers = list(payload.get("covers", ()))
        self.design_intent = payload.get("design_intent", "")
        self.raw_observations = list(payload.get("raw_observations", ()))
        self.controlled_expectation = payload.get("controlled_expectation")
        self.expectation_label_source = (
            self.controlled_expectation.get("label_source")
            if self.controlled_expectation
            else LABEL_SOURCE_UNLABELLED
        )

    @property
    def entity_id(self) -> str:
        """Entity part of the assessment id, which is everything before ``::``."""

        return self.assessment_id.split("::", 1)[0]

    @property
    def scope_key(self) -> str:
        """Globally unique scope identity.

        An assessment id is only unique within its own dataset, so the dataset
        is part of the key. Two datasets in this repository both carry a
        ``CSE-A01::Period-2`` scope.
        """

        return f"{self.dataset}::{self.assessment_id}"

    @property
    def period_label(self) -> str:
        """Period part of the assessment id."""

        parts = self.assessment_id.split("::", 1)

        return parts[1] if len(parts) > 1 else ""

    @property
    def is_expert_labelled(self) -> bool:
        """Controlled expectations are never expert labels."""

        return self.expectation_label_source == LABEL_SOURCE_EXPERT

    def expected_indicators(self, family: str) -> List[str]:
        """Controlled expectation for one family, or empty when unlabelled."""

        if not self.controlled_expectation:
            return []

        return list(self.controlled_expectation.get(family, ()))

    def expected_not_evaluable(self) -> List[str]:
        if not self.controlled_expectation:
            return []

        return list(
            self.controlled_expectation.get(
                "operational_pattern_not_evaluable", ()
            )
        )

    def expected_evidence_not_present(self) -> List[str]:
        if not self.controlled_expectation:
            return []

        return list(
            self.controlled_expectation.get(
                "operational_pattern_evidence_not_present", ()
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "dataset": self.dataset,
            "assessment_id": self.assessment_id,
            "case_type": self.case_type,
            "covers": list(self.covers),
            "design_intent": self.design_intent,
            "raw_observations": list(self.raw_observations),
            "controlled_expectation": self.controlled_expectation,
            "expectation_label_source": self.expectation_label_source,
        }


def _validate(payload: Dict[str, Any]) -> None:
    if payload.get("schema_version") != 1:
        raise CorpusError(
            "unsupported corpus schema_version: "
            f"{payload.get('schema_version')!r}"
        )

    cases = payload.get("cases")

    if not isinstance(cases, list) or not cases:
        raise CorpusError("corpus declares no cases")

    seen_ids = set()
    seen_scopes = set()

    for entry in cases:
        case = ValidationCase(entry)

        if case.case_id in seen_ids:
            raise CorpusError(f"duplicate case_id: {case.case_id}")

        # An assessment id is only unique inside its own dataset. Two
        # different datasets in this repository both contain a
        # CSE-A01::Period-2 scope, so a scope is identified by the pair.
        scope_key = (case.dataset, case.assessment_id)

        if scope_key in seen_scopes:
            raise CorpusError(
                f"duplicate scope: {case.dataset} / {case.assessment_id}"
            )

        seen_ids.add(case.case_id)
        seen_scopes.add(scope_key)

        if case.expectation_label_source not in LABEL_SOURCES:
            raise CorpusError(
                f"{case.case_id}: unknown label_source "
                f"{case.expectation_label_source!r}"
            )

        if case.expectation_label_source == LABEL_SOURCE_EXPERT:
            raise CorpusError(
                f"{case.case_id}: the corpus may not contain expert labels"
            )

        if not os.path.isfile(dataset_path(case.dataset)):
            raise CorpusError(
                f"{case.case_id}: dataset not found: {case.dataset}"
            )


def load_corpus(path: Optional[str] = None) -> List[ValidationCase]:
    """Load and validate the corpus."""

    with open(path or CORPUS_PATH, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    _validate(payload)

    return [ValidationCase(entry) for entry in payload["cases"]]


def load_corpus_document(path: Optional[str] = None) -> Dict[str, Any]:
    """The raw corpus document, for artefact writing and audit."""

    with open(path or CORPUS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)
