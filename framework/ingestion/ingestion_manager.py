"""
Ingestion dispatch.

One entry point, :meth:`IngestionManager.load`, turns any supported local source
into the same :class:`~framework.ingestion.base_loader.IngestionResult`, so no
downstream module needs to know whether records came from a CSV, a JSON export
or a SQLite table.

Responsibilities:

* **detect** the source type from the extension, falling back to inspecting
  content when the extension is missing or misleading, so a mislabelled file
  still loads (and a wrong guess is reported);
* **accept** an explicit type from the caller, which always wins;
* **dispatch** to the registered loader for that type;
* **materialise** a CSV for sources the profiler cannot read directly.

Why materialisation exists
--------------------------

``DatasetProfiler.profile(file_path)`` reads a file path and calls
``pandas.read_csv`` internally. That is part of the analytical engine, which
this work does not modify. So for a non-CSV source the manager writes the
normalized records to a temporary CSV and hands that path to the profiler. The
temporary files are listed in ``IngestionResult.temporary_files`` and removed by
:meth:`release`. For a CSV source the original file is passed straight through
and nothing is copied.

Offline by design
-----------------

No network loader ships. Asking for ``source_type="api"`` returns an explicit
refusal naming the extension point. A future *local* adapter implements
:class:`~framework.ingestion.base_loader.LocalApiAdapter` and is registered with
:meth:`register_api_adapter`, with no change here.

Run the tests with::

    python -m pytest framework/tests/test_ingestion.py -v
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.ingestion.base_loader import (
    DEFAULT_MAX_ROWS,
    KNOWN_EXTENSIONS,
    SOURCE_API,
    SOURCE_CSV,
    SOURCE_JSON,
    SOURCE_NDJSON,
    SOURCE_SQLITE,
    BaseLoader,
    IngestionError,
    IngestionResult,
    LocalApiAdapter,
    RemoteApiLoader,
    SourceNotFoundError,
    UnsupportedSourceError,
    records_frame,
    union_columns,
)
from framework.ingestion.csv_loader import CsvLoader
from framework.ingestion.database_loader import DatabaseLoader
from framework.ingestion.json_loader import JsonLoader


#: First bytes of a SQLite file, used when the extension is unhelpful.
SQLITE_MAGIC = b"SQLite format 3\x00"

#: Prefix on every materialised CSV, so a stray file is identifiable and can be
#: swept up if a process is killed before cleanup runs.
TEMP_CSV_PREFIX = "sat-sa-ingest-"


def _unlink_quietly(path: str) -> None:
    """Delete a file, ignoring the case where it is already gone."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:  # pragma: no cover - best effort cleanup
        pass


