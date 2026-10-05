"""
CSV ingestion.

Responsibilities:

* read a delimited text file as data, never as instructions;
* cope with the encodings that actually arrive from spreadsheet exports, rather
  than failing on the first non-UTF-8 byte;
* distinguish "no data" (a zero-byte file) from "no rows" (a header-only file);
* report a structurally broken file as a clear error instead of a pandas
  traceback;
* return normalized records.

Fidelity note
-------------

For a plain UTF-8 CSV -- the common case, and the case the existing pipeline
depends on -- this loader calls ``pandas.read_csv(path)`` with *no* additional
arguments, so the DataFrame is identical to the one the pipeline used to build
itself. Records are then extracted with ``iterrows()`` + ``to_dict()``, the
engine's own access pattern, so the values reaching the mapper are unchanged.
Only the extra ``encoding``/``delimiter`` arguments appear for files that need
them.

Run the tests with::

    python -m pytest framework/tests/test_ingestion.py -v
"""

from __future__ import annotations

import csv
import io
import os
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from framework.ingestion.base_loader import (
    SOURCE_CSV,
    BaseLoader,
    EmptySourceError,
    IngestionResult,
    MalformedSourceError,
    SourceAccessError,
    frame_records,
    normalise_records,
    union_columns,
)


#: Encoding candidates, tried in order. ``utf-8`` comes first because it is the
#: only encoding that needs no BOM handling; ``utf-8-sig`` is selected
#: separately, and only when a BOM is actually present. ``latin-1`` decodes any
#: byte sequence, so it is the last resort: a file that only survives that
#: fallback is reported as a warning rather than trusted silently.
ENCODING_CANDIDATES = ("utf-8", "cp1252", "latin-1")

#: How much of the file to inspect when guessing the encoding.
SNIFF_BYTES = 65536

#: Extensions whose delimiter is a tab unless the caller overrides it.
TAB_EXTENSIONS = (".tsv",)


