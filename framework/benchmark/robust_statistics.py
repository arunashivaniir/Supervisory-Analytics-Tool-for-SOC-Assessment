"""Robust descriptive statistics for peer benchmarking.

Every function here is pure, deterministic and dependency-free. No sampling,
no random seed, no numerical library: a reviewer must be able to recompute a
published peer baseline by hand from the peer values the tool also publishes.

WHY MEDIAN AND MAD, NOT MEAN AND STANDARD DEVIATION
====================================================

Peer populations in a supervisory assessment are small and heavily skewed.
One CSE that submitted a single extra month of data moves a mean and inflates
a standard deviation enough to hide the median entirely. The median and the
median absolute deviation (MAD) are used instead because a handful of extreme
peers cannot move them materially, which is what makes a peer statement
defensible rather than merely computed.

WHAT A ZERO MAD MEANS
=====================

A zero MAD means every peer reported an identical value. That is a real
property of the cohort, not an error, and it is reported as such. The
modified Z-score is then genuinely undefined, because the formula divides by
the spread: dividing by zero would manufacture an infinite deviation out of a
cohort that has no spread at all. ``NOT_COMPUTABLE`` is therefore returned
and the statistical status is set to ``NOT_COMPUTABLE``, which is a different
statement from "this scope is within the normal range".
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

#: Rounding applied to every published statistic, so JSON round-trips are
#: stable and two runs of the same cohort cannot disagree in the last digit.
PRECISION = 6

#: The consistency constant that makes the modified Z-score comparable with a
#: standard score for normally distributed data.
MODIFIED_Z_CONSTANT = 0.6745

COMPUTED = "COMPUTED"
NOT_COMPUTABLE = "NOT_COMPUTABLE"


def percentile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile of an ascending or unordered sequence.

    The same interpolation convention the anomaly explainer already uses, so
    the two layers cannot disagree about what ``p90`` means.
    """

    if not values:
        raise ValueError("percentile of an empty sequence")

    ordered = sorted(float(value) for value in values)

    if len(ordered) == 1:
        return float(ordered[0])

    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))

    if lower == upper:
        return float(ordered[lower])

    weight = position - lower

    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def median(values: Sequence[float]) -> float:
    """Median of a sequence."""

    return percentile(values, 0.50)


def quartiles(values: Sequence[float]) -> Dict[str, float]:
    """First quartile, median and third quartile.

    Q1 and Q3 are the 25th and 75th percentiles by the same linear
    interpolation used everywhere else in the framework.
    """

    return {
        "q1": round(percentile(values, 0.25), PRECISION),
        "median": round(median(values), PRECISION),
        "q3": round(percentile(values, 0.75), PRECISION),
    }


def median_absolute_deviation(
    values: Sequence[float], centre: Optional[float] = None
) -> float:
    """Median absolute deviation about ``centre`` (the median by default).

    Reported without the ``1.4826`` scaling factor. The scaling exists to
    make MAD comparable with a standard deviation under normality, which is a
    distributional assumption a peer cohort has not earned. The unscaled MAD
    combined with the consistency constant below gives the same modified
    Z-score, so nothing is lost by leaving the assumption out.
    """

    if not values:
        return 0.0

    pivot = median(values) if centre is None else float(centre)

    return median([abs(float(value) - pivot) for value in values])


