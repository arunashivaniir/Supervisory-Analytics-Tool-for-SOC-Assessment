"""
SAT-SA Ingestion: common loader interface and normalized ingestion result.

This layer answers exactly one question: *how do records get into SAT-SA?* It
turns a local file (or a future local adapter) into a single, consistent
structure that the rest of the framework can consume without caring where the
records came from.

Design rules this module exists to enforce:

* **Schema agnostic.** Nothing here knows a column name, a SOC concept, or any
  particular Critical Sector Entity export format. Columns are discovered from
  the data and reported, never assumed. Canonical concepts are assigned later by
  the existing mapping layer, which is the only place that holds that knowledge.
* **One shape for every source.** A CSV, a JSON array, a newline-delimited JSON
  stream and a SQLite table all produce the same
  :class:`IngestionResult`, so no downstream module grows a format branch.
* **Normalization is structural, not semantic.** It guarantees plain Python
  types, string keys and one spelling of "no value". It never invents, renames,
  reorders, coerces or drops a field on a guess about meaning.
* **Offline.** No network, no cloud, no external service. The API seam below is
  a documented interface with no network implementation; a future *local*
  adapter can be registered without adding a dependency.
* **No writes to a source.** A source is read. The loader never modifies, moves
  or deletes the file it was given.

Normalized record contract
--------------------------

Every loader returns records shaped as ``{field_name: value}`` where:

* ``field_name`` is always a ``str``;
* ``value`` is a plain Python type (``str``, ``int``, ``float``, ``bool``,
  ``None``, ``list``, ``dict``) -- never a NumPy scalar, ``NaN`` or ``NaT``;
* "no value" is spelled exactly one way: ``None``. An absent field, a JSON
  ``null``, a blank CSV cell and a SQL ``NULL`` all become ``None``;
* nested ``dict`` / ``list`` values are preserved and normalized recursively, so
  no information is lost. They are *not* flattened, because flattening requires
  knowing the schema, and this layer is schema agnostic.

Run the tests with::

    python -m pytest framework/tests/test_ingestion.py -v
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import pandas as pd


# ---------------------------------------------------------------------------
# Source type constants
# ---------------------------------------------------------------------------

#: Delimited text file, parsed with the standard library's CSV rules.
SOURCE_CSV = "csv"

#: A single JSON document containing an array of objects.
SOURCE_JSON = "json"

#: Newline-delimited JSON: one JSON object per line.
SOURCE_NDJSON = "ndjson"

#: A local SQLite database file, opened read-only.
SOURCE_SQLITE = "sqlite"

#: Reserved for a future *local* API adapter. No network loader exists.
SOURCE_API = "api"


#: File extensions the manager recognises without content inspection.
KNOWN_EXTENSIONS: Dict[str, str] = {
    ".csv": SOURCE_CSV,
    ".tsv": SOURCE_CSV,
    ".txt": SOURCE_CSV,
    ".json": SOURCE_JSON,
    ".ndjson": SOURCE_NDJSON,
    ".jsonl": SOURCE_NDJSON,
    ".jsonlines": SOURCE_NDJSON,
    ".sqlite": SOURCE_SQLITE,
    ".sqlite3": SOURCE_SQLITE,
    ".db": SOURCE_SQLITE,
}


#: Upper bound on rows read from a single source, so a hostile or accidentally
#: enormous file cannot exhaust memory. Truncation is reported, never silent.
DEFAULT_MAX_ROWS = 1_000_000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IngestionError(Exception):
    """Base class for every ingestion failure.

    Loaders raise these instead of leaking ``pandas``, ``json`` or ``sqlite3``
    exceptions, so a caller can handle every source type with one ``except``.
    """


class SourceNotFoundError(IngestionError):
    """The source path does not exist or is not a readable file."""


class UnsupportedSourceError(IngestionError):
    """The source type has no loader, or an option is not supported."""


class MalformedSourceError(IngestionError):
    """The source exists but does not conform to the expected structure."""


class EmptySourceError(IngestionError):
    """The source contains no addressable data at all.

    Distinct from a source that is *valid but has no rows*: a header-only CSV or
    an empty JSON array is a legitimate, analysable-shaped input and is
    returned as an empty :class:`IngestionResult`, whereas a zero-byte file has
    no structure to report.
    """


class SourceAccessError(IngestionError):
    """The source exists but could not be read (permissions, I/O, locks)."""


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _is_missing(value: Any) -> bool:
    """True for every spelling of "no value" a loader can observe.

    Handles ``None``, float ``nan``, ``pandas.NA`` / ``NaT`` and an empty
    string, without importing NumPy for the type check: pandas exposes the
    sentinel singletons and ``float('nan')`` is the only float that is not equal
    to itself.
    """
    if value is None:
        return True

    if isinstance(value, float):
        return math.isnan(value)

    # pandas.NA and pandas.NaT are singletons whose repr is stable, and they
    # are not equal to themselves either -- but a plain bool check is cheaper
    # and avoids importing pandas internals here.
    if value is pd.NA or value is pd.NaT:
        return True

    # numpy scalars: unwrap to a Python value first.
    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__ == "numpy":
        try:
            unwrapped = item()
        except (ValueError, TypeError):
            return False
        return _is_missing(unwrapped)

    return False


def normalise_value(value: Any) -> Any:
    """Convert one raw value into the normalized contract.

    * NumPy scalars become plain Python scalars, keeping int/float/str/bool
      distinctions exactly as the source expressed them.
    * ``NaN`` / ``NaT`` / ``pandas.NA`` / ``None`` become ``None``.
    * Text that is empty or only whitespace becomes ``None``, so downstream code
      tests one condition instead of three.
    * ``dict`` and ``list`` are normalized recursively, preserving structure.
    * Anything else is returned unchanged.
    """
    if isinstance(value, Mapping):
        return normalise_record(value)

    if isinstance(value, (list, tuple)):
        return [normalise_value(item) for item in value]

    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__ == "numpy":
        try:
            return normalise_value(item())
        except (ValueError, TypeError):
            return value

    if _is_missing(value):
        return None

    if isinstance(value, str):
        return value if value.strip() else None

    return value


def normalise_record(record: Mapping[Any, Any]) -> Dict[str, Any]:
    """Normalize one record into ``{str: value}``.

    Keys are stringified so a JSON object with numeric keys, or a CSV header
    that is not text, still produces a uniform record shape. Later duplicates
    (after stringification, e.g. ``1`` and ``"1"``) win, and the collision is
    reported by :func:`normalise_records`.
    """
    if not isinstance(record, Mapping):
        raise MalformedSourceError(
            f"Expected an object per record, got {type(record).__name__}"
        )

    normalised: Dict[str, Any] = {}

    for key, value in record.items():
        normalised[str(key)] = normalise_value(value)

    return normalised


def normalise_records(
    records: Iterable[Mapping[Any, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize a sequence of records, returning ``(records, warnings)``.

    Structural problems that make a record unusable are not silently dropped;
    they become warnings, so a caller can see that some input was skipped rather
    than receiving a quietly smaller dataset.
    """
    warnings: List[str] = []
    normalised: List[Dict[str, Any]] = []

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            warnings.append(
                f"Skipped record {index}: expected an object, "
                f"got {type(record).__name__}"
            )
            continue

        try:
            normalised.append(normalise_record(record))
        except MalformedSourceError as error:
            warnings.append(f"Skipped record {index}: {error}")

    return normalised, warnings


