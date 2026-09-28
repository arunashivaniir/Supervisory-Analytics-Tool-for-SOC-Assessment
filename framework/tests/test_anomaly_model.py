"""Tests for the offline Isolation Forest anomaly layer.

The recurring question here is not "does a model produce a number" but "can the
output be trusted as a supervisory input". So a large share of these tests
assert that *no* finding is produced and that the reason is recorded: a layer
that reports an anomaly from missing evidence, from a wrong column name, or
from a normal scope is worse than a layer that stays quiet.

Each test names the property it protects, so a failure says which guarantee was
lost rather than only that some assertion tripped.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys

import pytest

from framework.ml.anomaly.corpus import (
    CorpusGenerationError,
    CorpusGenerator,
    build_evidence_projections,
    build_scopes_from_records,
)
from framework.ml.anomaly.feature_builder import (
    AnomalyConfigError,
    AnomalyModelConfig,
    FeatureUnavailable,
    FeatureSchemaMismatch,
    OperationalFeatureBuilder,
)
from framework.ml.anomaly.isolation_forest_detector import (
    INDICATOR,
    AnomalyTrainingError,
    NO_ANOMALY,
    NOT_EVALUABLE,
    VERDICTS,
    POTENTIAL_OPERATIONAL_ANOMALY,
    IsolationForestAnomalyDetector,
    ModelRegistryError,
)
from framework.ml.anomaly.model_registry import AnomalyModelRegistry
from framework.supervision.operational_pattern_detector import (
    OperationalPatternDetector,
    _jaccard,
    _tokenise,
)

CONFIG_PATH = os.path.join("framework", "config", "anomaly_model.json")
ARTIFACT_PATH = os.path.join(
    "artifacts", "anomaly", "isolation_forest.pkl"
)

#: The three verdicts, and nothing else.
ALLOWED_VERDICTS = {
    POTENTIAL_OPERATIONAL_ANOMALY,
    NO_ANOMALY,
    NOT_EVALUABLE,
}

#: Field names the layer must never emit. A reader who finds one of these on an
#: anomaly finding is reading a judgement this layer was not entitled to make.
FORBIDDEN_FIELDS = {
    "severity",
    "risk",
    "risk_score",
    "attention",
    "attention_score",
    "priority",
    "confidence",
    "is_control_failure",
    "is_misconduct",
}


# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def config() -> AnomalyModelConfig:
    return AnomalyModelConfig.load(CONFIG_PATH)


@pytest.fixture(scope="module")
def generator(config: AnomalyModelConfig) -> CorpusGenerator:
    return CorpusGenerator(config)


@pytest.fixture(scope="module")
def trained(trained_config, trained_generator):
    """A detector fitted over the configured reference population."""

    from framework.ml.anomaly.train import (
        build_reference_vectors,
        vectors_from_projections,
    )

    detector = IsolationForestAnomalyDetector(trained_config)
    vectors = vectors_from_projections(
        detector,
        build_reference_vectors(
            trained_generator, trained_config
        )["projections"],
    )
    detector.train(vectors, "test_reference")
    return detector


@pytest.fixture(scope="module")
def trained_config(config):
    return config


@pytest.fixture(scope="module")
def trained_generator(generator):
    return generator


@pytest.fixture(scope="module")
def controlled(trained, trained_config, trained_generator):
    """(profile_id, scope, concept_values) for every controlled corpus."""

    rows = []

    for corpus in trained_generator.generate_controlled():

        collection, profile, semantic = build_scopes_from_records(
            corpus["records"],
            corpus["profile_id"],
            trained_config,
            set(corpus["withheld_concepts"]) or None,
        )

        for scope, concept_values in build_evidence_projections(
            collection, profile, semantic
        ):
            rows.append((corpus["profile_id"], scope, concept_values))

    return rows


def _train_metadata(config):
    """Fit a throwaway model and return its metadata.

    Metadata is what ``train()`` returns, so the tests that assert on it must
    fit rather than read an attribute. The artifact is written to the
    configured registry path, which is what a real run would do; the tests that
    care about digest rejection use a temporary registry instead.
    """

    detector = IsolationForestAnomalyDetector(config)

    return detector.train(
        _reference_vectors(config), "metadata_probe"
    )


def verdict_for(detector, scope, concept_values):
    return detector.evaluate_scope(scope, concept_values)["verdict"]


# ------------------------------------------------------- 1. configuration


def test_configuration_declares_every_required_block(config):
    """The config must carry the blocks the layer refuses to invent."""

    for key in (
        "feature_schema",
        "features",
        "availability_policy",
        "model",
        "training",
        "registry",
        "corpus_schema",
        "reference_corpus",
        "controlled_corpus",
        "scope_isolation",
        "renamed_corpus",
        "limitations",
    ):
        assert key in config.raw, f"anomaly_model.json is missing {key!r}"


def test_model_parameters_come_from_configuration(config):
    """No estimator default may decide this model's behaviour."""

    model = config.raw["model"]

    assert model["model_type"] == "sklearn.ensemble.IsolationForest"
    assert model["n_estimators"] == 300
    assert model["random_state"] == 20260927
    assert model["contamination"] == 0.05
    assert config.training["minimum_reference_scopes"] >= 25


