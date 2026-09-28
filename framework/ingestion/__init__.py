"""
SAT-SA Ingestion.

Local, offline source ingestion for the supervisory assessment pipeline.

Loaders:

* :class:`~framework.ingestion.csv_loader.CsvLoader` -- delimited text, with
  encoding detection;
* :class:`~framework.ingestion.json_loader.JsonLoader` -- JSON arrays, wrapped
  envelopes, and newline-delimited JSON;
* :class:`~framework.ingestion.database_loader.DatabaseLoader` -- local SQLite
  files, opened read-only;
* :class:`~framework.ingestion.base_loader.RemoteApiLoader` -- an explicit
  refusal that names the extension point for a future *local* API adapter.

Dispatch and normalisation:

* :class:`~framework.ingestion.ingestion_manager.IngestionManager` -- detects the
  source type, dispatches, and materialises a CSV the profiler can read.

This package is deliberately schema agnostic. It reports the fields a source
happens to contain and never interprets them; assigning SAT-SA concepts to those
fields remains the job of the existing mapping layer.

No network ingestion is implemented. SAT-SA runs fully offline.
"""

from framework.ingestion.base_loader import (
    DEFAULT_MAX_ROWS,
    KNOWN_EXTENSIONS,
    SOURCE_API,
    SOURCE_CSV,
    SOURCE_JSON,
    SOURCE_NDJSON,
    SOURCE_SQLITE,
    BaseLoader,
    EmptySourceError,
    IngestionError,
    IngestionResult,
    LocalApiAdapter,
    MalformedSourceError,
    RemoteApiLoader,
    SourceAccessError,
    SourceNotFoundError,
    UnsupportedSourceError,
    frame_records,
    normalise_record,
    normalise_records,
    normalise_value,
    records_frame,
    union_columns,
)
from framework.ingestion.csv_loader import CsvLoader
from framework.ingestion.database_loader import DatabaseLoader
from framework.ingestion.ingestion_manager import IngestionManager
from framework.ingestion.json_loader import JsonLoader

__all__ = [
    # Source types
    "SOURCE_API",
    "SOURCE_CSV",
    "SOURCE_JSON",
    "SOURCE_NDJSON",
    "SOURCE_SQLITE",
    "KNOWN_EXTENSIONS",
    "DEFAULT_MAX_ROWS",
    # Errors
    "IngestionError",
    "SourceNotFoundError",
    "UnsupportedSourceError",
    "MalformedSourceError",
    "EmptySourceError",
    "SourceAccessError",
    # Structure
    "IngestionResult",
    "BaseLoader",
    "LocalApiAdapter",
    "RemoteApiLoader",
    # Loaders
    "CsvLoader",
    "JsonLoader",
    "DatabaseLoader",
    "IngestionManager",
    # Normalization helpers
    "normalise_value",
    "normalise_record",
    "normalise_records",
    "frame_records",
    "records_frame",
    "union_columns",
]
