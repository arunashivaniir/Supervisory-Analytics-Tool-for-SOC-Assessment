"""Execution-path selection for SAT-SA Phase 2.

Two paths, one contract:

* ``small`` — the existing record-based flow, byte-identical behaviour,
  covered by the full regression suite.
* ``large`` — analytical scans, bounded memory, full counts; profile,
  mapping, validation and relationships complete; record-level analytics
  deferred to Phase 3 and marked as such, never faked.

Selection is deterministic: an explicit override wins, otherwise JSON
documents always take the small path (their nesting needs the document
loader), and anything else takes the large path above a size threshold.
"""

from __future__ import annotations

import os
from typing import Any, Optional

SMALL = "small"
LARGE = "large"

#: Files at or above this size take the large path. Overridable with
#: ``SATSA_LARGE_PATH_MB``. 64 MB keeps every repository fixture and
#: every committed test dataset on the small path while engaging scans
#: well before memory becomes interesting.
DEFAULT_LARGE_PATH_MB = 64

#: Suffixes the scan layer understands. Anything else takes the small
#: path, including JSON documents (nesting needs the document loader).
SCANNABLE_SUFFIXES = (".csv", ".tsv", ".txt", ".ndjson", ".jsonl")

#: Suffixes that always take the small path regardless of size.
DOCUMENT_SUFFIXES = (".json",)


def large_path_threshold_bytes() -> int:
    """Size threshold for the large path, in bytes."""

    raw = os.environ.get("SATSA_LARGE_PATH_MB")

    if raw is not None:
        try:
            return max(1, int(float(raw))) * 1024 * 1024
        except ValueError:
            pass

    return DEFAULT_LARGE_PATH_MB * 1024 * 1024


def select_execution_mode(
    source: Any,
    override: Optional[str] = None,
) -> str:
    """Choose ``small`` or ``large`` for a source path."""

    if override is not None:
        wanted = str(override).strip().lower()

        if wanted in (SMALL, LARGE):
            return wanted

        raise ValueError(
            "Unknown execution mode %r: use 'small', 'large' or omit "
            "for automatic selection." % (override,)
        )

    env = os.environ.get("SATSA_EXECUTION_MODE")

    if env is not None:
        return select_execution_mode(source, override=env)

    path = str(source)
    suffix = os.path.splitext(path)[1].lower()

    if suffix in DOCUMENT_SUFFIXES:
        return SMALL

    if suffix not in SCANNABLE_SUFFIXES:
        # Unknown suffix (SQLite included): the small path detects by
        # content. Scans stay suffix-gated so a mislabelled file can
        # never enter the large path on a wrong assumption.
        return SMALL

    try:
        size = os.path.getsize(path)
    except OSError:
        return SMALL

    if size >= large_path_threshold_bytes():
        return LARGE

    return SMALL