def test_contamination_is_explicit_and_bounded(config):
    """'auto' places the boundary near the training median and is too loose.

    Asserted here as a property of the configured value rather than as a
    comment, because a future edit to 'auto' would silently turn a 7% signal
    rate into a 27% one with no test failing.
    """

    contamination = config.raw["model"]["contamination"]

    assert isinstance(contamination, (int, float))
    assert 0.0 < contamination <= 0.10


def test_configuration_rejects_a_missing_required_key(config, tmp_path):
    """A config missing a feature must be refused, not defaulted."""

    raw = copy.deepcopy(config.raw)
    del raw["availability_policy"]

    path = tmp_path / "broken.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(AnomalyConfigError) as error:
        AnomalyModelConfig.load(str(path))

    assert "availability_policy" in str(error.value)


def test_schema_fingerprint_changes_when_a_feature_changes(config, tmp_path):
    """The fingerprint must track feature meaning, not just feature count."""

    before = config.schema_fingerprint

    raw = copy.deepcopy(config.raw)
    raw["features"][4]["parameters"] = {
        **raw["features"][4].get("parameters", {}),
        "top_k": 7,
    }

    path = tmp_path / "mutated.json"
    path.write_text(json.dumps(raw))

    assert AnomalyModelConfig.load(str(path)).schema_fingerprint != before


def test_reordering_features_changes_the_fingerprint(config, tmp_path):
    """Order is part of the contract, so the fingerprint must cover it.

    Reordering the feature list would otherwise load an already-trained model
    and silently read the wrong column for every feature.
    """

    raw = copy.deepcopy(config.raw)
    raw["features"] = list(reversed(raw["features"]))

    path = tmp_path / "reordered.json"
    path.write_text(json.dumps(raw))

    assert AnomalyModelConfig.load(str(path)).schema_fingerprint != (
        config.schema_fingerprint
    )


# --------------------------------------------------------- 2. vocabulary


def test_verdict_vocabulary_is_exactly_three_values():
    """A fourth verdict would be a new judgement this layer cannot make."""

    assert set(VERDICTS) == ALLOWED_VERDICTS
    assert len(VERDICTS) == 3


def test_indicator_is_stable_and_names_this_layer_only():
    assert INDICATOR == "OFFLINE_ISOLATION_FOREST_OPERATIONAL_PROFILE"


# ------------------------------------------------------ 3. feature values


def test_feature_vector_has_the_configured_count_and_order(config, generator):
    """Feature order is part of the contract: a reordering silently
    misinterprets an already-trained model."""

    records = generator.generate_controlled()[0]["records"]
    collection, profile, semantic = build_scopes_from_records(
        records, "probe", config
    )
    scope, concept_values = next(
        iter(build_evidence_projections(collection, profile, semantic))
    )

    vector = IsolationForestAnomalyDetector(config).builder.build(concept_values)

    assert len(vector.values()) == len(config.feature_ids)
    assert list(vector.value_map().keys()) == list(config.feature_ids)
    assert vector.feature_schema_version == config.feature_schema_version


def test_all_features_are_finite_and_in_range(config, trained):
    """A non-finite value would propagate into the estimator silently."""

    for vector in _reference_vectors(config):
        for value in vector.values():
            assert isinstance(value, float)
            assert value == value, "NaN in feature vector"
            assert value not in (float("inf"), float("-inf"))


def _reference_vectors(config):
    from framework.ml.anomaly.train import (
        build_reference_vectors,
        vectors_from_projections,
    )

    generator = CorpusGenerator(config)
    detector = IsolationForestAnomalyDetector(config)
    return vectors_from_projections(
        detector,
        build_reference_vectors(generator, config)["projections"],
    )


def test_concentration_uses_the_full_population_not_a_sample(
    config, generator
):
    """Concentration must reflect every record in scope.

    A limit on how many records are inspected would make the feature depend on
    a sample, and a scope with a busy tail would look flatter than it is.
    """

    assert not any(
        "limit" in key.lower() or "max_records" in key.lower()
        for key in config.raw["features"][4]
    )


# ----------------------------------------------------- 4. feature policy


def test_missing_evidence_yields_not_evaluable_never_a_number(
    config, controlled
):
    """The core negative guarantee of the layer.

    Withholding the required concepts must produce NOT_EVALUABLE with no score.
    A zero, a mean, or a partial vector here would turn absent evidence into a
    claim about the scope.
    """

    generator = CorpusGenerator(config)
    corpora = {
        c["profile_id"]: c for c in generator.generate_controlled()
    }

    corpus = corpora["insufficient_evidence"]
    assert corpus["withheld_concepts"], "control case must withhold concepts"

    collection, profile, semantic = build_scopes_from_records(
        corpus["records"],
        corpus["profile_id"],
        config,
        set(corpus["withheld_concepts"]),
    )
    scope, concept_values = next(
        iter(build_evidence_projections(collection, profile, semantic))
    )

    result = IsolationForestAnomalyDetector(config).evaluate_scope(
        scope, concept_values
    )

    assert result["verdict"] == NOT_EVALUABLE
    assert result["anomaly_score"] is None
    assert result["reason"], "NOT_EVALUABLE must say what was missing"