class IngestionManager:
    """Detects, dispatches and normalises ingestion of a local source."""

    def __init__(
        self,
        loaders: Optional[Sequence[BaseLoader]] = None,
        max_rows: int = DEFAULT_MAX_ROWS,
        materialise: bool = True,
    ) -> None:
        if loaders is None:
            loaders = [
                CsvLoader(max_rows=max_rows),
                JsonLoader(max_rows=max_rows),
                DatabaseLoader(max_rows=max_rows),
                RemoteApiLoader(max_rows=max_rows),
            ]

        self._loaders: Dict[str, BaseLoader] = {}
        self._api_adapter: Optional[LocalApiAdapter] = None
        self._created_files: set = set()

        for loader in loaders:
            self.register(loader)

        self.max_rows = max_rows
        self.materialise_enabled = materialise

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, loader: BaseLoader) -> None:
        """Register a loader for its declared source type and any aliases."""
        source_type = loader.SOURCE_TYPE

        if not source_type:
            raise UnsupportedSourceError(
                f"{type(loader).__name__} does not declare SOURCE_TYPE"
            )

        self._loaders[source_type] = loader

        for alias in getattr(loader, "SOURCE_ALIASES", ()):
            self._loaders[alias] = loader

    def register_api_adapter(self, adapter: LocalApiAdapter) -> None:
        """Register a local API adapter (the future-API extension point).

        The adapter must expose ``name()``, ``available()`` and ``fetch()``. It
        is not a network adapter: SAT-SA does not open sockets, and nothing here
        will do so on the adapter's behalf.
        """
        for method in ("name", "available", "fetch"):
            if not callable(getattr(adapter, method, None)):
                raise UnsupportedSourceError(
                    f"{type(adapter).__name__} is not a valid adapter: it has "
                    f"no callable {method}(). Implement "
                    f"framework.ingestion.base_loader.LocalApiAdapter."
                )

        self._api_adapter = adapter

    @property
    def api_adapter(self) -> Optional[LocalApiAdapter]:
        return self._api_adapter

    @property
    def supported_types(self) -> List[str]:
        return sorted(self._loaders)

    # ------------------------------------------------------------------
    # detection
    # ------------------------------------------------------------------

    def detect_source_type(self, source: Any) -> str:
        """Guess the source type, by extension first and content second.

        Content inspection matters because extensions are frequently wrong: a
        ``.txt`` that is really JSON, or a ``.csv`` that is really a SQLite
        database. Content wins over a conflicting extension only when the
        extension is unknown or generic.
        """
        path = str(source)
        suffix = os.path.splitext(path)[1].lower()

        sniffed = self._sniff(path)

        if suffix in KNOWN_EXTENSIONS:
            declared = KNOWN_EXTENSIONS[suffix]

            if sniffed is None or sniffed == declared:
                return declared

            # A definite mismatch between name and content. Trust the bytes and
            # say so, rather than failing on a file that is actually readable.
            return sniffed

        if sniffed is not None:
            return sniffed

        if suffix in (".tsv",):
            return SOURCE_CSV

        raise UnsupportedSourceError(
            f"Cannot determine how to ingest {path!r}: the extension "
            f"{suffix or '(none)'} is not recognised and the content was not "
            f"identifiable. Pass source_type= explicitly, or use one of: "
            f"{', '.join(sorted(KNOWN_EXTENSIONS))}."
        )

    def _sniff(self, path: str) -> Optional[str]:
        """Identify the content type from the first bytes, or ``None``."""
        if not os.path.isfile(path):
            return None

        try:
            with open(path, "rb") as handle:
                head = handle.read(4096)
        except (OSError, IOError):
            return None

        if head.startswith(SQLITE_MAGIC):
            return SOURCE_SQLITE

        stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")

        if not stripped:
            return None

        lines = [line.strip() for line in stripped.split(b"\n") if line.strip()]

        if not lines:
            return None

        if all(line.startswith(b"{") and line.endswith(b"}") for line in lines):
            # More than one complete object, one per line: newline-delimited.
            if len(lines) > 1:
                return SOURCE_NDJSON

            return SOURCE_JSON

        if stripped[:1] in (b"{", b"["):
            return SOURCE_JSON

        return None

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------

    def load(
        self,
        source: Any,
        source_type: Optional[str] = None,
        **options: Any,
    ) -> IngestionResult:
        """Load ``source`` into a normalized :class:`IngestionResult`.

        ``source_type`` overrides detection. Loader options (``table``,
        ``query``, ``delimiter``, ``max_rows``, ...) are passed through
        untouched, so this layer never needs to know a loader's own parameters.
        """
        if source_type is not None:
            resolved = self._normalise_type(source_type)
        else:
            resolved = self.detect_source_type(source)

        loader = self._loaders.get(resolved)

        if loader is None:
            raise UnsupportedSourceError(
                f"No loader for source type {resolved!r}. Supported: "
                f"{', '.join(self.supported_types)}."
            )

        if resolved == SOURCE_API:
            return self._load_from_api(source, **options)

        result = loader.load(source, **options)

        if self.materialise_enabled:
            self._ensure_profiling_target(result)

        return result

    def _normalise_type(self, source_type: str) -> str:
        text = str(source_type).strip().lower()

        aliases = {
            "text/csv": SOURCE_CSV,
            "application/json": SOURCE_JSON,
            "jsonl": SOURCE_NDJSON,
            "jsonlines": SOURCE_NDJSON,
            "sqlite3": SOURCE_SQLITE,
            "db": SOURCE_SQLITE,
        }

        return aliases.get(text, text)

    def _load_from_api(self, source: Any, **options: Any) -> IngestionResult:
        adapter = self._api_adapter

        if adapter is None:
            # Delegates to the refusing loader for the accurate message.
            return self._loaders[SOURCE_API].load(source, **options)

        if not adapter.available():
            raise IngestionError(
                f"Local API adapter {adapter.name()!r} is registered but not "
                f"available. SAT-SA makes no network connection, so a missing "
                f"local endpoint is reported rather than retried."
            )

        from framework.ingestion.base_loader import (  # local import: avoid cycle
            normalise_records,
        )

        raw = list(adapter.fetch(**options))
        records, warnings = normalise_records(raw)

        result = IngestionResult(
            source=str(source),
            source_type=SOURCE_API,
            records=records,
            columns=union_columns(records),
            warnings=warnings,
            metadata={
                "loader": type(adapter).__name__,
                "adapter": adapter.name(),
                "transport": "local adapter (no network access)",
            },
        )

        if self.materialise_enabled:
            self._ensure_profiling_target(result)

        return result

    # ------------------------------------------------------------------
    # profiling target
    # ------------------------------------------------------------------

    def _ensure_profiling_target(self, result: IngestionResult) -> None:
        """Give the result a CSV path the profiler can read.

        A CSV source already has one. Any other source is written to a
        temporary CSV, because the profiler accepts a file path only and is not
        modified here.
        """
        if result.source_type == SOURCE_CSV and result.profiling_target:
            return

        if result.profiling_target:
            return

        if not result.records:
            # An empty result still needs a header the profiler can read, so it
            # is materialised with the discovered columns and no rows.
            frame = records_frame([])
        else:
            frame = records_frame(result.records)

        handle, path = tempfile.mkstemp(
            prefix=f"{TEMP_CSV_PREFIX}{result.source_type}-",
            suffix=".csv",
        )
        os.close(handle)

        try:
            frame.to_csv(path, index=False)
        except (OSError, IOError) as error:
            try:
                os.unlink(path)
            except OSError:  # pragma: no cover - best effort cleanup
                pass
            raise IngestionError(
                f"Could not materialise a CSV for the profiler from "
                f"{result.source!r}: {error}"
            ) from error

        result.profiling_target = path
        result.temporary_files.append(path)
        result.metadata["materialised_csv"] = path
        self._created_files.add(path)

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    def release(self, result: Optional[IngestionResult]) -> None:
        """Delete any temporary files this manager created for ``result``.

        Safe to call twice, and safe on a result whose files were already
        removed. The records themselves are untouched, so a result stays usable
        after release -- only the materialised CSV goes away.
        """
        if result is None:
            return

        for path in list(result.temporary_files):
            _unlink_quietly(path)
            result.temporary_files.remove(path)
            self._created_files.discard(path)

    def cleanup(self) -> None:
        """Delete every temporary file this manager created and still tracks.

        :meth:`release` handles one result at a time. This is the safety net for
        a caller that loads and forgets: it cannot leak, because the manager
        keeps a record of everything it wrote. Called automatically on
        ``__exit__`` and, best-effort, on ``__del__``.
        """
        for path in list(self._created_files):
            _unlink_quietly(path)
            self._created_files.discard(path)

    @property
    def outstanding_files(self) -> List[str]:
        """Temporary files this manager created and has not yet deleted."""
        return sorted(self._created_files)

    def __enter__(self) -> "IngestionManager":
        return self

    def __exit__(self, *exception_info: Any) -> None:
        self.cleanup()

    def __del__(self) -> None:  # pragma: no cover - interpreter timing
        try:
            self.cleanup()
        except Exception:
            pass


__all__ = ["IngestionManager", "SQLITE_MAGIC"]
