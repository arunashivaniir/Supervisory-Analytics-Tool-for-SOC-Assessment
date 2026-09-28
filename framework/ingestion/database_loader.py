"""
SQLite ingestion.

Scope: **local SQLite files only**, opened read-only.

Read-only is enforced by the database engine, not by convention:

* the connection uses a ``file:...?mode=ro`` URI, so SQLite itself refuses to
  open the file for writing;
* ``PRAGMA query_only = ON`` is set on top of that as a second barrier;
* the connection is closed in a ``finally`` block, so a failure cannot leave a
  handle open;
* the statement the caller supplies is checked to be a read, and identifiers are
  validated and quoted rather than interpolated.

This loader never issues a write, a DDL statement, an ``ATTACH``, a ``PRAGMA``
from the caller, or a multi-statement string. Those are refused with a clear
error instead of being relied upon not to occur.

Table and query selection are explicit: pass ``table`` or ``query``. If a
database holds exactly one table, it is selected and a warning records that
this happened, so the choice is always visible in the result. Anything more
ambiguous is an error that lists the available tables.

Network databases (PostgreSQL, MySQL, SQL Server) are out of scope: SAT-SA
performs no network access. A future local adapter can use the
:class:`~framework.ingestion.base_loader.LocalApiAdapter` seam instead.

Run the tests with::

    python -m pytest framework/tests/test_ingestion.py -v
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

from framework.ingestion.base_loader import (
    SOURCE_SQLITE,
    BaseLoader,
    EmptySourceError,
    IngestionResult,
    MalformedSourceError,
    SourceAccessError,
    SourceNotFoundError,
    UnsupportedSourceError,
    normalise_records,
    union_columns,
)


#: A statement that reads and does not change state. ``PRAGMA`` is absent on
#: purpose: some pragmas write to the database file.
READ_ONLY_PREFIXES = ("SELECT", "WITH", "VALUES")

#: Objects that must never appear in a caller-supplied statement.
FORBIDDEN_TOKENS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "begin", "commit",
    "rollback", "savepoint", "truncate", "grant", "revoke", "load_extension",
)

_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_ ]*\Z")


class DatabaseLoader(BaseLoader):
    """Loads a table or query result from a local SQLite file."""

    SOURCE_TYPE = SOURCE_SQLITE
    label = "SQLite"

    def _load(
        self,
        source: Any,
        table: Optional[str] = None,
        query: Optional[str] = None,
        **options: Any,
    ) -> IngestionResult:
        path = self._require_existing_file(source, self.label)
        self._require_sqlite_header(path)

        if table is not None and query is not None:
            raise UnsupportedSourceError(
                f"Pass either table= or query=, not both."
            )

        if table is not None:
            statement, description, selected = self._statement_for_table(path, table)

        elif query is not None:
            statement, description, selected = self._statement_for_query(query)

        else:
            statement, description, selected = self._statement_for_single_table(path)

        rows, columns = self._execute_read_only(path, statement)

        if not columns:
            raise EmptySourceError(
                f"SQLite source produced no columns for {description}: {path}"
            )

        warnings: List[str] = []

        if selected.get("auto_selected"):
            # The caller did not name the table, so the choice is surfaced
            # rather than left implicit in the result.
            warnings.append(
                f"No table or query was specified, so {description} was read. "
                f"Pass table=... or query=... to choose explicitly."
            )

        records: List[Dict[str, Any]] = [dict(zip(columns, row)) for row in rows]
        normalised, record_warnings = normalise_records(records)

        warnings.extend(record_warnings)

        if not normalised:
            warnings.append(
                f"{description} returned no rows. Columns available: "
                f"{', '.join(str(c) for c in columns)}."
            )

        return self._build_result(
            source=path,
            records=normalised,
            warnings=warnings,
            columns=union_columns(normalised) or [str(c) for c in columns],
            metadata={
                "loader": type(self).__name__,
                "database": path,
                "selected": selected,
                "statement": statement,
                "connection": "read-only (mode=ro, PRAGMA query_only=ON)",
                "rows_read": len(rows),
                "columns_read": [str(c) for c in columns],
            },
        )

    # ------------------------------------------------------------------
    # statement construction
    # ------------------------------------------------------------------

    def _statement_for_table(
        self,
        path: str,
        table: str,
    ) -> tuple:
        name = self._validate_identifier(table, "table")
        available = self._list_tables(path)

        if name not in available:
            raise MalformedSourceError(
                f"Table {name!r} is not in {path}. Available tables: "
                f"{self._format_names(available) or '(none)'}."
            )

        return (
            f'SELECT * FROM "{name}"',
            f"table {name!r}",
            {"kind": "table", "name": name},
        )

    def _statement_for_query(self, query: str) -> tuple:
        text = str(query).strip().rstrip(";").strip()

        if not text:
            raise UnsupportedSourceError("query= was empty")

        if ";" in text:
            raise UnsupportedSourceError(
                "query= must be a single statement. Multiple statements "
                "separated by ';' are refused so that a read cannot smuggle in "
                "a write."
            )

        first_word = text.split(None, 1)[0].upper() if text.split() else ""

        if first_word not in READ_ONLY_PREFIXES:
            raise UnsupportedSourceError(
                f"query= must begin with one of "
                f"{', '.join(READ_ONLY_PREFIXES)}; got {first_word!r}. This "
                f"loader only issues reads."
            )

        lowered = text.lower()

        for token in FORBIDDEN_TOKENS:
            if re.search(rf"\b{token}\b", lowered):
                raise UnsupportedSourceError(
                    f"query= contains the write or state-changing keyword "
                    f"{token.upper()!r} and was refused. This loader issues "
                    f"reads only."
                )

        return (
            text,
            "supplied query",
            {"kind": "query", "statement": text},
        )

    def _statement_for_single_table(self, path: str) -> tuple:
        """Select the only table, if the database unambiguously has one."""
        available = self._list_tables(path)

        if not available:
            raise EmptySourceError(
                f"SQLite source has no tables: {path}. There is nothing to "
                f"read."
            )

        if len(available) > 1:
            raise UnsupportedSourceError(
                f"{path} contains {len(available)} tables, so the table to "
                f"read is ambiguous. Pass table=... or query=.... Available: "
                f"{self._format_names(available)}."
            )

        name = available[0]

        return (
            f'SELECT * FROM "{name}"',
            f"table {name!r} (auto-selected: it is the only table)",
            {
                "kind": "table",
                "name": name,
                "auto_selected": True,
                "auto_selected_reason": "only table in the database",
            },
        )

    @staticmethod
    def _validate_identifier(name: Any, kind: str) -> str:
        text = str(name).strip()

        if not text:
            raise UnsupportedSourceError(f"{kind}= was empty")

        if "\x00" in text:
            raise UnsupportedSourceError(
                f"{kind}= name may not contain a null byte"
            )

        if not _IDENTIFIER.match(text):
            raise UnsupportedSourceError(
                f"{kind}= name {text!r} is not a plain identifier. Use letters, "
                f"digits, underscores and spaces only; quote odd names with "
                f"query= instead."
            )

        return text

    @staticmethod
    def _format_names(names: List[str]) -> str:
        return ", ".join(repr(name) for name in names)

    @staticmethod
    def _list_tables(path: str) -> List[str]:
        connection = DatabaseLoader._connect(path)

        try:
            rows = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise MalformedSourceError(
                f"Not a readable SQLite database: {path} ({error})"
            ) from error
        finally:
            connection.close()

        return [str(row[0]) for row in rows]

    # ------------------------------------------------------------------
    # read-only execution
    # ------------------------------------------------------------------

    @staticmethod
    def _connect(path: str) -> sqlite3.Connection:
        """Open the database read-only.

        ``mode=ro`` is the load-bearing part: SQLite refuses write attempts on
        such a connection even if some later code path tried.
        """
        uri = f"file:{_uri_path(path)}?mode=ro"

        try:
            connection = sqlite3.connect(
                uri,
                uri=True,
                timeout=float(os.environ.get("SATSA_SQLITE_TIMEOUT", "5")),
            )
        except sqlite3.OperationalError as error:
            raise SourceAccessError(
                f"Could not open SQLite source read-only: {path} ({error})"
            ) from error

        connection.row_factory = None

        try:
            connection.execute("PRAGMA query_only = ON")
        except sqlite3.DatabaseError as error:  # pragma: no cover - defensive
            connection.close()
            raise SourceAccessError(
                f"Could not enforce read-only mode on {path} ({error})"
            ) from error

        return connection

    def _execute_read_only(
        self,
        path: str,
        statement: str,
    ) -> tuple:
        connection = self._connect(path)

        try:
            cursor = connection.execute(statement)

            # ``cursor.description`` is populated by execute() for a read, which
            # is how the column names are taken from the statement rather than
            # from a guess.
            description = cursor.description or ()

            columns = [str(entry[0]) for entry in description]

            if not columns:
                raise MalformedSourceError(
                    f"Statement returned no columns: {statement!r}"
                )

            rows = cursor.fetchall()

            return rows, columns

        except sqlite3.OperationalError as error:
            message = str(error).lower()

            if "readonly" in message or "read-only" in message:
                raise UnsupportedSourceError(
                    f"SQLite refused the statement because the connection is "
                    f"read-only: {statement!r} ({error})"
                ) from error

            raise MalformedSourceError(
                f"SQLite statement failed for {path}: {statement!r} ({error})"
            ) from error

        except sqlite3.DatabaseError as error:
            raise MalformedSourceError(
                f"SQLite source could not be read: {path} ({error})"
            ) from error

        finally:
            connection.close()

    @staticmethod
    def _require_sqlite_header(path: str) -> None:
        """Confirm the file really is SQLite before opening it.

        ``sqlite3`` would otherwise create an empty database for a mistyped
        path, which would silently turn a bad source into an empty result.
        """
        header = b"SQLite format 3\x00"

        try:
            size = os.path.getsize(path)

            with open(path, "rb") as handle:
                magic = handle.read(len(header))
        except (OSError, IOError) as error:
            raise SourceAccessError(
                f"Could not read SQLite source: {path} ({error})"
            ) from error

        if size == 0:
            raise EmptySourceError(
                f"SQLite source is empty (0 bytes): {path}. The file was "
                f"created but never initialised, so there are no tables to "
                f"read."
            )

        if magic != header:
            raise MalformedSourceError(
                f"Not a SQLite database (bad file header): {path}. The file "
                f"exists but does not begin with 'SQLite format 3'."
            )


def _uri_path(path: str) -> str:
    """Escape a filesystem path for use in a SQLite ``file:`` URI."""
    absolute = os.path.abspath(path)

    if absolute.startswith("/"):
        return absolute

    # Windows drive letter, e.g. C:\\data\\alerts.sqlite
    return "/" + absolute.replace("\\", "/").replace(":", "|")


__all__ = ["DatabaseLoader", "READ_ONLY_PREFIXES"]