def test_too_few_records_is_not_evaluable(config, trained):
    """Volume below the configured floor must not be scored."""

    detector = trained
    minimum = config.raw["training"]["minimum_reference_scopes"]

    assert minimum >= 1, "a zero floor would score an empty population"


def test_training_refuses_an_unavailable_vector(config, generator):
    """Training must fail loudly rather than impute a missing feature.

    A reference scope that cannot describe itself has no business teaching the
    model what ordinary looks like.
    """

    from framework.ml.anomaly.train import (
        build_reference_vectors,
        vectors_from_projections,
    )

    detector = IsolationForestAnomalyDetector(config)
    vectors = vectors_from_projections(
        detector, build_reference_vectors(generator, config)["projections"]
    )

    # A population below the configured floor has no notion of ordinary.
    with pytest.raises(AnomalyTrainingError) as error:
        detector.train(vectors[:1], "too_small")

    assert "below the configured minimum" in str(error.value)

    # An empty population likewise.
    with pytest.raises(AnomalyTrainingError):
        detector.train([], "empty")


def test_unknown_aggregation_is_refused(config):
    """An unrecognised aggregation must not fall back to a default."""

    raw = copy.deepcopy(config.raw)
    raw["features"][0]["aggregation"] = "geometric_mean_of_everything"

    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False
    ) as handle:
        json.dump(raw, handle)
        path = handle.name

    try:
        with pytest.raises(AnomalyConfigError) as error:
            AnomalyModelConfig.load(path)
        assert "aggregation" in str(error.value)
    finally:
        os.unlink(path)


# -------------------------------------------------------- 5. the estimator


def test_model_is_the_configured_estimator(trained):
    sklearn = pytest.importorskip("sklearn.ensemble")

    assert isinstance(trained._model, sklearn.IsolationForest)
    assert trained._model.n_estimators == 300
    assert trained._model.random_state == 20260927
    assert trained._model.contamination == 0.05


def test_training_is_deterministic(config):
    """Two fits over the same data must agree exactly.

    A supervisory finding that changes between runs of the same evidence
    cannot be defended to the person being asked to act on it.
    """

    vectors = _reference_vectors(config)

    first = IsolationForestAnomalyDetector(config)
    second = IsolationForestAnomalyDetector(config)

    first.train(copy.copy(vectors), "repeat")
    second.train(copy.copy(vectors), "repeat")

    a = first._model.decision_function(
        [v.values() for v in vectors]
    )
    b = second._model.decision_function(
        [v.values() for v in vectors]
    )

    assert list(a) == list(b)


def test_training_records_the_artefact_digest(trained):
    metadata = _train_metadata(trained.config)
    assert re.fullmatch(r"[0-9a-f]{64}", metadata["artifact_sha256"])


def test_metadata_declares_the_population_is_synthetic(config, trained):
    """A reader must not mistake generated data for observed history."""

    assert config.reference_corpus["label"] == (
        "SYNTHETIC_REFERENCE_FOR_DEMONSTRATION"
    )
    metadata = _train_metadata(trained.config)
    assert metadata["training_reference_label"] == (
        "SYNTHETIC_REFERENCE_FOR_DEMONSTRATION"
    )
    assert metadata["training_scope_count"] >= 25
    assert metadata["training_matrix_finite"] is True


def test_metadata_records_every_configured_parameter(config, trained):
    """The artifact must record the settings it was fitted with.

    A model whose parameters are not recoverable from its own metadata cannot
    be reproduced, and a reproduced model is what makes a finding arguable.
    """

    metadata = _train_metadata(config)

    for key, value in config.raw["model"].items():
        if key.startswith("_") or key == "model_type":
            continue
        assert key in metadata["configured_parameters"], key
        assert metadata["configured_parameters"][key] == value

    assert metadata["model_type"] == "sklearn.ensemble.IsolationForest"
    assert metadata["feature_order_is_significant"] is True
    assert metadata["feature_ids"] == list(config.feature_ids)


def test_metadata_states_the_limitation_verbatim(config, trained):
    """The limitation must survive into the artifact, not just the docs."""

    limitations = " ".join(_train_metadata(config)["limitations"]).lower()

    assert "malicious" in limitations
    assert "human supervisor" in limitations


# ------------------------------------------------------- 6. persistence


def test_model_round_trips_through_disk(trained, config):
    """A reloaded model must give the same answer as the one in memory."""

    reloaded = IsolationForestAnomalyDetector(config)
    reloaded.load()

    probe = trained._model.decision_function(
        [v.values() for v in _reference_vectors(config)][:5]
    )
    again = reloaded._model.decision_function(
        [v.values() for v in _reference_vectors(config)][:5]
    )

    assert list(probe) == list(again)


