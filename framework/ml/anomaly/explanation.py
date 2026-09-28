"""Human-readable explanation for an anomaly verdict.

Why this layer exists
---------------------
An Isolation Forest reports how isolated a point is, not why. It has no
notion of a feature being responsible for anything, and its internals are a
forest of random splits that cannot be read as reasons. Anything presented as
"the model thinks feature X caused this" would be an invention.

So the explanation layer does two honest things and no more:

  1. It describes the observed feature profile against the reference
     population's own distribution, per feature, with the availability of each
     feature stated explicitly.
  2. It ranks features by how far the observed value sits from the reference
     median in units of the reference spread, and calls that a *distance*, not
     an importance, because that is what it is.

The wording is fixed in ``anomaly_model.json`` under ``limitations`` and echoed
into every finding, so the caveat travels with the result rather than living in
a design document somebody has to remember to read.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.ml.anomaly.feature_builder import FeatureVector


# Features are ordered by this distance and the largest few are named in the
# narrative. The cap keeps the text readable and is a presentation limit, not
# an analytical threshold.
NARRATED_FEATURES = 3

SUMMARY_TEXT = (
    "The assessment's operational feature profile differs substantially from "
    "the reference population."
)

CONTRIBUTION_TEXT = (
    "The following features contributed to the unusual operational profile."
)

NOT_ANOMALOUS_TEXT = (
    "The assessment's operational feature profile sits within the range "
    "typical of the reference population."
)

NOT_EVALUABLE_TEXT = (
    "The assessment's operational profile could not be evaluated against the "
    "reference population with the evidence that was submitted."
)


class AnomalyExplainer:
    """Builds the explanation block for one scope-level anomaly verdict."""

    def __init__(
        self,
        reference_statistics: Mapping[str, Mapping[str, float]],
        limitations: Sequence[str],
        configuration: Optional[Mapping[str, Any]] = None,
    ) -> None:

        self.reference_statistics = {
            str(key): dict(value) for key, value in reference_statistics.items()
        }
        self.limitations = list(limitations)
        self.configuration = dict(configuration or {})

    # -- public API ---------------------------------------------------------

    def explain(
        self,
        verdict: str,
        vector: FeatureVector,
        anomaly_score: Optional[float],
        model_version: str,
        model_type: str,
    ) -> Dict[str, Any]:
        """Return the explanation block for one evaluated scope."""

        profile = self.feature_profile(vector)

        return {
            "assessment_id": vector.assessment_id,
            "entity": vector.entity,
            "period": vector.period,
            "verdict": verdict,
            "model_type": model_type,
            "model_version": model_version,
            "feature_schema_version": vector.feature_schema_version,
            "anomaly_score": anomaly_score,
            "feature_profile": profile,
            "narrative": self._narrative(verdict, profile),
            "explanation": self.explanation_text(verdict, profile),
            "evidence_concepts": self.evidence_concepts(profile),
            "limitations": list(self.limitations),
            "score_semantics": (
                "Raw scikit-learn Isolation Forest decision score. More "
                "negative means further from the reference population. It is "
                "a distance measure internal to the model, not a risk score, "
                "not a severity and not a confidence."
            ),
        }

    def feature_profile(
        self, vector: FeatureVector
    ) -> List[Dict[str, Any]]:
        """One profile row per configured feature, in configured order."""

        rows: List[Dict[str, Any]] = []

        for feature in vector.features:

            reference = self.reference_statistics.get(feature.feature_id, {})

            row: Dict[str, Any] = {
                "feature_id": feature.feature_id,
                "observed_value": feature.value,
                "available": feature.available,
                "source_concepts": list(feature.source_concepts),
                "reference_summary": self._reference_summary(reference),
                "distance_from_reference_median": None,
            }

            if feature.available and reference.get("median") is not None:

                row["distance_from_reference_median"] = _robust_distance(
                    float(feature.value), reference
                )

            if not feature.available:

                row["unavailable_reason"] = feature.note

            rows.append(row)

        return rows

    def explanation_text(
        self, verdict: str, profile: Sequence[Mapping[str, Any]]
    ) -> str:
        """The narrative. Descriptive by construction, never causal."""

        if verdict == "NOT_EVALUABLE":

            missing = [
                row["feature_id"]
                for row in profile
                if not row["available"]
            ]

            return (
                f"{NOT_EVALUABLE_TEXT} "
                f"Unavailable features: {', '.join(missing)}."
            )

        if verdict != "POTENTIAL_OPERATIONAL_ANOMALY":

            return NOT_ANOMALOUS_TEXT

        ranked = sorted(
            (
                row
                for row in profile
                if row["available"]
                and row["distance_from_reference_median"] is not None
            ),
            key=lambda row: row["distance_from_reference_median"],
            reverse=True,
        )

        if not ranked:
            return f"{SUMMARY_TEXT} {NOT_ANOMALOUS_TEXT}"

        phrases = [
            _describe(row) for row in ranked[:NARRATED_FEATURES]
        ]

        return (
            f"{SUMMARY_TEXT} {CONTRIBUTION_TEXT} "
            + "; ".join(phrases)
            + ". This is a description of where the profile sits relative to "
            "the reference population, not a causal claim about any feature."
        )

    def evidence_concepts(
        self, profile: Sequence[Mapping[str, Any]]
    ) -> List[str]:
        """Canonical concepts behind the features that were actually usable."""

        concepts: List[str] = []

        for row in profile:

            if not row["available"]:
                continue

            for concept in row["source_concepts"]:
                if concept not in concepts:
                    concepts.append(concept)

        return sorted(concepts)

    # -- internals ----------------------------------------------------------

    def _narrative(
        self, verdict: str, profile: Sequence[Mapping[str, Any]]
    ) -> str:
        """A short label a report can print next to the verdict."""

        if verdict == "POTENTIAL_OPERATIONAL_ANOMALY":
            return "Potential operational anomaly"

        if verdict == "NO_ANOMALY":
            return "No anomaly"

        return "Not evaluable"

    def _reference_summary(
        self, reference: Mapping[str, float]
    ) -> Dict[str, Any]:
        if not reference:
            return {
                "available": False,
                "note": "no reference distribution recorded for this feature",
            }

        return {
            "available": True,
            "minimum": reference.get("minimum"),
            "p10": reference.get("p10"),
            "median": reference.get("median"),
            "p90": reference.get("p90"),
            "maximum": reference.get("maximum"),
            "mean": reference.get("mean"),
            "standard_deviation": reference.get("standard_deviation"),
        }


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile of an ascending sequence."""

    if not ordered:
        raise ValueError("percentile of an empty sequence")

    if len(ordered) == 1:
        return float(ordered[0])

    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))

    if lower == upper:
        return float(ordered[lower])

    weight = position - lower

    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def summarise_distribution(values: Sequence[float]) -> Dict[str, float]:
    """Distribution summary stored in the model metadata.

    Median and p10/p90 rather than mean and standard deviation alone, because a
    model must remain describable when a reference population has a long tail.
    """

    ordered = sorted(float(v) for v in values)

    if not ordered:
        raise ValueError("cannot summarise an empty distribution")

    total = sum(ordered)
    mean = total / len(ordered)
    variance = sum((v - mean) ** 2 for v in ordered) / len(ordered)

    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "p10": _percentile(ordered, 0.10),
        "median": _percentile(ordered, 0.50),
        "p90": _percentile(ordered, 0.90),
        "maximum": ordered[-1],
        "mean": round(mean, 6),
        "standard_deviation": round(math.sqrt(variance), 6),
    }


