"""Profiler over an analytical scan, Phase 2.

Produces the exact profile shape ``DatasetProfiler`` produces —
``dataset_summary`` plus one entry per column with ``data_type``,
``unique_values``, ``null_values``, ``category`` and either numeric
statistics or ``sample_values`` — without loading the file into pandas.

Parity rules (verified by equality tests on fixtures):

* Categories follow the same decision tree: numeric-typed columns are
  ``numeric``; temporal-typed columns are ``categorical`` because the
  pandas path never parses dates and neither does this one; the rest use
  the same identifier-keyword / unique-ratio / common-category rule.
* ``sample_values`` are the first distinct raw spellings in file order,
  pandas NA spellings excluded — the same values
  ``dropna().astype(str).unique()[:10]`` yields.
* Null counts use the pandas NA set, so ``missing_percentage`` agrees.
* ``data_type`` is a best-effort pandas equivalent (``int64``,
  ``float64``, ``bool``, ``object``) for display only: nothing
  analytical consumes it, and the scan engine's native types differ by
  necessity.
* Numeric aggregates may differ from pandas in the last floating-point
  ulp (different summation order). Tests compare with tolerance.

The legacy ``DatasetProfiler`` is untouched and remains the small-data
path. This module is the large-data path.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from framework.ingestion.scan import DatasetScan

#: Pandas equivalent names for display. Informational only.
_TYPE_MAP = {
    "BIGINT": "int64",
    "HUGEINT": "int64",
    "INTEGER": "int64",
    "INT": "int64",
    "SMALLINT": "int64",
    "TINYINT": "int64",
    "DOUBLE": "float64",
    "FLOAT": "float64",
    "REAL": "float64",
    "DECIMAL": "float64",
    "NUMERIC": "float64",
    "BOOLEAN": "bool",
    "BOOL": "bool",
}

_NUMERIC_KINDS = set(_TYPE_MAP) - {"BOOLEAN", "BOOL"}

_TEMPORAL_KINDS = ("DATE", "TIMESTAMP", "TIMESTAMPTZ", "TIME", "TIMETZ")

#: Copied from ``DatasetProfiler.analyze_column``: the identifier rule is
#: replicated, not reinterpreted. Any change there must be mirrored here
#: (pinned by the equality tests).
_IDENTIFIER_KEYWORDS = [
    "id", "host", "hostname", "asset", "device", "server", "system",
    "machine",
]

_COMMON_CATEGORIES = [
    "HIGH", "MEDIUM", "LOW", "CRITICAL", "OPEN", "CLOSED", "TRUE",
    "FALSE", "YES", "NO", "NORMAL",
]


def profile_scan(scan: DatasetScan) -> Dict[str, Any]:
    """Profile the scanned source in the legacy profile shape."""

    row_count = scan.count()
    columns = scan.columns

    # One aggregation pass feeds every column's unique and null counts
    # (see DatasetScan.inventory); samples stream with early exit.
    inventory = scan.inventory()

    if row_count > 0 and columns:
        missing = round(
            sum(
                inventory[column]["null_values"] / row_count
                for column in columns
            )
            / len(columns)
            * 100,
            2,
        )
    else:
        # Matches the legacy formula's degenerate value (mean over an
        # empty frame), so header-only files profile identically.
        missing = float("nan")

    entries = []

    for column in columns:
        counts = inventory[column]
        entries.append(
            _profile_column(
                scan,
                column,
                row_count,
                counts["null_values"],
                counts["unique_values"],
                scan.appearance_samples(column, limit=10),
            )
        )

    return {
        "dataset_summary": {
            "records": row_count,
            "columns": len(columns),
            "missing_percentage": missing,
        },
        "columns": entries,
    }


def _profile_column(
    scan: DatasetScan,
    column: str,
    row_count: int,
    null_values: int,
    unique_values: int,
    samples: List[str],
) -> Dict[str, Any]:
    native = scan.column_types.get(column, "")
    kind = str(native).upper().split("(")[0].strip()

    info: Dict[str, Any] = {
        "data_type": _TYPE_MAP.get(kind, "object"),
        "unique_values": unique_values,
        "null_values": null_values,
        "column_name": column,
    }

    if kind in _NUMERIC_KINDS or kind in ("BOOLEAN", "BOOL"):
        stats = _numeric_stats(scan, column, kind)
        info.update({"category": "numeric"})
        info.update(stats)
        return info

    # Temporal columns stay categorical with raw samples: parity with the
    # pandas path, which never parses dates. Samples arrive with the
    # digest, so every column is profiled in a single grouped pass.

    if _is_identifier(column, unique_values, row_count, samples):
        info.update({"category": "identifier_like", "sample_values": samples})
    else:
        info.update({"category": "categorical", "sample_values": samples})

    return info


def _numeric_stats(
    scan: DatasetScan, column: str, kind: str
) -> Dict[str, Any]:
    if kind in ("BOOLEAN", "BOOL"):
        stats = scan.column_stats_boolean(column)
    else:
        stats = scan.column_stats(column)

    def number(value: Any) -> float:
        # Legacy parity: pandas yields NaN for min/max/mean over no
        # values (serialised downstream as an unrepresentable marker),
        # but forces std to 0. Replicated exactly, not improved.
        if value is None or (
            isinstance(value, float) and math.isnan(value)
        ):
            return float("nan")

        return float(value)

    minimum = stats["min"]
    maximum = stats["max"]

    return {
        "min": number(minimum),
        "max": number(maximum),
        "mean": number(stats["mean"]),
        "std": float(stats["std"])
        if stats["std"] is not None
        and not (
            isinstance(stats["std"], float) and math.isnan(stats["std"])
        )
        else 0.0,
    }


def _is_identifier(
    column: str, unique_values: int, row_count: int, samples: List[str]
) -> bool:
    lowered = str(column).lower()

    if any(keyword in lowered for keyword in _IDENTIFIER_KEYWORDS):
        return True

    unique_ratio = unique_values / row_count if row_count > 0 else 0
    average_length = (
        sum(len(item) for item in samples) / len(samples)
        if samples
        else 0
    )
    upper = [str(item).upper() for item in samples]
    common = any(item in _COMMON_CATEGORIES for item in upper)

    return bool(
        unique_ratio > 0.8 and average_length >= 6 and not common
    )