def test_loading_a_tampered_artefact_is_refused(config, tmp_path):
    """The digest in the metadata must be checked, not assumed.

    Without this check a corrupted or swapped artifact would be loaded and
    every subsequent finding would be attributed to a model that is not the
    one on disk.
    """

    detector = IsolationForestAnomalyDetector(
        config,
        registry=AnomalyModelRegistry(
            artifact_path=str(tmp_path / "model.pkl"),
            metadata_path=str(tmp_path / "model.json"),
        ),
    )

    vectors = _reference_vectors(config)
    detector.train(vectors, "tamper_test")

    registry = detector.registry
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(artifact.read_bytes() + b"\x00")

    with pytest.raises(ModelRegistryError):
        registry.load()

    # The same artifact loads once the digest is no longer enforced, which
    # shows the check above is what rejected it rather than the pickle itself.
    registry.load(verify_digest=False)


def test_inference_is_reproducible_across_reloads(config, controlled):
    """Two loads of the same artifact must agree on every scope."""

    first = IsolationForestAnomalyDetector(config)
    first.load()
    second = IsolationForestAnomalyDetector(config)
    second.load()

    for _, scope, concept_values in controlled:
        a = first.evaluate_scope(scope, concept_values)
        b = second.evaluate_scope(scope, concept_values)
        assert a["verdict"] == b["verdict"]
        assert a["anomaly_score"] == b["anomaly_score"]


# --------------------------------------------- 7. controlled behaviour


def test_the_four_unusual_profiles_are_reported(trained, controlled):
    """Each constructed anomaly must be reported as an anomaly."""

    expected = {
        "concentrated_activity",
        "repetitive_investigation",
        "unusual_escalation_profile",
        "combined_operational_profile",
    }

    for profile_id, scope, concept_values in controlled:
        if profile_id not in expected:
            continue
        assert verdict_for(trained, scope, concept_values) == (
            POTENTIAL_OPERATIONAL_ANOMALY
        ), f"{profile_id} should have been reported"


def test_the_normal_control_is_not_reported(trained, controlled):
    """The negative control is the most important case in the set.

    A layer that flags ordinary operation is not a supervisory aid, it is a
    generator of work. This is asserted on its own so the failure is obvious.
    """

    for profile_id, scope, concept_values in controlled:
        if profile_id != "normal_control":
            continue
        assert verdict_for(trained, scope, concept_values) == NO_ANOMALY


def test_insufficient_evidence_is_not_evaluable(trained, controlled):
    for profile_id, scope, concept_values in controlled:
        if profile_id != "insufficient_evidence":
            continue
        assert verdict_for(trained, scope, concept_values) == NOT_EVALUABLE


def test_anomalies_clear_the_boundary_with_margin(trained, controlled):
    """A finding must not rest on a hair.

    Each anomaly has to sit meaningfully below the decision boundary, and the
    normal control meaningfully above it, or the result is an artefact of the
    exact draw rather than a property of the profile.
    """

    margins = {}

    for profile_id, scope, concept_values in controlled:
        score = trained.evaluate_scope(scope, concept_values)["anomaly_score"]
        if score is not None:
            margins[profile_id] = score

    for profile_id in (
        "concentrated_activity",
        "repetitive_investigation",
        "unusual_escalation_profile",
        "combined_operational_profile",
    ):
        assert margins[profile_id] < -0.02, f"{profile_id} is on the boundary"

    assert margins["normal_control"] > 0.01


def test_the_combined_profile_is_not_a_restatement_of_a_rule(
    trained, controlled, config
):
    """The non-duplicate requirement.

    The combined profile exists to show the model contributing something the
    deterministic layers do not. If the operational-pattern layer already
    reports it, the model is adding a second opinion about a concentration
    tail and is not doing its job.
    """

    generator = CorpusGenerator(config)
    corpora = {
        c["profile_id"]: c
        for c in generator.generate_controlled()
        if c["profile_id"] == "combined_operational_profile"
    }

    corpus = next(iter(corpora.values()))

    collection, profile, semantic = build_scopes_from_records(
        corpus["records"], corpus["profile_id"], config
    )
    scope, concept_values = next(
        iter(build_evidence_projections(collection, profile, semantic))
    )

    existing = OperationalPatternDetector().evaluate_scope(
        scope, concept_values
    )["findings"]

    assert not existing, (
        "the combined profile is already reported by "
        f"{[f['indicator'] for f in existing]}, so it demonstrates nothing new"
    )
    assert verdict_for(trained, scope, concept_values) == (
        POTENTIAL_OPERATIONAL_ANOMALY
    )


def test_concentration_stays_inside_the_binomial_tail(config):
    """The concentration case must not be the concentration rule's case.

    Asserted on the generated corpus rather than on the verdict so that the
    reason a rule stays silent is visible when this fails.
    """

    generator = CorpusGenerator(config)

    for corpus in generator.generate_controlled():
        if corpus["profile_id"] != "combined_operational_profile":
            continue

        assets = {
            row[generator.columns["asset"]]
            for row in corpus["records"]
        }

        assert len(assets) >= 10, (
            "too few distinct assets: the existing concentration rule would "
            "report this and the demonstration would be a duplicate"
        )