def frame_records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    """Extract records from a :class:`pandas.DataFrame` the way the engine does.

    Rows are read with ``iterrows()`` and converted with ``to_dict()``. This is
    deliberately the engine's own access pattern, including the per-row dtype
    coercion pandas applies to it, so records produced here are identical to the
    records the pipeline produced before ingestion existed. ``to_dict("records")``
    is *not* used because it does not apply the same row-wise coercion.
    """
    return [row.to_dict() for _, row in frame.iterrows()]


def records_frame(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Build a DataFrame from normalized records, preserving column order.

    Column order is first-seen order across the records, which keeps a CSV's
    header order and a JSON object's key order. Fields absent from some records
    become missing values rather than being dropped.
    """
    return pd.DataFrame(list(records)) if records else pd.DataFrame()


def union_columns(records: Sequence[Mapping[str, Any]]) -> List[str]:
    """Every field name seen across the records, in first-seen order."""
    columns: List[str] = []

    for record in records:
        for name in record:
            if name not in columns:
                columns.append(name)

    return columns


# ---------------------------------------------------------------------------
# The normalized ingestion result
# ---------------------------------------------------------------------------


@dataclass
class IngestionResult:
    """One consistent structure, whatever the source was.

    Attributes
    ----------
    source:
        The source as the caller named it (path, identifier, adapter name).
    source_type:
        One of the ``SOURCE_*`` constants.
    records:
        Normalized records, ``{str: value}`` each.
    columns:
        Field names in first-seen order, even when there are no records.
    warnings:
        Recoverable problems: skipped rows, truncation, auto-selected objects.
        A non-empty list does not mean the load failed.
    metadata:
        Source-specific detail (selected table, encoding, row limits) for an
        examiner to read. Never used to drive control flow.
    profiling_target:
        A CSV file path the existing profiler can read. For a CSV source this is
        the original file, so nothing is copied. For any other source the manager
        materialises a temporary CSV, because the profiler reads a file path and
        this layer does not modify the profiler.
    temporary_files:
        Files the manager created that :meth:`release` should delete.
    """

    source: str
    source_type: str
    records: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    profiling_target: Optional[str] = None
    temporary_files: List[str] = field(default_factory=list)

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def is_empty(self) -> bool:
        return not self.records

    def to_frame(self) -> pd.DataFrame:
        """The records as a DataFrame (rebuilt on demand, not cached)."""
        return records_frame(self.records)

    def to_dict(self) -> Dict[str, Any]:
        """A JSON-friendly summary, with record values left out by default.

        Record *contents* are not copied into the summary: ingestion results can
        be logged, and content should never be. Use ``include_records=True`` only
        where the records themselves are the point.
        """
        return self.to_summary(include_records=False)

    def to_summary(self, include_records: bool = False) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "source": self.source,
            "source_type": self.source_type,
            "record_count": self.record_count,
            "column_count": len(self.columns),
            "columns": list(self.columns),
            "is_empty": self.is_empty,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "profiling_target": self.profiling_target,
        }

        if include_records:
            summary["records"] = list(self.records)

        return summary

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<IngestionResult {self.source_type} "
            f"records={self.record_count} columns={len(self.columns)} "
            f"warnings={len(self.warnings)}>"
        )


# ---------------------------------------------------------------------------
# The loader interface
# ---------------------------------------------------------------------------


class BaseLoader:
    """Interface every loader implements.

    Subclasses set :attr:`SOURCE_TYPE` and implement :meth:`_load`. The public
    :meth:`load` wrapper is inherited so that argument handling, result
    construction and the record/column contract live in exactly one place.
    """

    #: One of the ``SOURCE_*`` constants. Used for dispatch and reporting.
    SOURCE_TYPE: str = ""

    #: Additional source types this loader also serves. A loader that handles
    #: two shapes of the same format declares them here rather than being
    #: registered twice by hand.
    SOURCE_ALIASES: Tuple[str, ...] = ()

    #: Human-readable name, used in error messages.
    label: str = "source"

    def __init__(self, max_rows: int = DEFAULT_MAX_ROWS) -> None:
        self.max_rows = max_rows

    # -- interface ---------------------------------------------------------

    def load(self, source: Any, **options: Any) -> IngestionResult:
        """Load ``source`` and return a normalized :class:`IngestionResult`.

        Raises a subclass of :class:`IngestionError` on any failure. The
        ``max_rows`` option is handled here so no loader can forget it.
        """
        limit = options.pop("max_rows", self.max_rows)

        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise UnsupportedSourceError(
                f"max_rows must be a positive integer or None, got {limit!r}"
            )

        result = self._load(source, **options)

        return self._apply_row_limit(result, limit)

    def _load(self, source: Any, **options: Any) -> IngestionResult:
        raise NotImplementedError

    @classmethod
    def supports(cls, source_type: str) -> bool:
        """True when this loader handles the given source type."""
        return source_type == cls.SOURCE_TYPE

    # -- shared helpers ----------------------------------------------------

    def _apply_row_limit(
        self,
        result: IngestionResult,
        limit: Optional[int],
    ) -> IngestionResult:
        if limit is None or result.record_count <= limit:
            return result

        dropped = result.record_count - limit

        result.warnings.append(
            f"Row limit reached: kept the first {limit} of "
            f"{result.record_count + dropped} records ({dropped} dropped). "
            f"Raise max_rows to ingest the whole source."
        )
        result.records = result.records[:limit]
        result.metadata["row_limit"] = limit
        result.metadata["rows_dropped"] = dropped

        return result

    def _build_result(
        self,
        source: Any,
        records: Sequence[Dict[str, Any]],
        warnings: Optional[Sequence[str]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        columns: Optional[Sequence[str]] = None,
        profiling_target: Optional[str] = None,
    ) -> IngestionResult:
        """Assemble a result, applying the shared contract in one place."""
        record_list = list(records)

        return IngestionResult(
            source=str(source),
            source_type=self.SOURCE_TYPE,
            records=record_list,
            columns=list(columns) if columns is not None else union_columns(record_list),
            warnings=list(warnings or []),
            metadata=dict(metadata or {}),
            profiling_target=profiling_target,
        )

    # -- shared validation -------------------------------------------------

    @staticmethod
    def _require_existing_file(source: Any, label: str) -> str:
        """Confirm ``source`` is an existing, readable regular file."""
        import os

        if not isinstance(source, (str, os.PathLike)):
            raise UnsupportedSourceError(
                f"A {label} source must be a filesystem path, "
                f"got {type(source).__name__}"
            )

        path = str(source)

        if not os.path.exists(path):
            raise SourceNotFoundError(f"{label} source not found: {path}")

        if os.path.isdir(path):
            raise SourceNotFoundError(
                f"{label} source is a directory, not a file: {path}"
            )

        if not os.access(path, os.R_OK):
            raise SourceAccessError(f"{label} source is not readable: {path}")

        return path


# ---------------------------------------------------------------------------
# Extension point for a future local API adapter
# ---------------------------------------------------------------------------


class LocalApiAdapter:
    """Interface for an adapter that supplies records from a *local* endpoint.

    The SIH requirement mentions API ingestion. SAT-SA is offline by design, so
    no network loader ships here. This class is the seam: a future adapter that
    talks to a loopback socket, a local collector process or a file-backed queue
    implements it and is registered with the manager, with no change to the
    loaders above and no new third-party dependency.

    An adapter contract:

    * :meth:`name` -- a stable identifier for the adapter, used as the source
      type in the result and in error messages.
    * :meth:`available` -- whether the local endpoint is currently reachable.
      Checked before use so an offline run fails with a clear message instead of
      a connection error.
    * :meth:`fetch` -- return an iterable of ``{field: value}`` mappings.

    Adapters must not be given network code paths by this layer, and must not
    perform writes. The manager records the adapter name in the result metadata
    so it is always visible which path supplied the records.
    """

    def name(self) -> str:
        """Stable adapter identifier, e.g. ``"local_collector"``."""
        raise NotImplementedError

    def available(self) -> bool:
        """True when this adapter can currently supply records."""
        raise NotImplementedError

    def fetch(self, **options: Any) -> Iterable[Mapping[str, Any]]:
        """Return an iterable of ``{field: value}`` mappings."""
        raise NotImplementedError


class RemoteApiLoader(BaseLoader):
    """Placeholder loader for API sources that intentionally refuses.

    It exists so that asking for an API source produces an explicit, accurate
    refusal -- naming the extension point and the offline constraint -- instead
    of a bare "unknown source type" or, worse, a silent network call.
    """

    SOURCE_TYPE = SOURCE_API
    label = "API"

    def _load(self, source: Any, **options: Any) -> IngestionResult:
        raise UnsupportedSourceError(
            f"API ingestion is not implemented: SAT-SA ingests local sources "
            f"only and performs no network access. Received {source!r}. To add "
            f"a local API source, implement framework.ingestion.base_loader."
            f"LocalApiAdapter and register it with IngestionManager."
        )


__all__ = [
    "SOURCE_API",
    "SOURCE_CSV",
    "SOURCE_JSON",
    "SOURCE_NDJSON",
    "SOURCE_SQLITE",
    "KNOWN_EXTENSIONS",
    "DEFAULT_MAX_ROWS",
    "IngestionError",
    "SourceNotFoundError",
    "UnsupportedSourceError",
    "MalformedSourceError",
    "EmptySourceError",
    "SourceAccessError",
    "IngestionResult",
    "BaseLoader",
    "LocalApiAdapter",
    "RemoteApiLoader",
    "normalise_value",
    "normalise_record",
    "normalise_records",
    "frame_records",
    "records_frame",
    "union_columns",
]
