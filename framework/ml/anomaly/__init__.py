"""Offline Isolation Forest anomaly discovery.

Read in this order:

``feature_builder``
    Declares the scope-level operational features over canonical concepts and
    decides, per feature, whether a number is legitimately available.

``isolation_forest_detector``
    Trains the estimator over a reference population and applies it one
    assessment scope at a time. The verdict comes from the estimator.

``model_registry``
    Stores the artifact beside readable JSON metadata and verifies the artifact
    digest with the existing evidence integrity utility.

``explanation``
    Describes the observed profile against the reference distribution without
    claiming causation.

``corpus``
    Generates the labelled synthetic reference population and the controlled
    inference profiles, entirely from configuration.

The layer emits ``POTENTIAL_OPERATIONAL_ANOMALY``, ``NO_ANOMALY`` or
``NOT_EVALUABLE``. It establishes no control failure, no severity, no risk
level, no confidence and no root cause.
"""

from framework.ml.anomaly.explanation import AnomalyExplainer
from framework.ml.anomaly.feature_builder import (
    AnomalyConfigError,
    AnomalyModelConfig,
    FeatureDefinition,
    FeatureSchemaMismatch,
    FeatureUnavailable,
    FeatureValue,
    FeatureVector,
    OperationalFeatureBuilder,
)
from framework.ml.anomaly.isolation_forest_detector import (
    INDICATOR,
    NO_ANOMALY,
    VERDICTS,
    AnomalyTrainingError,
    IsolationForestAnomalyDetector,
)
from framework.ml.anomaly.model_registry import (
    AnomalyModelRegistry,
    ModelRegistryError,
)

__all__ = [
    "AnomalyConfigError",
    "AnomalyExplainer",
    "AnomalyModelConfig",
    "AnomalyModelRegistry",
    "AnomalyTrainingError",
    "FeatureDefinition",
    "FeatureSchemaMismatch",
    "FeatureUnavailable",
    "FeatureValue",
    "FeatureVector",
    "INDICATOR",
    "IsolationForestAnomalyDetector",
    "ModelRegistryError",
    "NO_ANOMALY",
    "OperationalFeatureBuilder",
    "VERDICTS",
]
