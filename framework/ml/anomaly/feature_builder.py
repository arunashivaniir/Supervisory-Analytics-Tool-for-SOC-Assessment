"""Scope-level operational feature vectors for offline anomaly discovery.

Where this sits in the architecture
-----------------------------------
``AssessmentScope`` -> this module -> ``IsolationForest`` -> explanation.

The builder receives the *projected concept values* that
``EvidenceIndex.concept_values`` already produced, so by the time a number is
computed here the source column names are gone. A feature is declared over a
canonical concept (``SECURITY_SEVERITY``), never over a submitted column. That
is what makes a renamed column produce an identical vector without a single
special case, and it is why this file contains no dataset name, entity name,
period label or source column literal.

Availability is a first-class result
------------------------------------
Every feature returns either a number or an explanation of why no number is
legitimately available. A missing ``escalation_status`` is not an escalation
coverage of zero; it is an unevaluable coverage. The builder therefore raises
:class:`FeatureUnavailable` rather than substituting a default, and the detector
turns that into ``NOT_EVALUABLE``. Absent evidence can never become an anomaly.

The minimum-observations floor
------------------------------
Each feature declares ``minimum_records`` in configuration. Below that floor the
feature is unavailable rather than computed from a handful of observations,
which is the same discipline the operational-pattern layer already applies.

Why the aggregations look the way they do
------------------------------------------
No aggregation compares an observation against a hand-picked cut-point, because
a fixed number cannot tell a small scope from a large one. Distributions are
described by shares, entropies and similarities, all of which are scale-free;
the model, not this file, decides what counts as unusual.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from framework.evidence import calculate_sha256_of_text
from framework.ml.anomaly.minhash_lsh import find_max_similarities_minhash
from framework.supervision.execution_gap_detector import has_evidence
from framework.supervision.text_similarity import _jaccard, _tokenise
from framework.supervisory.rules.rule_engine import normalise_value


DEFAULT_CONFIG_PATH = "framework/config/anomaly_model.json"


class AnomalyConfigError(Exception):
    """The anomaly model configuration is missing or internally inconsistent."""


class FeatureUnavailable(Exception):
    """A feature cannot be computed from the evidence that was submitted.

    This is a normal outcome, not a failure. The scope is reported
    ``NOT_EVALUABLE`` rather than scored on a guessed value.
    """

    def __init__(self, feature_id: str, reason: str) -> None:

        self.feature_id = feature_id
        self.reason = reason

        super().__init__(f"{feature_id}: {reason}")


class FeatureSchemaMismatch(Exception):
    """A model and the current feature schema are not the same contract.

    Raised when the ordered feature definitions, their aggregations or their
    source concepts differ from the ones a model was trained on. Serving a
    V1-trained model a V2 vector would silently compare unrelated columns, so
    the mismatch is refused instead.
    """


class FeatureValue:
    """One entry of a feature vector, carrying its own availability."""

    __slots__ = ("feature_id", "value", "available", "source_concepts", "note")

    def __init__(
        self,
        feature_id: str,
        value: Optional[float],
        available: bool,
        source_concepts: Sequence[str],
        note: Optional[str] = None,
    ) -> None:

        self.feature_id = feature_id
        self.value = value
        self.available = available
        self.source_concepts = list(source_concepts)
        self.note = note

    def to_dict(self) -> Dict[str, Any]:

        return {
            "feature_id": self.feature_id,
            "value": self.value,
            "available": self.available,
            "source_concepts": list(self.source_concepts),
            **({"note": self.note} if self.note else {}),
        }


class FeatureVector:
    """The explicit feature schema shared by training and inference.

    ``features`` is always in configured order, which is the matrix column
    order. Order is never sorted, de-duplicated or inferred from a dict, so a
    model trained on one ordering cannot silently receive another.
    """

    def __init__(
        self,
        feature_schema_version: str,
        features: Sequence[FeatureValue],
        assessment_id: Optional[str] = None,
        entity: Optional[Mapping[str, Any]] = None,
        period: Optional[Mapping[str, Any]] = None,
    ) -> None:

        self.feature_schema_version = feature_schema_version
        self.features = list(features)
        self.assessment_id = assessment_id
        self.entity = dict(entity) if entity else None
        self.period = dict(period) if period else None

    @property
    def feature_ids(self) -> List[str]:
        return [feature.feature_id for feature in self.features]

    @property
    def unavailable(self) -> List[FeatureValue]:
        return [f for f in self.features if not f.available]

    @property
    def available(self) -> bool:
        return not self.unavailable

    def values(self) -> List[float]:
        """The numeric row, or a clear error naming what is missing.

        Refusing here is deliberate: building a row with a placeholder would
        let absent evidence reach the estimator.
        """

        missing = self.unavailable

        if missing:

            detail = "; ".join(
                f"{f.feature_id} ({f.note})" for f in missing
            )

            raise FeatureUnavailable(
                ",".join(f.feature_id for f in missing),
                f"feature vector incomplete: {detail}",
            )

        return [float(f.value) for f in self.features]

    def value_map(self) -> Dict[str, float]:
        return {
            f.feature_id: float(f.value)
            for f in self.features
            if f.available
        }

    def to_dict(self) -> Dict[str, Any]:

        return {
            "feature_schema_version": self.feature_schema_version,
            "assessment_id": self.assessment_id,
            "features": [f.to_dict() for f in self.features],
        }


class FeatureDefinition:
    """One configured feature, read verbatim from ``anomaly_model.json``."""

    __slots__ = (
        "feature_id",
        "description",
        "source_concepts",
        "aggregation",
        "parameters",
        "minimum_records",
        "missing_policy",
    )

    def __init__(self, payload: Mapping[str, Any]) -> None:

        self.feature_id = str(payload["feature_id"])
        self.description = str(payload.get("description", ""))
        self.source_concepts = list(payload.get("source_concepts") or [])
        self.aggregation = str(payload["aggregation"])
        self.parameters = dict(payload.get("parameters") or {})
        self.minimum_records = int(payload.get("minimum_records", 1))
        self.missing_policy = str(
            payload.get("missing_policy", "unavailable_without_source_evidence")
        )

        if self.minimum_records < 1:
            raise AnomalyConfigError(
                f"{self.feature_id}: minimum_records must be at least 1"
            )

    def signature(self) -> Dict[str, Any]:
        """The part of the definition that a model is bound to."""

        return {
            "feature_id": self.feature_id,
            "aggregation": self.aggregation,
            "source_concepts": sorted(self.source_concepts),
            "parameters": _canonical(self.parameters),
            "minimum_records": self.minimum_records,
            "missing_policy": self.missing_policy,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "description": self.description,
            "source_concepts": list(self.source_concepts),
            "aggregation": self.aggregation,
            "parameters": dict(self.parameters),
            "minimum_records": self.minimum_records,
            "missing_policy": self.missing_policy,
        }


def _canonical(value: Any) -> Any:
    """Recursively order a JSON-ish payload so digests are stable."""

    if isinstance(value, Mapping):
        return {k: _canonical(value[k]) for k in sorted(value)}

    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]

    return value


class AnomalyModelConfig:
    """Typed view over ``framework/config/anomaly_model.json``."""

    def __init__(self, payload: Mapping[str, Any]) -> None:

        self.raw = dict(payload)

        self.feature_schema_version = str(
            payload["feature_schema_version"]
        )
        self.model_version = str(payload.get("model_version", "1.0.0"))
        self.schema_version = str(payload.get("schema_version", "1.0"))

        self.features = [
            FeatureDefinition(item) for item in payload["features"]
        ]

        # Vocabularies are stripped of their ``_comment`` documentation keys so a
        # self-documenting config file does not leak prose into the numbers the
        # feature builder compares values against.
        self.vocabularies = {
            str(name): {
                key: value
                for key, value in body.items()
                if not str(key).startswith("_")
            }
            if isinstance(body, Mapping)
            else list(body)
            for name, body in (payload.get("vocabularies") or {}).items()
        }

        self.model_parameters = dict(payload.get("model") or {})
        self.training = dict(payload.get("training") or {})
        self.availability_policy = dict(
            payload.get("availability_policy") or {}
        )
        self.registry = dict(payload.get("registry") or {})
        self.reference_corpus = dict(payload.get("reference_corpus") or {})
        self.controlled_corpus = dict(payload.get("controlled_corpus") or {})
        self.limitations = list(payload.get("limitations") or [])

        self._validate()

    @classmethod
    def load(cls, path: str = DEFAULT_CONFIG_PATH) -> "AnomalyModelConfig":

        resolved = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)

        try:
            with open(resolved, "r") as handle:
                return cls(json.load(handle))

        except FileNotFoundError as error:
            raise AnomalyConfigError(
                f"anomaly model configuration not found: {path}"
            ) from error

    @property
    def feature_ids(self) -> List[str]:
        return [feature.feature_id for feature in self.features]

    def feature(self, feature_id: str) -> Optional[FeatureDefinition]:
        for candidate in self.features:
            if candidate.feature_id == feature_id:
                return candidate
        return None

    def vocabulary(self, name: str) -> Any:
        if name not in self.vocabularies:
            raise AnomalyConfigError(f"vocabulary not configured: {name!r}")
        return self.vocabularies[name]

    @property
    def schema_fingerprint(self) -> str:
        """Digest of the ordered feature definitions.

        Derived from the definitions rather than trusted from the file, so
        editing a feature without bumping ``feature_schema_version`` is caught
        as a mismatch instead of being silently trained and served.
        """

        payload = _canonical(
            {
                "feature_schema_version": self.feature_schema_version,
                "features": [f.signature() for f in self.features],
            }
        )

        return calculate_sha256_of_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )

    def _validate(self) -> None:

        if not self.features:
            raise AnomalyConfigError("no features configured")

        seen = set()

        for feature in self.features:
            if feature.feature_id in seen:
                raise AnomalyConfigError(
                    f"duplicate feature_id: {feature.feature_id}"
                )
            seen.add(feature.feature_id)

        self._validate_required_blocks()
        self._validate_features()
        self._validate_model_parameters()
        self._validate_availability_policy()

    #: Blocks inference cannot proceed without. Their absence is a
    #: configuration error rather than something to default, because a
    #: defaulted value here would silently become a model decision.
    #:
    #: Generation-only blocks (``corpus_schema``, ``reference_corpus``,
    #: ``controlled_corpus``, ``scope_isolation``, ``renamed_corpus``) are
    #: deliberately absent: a deployment serving the model does not need to be
    #: able to regenerate a demonstration corpus. The generator checks those
    #: itself, and says so, when it is the one being used.
    _REQUIRED_BLOCKS = (
        "feature_schema_version",
        "features",
        "availability_policy",
        "model",
        "training",
        "registry",
        "vocabularies",
    )

    def _validate_required_blocks(self) -> None:

        missing = [
            key for key in self._REQUIRED_BLOCKS if not self.raw.get(key)
        ]

        if missing:
            raise AnomalyConfigError(
                "anomaly model configuration is missing required block(s): "
                + ", ".join(missing)
            )

        for key in ("artifact_path", "metadata_path"):
            if not self.registry.get(key):
                raise AnomalyConfigError(
                    f"registry.{key} must be configured; the layer does not "
                    "choose where a model is stored"
                )

    #: Aggregations the feature builder knows how to compute. An
    #: unrecognised name is refused rather than mapped to a default, because a
    #: silent default would put a number in the output that no one specified.
    _KNOWN_AGGREGATIONS = frozenset(
        {
            "scope_record_count",
            "populated_share",
            "positive_share",
            "ordinal_share_equals",
            "ordinal_mean_normalised",
            "ordinal_entropy_normalised",
            "mean_max_token_similarity",
            "max_group_share",
            "concept_coverage_share",
        }
    )

    #: Aggregations that read the scope's own size rather than its evidence.
    #: These legitimately name no concept, because there is nothing in the
    #: evidence to read: the number of records in scope is the quantity.
    _SCOPE_OWNED_AGGREGATIONS = frozenset({"scope_record_count"})

    def _validate_features(self) -> None:

        for feature in self.features:

            if feature.aggregation not in self._KNOWN_AGGREGATIONS:
                raise AnomalyConfigError(
                    f"feature {feature.feature_id!r} declares unknown "
                    f"aggregation {feature.aggregation!r}. Known: "
                    + ", ".join(sorted(self._KNOWN_AGGREGATIONS))
                )

            if (
                not feature.source_concepts
                and feature.aggregation
                not in self._SCOPE_OWNED_AGGREGATIONS
            ):
                raise AnomalyConfigError(
                    f"feature {feature.feature_id!r} declares aggregation "
                    f"{feature.aggregation!r} but names no source concepts, "
                    "so there is no evidence for it to read"
                )

    def _validate_model_parameters(self) -> None:

        model = self.model_parameters

        if model.get("model_type") != "sklearn.ensemble.IsolationForest":
            raise AnomalyConfigError(
                "this layer implements exactly one estimator; model_type must "
                f"be sklearn.ensemble.IsolationForest, got "
                f"{model.get('model_type')!r}"
            )

        for key in ("random_state", "n_estimators", "contamination"):
            if key not in model:
                raise AnomalyConfigError(
                    f"model.{key} must be configured; the layer does not "
                    "supply an estimator default of its own"
                )

        contamination = model["contamination"]

        if not isinstance(contamination, (int, float)):
            raise AnomalyConfigError(
                "model.contamination must be a number. 'auto' is refused: it "
                "places the decision boundary near the middle of the training "
                "distribution, which flags a large fraction of the reference "
                "population itself and is noise rather than a finding."
            )

        if not 0.0 < float(contamination) <= 0.5:
            raise AnomalyConfigError(
                f"model.contamination {contamination!r} is outside a usable "
                "range (0, 0.5]"
            )

        if int(model["n_estimators"]) < 1:
            raise AnomalyConfigError("model.n_estimators must be positive")

    def _validate_availability_policy(self) -> None:

        policy = self.availability_policy

        if "require_all_features" not in policy:
            raise AnomalyConfigError(
                "availability_policy.require_all_features must be configured. "
                "Partial imputation would let a scope with little evidence be "
                "judged on guesses, and a guessed value is what manufactures a "
                "false anomaly."
            )

        if "require_finite_values" not in policy:
            raise AnomalyConfigError(
                "availability_policy.require_finite_values must be configured"
            )

        minimum = self.training.get("minimum_reference_scopes")

        if minimum is None or int(minimum) < 1:
            raise AnomalyConfigError(
                "training.minimum_reference_scopes must be at least 1; a model "
                "fitted on an empty or near-empty population has no notion of "
                "ordinary to compare against"
            )

    def to_dict(self) -> Dict[str, Any]:

        return {
            "feature_schema_version": self.feature_schema_version,
            "model_version": self.model_version,
            "feature_ids": self.feature_ids,
            "schema_fingerprint": self.schema_fingerprint,
            "features": [f.to_dict() for f in self.features],
        }


class OperationalFeatureBuilder:
    """Builds one scope-level feature vector per assessment scope."""

    def __init__(self, config: Optional[AnomalyModelConfig] = None) -> None:

        self.config = config or AnomalyModelConfig.load()

        # Aggregation name -> bound method. The configuration names the
        # aggregation; the code never names a dataset, an entity or a column.
        self._aggregations = {
            "scope_record_count": self._scope_record_count,
            "ordinal_share_equals": self._ordinal_share_equals,
            "ordinal_mean_normalised": self._ordinal_mean_normalised,
            "ordinal_entropy_normalised": self._ordinal_entropy_normalised,
            "max_group_share": self._max_group_share,
            "populated_share": self._populated_share,
            "mean_max_token_similarity": self._mean_max_token_similarity,
            "positive_share": self._positive_share,
            "concept_coverage_share": self._concept_coverage_share,
        }

        for feature in self.config.features:
            if feature.aggregation not in self._aggregations:
                raise AnomalyConfigError(
                    f"{feature.feature_id}: unknown aggregation "
                    f"{feature.aggregation!r}"
                )

    # -- public API ---------------------------------------------------------

    def build(
        self,
        concept_values: Sequence[Mapping[str, Any]],
        assessment_id: Optional[str] = None,
        entity: Optional[Mapping[str, Any]] = None,
        period: Optional[Mapping[str, Any]] = None,
    ) -> FeatureVector:
        """Build the feature vector for one scope, availability included.

        ``concept_values`` is what ``EvidenceIndex.concept_values`` returns:
        one mapping per record, keyed by canonical concept. An empty sequence is
        an empty scope, and every feature is unavailable rather than zero.
        """

        entries: List[FeatureValue] = []

        for definition in self.config.features:
            entries.append(self._build_feature(definition, concept_values))

        return FeatureVector(
            self.config.feature_schema_version,
            entries,
            assessment_id=assessment_id,
            entity=entity,
            period=period,
        )

    def build_matrix(
        self, vectors: Sequence[FeatureVector]
    ) -> List[List[float]]:
        """Stack complete vectors into rows, refusing to guess any value."""

        if not vectors:
            raise FeatureUnavailable(
                "matrix",
                "no feature vectors supplied",
            )

        expected = self.config.feature_ids

        rows: List[List[float]] = []

        for vector in vectors:

            if vector.feature_ids != expected:
                raise AnomalyConfigError(
                    "feature ordering differs from the configured schema: "
                    f"expected {expected}, received {vector.feature_ids}"
                )

            rows.append(vector.values())

        return rows

    # -- per-feature construction -------------------------------------------

    def _build_feature(
        self,
        definition: FeatureDefinition,
        concept_values: Sequence[Mapping[str, Any]],
    ) -> FeatureValue:
        """Run one configured aggregation, converting refusal into availability."""

        try:
            method = self._aggregations[definition.aggregation]
            value = method(definition, concept_values)

            if value is None or not math.isfinite(float(value)):
                raise FeatureUnavailable(
                    definition.feature_id,
                    "computed value is not finite",
                )

            return FeatureValue(
                definition.feature_id,
                float(value),
                True,
                definition.source_concepts,
            )

        except FeatureUnavailable as unavailable:
            return FeatureValue(
                definition.feature_id,
                None,
                False,
                definition.source_concepts,
                note=unavailable.reason,
            )

    # -- helpers ------------------------------------------------------------

    def _values_for(
        self, records: Sequence[Mapping[str, Any]], concept: str
    ) -> List[str]:
        """Normalised, populated values of one concept across a scope."""

        collected: List[str] = []

        for record in records:
            if concept in record and has_evidence(record[concept]):
                normalised = normalise_value(record[concept])
                if normalised:
                    collected.append(normalised)

        return collected

    def _require_observations(
        self,
        definition: FeatureDefinition,
        observed: int,
        what: str,
    ) -> None:
        if observed < definition.minimum_records:
            raise FeatureUnavailable(
                definition.feature_id,
                f"only {observed} usable {what}, below the configured "
                f"minimum of {definition.minimum_records}",
            )

    # -- aggregations -------------------------------------------------------

    def _scope_record_count(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Record count of the scope. The one structural feature."""

        self._require_observations(
            definition, len(records), "records in scope"
        )

        return float(len(records))

    def _ordinal_share_equals(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Share of records sitting on one named band of an ordinal scale."""

        concept = self._single_concept(definition)
        vocabulary = self.config.vocabulary(
            definition.parameters["ordinal_vocabulary"]
        )
        target = normalise_value(definition.parameters["ordinal_equals"])

        values = self._values_for(records, concept)

        self._require_observations(
            definition, len(values), f"recognised {concept} values"
        )

        recognised = [v for v in values if v in vocabulary]

        if len(recognised) < definition.minimum_records:
            raise FeatureUnavailable(
                definition.feature_id,
                f"only {len(recognised)} {concept} values are in the "
                f"configured vocabulary, below the minimum of "
                f"{definition.minimum_records}",
            )

        return sum(1 for v in recognised if v == target) / len(recognised)

    def _ordinal_mean_normalised(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Mean ordinal position, rescaled to 0..1 over the vocabulary."""

        concept = self._single_concept(definition)
        vocabulary = self.config.vocabulary(
            definition.parameters["ordinal_vocabulary"]
        )

        values = self._values_for(records, concept)

        self._require_observations(
            definition, len(values), f"recognised {concept} values"
        )

        recognised = [
            float(vocabulary[v]) for v in values if v in vocabulary
        ]

        if len(recognised) < definition.minimum_records:
            raise FeatureUnavailable(
                definition.feature_id,
                f"only {len(recognised)} {concept} values are in the "
                f"configured vocabulary, below the minimum of "
                f"{definition.minimum_records}",
            )

        highest = max(float(v) for v in vocabulary.values())

        if highest <= 0:
            raise FeatureUnavailable(
                definition.feature_id,
                "configured ordinal vocabulary has no positive band",
            )

        return sum(recognised) / len(recognised) / highest

    def _ordinal_entropy_normalised(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Normalised Shannon entropy of an ordinal distribution.

        One dominant band gives 0.0; an even spread across the configured bands
        gives 1.0. No cut-point is involved: the shape itself is the feature.
        """

        concept = self._single_concept(definition)
        vocabulary = self.config.vocabulary(
            definition.parameters["ordinal_vocabulary"]
        )

        values = self._values_for(records, concept)

        self._require_observations(
            definition, len(values), f"recognised {concept} values"
        )

        recognised = [v for v in values if v in vocabulary]

        if len(recognised) < definition.minimum_records:
            raise FeatureUnavailable(
                definition.feature_id,
                f"only {len(recognised)} {concept} values are in the "
                f"configured vocabulary, below the minimum of "
                f"{definition.minimum_records}",
            )

        counts: Dict[str, int] = {}

        for value in recognised:
            counts[value] = counts.get(value, 0) + 1

        total = float(len(recognised))
        bands = float(len(vocabulary))

        if bands <= 1.0:
            raise FeatureUnavailable(
                definition.feature_id,
                "configured ordinal vocabulary has a single band",
            )

        entropy = 0.0

        for count in counts.values():
            share = count / total
            entropy -= share * math.log(share)

        return entropy / math.log(bands)

    def _max_group_share(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Share of records held by the most repeated value of one concept."""

        concept = self._single_concept(definition)
        values = self._values_for(records, concept)

        self._require_observations(
            definition, len(values), f"{concept} values"
        )

        counts: Dict[str, int] = {}

        for value in values:
            counts[value] = counts.get(value, 0) + 1

        return max(counts.values()) / len(values)

    def _populated_share(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Share of records carrying a populated value for one concept.

        A scope with no such column is unavailable, not 0.0: an absent
        escalation column says nothing about escalation coverage.
        """

        concept = self._single_concept(definition)

        if not records:
            raise FeatureUnavailable(
                definition.feature_id, "scope contains no records"
            )

        present = sum(
            1
            for record in records
            if concept in record and has_evidence(record[concept])
        )

        if present == 0:
            raise FeatureUnavailable(
                definition.feature_id,
                f"no record carries a populated {concept} value, so coverage "
                f"cannot be evaluated",
            )

        return present / len(records)

    def _mean_max_token_similarity(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Mean best-match token similarity of one concept's text values.

        Reuses the operational-pattern layer's tokeniser and Jaccard similarity
        verbatim, so the two layers cannot drift apart in what they mean by
        "similar wording". Returns a share, not a pass/fail: the similarity
        floor that the pattern layer needs for grouping is deliberately absent
        here, because the model decides what counts as unusual.

        Uses MinHash LSH for sub-quadratic max-similarity computation.
        """

        concept = self._single_concept(definition)

        token_sets = [
            _tokenise(record[concept])
            for record in records
            if concept in record and has_evidence(record[concept])
        ]

        usable = [tokens for tokens in token_sets if tokens]

        self._require_observations(
            definition, len(usable), f"text-bearing {concept} values"
        )

        if len(usable) < 2:
            return 0.0

        max_sims = find_max_similarities_minhash(
            token_sets, exact_jaccard_fn=_jaccard
        )

        return sum(max_sims) / len(max_sims) if max_sims else 0.0

    def _positive_share(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Share of classified values in the configured positive vocabulary.

        A value matching neither vocabulary is left unclassified rather than
        counted as negative, and the share is taken over classified values only.
        """

        concept = self._single_concept(definition)

        positive = {
            normalise_value(item)
            for item in self.config.vocabulary(
                definition.parameters["positive_vocabulary"]
            )
        }
        negative = {
            normalise_value(item)
            for item in self.config.vocabulary(
                definition.parameters["negative_vocabulary"]
            )
        }

        values = self._values_for(records, concept)

        self._require_observations(
            definition, len(values), f"populated {concept} values"
        )

        classified = [v for v in values if v in positive or v in negative]

        if len(classified) < definition.minimum_records:
            raise FeatureUnavailable(
                definition.feature_id,
                f"only {len(classified)} {concept} values are in the "
                f"configured positive or negative vocabulary, below the "
                f"minimum of {definition.minimum_records}",
            )

        return sum(1 for v in classified if v in positive) / len(classified)

    def _concept_coverage_share(
        self,
        definition: FeatureDefinition,
        records: Sequence[Mapping[str, Any]],
    ) -> float:
        """Mean per-concept coverage over the feature's declared concepts.

        Every declared concept must actually carry evidence somewhere. A concept
        that is entirely absent makes the whole feature unavailable, because
        averaging an absent concept in as zero would report incomplete
        submission as a measured property of the scope.
        """

        if not definition.source_concepts:
            raise FeatureUnavailable(
                definition.feature_id,
                "no source concepts declared",
            )

        if not records:
            raise FeatureUnavailable(
                definition.feature_id, "scope contains no records"
            )

        shares: List[float] = []

        for concept in definition.source_concepts:

            present = sum(
                1
                for record in records
                if concept in record and has_evidence(record[concept])
            )

            if present == 0:
                raise FeatureUnavailable(
                    definition.feature_id,
                    f"no record carries a populated {concept} value, so "
                    f"evidence completeness cannot be evaluated",
                )

            shares.append(present / len(records))

        return sum(shares) / len(shares)

    def _single_concept(self, definition: FeatureDefinition) -> str:
        if len(definition.source_concepts) != 1:
            raise AnomalyConfigError(
                f"{definition.feature_id}: this aggregation needs exactly one "
                f"source concept, found {definition.source_concepts}"
            )

        return definition.source_concepts[0]
