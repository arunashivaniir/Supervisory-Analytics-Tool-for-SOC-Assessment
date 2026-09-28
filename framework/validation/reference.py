"""SAT-SA reference output for the validation corpus.

This is the machine-generated side of the comparison. It is produced by running
the existing pipeline over each dataset the corpus names and slicing the
existing per-scope result payloads. No result key is added to, removed from or
rewritten in the pipeline output; the reference file is a separate artefact that
reads the result.

The reference output is deliberately a separate step from the human review, so
the reviewer can complete their review without having seen it.
"""

from __future__ import annotations

import contextlib
import io
import os
from typing import Any, Dict, List, Mapping, Optional

from framework.validation.corpus import (
    FAMILY_RESULT_KEYS,
    ValidationCase,
    dataset_path,
    load_corpus,
)

REFERENCE_SCHEMA_VERSION = 1


def _scope_block(
    block: Optional[Mapping[str, Any]], assessment_id: str
) -> Optional[Mapping[str, Any]]:
    for entry in (block or {}).get("scopes") or ():
        if entry.get("assessment_id") == assessment_id:
            return entry

    return None


def build_reference(
    cases: List[ValidationCase],
    pipeline_factory=None,
) -> Dict[str, Any]:
    """Run the existing pipeline and slice out one record per corpus case.

    ``pipeline_factory`` exists so tests can supply a pipeline instance. It
    defaults to the real :class:`~framework.pipeline.SATSAPipeline`, which is
    the point: the reference output has to come from the real thing.
    """

    if pipeline_factory is None:
        from framework.pipeline import SATSAPipeline

        pipeline_factory = SATSAPipeline

    by_dataset: Dict[str, Dict[str, Any]] = {}

    for case in cases:

        dataset = case.dataset

        if dataset not in by_dataset:

            pipeline = pipeline_factory()

            # The pipeline prints progress to stdout. That noise is not part of
            # the artefact, so it is suppressed here.
            with contextlib.redirect_stdout(io.StringIO()):
                by_dataset[dataset] = pipeline.run(dataset_path(dataset))

    records: List[Dict[str, Any]] = []

    for case in cases:

        result = by_dataset[case.dataset]

        record: Dict[str, Any] = {
            "case_id": case.case_id,
            "assessment_id": case.assessment_id,
            "dataset": case.dataset,
        }

        for family, key in FAMILY_RESULT_KEYS.items():

            scope = _scope_block(result.get(key), case.assessment_id)

            record[f"sat_sa_{family}_findings"] = list(
                (scope or {}).get("findings") or ()
            )

        # Pattern states are read from the existing operational-pattern scope
        # payload rather than recomputed, because NOT_EVALUABLE accounting has
        # to reflect what the layer actually reported.
        op_scope = _scope_block(
            result.get(FAMILY_RESULT_KEYS["operational_pattern"]),
            case.assessment_id,
        )

        record["sat_sa_operational_pattern_states"] = list(
            (op_scope or {}).get("pattern_states") or ()
        )

        ns_scope = _scope_block(
            result.get(FAMILY_RESULT_KEYS["negative_space"]),
            case.assessment_id,
        )

        record["sat_sa_absence_state_counts"] = dict(
            (ns_scope or {}).get("absence_state_counts") or {}
        )

        cap_scope = None

        for entry in (result.get("capability_assessment") or {}).get("scopes") or ():
            if entry.get("assessment_id") == case.assessment_id:
                cap_scope = entry
                break

        record["sat_sa_record_count"] = (cap_scope or {}).get("record_count")

        records.append(record)

    mapping_observations = _mapping_observations(by_dataset)
    unmapped_observations = unmapped_concept_observations(by_dataset)

    return {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "artefact": "SAT_SA_REFERENCE_OUTPUT",
        "generated_by": "framework.validation.reference",
        "note": [
            "Machine generated from the existing SAT-SA pipeline result.",
            "Every field below is a verbatim slice of an existing result key.",
            "No existing result schema was modified to produce this artefact.",
            "This file is produced only after the human review is locked.",
        ],
        "datasets": sorted(by_dataset),
        "concept_collisions": mapping_observations,
        "concepts_absent_from_semantic_mapping": unmapped_observations,
        "case_count": len(records),
        "records": records,
    }


def _mapping_observations(
    by_dataset: Mapping[str, Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Report concepts fed by more than one source column, per dataset.

    A collision means a finding's evidence for that concept could have been read
    from either column. Surfacing it is part of judging whether evidence is
    trustworthy, and it is derived from the system's own mapping.
    """

    from framework.validation.evidence import find_concept_collisions

    observations = []

    for dataset in sorted(by_dataset):

        collisions = find_concept_collisions(
            by_dataset[dataset].get("semantic_mapping") or ()
        )

        if not collisions:
            continue

        observations.append(
            {
                "dataset": dataset,
                "collisions": {
                    concept: sorted(columns)
                    for concept, columns in sorted(collisions.items())
                },
                "note": "more than one source column feeds this canonical "
                "concept, so a finding's evidence value for it is ambiguous "
                "unless the columns agree",
            }
        )

    return observations


def unmapped_concept_observations(by_dataset: Mapping[str, Any]) -> List[Any]:
    """Concepts a finding relies on that the published mapping never declares.

    A finding can cite a canonical concept the semantic mapping does not
    mention, which leaves the reader unable to tell which submitted column the
    evidence came from. That is a traceability gap in the system's own
    reporting, so it is recorded next to the collisions rather than absorbed by
    the validator's column-name fallback.
    """

    from framework.validation.corpus import dataset_path
    from framework.validation.evidence import (
        read_rows,
        unmapped_concepts,
    )
    from framework.validation.normalize import normalise_result

    observations = []

    for dataset in sorted(by_dataset):

        result = by_dataset[dataset]
        signals = normalise_result(result)

        if not signals:
            continue

        try:
            columns = list(read_rows(dataset)[0])
        except (IndexError, OSError):
            columns = []

        missing = unmapped_concepts(
            result.get("semantic_mapping") or (), signals, columns
        )

        if not missing:
            continue

        observations.append(
            {
                "dataset": dataset,
                "concepts_not_in_semantic_mapping": sorted(missing),
                "note": "findings cite these canonical concepts and the "
                "submitted data contains a matching column, but the pipeline's "
                "semantic mapping does not declare it, so their evidence "
                "cannot be traced through the mapping alone",
            }
        )

    return observations


def semantic_mapping_for(
    cases: List[ValidationCase], dataset: str
) -> List[Mapping[str, Any]]:
    """The semantic mapping the system produced for one dataset."""

    from framework.pipeline import SATSAPipeline

    with contextlib.redirect_stdout(io.StringIO()):
        result = SATSAPipeline().run(dataset_path(dataset))

    return result.get("semantic_mapping") or []


def write_reference(reference: Dict[str, Any], path: str) -> str:
    import json

    directory = os.path.dirname(os.path.abspath(path))

    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(reference, handle, indent=2, sort_keys=True)
        handle.write("\n")

    return path


def reference_by_case(reference: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {
        record["case_id"]: record for record in reference.get("records", ())
    }


def build_default_reference() -> Dict[str, Any]:
    """Reference output for the whole shipped corpus."""

    return build_reference(load_corpus())
