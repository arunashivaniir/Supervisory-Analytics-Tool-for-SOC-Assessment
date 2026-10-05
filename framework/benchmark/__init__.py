"""SAT-SA peer benchmarking.

Compares one assessment scope with a deterministic cohort of peer scopes drawn
from the same assessment, using quantities other supervisory layers have
already produced. The engine adds no new intelligence: it normalises raw
counts into rates, resolves a cohort, and publishes robust statistics with
their availability stated.

The module is import-safe and dependency-free. Nothing here requires numpy,
scikit-learn, pandas or duckdb, so the layer behaves identically whether or
not the optional analytical dependencies are installed.
"""

from framework.benchmark.cohort import (
    BenchmarkConfigError,
    CohortTier,
    PeerCohortResolver,
)
from framework.benchmark.engine import (
    BASELINE_LIMITED,
    BASELINE_ROBUST,
    BASELINE_UNAVAILABLE,
    DEFAULT_PEER_BENCHMARK_CONFIG,
    MetricDefinition,
    PeerBenchmarkEngine,
    evaluate_collection_or_report_unavailable,
)
from framework.benchmark.robust_statistics import (
    median_absolute_deviation,
    modified_z_score,
    outlier_flags,
    peer_percentile,
    percentile,
    summarise_peers,
)

__all__ = [
    "BASELINE_LIMITED",
    "BASELINE_ROBUST",
    "BASELINE_UNAVAILABLE",
    "BenchmarkConfigError",
    "CohortTier",
    "DEFAULT_PEER_BENCHMARK_CONFIG",
    "MetricDefinition",
    "PeerBenchmarkEngine",
    "PeerCohortResolver",
    "evaluate_collection_or_report_unavailable",
    "median_absolute_deviation",
    "modified_z_score",
    "outlier_flags",
    "peer_percentile",
    "percentile",
    "summarise_peers",
]