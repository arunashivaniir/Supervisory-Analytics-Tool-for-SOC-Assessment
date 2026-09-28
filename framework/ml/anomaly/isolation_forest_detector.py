"""Offline Isolation Forest anomaly discovery for SAT-SA.

What this layer does
--------------------
Answers one question per ``AssessmentScope``: does this scope's operational
feature profile sit unusually far from a reference population, compared with how
that population's own scopes sit? The output is a verdict of
``POTENTIAL_OPERATIONAL_ANOMALY``, ``NO_ANOMALY`` or ``NOT_EVALUABLE``.

What it deliberately does not do
--------------------------------
It does not detect insecurity, establish a control failure, assign a severity,
produce a risk level or risk score, invent a confidence, or name a root cause.
The execution-gap layer is the only layer whose logic can establish a
contradicted expectation; this one cannot, and the finding structure contains
no field in which such a claim could be recorded.

The verdict comes from the estimator
-----------------------------------
``IsolationForest.predict`` decides the verdict. No threshold on any feature,
no conjunction of conditions, no comparison against a named entity, dataset or
period appears in this module. The gates that run *before* the model exist only
to refuse a judgement that cannot be made -- unavailable features, a
non-finite value, a schema mismatch -- and they produce ``NOT_EVALUABLE``,
never an anomaly.

The model cannot see a column name
----------------------------------
Features are built from ``EvidenceIndex`` concept projections, so a renamed
source column produces an identical vector. Nothing in this module branches on
a submitted value.

Optional dependency
-------------------
scikit-learn is imported lazily so the rest of SAT-SA, and its test suite, run
unchanged on a runtime where it is absent. When it is missing this layer
reports itself unavailable with the reason; it never fabricates a verdict.
"""

from __future__ import annotations

import datetime as _datetime
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.ml.anomaly.explanation import (
    AnomalyExplainer,
    summarise_distribution,
)
from framework.ml.anomaly.feature_builder import (
    AnomalyConfigError,
    AnomalyModelConfig,
    FeatureSchemaMismatch,
    FeatureUnavailable,
    FeatureVector,
    OperationalFeatureBuilder,
)
from framework.ml.anomaly.model_registry import (
    AnomalyModelRegistry,
    ModelRegistryError,
)
from framework.supervisory.rules.operational_pattern_rules import (
    NOT_EVALUABLE,
    POTENTIAL_OPERATIONAL_ANOMALY,
)


# Reused verbatim from the operational-pattern layer so the two layers cannot
# disagree about the spelling of a verdict. The operational-pattern layer has no
# "nothing found" state, so this layer declares its own.
NO_ANOMALY = "NO_ANOMALY"

VERDICTS = (
    POTENTIAL_OPERATIONAL_ANOMALY,
    NO_ANOMALY,
    NOT_EVALUABLE,
)

INDICATOR = "OFFLINE_ISOLATION_FOREST_OPERATIONAL_PROFILE"

REASON_ANOMALY = (
    "Operational feature profile differs substantially from the reference "
    "population."
)

REASON_NORMAL = (
    "Operational feature profile sits within the range typical of the "
    "reference population."
)

# Estimator parameters SAT-SA is willing to pass through from configuration.
# Anything else is a configuration error rather than a silently ignored key, so
# a typo in anomaly_model.json cannot leave the estimator at a default the
# operator believes they changed.
ALLOWED_MODEL_PARAMETERS = frozenset(
    {
        "random_state",
        "n_estimators",
        "max_samples",
        "contamination",
        "n_jobs",
    }
)


class AnomalyTrainingError(Exception):
    """The reference population cannot produce a trustworthy model.

    Raised rather than repaired: a silently patched training set is how a model
    ends up scoring scopes on invented values.
    """