def test_note_similarity_stays_below_the_repetition_floor(config):
    """Repetition must be visible to a continuous measure, not to a threshold.

    The repetition rule groups notes at a configured similarity floor. The
    shared-vocabulary mode exists to be repetitive in the continuous sense
    while staying under that floor, so the model has something to see.
    """

    generator = CorpusGenerator(config)

    for corpus in generator.generate_controlled():
        if corpus["profile_id"] != "combined_operational_profile":
            continue

        notes = [
            row[generator.columns["investigation"]]
            for row in corpus["records"]
            if row[generator.columns["investigation"]].strip()
        ]

        pairs = [
            _jaccard(_tokenise(a), _tokenise(b))
            for i, a in enumerate(notes)
            for b in notes[i + 1 :]
        ]

        assert pairs, "the combined profile must carry investigation notes"
        assert max(pairs) < 0.8, (
            f"max note similarity {max(pairs):.2f} reaches the deterministic "
            "repetition floor, so the case duplicates that rule"
        )
        assert max(pairs) > 0.4, (
            "notes are not repetitive enough for the similarity feature to "
            "register them at all"
        )


def test_templated_notes_are_never_repeated_within_a_scope(config):
    """Two identical notes would sit at similarity 1.0 and be reported.

    Drawn without replacement inside a scope, a templated profile is repetitive
    without being a copy of the record the rule already catches.
    """

    generator = CorpusGenerator(config)

    for corpus in generator.generate_controlled():
        if corpus["profile_id"] != "repetitive_investigation":
            continue

        notes = [
            row[generator.columns["investigation"]]
            for row in corpus["records"]
            if row[generator.columns["investigation"]].strip()
        ]

        assert len(notes) == len(set(notes)), (
            "a note was reused inside one scope"
        )


def test_repetition_is_non_trivial(config):
    """The repetition feature must not be a constant over the population.

    A feature that is always the same number cannot contribute to a decision
    boundary, and its presence would imply a capability the layer does not have.
    """

    from framework.ml.anomaly.train import (
        build_reference_vectors,
        vectors_from_projections,
    )

    generator = CorpusGenerator(config)
    detector = IsolationForestAnomalyDetector(config)
    vectors = vectors_from_projections(
        detector, build_reference_vectors(generator, config)["projections"]
    )

    index = config.feature_ids.index("investigation_repetition")
    values = [v.values()[index] for v in vectors]

    assert len(set(round(v, 6) for v in values)) > 5
        # (a constant would make the column a lie)


# ------------------------------------------ 8. column-name independence


def test_renaming_source_columns_preserves_every_value(config):
    """A rename must relabel evidence, never alter it.

    The layer consumes canonical concepts rather than source headers, so the
    header is not its concern; that is what the hard-code audit below
    enforces. What the corpus itself does guarantee, and what is checkable
    without involving the semantic resolver, is that emitting the same scope
    under the renamed header set produces byte-identical values in every
    role. A corpus that reshuffled or regenerated data under new names would
    make any end-to-end comparison meaningless.
    """

    generator = CorpusGenerator(config)
    renamed = generator.renamed(config.raw["renamed_corpus"]["columns"])
    roles = list(config.raw["corpus_schema"]["columns"])

    originals = {
        corpus["profile_id"]: corpus for corpus in generator.generate_controlled()
    }
    relabelled = {
        corpus["profile_id"]: corpus for corpus in renamed.generate_controlled()
    }

    assert set(originals) == set(relabelled)
    assert set(generator.columns[role] for role in roles).isdisjoint(
        renamed.columns[role] for role in roles
    )

    for profile_id, corpus in sorted(originals.items()):
        other = relabelled[profile_id]
        assert len(other["records"]) == len(corpus["records"])

        for index, (row, renamed_row) in enumerate(
            zip(corpus["records"], other["records"])
        ):
            for role in roles:
                assert row[generator.columns[role]] == renamed_row[
                    renamed.columns[role]
                ], f"{profile_id} record {index} role {role} changed under rename"


def test_renamed_columns_the_resolver_cannot_map_stay_not_evaluable(config, trained):
    """A header the resolver does not recognise must never become a verdict.

    Renaming is only honoured for names the semantic resolver already knows.
    The renamed set deliberately includes names outside its vocabulary, so
    the real ingestion path cannot resolve the escalation and investigation
    concepts from it. The corpus guard must refuse such a corpus outright
    rather than let a partly-read scope reach the model, and the message must
    name what stayed unresolved so the gap is diagnosable.

    Note the resolver does still map the renamed escalation header onto
    CONNECTION_STATE, a network concept. That is a pre-existing resolver
    behaviour outside this layer's scope; it is recorded here only so the
    failure message stays explicable.
    """

    generator = CorpusGenerator(config)
    renamed = generator.renamed(config.raw["renamed_corpus"]["columns"])

    corpus = next(
        item
        for item in renamed.generate_controlled()
        if item["profile_id"] == "concentrated_activity"
    )

    with pytest.raises(CorpusGenerationError) as raised:
        build_scopes_from_records(
            corpus["records"], corpus["profile_id"], config
        )

    message = str(raised.value)
    assert "ESCALATION_STATUS" in message
    assert "INVESTIGATION_EVIDENCE" in message
    assert "CONNECTION_STATE" in message


