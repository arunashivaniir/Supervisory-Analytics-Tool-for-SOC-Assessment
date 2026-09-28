"""Explicit training path for the offline anomaly model.

Run it with::

    python -m framework.ml.anomaly.train

What it does, in order
----------------------
1. Generates the configured reference population and writes it to disk so the
   training data is inspectable rather than an in-memory surprise.
2. Sends it through SAT-SA's own ingestion, semantic mapping and scope builder.
3. Builds one feature vector per assessment scope.
4. Validates the whole matrix before fitting anything.
5. Fits the Isolation Forest and saves the artifact plus its metadata.

Nothing here is repaired silently. If a reference scope is missing required
evidence, carries a non-finite value, is in the wrong feature order, or the
population is smaller than the configured minimum, training stops and says so.

The reference corpus is labelled ``SYNTHETIC_REFERENCE_FOR_DEMONSTRATION`` in
configuration and the label is copied into the model metadata, so a later reader
cannot mistake generated data for observed history.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from framework.ml.anomaly.corpus import (
    CorpusGenerator,
    build_evidence_projections,
    build_scopes_from_records,
)
from framework.ml.anomaly.feature_builder import AnomalyModelConfig
from framework.ml.anomaly.isolation_forest_detector import (
    IsolationForestAnomalyDetector,
)


DEFAULT_REFERENCE_PATH = os.path.join(
    "data", "generated", "anomaly_reference_synthetic.csv"
)

DEFAULT_CONTROLLED_DIRECTORY = os.path.join(
    "data", "generated", "anomaly_controlled"
)

DEFAULT_GRID_DIRECTORY = os.path.join(
    "data", "generated", "anomaly_scope_isolation"
)


def renamed_columns(config: AnomalyModelConfig) -> Dict[str, str]:
    """The renamed-column map, read from configuration.

    The alternative was to hold it here, but this script is executable code in
    the anomaly layer and the layer's rule is that no code in it names a source
    column. Configuration is where a deployment's own column names belong
    anyway, so the map is read rather than declared.
    """

    declared = (config.raw.get("renamed_corpus") or {}).get("columns") or {}

    if not declared:
        raise SystemExit(
            "anomaly_model.json must declare renamed_corpus.columns to write "
            "the renamed demonstration corpora."
        )

    return {
        key: str(value)
        for key, value in declared.items()
        if not key.startswith("_")
    }


def build_reference_vectors(
    generator: CorpusGenerator,
    config: AnomalyModelConfig,
    reference_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate, persist and featurise the reference population."""

    corpus = generator.generate_reference()[0]

    if reference_path:
        generator.write_csv(corpus["records"], reference_path)

    collection, profile, semantic_results = build_scopes_from_records(
        corpus["records"],
        "synthetic_reference_for_demonstration",
        config,
    )

    projections = build_evidence_projections(
        collection, profile, semantic_results
    )

    return {
        "corpus": corpus,
        "projections": projections,
        "reference_path": reference_path,
    }


def vectors_from_projections(
    detector: IsolationForestAnomalyDetector,
    projections: Sequence[Any],
) -> List[Any]:
    """One feature vector per scope, in scope order."""

    return [
        detector.builder.build(
            concept_values,
            assessment_id=scope.assessment_id,
            entity=scope.entity.to_dict(),
            period=scope.period.to_dict(),
        )
        for scope, concept_values in projections
    ]


