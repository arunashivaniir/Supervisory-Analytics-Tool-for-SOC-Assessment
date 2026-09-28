"""Local analytical scan layer for SAT-SA Phase 2.

A ``DatasetScan`` opens a structured file for SQL inspection without
materializing its rows as Python objects: schema, exact counts,
representative samples, column projection, filtered retrieval and
bounded streaming all run inside the embedded engine (DuckDB) and only
the requested subset crosses into Python.

Design rules:

* Only the requested subset is materialized. There is deliberately no
  ``read_all()``: callers that need everything use the small-data path.
* Ordering is file order, made explicit with a generated row number, so
  every bounded read is deterministic.
* Values crossing into Python match the small-data path's conventions:
  NULL becomes None, temporal types arrive as their original text (the
  pandas-based path never parses dates, and neither does this one),
  numbers and booleans keep native types.
* Identifiers are always quoted; filter values are always bound
  parameters. Imported content is data, never SQL.

Supported: CSV/TSV (``csv``), NDJSON (``ndjson``), SQLite tables
(``sqlite``). JSON-array documents stay on the small-data path: their
nesting and envelopes need the document loader, and pretending a flat
scan understands them would be dishonest (see module docstring there).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import duckdb

from framework.ingestion.base_loader import (
    SOURCE_CSV,
    SOURCE_NDJSON,
    SOURCE_SQLITE,
)

#: Filter operators accepted by ``project``/``count_where``/``iter_rows``.
_OPS = ("eq", "ne", "gt", "ge", "lt", "le", "contains", "isnull", "notnull")

#: Pandas-compatible NA spellings. Mirrors ``pandas.read_csv`` defaults so
#: null counts agree with the small-data profiler.
NA_STRINGS = frozenset({
    "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QN", "-NaN", "-nan",
    "1.#IND", "1.#QN", "<NA>", "N/A", "NA", "NULL", "NaN", "None",
    "n/a", "nan", "null",
})


def quote_identifier(name: str) -> str:
    """Quote a column name for SQL. Embedded quotes are escaped."""

    return '"%s"' % str(name).replace('"', '""')


def _is_numeric_type(duckdb_type: str) -> bool:
    """Whether a DuckDB type supports aggregates (not text)."""

    kind = str(duckdb_type).upper().split("(")[0].strip()

    return kind in (
        "BIGINT", "INTEGER", "INT", "SMALLINT", "TINYINT", "HUGEINT",
        "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC",
    )


def _escape_literal(value: str) -> str:
    return "'%s'" % str(value).replace("'", "''")


class ScanError(Exception):
    """A scan that could not be opened or queried."""


class DatasetScan:
    """An open analytical scan over one source file.

    Use as a context manager or call :meth:`close`. All query methods
    translate DuckDB failures into :class:`ScanError` so callers handle
    one exception type.
    """

    def __init__(
        self,
        path: str,
        source_type: str,
        connection: "duckdb.DuckDBPyConnection",
        relation: str,
        raw_relation: Optional[str],
        columns: List[str],
        column_types: Dict[str, str],
        size_bytes: int,
        table: Optional[str] = None,
    ) -> None:
        self.path = path
        self.source_type = source_type
        self._connection = connection
        self._relation = relation
        self._raw_relation = raw_relation
        self.columns = list(columns)
        self.column_types = dict(column_types)
        self.size_bytes = size_bytes
        self.table = table
        self._closed = False

    # ------------------------------------------------------------------
    # lifetime
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release the engine connection. Safe to call twice."""

        if not self._closed:
            self._closed = True

            try:
                self._connection.close()
            except Exception:
                pass

    def __enter__(self) -> "DatasetScan":
        return self

    def __exit__(self, *exception_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _query(
        self, sql: str, parameters: Optional[Sequence[Any]] = None
    ) -> List[Tuple[Any, ...]]:
        if self._closed:
            raise ScanError("Scan is closed: %s" % self.path)

        try:
            cursor = self._connection.execute(sql, parameters or [])
            return cursor.fetchall()
        except Exception as error:
            raise ScanError(
                "Scan query failed on %s: %s" % (self.path, error)
            ) from error

    def _where(
        self, filters: Optional[Sequence[Tuple[str, str, Any]]]
    ) -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        parameters: List[Any] = []

        for column, operator, value in filters or []:
            if column not in self.columns:
                raise ScanError(
                    "Filter on unknown column %r in %s" % (column, self.path)
                )

            if operator not in _OPS:
                raise ScanError("Unknown filter operator %r" % (operator,))

            quoted = quote_identifier(column)

            if operator == "eq":
                clauses.append("%s IS NOT DISTINCT FROM ?" % quoted)
                parameters.append(value)
            elif operator == "ne":
                clauses.append("%s IS DISTINCT FROM ?" % quoted)
                parameters.append(value)
            elif operator == "gt":
                clauses.append("%s > ?" % quoted)
                parameters.append(value)
            elif operator == "ge":
                clauses.append("%s >= ?" % quoted)
                parameters.append(value)
            elif operator == "lt":
                clauses.append("%s < ?" % quoted)
                parameters.append(value)
            elif operator == "le":
                clauses.append("%s <= ?" % quoted)
                parameters.append(value)
            elif operator == "contains":
                clauses.append("CAST(%s AS VARCHAR) LIKE ?" % quoted)
                parameters.append("%%%s%%" % str(value).replace("%", "\\%"))
            elif operator == "isnull":
                clauses.append("%s IS NULL" % quoted)
            elif operator == "notnull":
                clauses.append("%s IS NOT NULL" % quoted)

        if not clauses:
            return "", []

        return "WHERE " + " AND ".join(clauses), parameters

    def _ordered(self, relation: str) -> str:
        # Row numbers follow scan order, which for a sequential file scan
        # is file order. Stated once here so every bounded read shares
        # the same determinism contract.
        return (
            "(SELECT _scan.*, ROW_NUMBER() OVER () AS _satsa_rn "
            "FROM %s AS _scan)" % relation
        )

    @staticmethod
    def _normalise_row(
        columns: Sequence[str], row: Tuple[Any, ...]
    ) -> Dict[str, Any]:
        import datetime

        record: Dict[str, Any] = {}

        for column, value in zip(columns, row):
            if value is None:
                record[column] = None
            elif isinstance(
                value, (datetime.date, datetime.datetime, datetime.time)
            ):
                # The pandas path never parses dates, so dates cross here
                # as text, exactly as the file spelled them in the raw
                # read. Typed reads only feed aggregates, never records.
                record[column] = value.isoformat()
            else:
                record[column] = value

        return record

    # ------------------------------------------------------------------
    # inspection
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Exact row count without materializing rows."""

        rows = self._query("SELECT COUNT(*) FROM %s" % self._relation)

        return int(rows[0][0])

    def count_where(
        self, filters: Optional[Sequence[Tuple[str, str, Any]]] = None
    ) -> int:
        """Exact count of rows matching filters."""

        clause, parameters = self._where(filters)
        rows = self._query(
            "SELECT COUNT(*) FROM %s %s" % (self._relation, clause),
            parameters,
        )

        return int(rows[0][0])

    def null_count(self, column: str) -> int:
        """Exact null count, using pandas-compatible NA spellings.

        Counts engine NULLs plus the raw spellings pandas treats as NA,
        so the figure agrees with ``Series.isnull().sum()``.
        """

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        quoted = quote_identifier(column)
        na_list = ", ".join(_escape_literal(item) for item in NA_STRINGS)

        if self._raw_relation is not None:
            rows = self._query(
                "SELECT COUNT(*) FROM %s WHERE %s IS NULL "
                "OR CAST(%s AS VARCHAR) IN (%s)"
                % (
                    self._raw_relation, quoted, quoted, na_list,
                )
            )
        else:
            rows = self._query(
                "SELECT COUNT(*) FROM %s WHERE %s IS NULL"
                % (self._relation, quoted)
            )

        return int(rows[0][0])

    def distinct_count(self, column: str) -> int:
        """Exact distinct count (NULL excluded, like pandas nunique)."""

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        rows = self._query(
            "SELECT COUNT(DISTINCT %s) FROM %s"
            % (quote_identifier(column), self._relation)
        )

        return int(rows[0][0])

    def duplicate_values(
        self, column: str, limit: int = 50
    ) -> Dict[str, Any]:
        """Values occurring more than once, exact counts.

        Bounded: at most ``limit`` entries cross into Python, with an
        overflow flag. Duplicate-heavy keys are few by nature; a file
        whose every key repeats is reported, not materialized.
        """

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        quoted = quote_identifier(column)
        rows = self._query(
            "SELECT CAST(%s AS VARCHAR) AS _v, COUNT(*) AS _c "
            "FROM %s WHERE %s IS NOT NULL GROUP BY _v "
            "HAVING COUNT(*) > 1 ORDER BY _c DESC, _v LIMIT %d"
            % (quoted, self._relation, quoted, int(limit) + 1)
        )

        truncated = len(rows) > limit
        items = [(value, int(count)) for value, count in rows[:limit]]

        return {"items": items, "truncated": truncated}

    def distinct_values(self, column: str, limit: int = 1000) -> Dict[str, Any]:
        """Distinct non-null values as text, ordered deterministically.

        Bounded with an overflow flag: vocabularies are small in
        practice, and a high-cardinality column must not flood Python.
        """

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        quoted = quote_identifier(column)
        rows = self._query(
            "SELECT DISTINCT CAST(%s AS VARCHAR) AS _v FROM %s "
            "WHERE %s IS NOT NULL ORDER BY _v LIMIT %d"
            % (quoted, self._relation, quoted, int(limit) + 1)
        )

        values = [row[0] for row in rows[:limit]]

        return {"values": values, "truncated": len(rows) > limit}

    def column_stats(self, column: str) -> Dict[str, Any]:
        """min/max/mean/std over non-null values, or all None.

        Only numeric-typed columns aggregate; anything else reports
        None, because averaging text is not statistics.
        """

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        if not _is_numeric_type(self.column_types.get(column, "")):
            return {"min": None, "max": None, "mean": None, "std": None}

        quoted = quote_identifier(column)
        rows = self._query(
            "SELECT MIN(%s), MAX(%s), AVG(%s), STDDEV_SAMP(%s) "
            "FROM %s WHERE %s IS NOT NULL"
            % ((quoted,) * 4 + (self._relation, quoted))
        )
        minimum, maximum, average, std = rows[0]

        def number(value: Any) -> Optional[float]:
            if value is None:
                return None

            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return {
            "min": number(minimum),
            "max": number(maximum),
            "mean": number(average),
            "std": number(std) if number(std) is not None else 0.0,
        }

    def column_stats_boolean(self, column: str) -> Dict[str, Any]:
        """min/max/mean/std for a boolean column via 0/1 cast.

        Pandas treats booleans as numeric, so the scan profiler does
        the same rather than inventing a separate boolean branch.
        """

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        quoted = quote_identifier(column)
        rows = self._query(
            "SELECT MIN(%s::INTEGER), MAX(%s::INTEGER), "
            "AVG(%s::INTEGER), STDDEV_SAMP(%s::INTEGER) "
            "FROM %s WHERE %s IS NOT NULL"
            % ((quoted,) * 4 + (self._relation, quoted))
        )
        minimum, maximum, average, std = rows[0]

        def number(value: Any) -> Optional[float]:
            if value is None:
                return None

            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return {
            "min": number(minimum),
            "max": number(maximum),
            "mean": number(average),
            "std": number(std) if number(std) is not None else 0.0,
        }

    def inventory(self) -> Dict[str, Dict[str, int]]:
        """Exact unique and null counts for every column.

        One small query per column rather than one wide aggregation:
        wide multi-column DISTINCT builds a hash table per column at
        once, which is exactly the memory spike this path exists to
        avoid. Sequential narrow queries keep transient state small;
        the file pages stay hot in cache between them.
        """

        return {
            column: self.column_inventory(column) for column in self.columns
        }

    def column_inventory(self, column: str) -> Dict[str, int]:
        """Exact unique and null counts for one column."""

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        quoted = quote_identifier(column)
        na_list = ", ".join(_escape_literal(item) for item in NA_STRINGS)
        relation = self._raw_relation or self._relation

        rows = self._query(
            "SELECT COUNT(DISTINCT CASE WHEN CAST(%s AS VARCHAR) IN (%s) "
            "THEN NULL ELSE CAST(%s AS VARCHAR) END) AS _u, "
            "SUM(CASE WHEN CAST(%s AS VARCHAR) IS NULL "
            "OR CAST(%s AS VARCHAR) IN (%s) THEN 1 ELSE 0 END) AS _n "
            "FROM %s"
            % (quoted, na_list, quoted, quoted, quoted, na_list, relation)
        )

        unique, nulls = rows[0]

        return {
            "unique_values": int(unique or 0),
            "null_values": int(nulls or 0),
        }

    def column_digest(
        self, column: str, sample_limit: int = 10
    ) -> Dict[str, Any]:
        """Unique count, null count and first-appearance samples.

        Counts come from the inventory aggregation; samples come from
        a top-N-by-first-appearance query. Both run engine-side with
        bounded Python output: only ten sample strings cross over no
        matter how many distinct values the column holds.
        """

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        inventory = self.column_inventory(column)

        return {
            "unique_values": inventory["unique_values"],
            "null_values": inventory["null_values"],
            "samples": self.appearance_samples(column, sample_limit),
        }

    def appearance_samples(
        self, column: str, limit: int = 10
    ) -> List[str]:
        """First distinct raw values in file order, NA spellings skipped.

        Mirrors ``Series.dropna().astype(str).unique()[:10]``: original
        spellings, first-appearance order, pandas NA set excluded. Read
        from the raw (all-varchar) relation so dates arrive as the file
        spelled them, exactly as the pandas path sees them. The
        grouping runs engine-side (spillable); only the top entries
        cross into Python.
        """

        if column not in self.columns:
            raise ScanError(
                "Unknown column %r in %s" % (column, self.path)
            )

        quoted = quote_identifier(column)
        na_list = ", ".join(_escape_literal(item) for item in NA_STRINGS)
        relation = self._raw_relation or self._relation

        rows = self._query(
            "SELECT _t._v FROM (SELECT CAST(%s AS VARCHAR) AS _v, "
            "MIN(_satsa_rn) AS _m FROM %s GROUP BY _v) AS _t "
            "WHERE _t._v IS NOT NULL AND _t._v NOT IN (%s) "
            "ORDER BY _t._m LIMIT %d"
            % (quoted, self._ordered(relation), na_list, int(limit))
        )

        return [str(row[0]) for row in rows]

    # ------------------------------------------------------------------
    # bounded access
    # ------------------------------------------------------------------

    def sample(self, limit: int = 10) -> List[Dict[str, Any]]:
        """First ``limit`` rows in file order."""

        return self.project(self.columns, limit=limit, offset=0)

    def project(
        self,
        columns: Sequence[str],
        limit: int = 1000,
        offset: int = 0,
        filters: Optional[Sequence[Tuple[str, str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Bounded column projection with deterministic file order.

        ``limit`` is mandatory and capped: this API hands out evidence
        samples, never datasets.
        """

        unknown = [name for name in columns if name not in self.columns]

        if unknown:
            raise ScanError(
                "Unknown columns %r in %s" % (unknown, self.path)
            )

        limit = max(0, min(int(limit), 10000))
        offset = max(0, int(offset))
        clause, parameters = self._where(filters)
        names = ", ".join(quote_identifier(name) for name in columns)

        rows = self._query(
            "SELECT %s FROM %s %s ORDER BY _satsa_rn LIMIT %d OFFSET %d"
            % (names, self._ordered(self._relation), clause, limit, offset),
            parameters,
        )

        return [self._normalise_row(columns, row) for row in rows]

    def iter_rows(
        self,
        columns: Sequence[str],
        filters: Optional[Sequence[Tuple[str, str, Any]]] = None,
        batch: int = 10000,
        raw: bool = False,
    ) -> Iterator[Dict[str, Any]]:
        """Stream rows with O(batch) Python memory.

        Single pass: the generator must be consumed once. Aggregation
        callers hold only their own accumulators, never the rows.
        Rows arrive in scan order without an ORDER BY (a full sort
        would materialize the stream this method exists to avoid), so
        this suits order-free aggregation, not paging — use
        :meth:`project` for deterministic pages. ``raw`` reads the
        all-varchar relation.
        """

        unknown = [name for name in columns if name not in self.columns]

        if unknown:
            raise ScanError(
                "Unknown columns %r in %s" % (unknown, self.path)
            )

        clause, parameters = self._where(filters)
        names = ", ".join(quote_identifier(name) for name in columns)
        relation = (
            self._raw_relation if raw and self._raw_relation is not None
            else self._relation
        )
        sql = "SELECT %s FROM %s %s" % (
            names, relation, clause,
        )

        if self._closed:
            raise ScanError("Scan is closed: %s" % self.path)

        try:
            cursor = self._connection.execute(sql, list(parameters or []))

            while True:
                rows = cursor.fetchmany(int(batch))

                if not rows:
                    break

                for row in rows:
                    yield self._normalise_row(columns, row)
        except Exception as error:
            raise ScanError(
                "Scan streaming failed on %s: %s" % (self.path, error)
            ) from error


# ---------------------------------------------------------------------------
# opening
# ---------------------------------------------------------------------------


def open_scan(
    path: str,
    source_type: Optional[str] = None,
    table: Optional[str] = None,
    delimiter: Optional[str] = None,
    encoding: Optional[str] = None,
) -> DatasetScan:
    """Open an analytical scan over a local file.

    ``source_type`` is one of ``csv``/``ndjson``/``sqlite`` (auto-detected
    from the path when omitted). ``table`` is required for SQLite.
    Raises :class:`ScanError` for anything unscannable — including JSON
    documents, which stay on the record path by design.
    """

    if not os.path.isfile(path):
        raise ScanError("Scan source is not a file: %s" % path)

    resolved = (source_type or _detect(path)).strip().lower()

    if resolved not in (SOURCE_CSV, SOURCE_NDJSON, SOURCE_SQLITE):
        raise ScanError(
            "No analytical scan for source type %r (SQLite tables, CSV "
            "and NDJSON are scannable; JSON documents use the record "
            "path): %s" % (resolved, path)
        )

    size_bytes = os.path.getsize(path)
    connection = duckdb.connect()

    # Bounded engine memory with disk spill: aggregations larger than
    # this spill to temp files instead of growing RSS without limit.
    connection.execute(
        "PRAGMA memory_limit='%s'" % _memory_limit()
    )
    connection.execute(
        "PRAGMA temp_directory='%s'" % _temp_directory().replace("'", "''")
    )
    connection.execute("PRAGMA disable_progress_bar")

    try:
        if resolved == SOURCE_CSV:
            relation, raw, columns, types = _open_csv(
                connection, path, delimiter, encoding
            )
        elif resolved == SOURCE_NDJSON:
            relation, raw, columns, types = _open_ndjson(connection, path)
        else:
            relation, raw, columns, types = _open_sqlite(
                connection, path, table
            )
    except ScanError:
        connection.close()
        raise
    except Exception as error:
        connection.close()
        raise ScanError(
            "Could not open scan on %s: %s" % (path, error)
        ) from error

    return DatasetScan(
        path=path,
        source_type=resolved,
        connection=connection,
        relation=relation,
        raw_relation=raw,
        columns=columns,
        column_types=types,
        size_bytes=size_bytes,
        table=table,
    )


def _memory_limit() -> str:
    """Engine memory budget: env ``SATSA_DUCKDB_MEMORY``, default 512MB.

    Deliberately modest: the scan path streams and spills, so it must
    not need gigabytes. Raise it for speed on large machines, never
    for correctness.
    """

    raw = (os.environ.get("SATSA_DUCKDB_MEMORY") or "512MB").strip()

    if not raw:
        return "512MB"

    return raw


def _temp_directory() -> str:
    """Spill directory for larger-than-memory aggregations."""

    import tempfile

    base = os.environ.get("SATSA_DUCKDB_TMP", tempfile.gettempdir())
    path = os.path.join(base, "satsa-duckdb-spill")

    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return base

    return path


def _detect(path: str) -> str:
    suffix = os.path.splitext(path)[1].lower()

    if suffix in (".csv", ".tsv", ".txt"):
        return SOURCE_CSV

    if suffix in (".ndjson", ".jsonl"):
        return SOURCE_NDJSON

    if suffix in (".db", ".sqlite", ".sqlite3"):
        return SOURCE_SQLITE

    if suffix == ".json":
        # A .json document may be an array, an envelope or NDJSON with
        # the wrong suffix. The document loader owns that ambiguity;
        # the scan layer refuses to guess.
        raise ScanError(
            "JSON documents use the record path, not scans "
            "(use .ndjson for newline-delimited JSON): %s" % path
        )

    raise ScanError("Cannot infer a scannable type for %s" % path)


def _open_csv(
    connection: "duckdb.DuckDBPyConnection",
    path: str,
    delimiter: Optional[str],
    encoding: Optional[str],
) -> Tuple[str, Optional[str], List[str], Dict[str, str]]:
    from framework.ingestion.csv_loader import CsvLoader

    loader = CsvLoader()
    warnings: List[str] = []
    resolved_encoding = encoding or loader._detect_encoding(path, warnings)

    if delimiter is None and loader._looks_tab_separated(
        path, resolved_encoding
    ):
        delimiter = "\t"

    options = "header=true, auto_detect=true, quote='\"'"
    escaped = path.replace("'", "''")

    if delimiter is not None:
        options += ", delim='%s'" % delimiter.replace("'", "''")

    if resolved_encoding.lower().replace("-", "") not in ("utf8", "utf8sig"):
        options += ", encoding='%s'" % resolved_encoding.replace("'", "''")

    typed = "(SELECT * FROM read_csv('%s', %s))" % (escaped, options)
    raw = (
        "(SELECT * FROM read_csv('%s', %s, all_varchar=true))"
        % (escaped, options)
    )

    try:
        described = connection.execute(
            "DESCRIBE SELECT * FROM %s" % typed
        ).fetchall()
    except Exception as error:
        raise ScanError(
            "CSV scan could not read %s: %s" % (path, error)
        ) from error

    if not described:
        raise ScanError("CSV scan found no columns: %s" % path)

    columns = [str(row[0]) for row in described]
    types = {str(row[0]): str(row[1]) for row in described}

    return typed, raw, columns, types


def _open_ndjson(
    connection: "duckdb.DuckDBPyConnection",
    path: str,
) -> Tuple[str, Optional[str], List[str], Dict[str, str]]:
    escaped = path.replace("'", "''")
    typed = "(SELECT * FROM read_json_auto('%s'))" % escaped

    try:
        described = connection.execute(
            "DESCRIBE SELECT * FROM %s" % typed
        ).fetchall()
    except Exception as error:
        raise ScanError(
            "NDJSON scan could not read %s: %s" % (path, error)
        ) from error

    if not described:
        raise ScanError("NDJSON scan found no columns: %s" % path)

    columns = [str(row[0]) for row in described]
    types = {str(row[0]): str(row[1]) for row in described}

    # JSON values arrive typed; the raw read keeps original spellings for
    # samples. Nested structures arrive as JSON text either way.
    raw = (
        "(SELECT * FROM read_json_auto('%s', "
        "columns=%s))" % (escaped, _varchar_columns(described))
    )

    return typed, raw, columns, types


def _varchar_columns(described: Sequence[Sequence[Any]]) -> str:
    parts = []

    for row in described:
        parts.append("'%s': 'VARCHAR'" % str(row[0]).replace("'", "''"))

    return "{%s}" % ", ".join(parts)


def _open_sqlite(
    connection: "duckdb.DuckDBPyConnection",
    path: str,
    table: Optional[str],
) -> Tuple[str, Optional[str], List[str], Dict[str, str]]:
    if not table:
        raise ScanError(
            "SQLite scans need a table name: %s" % path
        )

    escaped = path.replace("'", "''")

    try:
        connection.execute(
            "ATTACH '%s' AS _satsa_src (READ_ONLY)" % escaped
        )
        described = connection.execute(
            "DESCRIBE SELECT * FROM _satsa_src.%s" % quote_identifier(table)
        ).fetchall()
    except Exception as error:
        raise ScanError(
            "SQLite scan could not read %s table %s: %s"
            % (path, table, error)
        ) from error

    if not described:
        raise ScanError(
            "SQLite scan found no columns: %s table %s" % (path, table)
        )

    columns = [str(row[0]) for row in described]
    types = {str(row[0]): str(row[1]) for row in described}
    relation = "(SELECT * FROM _satsa_src.%s)" % quote_identifier(table)

    return relation, None, columns, types