class IsolationForestAnomalyDetector:
    """Trains and applies the offline anomaly model, one scope at a time."""

    def __init__(
        self,
        config: Optional[AnomalyModelConfig] = None,
        registry: Optional[AnomalyModelRegistry] = None,
        builder: Optional[OperationalFeatureBuilder] = None,
    ) -> None:

        self.config = config or AnomalyModelConfig.load()
        self.registry = registry or AnomalyModelRegistry.from_config(self.config)
        self.builder = builder or OperationalFeatureBuilder(self.config)

        self._model: Any = None
        self._metadata: Optional[Dict[str, Any]] = None
        self._explainer: Optional[AnomalyExplainer] = None

    # -- dependency availability -------------------------------------------

    @staticmethod
    def sklearn_available() -> bool:
        """Whether the estimator can be imported from this runtime.

        Returns a real ``bool``. The import guard yields ``None`` for the
        estimator class when the import fails, and returning that ``None``
        directly would give a method annotated ``bool`` an answer that is
        neither ``True`` nor ``False`` -- surprising for a caller writing
        ``if not detector.sklearn_available():`` in a place that also records
        the value.
        """

        return _sklearn_state()[0] is not None

    @staticmethod
    def sklearn_unavailable_reason() -> Optional[str]:
        return _sklearn_state()[1]

    @property
    def model_available(self) -> bool:
        """True only when the estimator can be imported and is loaded."""

        return self._model is not None and self.sklearn_available()

    @property
    def model_status(self) -> Dict[str, Any]:
        """Why the layer is or is not currently able to produce a verdict."""

        if not self.sklearn_available():
            return {
                "status": "UNAVAILABLE",
                "reason": self.sklearn_unavailable_reason(),
            }

        if self._model is None:
            return {
                "status": "NOT_TRAINED",
                "reason": (
                    "No anomaly model artifact is loaded. Run the training "
                    "path over a reference population before inference."
                ),
            }

        return {"status": "AVAILABLE", "reason": None}

    # -- training -----------------------------------------------------------

    def train(
        self,
        vectors: Sequence[FeatureVector],
        training_dataset_id: str,
    ) -> Dict[str, Any]:
        """Fit the model over a reference population and persist the artifact.

        The reference population must be *separate* from anything this model
        will later describe; the caller chooses it, and the label it carries is
        recorded in the metadata so no reader can mistake a generated
        population for observed history.
        """

        available, unavailable_reason = _sklearn_state()

        if not available:
            raise AnomalyTrainingError(
                f"scikit-learn is required to train the anomaly model: "
                f"{unavailable_reason}"
            )

        training = self.config.training
        expected_order = self.config.feature_ids

        if not vectors:
            raise AnomalyTrainingError(
                "reference population supplied no feature vectors"
            )

        minimum = int(training.get("minimum_reference_scopes", 0))

        if len(vectors) < minimum:
            raise AnomalyTrainingError(
                f"reference population has {len(vectors)} usable scope(s), "
                f"below the configured minimum of {minimum}"
            )

        fingerprint = self.config.schema_fingerprint

        for position, vector in enumerate(vectors):
            self._assert_vector_usable(
                vector, position, training, fingerprint, expected_order
            )

        matrix = self.builder.build_matrix(vectors)
        self._assert_matrix_finite(matrix, training)

        parameters = self._model_parameters()

        model = _sklearn_state()[0](**parameters)
        model.fit(matrix)

        reference_statistics = self._reference_statistics(vectors)

        self._model = model
        self._metadata = None
        self._explainer = AnomalyExplainer(
            reference_statistics,
            self.config.limitations,
            configuration=parameters,
        )

        metadata = self.registry.save(
            model,
            {
                "model_type": self._model_type(),
                "model_version": self.config.model_version,
                "feature_schema_version": (
                    self.config.feature_schema_version
                ),
                "feature_schema_fingerprint": fingerprint,
                "training_dataset_id": training_dataset_id,
                "training_reference_label": self.config.reference_corpus.get(
                    "label"
                ),
                "training_scope_count": len(vectors),
                "training_timestamp": _datetime.datetime.now(
                    _datetime.timezone.utc
                ).isoformat(timespec="seconds"),
                "random_state": parameters["random_state"],
                "configured_parameters": parameters,
                "feature_ids": list(expected_order),
                "feature_order_is_significant": True,
                "reference_statistics": reference_statistics,
                "limitations": list(self.config.limitations),
                "training_matrix_finite": True,
            },
        )

        self._metadata = metadata

        return metadata

    def load(self, verify_digest: bool = True) -> Dict[str, Any]:
        """Load a persisted artifact and its metadata."""

        available, _ = _sklearn_state()

        if not available:
            raise ModelRegistryError(
                "scikit-learn is required to load the anomaly model: "
                f"{self.sklearn_unavailable_reason()}"
            )

        model = self.registry.load(verify_digest=verify_digest)
        metadata = self.registry.load_metadata()

        fingerprint = self.config.schema_fingerprint

        stored = metadata.get("feature_schema_fingerprint")

        if stored and stored != fingerprint:
            raise FeatureSchemaMismatch(
                "the loaded model was trained on a different feature schema "
                f"fingerprint ({stored}) than the configured one "
                f"({fingerprint})"
            )

        if list(metadata.get("feature_ids") or []) != self.config.feature_ids:
            raise FeatureSchemaMismatch(
                "the loaded model's feature order does not match the "
                "configured feature schema"
            )

        self._model = model
        self._metadata = metadata
        self._explainer = AnomalyExplainer(
            metadata.get("reference_statistics") or {},
            metadata.get("limitations") or self.config.limitations,
            configuration=metadata.get("configured_parameters") or {},
        )

        return metadata

    # -- inference ----------------------------------------------------------

    def evaluate_scope(
        self,
        scope,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Evaluate one assessment scope. Scopes are never pooled."""

        vector = self.builder.build(
            concept_values,
            assessment_id=scope.assessment_id,
            entity=scope.entity.to_dict(),
            period=scope.period.to_dict(),
        )

        verdict, score, reason = self._decide(vector)

        metadata = self._metadata or {}

        explanation: Dict[str, Any] = {}

        if self._explainer is not None:
            explanation = self._explainer.explain(
                verdict=verdict,
                vector=vector,
                anomaly_score=score,
                model_version=str(
                    metadata.get("model_version", self.config.model_version)
                ),
                model_type=str(
                    metadata.get("model_type") or self._model_type()
                ),
            )

        return {
            "assessment_id": scope.assessment_id,
            "entity": scope.entity.to_dict(),
            "period": scope.period.to_dict(),
            "record_count": scope.record_count,
            "verdict": verdict,
            "reason": reason,
            "anomaly_score": score,
            "feature_schema_version": vector.feature_schema_version,
            "model_version": str(
                metadata.get("model_version", self.config.model_version)
            ),
            "features": [f.to_dict() for f in vector.features],
            "feature_schema": self.config.to_dict(),
            "unavailable_features": [
                {"feature_id": f.feature_id, "reason": f.note}
                for f in vector.unavailable
            ],
            "explanation": explanation,
            "evidence_concepts": explanation.get("evidence_concepts", []),
            "limitations": explanation.get(
                "limitations", list(self.config.limitations)
            ),
        }

    def evaluate_collection(
        self,
        collection,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
        capability_evaluator=None,
    ) -> Dict[str, Any]:
        """Evaluate every scope independently and summarise the verdicts.

        The same ``(collection, profile, semantic_results, evaluator)`` shape the
        other supervision layers take, so the pipeline call site reads the same.
        Scopes are never pooled: a profile that is ordinary for one entity can
        be unusual for another, and pooling would manufacture signals out of
        the difference between entities rather than out of anything unusual.
        """

        from framework.capability.capability_evaluator import (
            CapabilityEvaluator,
        )

        evaluator = capability_evaluator or CapabilityEvaluator()

        scope_payloads: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []

        for scope in collection:

            records = scope.records

            evidence_index = evaluator.build_evidence_index(
                records, profile, semantic_results
            )

            payload = self.evaluate_scope(
                scope, evidence_index.concept_values(records)
            )

            scope_payloads.append(payload)

            finding = self._build_finding(payload)

            if finding is not None:
                findings.append(finding)

        counts: Dict[str, int] = {verdict: 0 for verdict in VERDICTS}

        for payload in scope_payloads:
            counts[payload["verdict"]] = counts.get(payload["verdict"], 0) + 1

        return {
            "anomaly_model_status": self.model_status,
            "verdict_counts": counts,
            "scope_count": len(scope_payloads),
            "scope_results": scope_payloads,
            "findings": findings,
            "feature_schema": self.config.to_dict(),
            "limitations": list(self.config.limitations),
        }

    # -- decision path ------------------------------------------------------

    def _decide(
        self, vector: FeatureVector
    ) -> tuple:
        """Return (verdict, score, reason).

        The pre-model gates below can only ever return ``NOT_EVALUABLE``. The
        ``POTENTIAL_OPERATIONAL_ANOMALY`` / ``NO_ANOMALY`` split comes from the
        estimator and nowhere else.
        """

        available, reason = _sklearn_state()

        if not available:
            return NOT_EVALUABLE, None, reason

        if self._model is None:
            return (
                NOT_EVALUABLE,
                None,
                "No anomaly model is loaded, so no scope can be evaluated "
                "against a reference population.",
            )

        if not vector.available:

            missing = ", ".join(
                f"{f.feature_id} ({f.note})" for f in vector.unavailable
            )

            return (
                NOT_EVALUABLE,
                None,
                f"The feature vector is incomplete and cannot be evaluated "
                f"without inventing values: {missing}.",
            )

        try:
            row = vector.values()
        except FeatureUnavailable as unavailable:
            return NOT_EVALUABLE, None, str(unavailable)

        for value in row:
            if not math.isfinite(value):
                return (
                    NOT_EVALUABLE,
                    None,
                    "The feature vector contains a non-finite value, so no "
                    "verdict can be produced.",
                )

        if self._explainer is None or self._metadata is None:
            self.load()

        # The estimator decides. There is no threshold here and no branch on a
        # feature value, an entity, a dataset or a period.
        prediction = int(self._model.predict([row])[0])
        score = float(self._model.decision_function([row])[0])

        if prediction == -1:

            return POTENTIAL_OPERATIONAL_ANOMALY, score, REASON_ANOMALY

        return NO_ANOMALY, score, REASON_NORMAL

    # -- finding construction ----------------------------------------------

    def _build_finding(
        self, payload: Mapping[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """One anomaly finding, or ``None`` for the other two verdicts.

        The structure carries an indicator, a verdict and the evidence behind
        it. It has no severity, risk score, attention score, ranking or
        confidence field, so a consumer cannot read a judgement out of it that
        this layer did not make.
        """

        if payload["verdict"] != POTENTIAL_OPERATIONAL_ANOMALY:
            return None

        explanation = payload.get("explanation") or {}

        return {
            "indicator": INDICATOR,
            "verdict": payload["verdict"],
            "assessment_id": payload["assessment_id"],
            "entity": payload["entity"],
            "period": payload["period"],
            "reason": payload["reason"],
            "anomaly_score": payload["anomaly_score"],
            "features": payload["features"],
            "evidence_concepts": payload.get("evidence_concepts", []),
            "model_version": payload["model_version"],
            "feature_schema_version": payload["feature_schema_version"],
            "explanation": explanation.get("explanation"),
            "narrative": explanation.get("narrative"),
            "limitations": payload["limitations"],
        }

    # -- training validation ------------------------------------------------

    def _model_parameters(self) -> Dict[str, Any]:
        """The estimator keyword arguments, validated against a whitelist.

        Anything the configuration declares that is not a parameter this layer
        will pass through is a configuration error rather than a silently
        ignored key, so a typo cannot leave the estimator running on a default
        the operator believes they changed.
        """

        settings = dict(self.config.model_parameters)

        unexpected = set(settings) - ALLOWED_MODEL_PARAMETERS - {
            "model_type",
            "_comment",
        }

        if unexpected:
            raise AnomalyConfigError(
                "anomaly_model.json declares model parameters this layer does "
                f"not pass to the estimator: {sorted(unexpected)}"
            )

        parameters: Dict[str, Any] = {}

        for name in sorted(ALLOWED_MODEL_PARAMETERS):
            if name in settings:
                parameters[name] = settings[name]

        if parameters.get("random_state") is None:
            raise AnomalyConfigError(
                "model.random_state must be configured; an anomaly model "
                "without a fixed seed cannot be reproduced"
            )

        if parameters.get("n_estimators") is None:
            raise AnomalyConfigError(
                "model.n_estimators must be configured"
            )

        return parameters

    def _model_type(self) -> str:
        """The declared estimator type, recorded in metadata and explanations."""

        return str(
            self.config.model_parameters.get("model_type") or ""
        )

    def _assert_vector_usable(
        self,
        vector: FeatureVector,
        position: int,
        training: Mapping[str, Any],
        fingerprint: str,
        expected_order: Sequence[str],
    ) -> None:
        if training.get("reject_on_schema_mismatch", True) and (
            vector.feature_schema_version != self.config.feature_schema_version
        ):
            raise AnomalyTrainingError(
                f"reference scope {position} carries feature schema "
                f"{vector.feature_schema_version!r}, expected "
                f"{self.config.feature_schema_version!r}"
            )

        if training.get("reject_on_inconsistent_feature_order", True) and (
            vector.feature_ids != list(expected_order)
        ):
            raise AnomalyTrainingError(
                f"reference scope {position} has feature order "
                f"{vector.feature_ids}, expected {list(expected_order)}"
            )

        if training.get("require_all_features_available", True) and (
            not vector.available
        ):
            missing = ", ".join(
                f"{f.feature_id} ({f.note})" for f in vector.unavailable
            )
            raise AnomalyTrainingError(
                f"reference scope {position} is missing required feature "
                f"evidence: {missing}. Training on a partly imputed vector "
                f"would teach the model that absent evidence is a low value."
            )

        if not fingerprint:
            raise AnomalyTrainingError("feature schema fingerprint is empty")

    def _assert_matrix_finite(
        self, matrix: Sequence[Sequence[float]], training: Mapping[str, Any]
    ) -> None:
        if not training.get("require_finite_values", True):
            return

        for row_index, row in enumerate(matrix):
            for column_index, value in enumerate(row):
                if not math.isfinite(float(value)):
                    raise AnomalyTrainingError(
                        f"feature matrix contains a non-finite value at row "
                        f"{row_index}, column {column_index}"
                    )

    def _reference_statistics(
        self, vectors: Sequence[FeatureVector]
    ) -> Dict[str, Dict[str, float]]:
        """Per-feature reference distribution, stored with the model.

        This is what the explanation layer compares an observation against. It
        is a description of the reference population, not a set of thresholds:
        the model still decides what is unusual, and no feature is compared
        against a cut-point anywhere in this layer.
        """

        by_feature: Dict[str, List[float]] = {
            feature_id: [] for feature_id in self.config.feature_ids
        }

        for vector in vectors:
            for feature in vector.features:
                by_feature[feature.feature_id].append(float(feature.value))

        return {
            feature_id: summarise_distribution(values)
            for feature_id, values in by_feature.items()
        }


def _sklearn_state() -> tuple:
    """Import scikit-learn once, reporting the reason if it is absent.

    Optional so SAT-SA and its test suite keep working on a runtime without
    the estimator. Nothing else in the framework is affected.
    """

    global _SKLEARN_STATE

    if _SKLEARN_STATE is None:

        try:
            from sklearn.ensemble import IsolationForest

            _SKLEARN_STATE = (IsolationForest, None)

        except Exception as error:  # pragma: no cover - environment specific

            _SKLEARN_STATE = (
                None,
                f"scikit-learn is not importable from this runtime "
                f"({error.__class__.__name__}: {error}), so the offline "
                f"Isolation Forest layer cannot produce a verdict",
            )

    return _SKLEARN_STATE


_SKLEARN_STATE: Optional[tuple] = None
