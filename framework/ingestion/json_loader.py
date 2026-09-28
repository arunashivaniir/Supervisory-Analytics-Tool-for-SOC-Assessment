"""
JSON ingestion.

Handles the two shapes that SOC exports actually arrive in:

* a **JSON document** whose payload is an array of objects, and
* **newline-delimited JSON** (NDJSON / JSONL), one object per line, which is
  what streaming log and queue exports produce.

A top-level object that wraps an array is also accepted, because "array under a
key" is the most common envelope shape. The wrapper key is discovered from the
document rather than configured, so no particular submitter's schema is
baked in; the key that was used is reported in the result metadata.

Structure is validated, not guessed: a payload element that is not an object is
reported, with its index, rather than being coerced into a one-field record or
silently dropped.

Run the tests with::

    python -m pytest framework/tests/test_ingestion.py -v
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from framework.ingestion.base_loader import (
    SOURCE_JSON,
    SOURCE_NDJSON,
    BaseLoader,
    EmptySourceError,
    IngestionResult,
    MalformedSourceError,
    SourceAccessError,
    normalise_records,
    union_columns,
)


#: Keys checked, in order, when a top-level object wraps the array. Reported in
#: metadata, but the search also falls back to the first array-of-objects value
#: found, so an unfamiliar envelope still loads.
ENVELOPE_KEYS = ("records", "data", "items", "results", "rows", "events")


class JsonLoader(BaseLoader):
    """Loads JSON and newline-delimited JSON into normalized records.

    One loader serves both shapes because they produce identical records; the
    detected shape is reported as the source type.
    """

    SOURCE_TYPE = SOURCE_JSON

    #: The manager can detect and dispatch newline-delimited JSON, and it is the
    #: same reader, so one loader serves both shapes.
    SOURCE_ALIASES = (SOURCE_NDJSON,)

    label = "JSON"

    def _load(
        self,
        source: Any,
        allow_envelope: bool = True,
        max_depth: int = 64,
        **options: Any,
    ) -> IngestionResult:
        path = self._require_existing_file(source, self.label)
        text = self._read_text(path)

        if not text.strip():
            raise EmptySourceError(
                f"JSON source is empty or whitespace only: {path}"
            )

        shape, records, envelope_key = self._parse(text, path, allow_envelope)

        if not records:
            # A valid document with an empty array is structurally sound, so it
            # is returned as an empty result rather than raised: the caller can
            # see "0 records" and carry on, which is different from "no data".
            warning = f"JSON source contains an empty array: {path}"

            return self._finish(
                self._build_result(
                    source=path,
                    records=[],
                    warnings=[warning],
                    columns=[],
                    metadata={"shape": shape},
                ),
                shape,
                text,
                envelope_key,
                None,
            )

        normalised, warnings = normalise_records(records)

        return self._finish(
            self._build_result(
                source=path,
                records=normalised,
                warnings=warnings,
                columns=union_columns(normalised),
                metadata={
                    "shape": shape,
                    "records_in_document": len(records),
                },
            ),
            shape,
            text,
            envelope_key,
            None,
        )

    def _finish(
        self,
        result: IngestionResult,
        shape: str,
        text: str,
        envelope_key: Optional[str],
        extra: Optional[Dict[str, Any]],
    ) -> IngestionResult:
        """Report the *detected* shape as the source type.

        This loader handles both JSON and newline-delimited JSON, so the
        declared type alone would misreport an NDJSON file. Dispatch uses the
        requested type, not this value, so overriding it here is safe.
        """
        result.source_type = shape
        result.metadata["loader"] = type(self).__name__
        result.metadata["envelope_key"] = envelope_key
        result.metadata["size_bytes"] = len(text.encode("utf-8"))

        if extra:
            result.metadata.update(extra)

        return result

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _read_text(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                return handle.read()
        except UnicodeDecodeError as error:
            raise MalformedSourceError(
                f"JSON source is not valid UTF-8: {path}"
            ) from error
        except (OSError, IOError) as error:
            raise SourceAccessError(
                f"Could not read JSON source: {path} ({error})"
            ) from error

    def _parse(
        self,
        text: str,
        path: str,
        allow_envelope: bool,
    ) -> Tuple[str, List[Any], Optional[str]]:
        """Return ``(shape, payload, envelope_key)``.

        A whole-document parse is attempted first, because that is unambiguous.
        Only if that fails is newline-delimited parsing tried, so a file that is
        broken JSON is not silently reinterpreted line by line.
        """
        document_error: Optional[Exception] = None

        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            document_error = error
        else:
            return self._from_document(document, path, allow_envelope)

        # Fall back to newline-delimited JSON.
        records = self._parse_ndjson(text, path)

        if records is not None:
            return SOURCE_NDJSON, records, None

        raise MalformedSourceError(
            f"Malformed JSON: {path} is neither a valid JSON document nor "
            f"valid newline-delimited JSON. Document parse failed at line "
            f"{document_error.lineno if document_error else '?'}, column "
            f"{document_error.colno if document_error else '?'}: "
            f"{document_error.msg if document_error else 'unknown'}. "
            f"NDJSON parse failed because "
            f"{'some lines were not valid JSON objects' if records is None else ''}"
        ) from document_error

    def _from_document(
        self,
        document: Any,
        path: str,
        allow_envelope: bool,
    ) -> Tuple[str, List[Any], Optional[str]]:
        if isinstance(document, list):
            self._require_record_like(document, path, "the top-level array")

            return SOURCE_JSON, document, None

        if isinstance(document, dict):
            if not allow_envelope:
                raise MalformedSourceError(
                    f"JSON source is a single object, not an array of "
                    f"records: {path}"
                )

            return self._from_envelope(document, path)

        raise MalformedSourceError(
            f"JSON source must contain an array of records or an object "
            f"wrapping one, but its top level is "
            f"{type(document).__name__}: {path}"
        )

    @staticmethod
    def _require_record_like(
        payload: Sequence[Any],
        path: str,
        where: str,
    ) -> None:
        """Require at least one object in an otherwise record-shaped array.

        An array of *only* scalars is a wrong shape, not a partially usable
        file, so it is refused. A *mixed* array is handled by the caller: the
        objects load and each skipped element is reported as a warning.
        """
        if not payload:
            return

        if not any(isinstance(item, Mapping) for item in payload):
            kinds = sorted({type(item).__name__ for item in payload})

            raise MalformedSourceError(
                f"JSON source has an array in {where} whose {len(payload)} "
                f"element(s) are all {', '.join(kinds)}, but each record must "
                f"be a JSON object: {path}"
            )

    def _from_envelope(
        self,
        document: Mapping[str, Any],
        path: str,
    ) -> Tuple[str, List[Any], Optional[str]]:
        for key in ENVELOPE_KEYS:
            value = document.get(key)

            if isinstance(value, list):
                self._require_record_like(value, path, f"{key!r}")

                return SOURCE_JSON, value, key

        # Unfamiliar envelope: take the first array-of-objects value, so a
        # submitter's own key name does not need to be configured.
        for key, value in document.items():
            if isinstance(value, list) and self._looks_like_records(value):
                return SOURCE_JSON, value, str(key)

        arrays = [k for k, v in document.items() if isinstance(v, list)]

        if arrays:
            raise MalformedSourceError(
                f"JSON envelope in {path} has an array field "
                f"({', '.join(sorted(str(a) for a in arrays))}) whose elements "
                f"are not objects. Each record must be a JSON object."
            )

        raise MalformedSourceError(
            f"JSON source is an object but holds no array of records: {path}. "
            f"Top-level keys: "
            f"{', '.join(sorted(str(k) for k in document)) or '(none)'}"
        )

    def _parse_ndjson(self, text: str, path: str) -> Optional[List[Any]]:
        """Parse one JSON value per line. Returns ``None`` if that is not it."""
        records: List[Any] = []
        saw_value = False

        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()

            if not stripped:
                continue

            saw_value = True

            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as error:
                if not records:
                    return None

                raise MalformedSourceError(
                    f"Malformed newline-delimited JSON: {path} line {number} "
                    f"is not a valid JSON value: {error.msg}"
                ) from error

        if not saw_value:
            return None

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise MalformedSourceError(
                    f"Malformed newline-delimited JSON: {path} record {index} "
                    f"is a {type(record).__name__}, but every line must be a "
                    f"JSON object."
                )

        return records

    @staticmethod
    def _looks_like_records(candidate: Sequence[Any]) -> bool:
        return bool(candidate) and all(
            isinstance(item, dict) for item in candidate
        )


__all__ = ["JsonLoader", "ENVELOPE_KEYS"]