def _robust_distance(
    observed: float, reference: Mapping[str, float]
) -> float:
    """How many reference spreads the observation sits from the median.

    Uses the p10..p90 span as the spread so a single extreme reference value
    cannot compress every other feature's distance. Returns 0.0 when the
    reference span is zero, which means "indistinguishable from the reference".
    """

    low = reference.get("p10")
    high = reference.get("p90")
    median = reference.get("median")

    if low is None or high is None or median is None:
        return 0.0

    span = float(high) - float(low)

    if span <= 0.0:
        return 0.0

    return round(abs(observed - float(median)) / span, 6)


def _describe(row: Mapping[str, Any]) -> str:
    """One feature, phrased as a comparison with the reference population."""

    observed = row["observed_value"]
    summary = row["reference_summary"]

    if summary.get("available") and summary.get("median") is not None:

        return (
            f"{row['feature_id']} observed {_number(observed)} against a "
            f"reference median of {_number(summary['median'])} "
            f"(p10 {_number(summary['p10'])}, p90 {_number(summary['p90'])})"
        )

    return (
        f"{row['feature_id']} observed {_number(observed)}, with no recorded "
        f"reference distribution for this feature"
    )


def _number(value: Any) -> str:
    if value is None:
        return "an unavailable value"

    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.4f}"

    return str(value)