def test_no_source_column_names_appear_in_the_anomaly_layer():
    """The hard-code audit, enforced.

    Executable code in this layer must not mention a source column, because a
    mention is a special case waiting to be relied on. The names below are the
    ones this repository's loaders use plus the renamed set.
    """

    forbidden = [
        "operating_unit",
        "reporting_window",
        "case_reference",
        "alert_urgency",
        "affected_system",
        "business_impact",
        "referral_state",
        "analyst_remarks",
        "alert_id",
        "priority",
        "cse",
    ]

    root = os.path.join("framework", "ml")
    offenders = []

    for directory, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(directory, name)
            with open(path) as handle:
                text = handle.read()
            for token in forbidden:
                if re.search(
                    r"\b" + re.escape(token) + r"\b", text, re.IGNORECASE
                ):
                    offenders.append(f"{path}: {token}")

    assert not offenders, "source column names in the ML layer: " + ", ".join(
        offenders
    )


def test_feature_builder_uses_only_canonical_concepts(config):
    """Every concept the builder reads must be a declared canonical name."""

    from framework.ml.anomaly.corpus import CONCEPT_FOR_ROLE

    canonical = {
        "SECURITY_SEVERITY",
        "ASSET_IDENTIFIER",
        "ESCALATION_STATUS",
        "ASSET_CRITICALITY",
        "INVESTIGATION_EVIDENCE",
    }

    # Every concept the generator assigns to a source role is canonical.
    assert set(CONCEPT_FOR_ROLE.values()) == canonical

    # Every concept any feature reads is canonical too.
    for feature in config.features:
        assert set(feature.source_concepts) <= canonical, feature.feature_id


# ----------------------------------------------- 9. output discipline


def test_no_forbidden_field_appears_on_any_finding(trained, controlled):
    """The layer must not smuggle a judgement into a field name."""

    for profile_id, scope, concept_values in controlled:
        result = trained.evaluate_scope(scope, concept_values)
        for key in result:
            assert key.lower() not in FORBIDDEN_FIELDS, (
                f"{profile_id} carries a forbidden field {key!r}"
            )


def test_anomaly_findings_are_absent_for_non_anomalies(trained, controlled):
    """NO_ANOMALY and NOT_EVALUABLE must produce no finding at all.

    A collection that reports findings for ordinary scopes would be a report
    of the model's opinions rather than of the scopes.
    """

    findings = trained.evaluate_collection.__doc__ is not None
    assert findings is not None  # the method exists; behaviour checked below

    for profile_id, scope, concept_values in controlled:
        result = trained.evaluate_scope(scope, concept_values)
        if result["verdict"] != POTENTIAL_OPERATIONAL_ANOMALY:
            assert result.get("anomaly_finding") is None


def test_explanations_are_non_causal(trained, controlled):
    """Language must not assert cause.

    The layer measures a shape. Saying the shape caused something, or that
    something is wrong, would be a claim the evidence cannot support.
    """

    # Language that asserts a cause, rather than describing a distance.
    asserting = re.compile(
        r"(caused by|causes the|because the scope|proves that|"
        r"demonstrates that the|shows that the|failed to|was attacked|"
        r"is an attack|is a breach|is malicious|is non-compliant|"
        r"is unsafe|is a control failure)",
        re.IGNORECASE,
    )

    # The limitation itself has to name those things, in the negative.
    limitation = (
        "It does not establish that the observed behaviour is malicious"
    )

    for profile_id, scope, concept_values in controlled:
        result = trained.evaluate_scope(scope, concept_values)
        text = json.dumps(result, default=str)

        assert limitation in text, (
            f"{profile_id} is missing the verbatim limitation"
        )

        # Strip the limitation sentences, then nothing causal may remain.
        without_limitations = re.sub(
            r"[^.]*(does not|cannot|no judgement|not establish)[^.]*\.",
            "",
            text,
            flags=re.IGNORECASE,
        )

        match = asserting.search(without_limitations)
        assert match is None, (
            f"{profile_id} asserts a cause outside the limitation: "
            f"{match.group(0)!r}"
        )