class CsvLoader(BaseLoader):
    """Loads delimited text into normalized records."""

    SOURCE_TYPE = SOURCE_CSV
    label = "CSV"

    def _load(
        self,
        source: Any,
        delimiter: Optional[str] = None,
        encoding: Optional[str] = None,
        skip_blank_lines: bool = True,
        **options: Any,
    ) -> IngestionResult:
        path = self._require_existing_file(source, self.label)

        warnings: List[str] = []
        size = self._file_size(path)

        if size == 0:
            raise EmptySourceError(
                f"CSV source is empty (0 bytes): {path}. There is no header to "
                f"report, so there is nothing to analyse. Supply a file with at "
                f"least a header row."
            )

        resolved_encoding = encoding or self._detect_encoding(path, warnings)

        if delimiter is None and self._looks_tab_separated(path, resolved_encoding):
            delimiter = "\t"

        self._check_field_consistency(path, resolved_encoding, delimiter)

        frame = self._read_frame(
            path=path,
            encoding=resolved_encoding,
            delimiter=delimiter,
            skip_blank_lines=skip_blank_lines,
        )

        if frame.shape[1] == 0:
            raise EmptySourceError(
                f"CSV source has no columns: {path}"
            )

        # Column names come from the file, never from a hardcoded list. They are
        # made text so that ``map_record``'s ``source_column not in record``
        # check and the profiler's ``column.get("column_name", "")`` both work
        # on a uniform type.
        frame = frame.rename(columns=lambda name: str(name))

        records, record_warnings = normalise_records(frame_records(frame))
        warnings.extend(record_warnings)

        if frame.shape[0] == 0:
            warnings.append(
                f"CSV has a header but no data rows: {path}. "
                f"Columns discovered: {len(frame.columns)}."
            )

        return self._build_result(
            source=path,
            records=records,
            warnings=warnings,
            columns=union_columns(records) or [str(c) for c in frame.columns],
            profiling_target=path,
            metadata={
                "encoding": resolved_encoding,
                "encoding_detected": encoding is None,
                "delimiter": delimiter or ",",
                "delimiter_detected": delimiter is None,
                "size_bytes": size,
                "rows_read": int(frame.shape[0]),
                "columns_read": [str(c) for c in frame.columns],
            },
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _read_frame(
        self,
        path: str,
        encoding: str,
        delimiter: Optional[str],
        skip_blank_lines: bool,
    ) -> pd.DataFrame:
        """Read the file, translating pandas failures into ingestion errors."""
        read_options: Dict[str, Any] = {
            "skip_blank_lines": skip_blank_lines,
        }

        if delimiter is not None:
            read_options["sep"] = delimiter

        try:
            if encoding == "utf-8":
                # The default case. No extra arguments, so the DataFrame is the
                # same one ``pandas.read_csv(path)`` would have produced.
                return pd.read_csv(path, **read_options)

            return pd.read_csv(path, encoding=encoding, **read_options)

        except pd.errors.EmptyDataError as error:
            raise EmptySourceError(
                f"CSV source contains no parsable content: {path}"
            ) from error

        except pd.errors.ParserError as error:
            raise MalformedSourceError(
                f"Malformed CSV: {path} has rows that do not match its header "
                f"({len(error.args[0].splitlines()) if error.args else 0} line(s) "
                f"reported by the parser). Every row must have the same number "
                f"of fields as the header."
            ) from error

        except UnicodeDecodeError as error:
            raise MalformedSourceError(
                f"CSV source is not decodable as {encoding}: {path}"
            ) from error

        except (OSError, IOError) as error:
            raise SourceAccessError(
                f"Could not read CSV source: {path} ({error})"
            ) from error

    def _detect_encoding(self, path: str, warnings: List[str]) -> str:
        """Pick the first candidate encoding that decodes the file's head.

        A UTF-8 BOM is reported as ``utf-8-sig`` so the BOM does not end up
        glued to the first column name.
        """
        try:
            with open(path, "rb") as handle:
                head = handle.read(SNIFF_BYTES)
        except (OSError, IOError) as error:
            raise SourceAccessError(
                f"Could not read CSV source: {path} ({error})"
            ) from error

        if head.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"

        for candidate in ENCODING_CANDIDATES:
            try:
                head.decode(candidate)
            except UnicodeDecodeError:
                continue
            else:
                if candidate == "latin-1":
                    warnings.append(
                        f"CSV is not valid UTF-8, CP1252 or Latin-1 text; "
                        f"decoded as latin-1. Non-ASCII characters may be "
                        f"wrong: {path}"
                    )
                return candidate

        # Unreachable in practice: latin-1 decodes any byte. Kept so a future
        # edit that removes latin-1 fails loudly instead of returning None.
        raise MalformedSourceError(  # pragma: no cover
            f"Could not determine an encoding for CSV source: {path}"
        )

    @staticmethod
    def _check_field_consistency(
        path: str,
        encoding: str,
        delimiter: Optional[str],
    ) -> None:
        """Refuse a file whose rows disagree with the header.

        This check exists because of a silent pandas behaviour: when the header
        has exactly one fewer field than the data rows, pandas promotes the first
        column to the *index* instead of raising. The value survives as an index
        but disappears from the data, so a column of evidence would vanish from
        the analysis with no error at all. Comparing the header's field count
        with the first data record's -- using the csv module, so quoted
        delimiters and embedded newlines are counted correctly -- turns that
        case into an explicit error.
        """
        resolved = delimiter or ","

        try:
            with open(
                path, "r", encoding=encoding, errors="replace", newline=""
            ) as handle:
                head = handle.read(SNIFF_BYTES)
        except (OSError, IOError):  # pragma: no cover - already read above
            return

        if len(head) >= SNIFF_BYTES:
            # The read was truncated, so the final record may be cut in half --
            # possibly inside a quoted field spanning many lines. A partial
            # record would give a field count that looks like a real mismatch,
            # so the check is skipped rather than risk refusing a valid file.
            # Genuinely broken files are still caught by pandas below.
            return

        try:
            parsed = [
                row
                for row in csv.reader(io.StringIO(head), delimiter=resolved)
                if row and any(field.strip() for field in row)
            ]
        except csv.Error:
            # A quoting error: leave it to pandas, which reports it properly.
            return

        if len(parsed) < 2:
            return

        header_fields = len(parsed[0])
        row_fields = len(parsed[1])

        if header_fields != row_fields:
            raise MalformedSourceError(
                f"Malformed CSV: the header declares {header_fields} field(s) "
                f"but the first data row has {row_fields}: {path}. Every row "
                f"must have the same number of fields as the header. (A file "
                f"that is short by exactly one field would otherwise be read "
                f"with its first column silently moved out of the data.)"
            )

    @staticmethod
    def _looks_tab_separated(path: str, encoding: str) -> bool:
        """True for a .tsv file, or a header whose first line is tab-delimited."""
        if path.lower().endswith(TAB_EXTENSIONS):
            return True

        try:
            with open(path, "r", encoding=encoding, errors="replace") as handle:
                first_line = handle.readline()
        except (OSError, IOError):
            return False

        return "\t" in first_line and "," not in first_line

    @staticmethod
    def _file_size(path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError as error:  # pragma: no cover - race with the stat above
            raise SourceAccessError(
                f"Could not determine the size of CSV source: {path}"
            ) from error


__all__ = ["CsvLoader", "ENCODING_CANDIDATES"]