def summarise_peers(values: Sequence[float]) -> Dict[str, Any]:
    """The full peer distribution published for every benchmarked metric.

    Minimum and maximum are included as well as the quartiles, because an
    examiner checking whether a scope sits inside its peer range needs the
    actual bounds, not only the middle half.
    """

    if not values:
        return {
            "count": 0,
            "minimum": None,
            "q1": None,
            "median": None,
            "q3": None,
            "maximum": None,
            "iqr": None,
            "mad": None,
            "statistical_status": NOT_COMPUTABLE,
            "not_computable_reason": "no peer reported a value for this metric",
        }

    ordered = sorted(float(value) for value in values)
    quart = quartiles(ordered)
    mad = median_absolute_deviation(ordered, centre=quart["median"])

    return {
        "count": len(ordered),
        "minimum": round(ordered[0], PRECISION),
        "q1": quart["q1"],
        "median": quart["median"],
        "q3": quart["q3"],
        "maximum": round(ordered[-1], PRECISION),
        "iqr": round(quart["q3"] - quart["q1"], PRECISION),
        "mad": round(mad, PRECISION),
        "statistical_status": COMPUTED,
        "not_computable_reason": None,
    }


def modified_z_score(
    observed: Optional[float],
    peer_median: Optional[float],
    mad: Optional[float],
) -> Optional[float]:
    """Robust standardised deviation of ``observed`` from the peer median.

    ``0.6745 * (observed - peer_median) / MAD``

    Returns ``None`` whenever the value is not computable: a missing
    observation, a missing peer centre, a cohort with no spread, or a cohort
    that is too small to summarise. The caller turns ``None`` into
    ``NOT_COMPUTABLE`` rather than into zero.
    """

    if observed is None or peer_median is None or mad is None:
        return None

    if mad <= 0.0:
        return None

    return round(
        MODIFIED_Z_CONSTANT * (float(observed) - float(peer_median)) / float(mad),
        PRECISION,
    )


def peer_percentile(
    observed: Optional[float], peer_values: Sequence[float]
) -> Optional[float]:
    """Where ``observed`` sits inside the observed peer values.

    This is a description of position, never a risk score. A scope that sits
    above its peers on an adverse metric and a scope that sits above its peers
    on a favourable metric both land at a high percentile; only the metric's
    configured direction says which reading applies, and that direction is
    declared in configuration, not chosen here.
    """

    if observed is None or not peer_values:
        return None

    ordered = sorted(float(value) for value in peer_values)
    below = sum(1 for value in ordered if value < float(observed))
    equal = sum(1 for value in ordered if value == float(observed))

    return round((below + 0.5 * equal) / len(ordered), PRECISION)


def rank_of(observed: Optional[float], peer_values: Sequence[float]) -> Optional[int]:
    """Position of ``observed`` in the ascending peer ordering, 1-based.

    The target scope's own value is not a peer, so this ranks it strictly
    against the cohort it was compared with.
    """

    if observed is None or not peer_values:
        return None

    ordered = sorted(float(value) for value in peer_values)

    return 1 + sum(1 for value in ordered if value < float(observed))


def outlier_flags(
    peer_values: Sequence[float],
) -> Dict[str, Any]:
    """Which peers are extreme within their own cohort, by the Tukey fences.

    Used to render a cohort honestly: when the median is carried by a handful
    of outlying peers, a reviewer needs to see that before reading a target's
    percentile. Fences are a property of the data (1.5 x IQR) rather than a
    supervisory policy, and no peer is removed from the baseline because of
    one.
    """

    if len(peer_values) < 4:
        return {
            "applicable": False,
            "reason": (
                "Tukey fences need at least four peers to describe a spread"
            ),
            "lower_fence": None,
            "upper_fence": None,
            "below_lower": [],
            "above_upper": [],
        }

    summary = summarise_peers(peer_values)
    q1 = float(summary["q1"])
    q3 = float(summary["q3"])
    spread = q3 - q1
    lower = q1 - 1.5 * spread
    upper = q3 + 1.5 * spread

    below: List[float] = []
    above: List[float] = []

    for value in peer_values:
        if float(value) < lower:
            below.append(float(value))
        elif float(value) > upper:
            above.append(float(value))

    return {
        "applicable": True,
        "reason": None,
        "lower_fence": round(lower, PRECISION),
        "upper_fence": round(upper, PRECISION),
        "below_lower": sorted(below),
        "above_upper": sorted(above),
    }