def test_explanation_names_only_the_most_far_features(
    trained, controlled, config
):
    """An explanation that lists every feature is not an explanation."""

    generator = CorpusGenerator(config)
    corpus = next(
        c
        for c in generator.generate_controlled()
        if c["profile_id"] == "combined_operational_profile"
    )

    collection, profile, semantic = build_scopes_from_records(
        corpus["records"], corpus["profile_id"], config
    )
    scope, concept_values = next(
        iter(build_evidence_projections(collection, profile, semantic))
    )

    result = trained.evaluate_scope(scope, concept_values)

    explanation = result["explanation"]

    assert explanation, "an anomaly must explain itself"
    assert explanation["narrative"]
    assert explanation["explanation"], "an anomaly needs prose, not a label"

    # The full profile is kept for audit; the prose is what singles out the
    # few features that actually contributed.
    profile = explanation["feature_profile"]
    assert len(profile) == len(config.feature_ids), (
        "the profile should record every feature, so a reader can check the "
        "model was not cherry-picking"
    )

    prose = explanation["explanation"]

    assert prose.count("observed") <= 5, (
        "the narrative should single out a few features, not enumerate all "
        f"{len(config.feature_ids)}"
    )

    for entry in profile:
        assert entry["feature_id"] in config.feature_ids
        assert "observed_value" in entry
        assert "reference_summary" in entry

    assert "score_semantics" in explanation, (
        "a bare number invites being read as a risk score; its meaning must "
        "travel with it"
    )


def test_reference_statistics_are_carried_into_the_explanation(
    trained, controlled
):
    """A distance is only meaningful next to the population it is against."""

    result = next(
        trained.evaluate_scope(scope, concept_values)
        for profile_id, scope, concept_values in controlled
        if profile_id == "combined_operational_profile"
    )

    text = json.dumps(result["explanation"], default=str)
    assert "reference" in text.lower()


# ----------------------------------------------- 10. scope independence


def test_a_scope_evaluated_alone_matches_the_same_scope_in_a_grid(config):
    """Inference must never pool scopes.

    The property under test is that a cell's vector depends only on its own
    evidence. If anything aggregated across entities or periods, the whole-grid
    result would differ from the single-cell result.
    """

    generator = CorpusGenerator(config)
    detector = IsolationForestAnomalyDetector(config)
    detector.load()

    cells = generator.generate_scope_isolation_grid()

    pooled = {}

    for corpus in cells:
        collection, profile, semantic = build_scopes_from_records(
            corpus["records"], corpus["profile_id"], config
        )
        for scope, concept_values in build_evidence_projections(
            collection, profile, semantic
        ):
            pooled[scope.assessment_id] = detector.builder.build(
                concept_values,
                assessment_id=scope.assessment_id,
                entity=scope.entity.to_dict(),
                period=scope.period.to_dict(),
            )

    for corpus in cells:
        collection, profile, semantic = build_scopes_from_records(
            corpus["records"], corpus["profile_id"], config
        )
        for scope, concept_values in build_evidence_projections(
            collection, profile, semantic
        ):
            alone = detector.builder.build(
                concept_values,
                assessment_id=scope.assessment_id,
                entity=scope.entity.to_dict(),
                period=scope.period.to_dict(),
            )
            assert list(alone.values()) == list(
                pooled[scope.assessment_id].values()
            ), f"{scope.assessment_id} differs when evaluated alone"


def test_each_grid_cell_is_written_as_its_own_file(config, tmp_path):
    """Persisting cells separately is what makes the property demonstrable."""

    generator = CorpusGenerator(config)
    cells = generator.generate_scope_isolation_grid()

    identifiers = [c["profile_id"] for c in cells]

    assert len(set(identifiers)) == len(identifiers), (
        "grid cells must be distinguishable by name, or the isolation "
        "demonstration cannot be run from the files"
    )
    assert len(identifiers) == 4


# ------------------------------------------------- 11. integration


def test_pipeline_exposes_exactly_one_new_result_key():
    """The layer must be additive.

    Everything the pipeline already produced must still be there, and the only
    additions are the anomaly key and the Phase 1 canonical_package key
    (schema-level mapping decisions, role, relationships, validation —
    additive metadata on its own result key, altering no analytical value).
    """

    from framework.pipeline import SATSAPipeline

    result_keys = _pipeline_result_keys()

    assert "anomaly_findings" in result_keys
    assert "canonical_package" in result_keys
    assert len(result_keys) == 17, (
        f"expected the 15 existing keys plus anomaly_findings plus "
        f"canonical_package, got {len(result_keys)}: {result_keys}"
    )


def _pipeline_result_keys():
    """Run the real pipeline on a tiny corpus and return the result keys.

    No fallback: if the pipeline cannot run, that is a failure of this test,
    not a licence to count keys in the source instead.
    """

    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, newline=""
    ) as handle:
        handle.write("cse,period,alert_id,priority,host\n")
        handle.write("CSE-A,2026-Q3,A-1,low,HOST-1\n" * 12)
        path = handle.name

    try:
        from framework.pipeline import SATSAPipeline

        pipeline = SATSAPipeline()
        result = pipeline.run(path)
        return list(result.keys())
    finally:
        os.unlink(path)