def write_controlled_corpora(
    generator: CorpusGenerator,
    directory: str = DEFAULT_CONTROLLED_DIRECTORY,
    renamed_columns: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Write each controlled profile, and its renamed equivalent, to disk.

    The renamed set is produced by the same generator with a different
    ``corpus_schema.columns`` map, so any difference in the resulting feature
    vector would have to come from semantic mapping rather than from the ML
    layer. That is the generalisation claim, tested rather than asserted.
    """

    os.makedirs(directory, exist_ok=True)

    written: List[str] = []

    for corpus in generator.generate_controlled():

        written.append(
            generator.write_csv(
                corpus["records"],
                os.path.join(directory, f"{corpus['profile_id']}.csv"),
            )
        )

        if renamed_columns:

            renamed = generator.renamed(renamed_columns)

            written.append(
                renamed.write_csv(
                    corpus["records"],
                    os.path.join(
                        directory, f"{corpus['profile_id']}_renamed.csv"
                    ),
                )
            )

    return written



def write_scope_isolation_corpora(
    generator: CorpusGenerator,
    directory: str = DEFAULT_GRID_DIRECTORY,
) -> List[str]:
    """Write every cell of the scope-isolation grid to its own file.

    One file per cell, so the property under test can be demonstrated rather
    than argued: a cell evaluated on its own must produce the same feature
    vector as the same cell evaluated inside the whole grid. If anything pooled
    scopes, the two would disagree.
    """

    os.makedirs(directory, exist_ok=True)

    written: List[str] = []

    for corpus in generator.generate_scope_isolation_grid():

        written.append(
            generator.write_csv(
                corpus["records"],
                os.path.join(directory, f"{corpus['profile_id']}.csv"),
            )
        )

    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Train the offline Isolation Forest anomaly model over the "
            "configured synthetic reference population."
        )
    )

    parser.add_argument(
        "--config",
        default="framework/config/anomaly_model.json",
        help="path to the anomaly model configuration",
    )
    parser.add_argument(
        "--reference-path",
        default=DEFAULT_REFERENCE_PATH,
        help="where to write the generated reference corpus",
    )
    parser.add_argument(
        "--controlled-directory",
        default=DEFAULT_CONTROLLED_DIRECTORY,
        help="where to write the controlled inference corpora",
    )
    parser.add_argument(
        "--grid-directory",
        default=DEFAULT_GRID_DIRECTORY,
        help="where to write the scope-isolation grid corpora",
    )
    parser.add_argument(
        "--skip-controlled",
        action="store_true",
        help="train without writing the demonstration corpora",
    )

    arguments = parser.parse_args(argv)

    config = AnomalyModelConfig.load(arguments.config)

    print("[+] Reading anomaly model configuration")
    print(f"    feature schema version : {config.feature_schema_version}")
    print(f"    schema fingerprint     : {config.schema_fingerprint[:16]}")
    print(f"    features               : {len(config.features)}")

    generator = CorpusGenerator(config)

    print("[+] Generating synthetic reference population")
    prepared = build_reference_vectors(
        generator, config, arguments.reference_path
    )

    print(
        f"    {len(prepared['corpus']['scopes'])} reference scopes, "
        f"{len(prepared['corpus']['records'])} records"
    )
    print(
        "    label: "
        f"{config.reference_corpus.get('label')} "
        "(generated, not a real-world baseline, not ground truth)"
    )

    if arguments.reference_path:
        print(f"    written to             : {arguments.reference_path}")

    detector = IsolationForestAnomalyDetector(config)

    print("[+] Building feature vectors")
    vectors = vectors_from_projections(
        detector, prepared["projections"]
    )

    unusable = [
        (vector.assessment_id, [f.feature_id for f in vector.unavailable])
        for vector in vectors
        if not vector.available
    ]

    if unusable:

        for assessment_id, missing in unusable[:10]:
            print(f"    {assessment_id}: missing {missing}")

        raise SystemExit(
            f"{len(unusable)} reference scope(s) lack required feature "
            f"evidence. Refusing to train on a partly imputed matrix."
        )

    print(f"    {len(vectors)} complete feature vectors")

    print("[+] Training Isolation Forest")
    metadata = detector.train(
        vectors,
        training_dataset_id=str(
            config.reference_corpus.get("label", "reference")
        ),
    )

    print(f"    model version          : {metadata['model_version']}")
    print(f"    training scopes        : {metadata['training_scope_count']}")
    print(f"    training timestamp     : {metadata['training_timestamp']}")
    print(f"    random state           : {metadata['random_state']}")
    print(f"    artifact sha256        : {metadata['artifact_sha256']}")
    print(f"    artifact               : {metadata['artifact_path']}")

    if not arguments.skip_controlled:

        print("[+] Writing controlled inference corpora")
        written = write_controlled_corpora(
            generator,
            arguments.controlled_directory,
            renamed_columns(config),
        )
        print(f"    {len(written)} files under {arguments.controlled_directory}")

        print("[+] Writing scope-isolation grid corpora")
        grid = write_scope_isolation_corpora(
            generator, arguments.grid_directory
        )
        print(f"    {len(grid)} files under {arguments.grid_directory}")

    print("[+] Done")

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point

    raise SystemExit(main())