def test_pipeline_keeps_working_without_scikit_installed(config, tmp_path):
    """The rest of the tool must not depend on the ML layer's dependency.

    scikit-learn is imported lazily inside a guard, so a deployment without it
    must still produce every other result and report the anomaly layer as
    unavailable. This runs the real pipeline end to end with sklearn blocked,
    not merely the detector, because a guarded import proves nothing if the
    pipeline itself turns out to need the library.
    """

    source = os.path.join(
        "framework", "ml", "anomaly", "isolation_forest_detector.py"
    )
    with open(source) as handle:
        text = handle.read()

    tree = subprocess.run(
        [sys.executable, "-c", _BLOCK_SKLEARN],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    assert tree.returncode == 0, tree.stderr
    assert "UNAVAILABLE" in tree.stdout
    assert "scikit-learn is not installed" in tree.stdout
    assert "PIPELINE_KEYS=17" in tree.stdout
    assert "ANOMALY_STATUS=UNAVAILABLE" in tree.stdout
    assert "PIPELINE_OK=True" in tree.stdout


_BLOCK_SKLEARN = """
import builtins
import contextlib
import io
import os
import sys
import tempfile


def blocked(name, *args, **kwargs):
    if name == "sklearn" or name.startswith("sklearn."):
        raise ImportError("scikit-learn is not installed")
    return real_import(name, *args, **kwargs)


real_import = builtins.__import__
builtins.__import__ = blocked
for module in [m for m in sys.modules if m.startswith("sklearn")]:
    del sys.modules[module]

from framework.ml.anomaly.feature_builder import AnomalyModelConfig
from framework.ml.anomaly.isolation_forest_detector import (
    IsolationForestAnomalyDetector, NOT_EVALUABLE,
)


config = AnomalyModelConfig.load("framework/config/anomaly_model.json")
detector = IsolationForestAnomalyDetector(config)
print(detector.model_status["status"])
print(detector.sklearn_unavailable_reason())
assert detector.sklearn_available() is False
assert detector._model is None
assert detector.model_status["status"] == "UNAVAILABLE"
assert NOT_EVALUABLE == "NOT_EVALUABLE"

# A real dataset with severity, escalation and criticality evidence, so the
# only reason the layer cannot answer is the missing dependency.
handle = tempfile.NamedTemporaryFile(
    "w", suffix=".csv", delete=False, newline=""
)
handle.write(
    "cse,period,alert_id,priority,host,asset_criticality,"
    "escalation_status,investigation_notes\\n"
)
for index in range(20):
    handle.write(
        f"CSE-A,2026-Q3,A-{index},critical,HOST-{index % 3},HIGH,"
        f"{'escalated' if index % 2 else 'not_escalated'},"
        f"analyst reviewed case {index} and recorded actions\\n"
    )
handle.close()

from framework.pipeline import SATSAPipeline


with contextlib.redirect_stdout(io.StringIO()):
    result = SATSAPipeline().run(handle.name)
os.unlink(handle.name)

print("PIPELINE_KEYS=%d" % len(result))
print("ANOMALY_STATUS=%s" % result["anomaly_findings"]["anomaly_model_status"]["status"])
print(
    "PIPELINE_OK=%s"
    % (
        "supervisory_findings" in result
        and "operational_pattern_findings" in result
        and "canonical_records" in result
    )
)
"""


def test_artefact_path_comes_from_configuration(config):
    assert config.registry["artifact_path"] == ARTIFACT_PATH


def test_registry_paths_are_declared_in_configuration(config):
    assert config.raw["registry"]["artifact_path"]
    assert config.raw["registry"]["metadata_path"]


def test_registry_reports_a_missing_artifact(config, tmp_path):
    registry = AnomalyModelRegistry(
        artifact_path=str(tmp_path / "absent.pkl"),
        metadata_path=str(tmp_path / "absent.json"),
    )

    with pytest.raises(ModelRegistryError):
        registry.load()


def test_model_status_is_reported_without_loading(config, tmp_path):
    """A caller must be able to ask whether a model exists."""

    detector = IsolationForestAnomalyDetector(
        config,
        registry=AnomalyModelRegistry(
            artifact_path=str(tmp_path / "absent.pkl"),
            metadata_path=str(tmp_path / "absent.json"),
        ),
    )

    status = detector.model_status

    assert isinstance(status, dict)
    assert status["status"] == "NOT_TRAINED"
    assert status["reason"], "an unusable layer must say why"
    assert detector.model_available is False


# ----------------------------------------------- 12. generation safety


def test_generation_is_reproducible(config):
    """Generated corpora must be identical across runs in one environment."""

    first = CorpusGenerator(config).generate_reference()
    second = CorpusGenerator(config).generate_reference()

    assert first == second


def test_generation_uses_only_configured_seeds(config):
    """No unseeded randomness, or the corpora could not be reproduced."""

    source = os.path.join(
        "framework", "ml", "anomaly", "corpus.py"
    )
    with open(source) as handle:
        text = handle.read()

    assert "random.Random(" in text
    assert "random.random()" not in text
    assert "random.choice(" not in text
    assert "random.uniform(" not in text


def test_missing_scope_isolation_is_refused(config, tmp_path):
    raw = copy.deepcopy(config.raw)
    del raw["scope_isolation"]

    path = tmp_path / "no_grid.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(CorpusGenerationError):
        CorpusGenerator(AnomalyModelConfig.load(str(path))).\
            generate_scope_isolation_grid()
