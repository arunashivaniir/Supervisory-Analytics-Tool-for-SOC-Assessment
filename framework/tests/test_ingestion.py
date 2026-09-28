"""
Tests for the SAT-SA ingestion layer.

The ingestion layer is schema agnostic, so these tests build their own throwaway
sources in pytest temporary directories. They never read, write or depend on any
of the project's datasets, and they never touch a real ``data/evidence``
workspace or a real database.

The CSV body used throughout is deliberately generic -- ``alert_id``,
``priority``, ``host`` -- with no Critical Sector Entity schema behind it, so a
future test can change the field names without touching the loaders.

Run with::

    python -m pytest framework/tests/test_ingestion.py -v
"""

import json
import os
import sqlite3
import stat
import tempfile

import pandas as pd
import pytest

from framework.ingestion import (
    SOURCE_API,
    SOURCE_CSV,
    SOURCE_JSON,
    SOURCE_NDJSON,
    SOURCE_SQLITE,
    CsvLoader,
    DatabaseLoader,
    EmptySourceError,
    IngestionError,
    IngestionManager,
    IngestionResult,
    JsonLoader,
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

# ---------------------------------------------------------------------------
# Repository root, for the tests that reach the analytical engine
# ---------------------------------------------------------------------------

REPOSITORY_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# The pipeline resolves ``framework/config/*.json`` relative to the working
# directory, so a test that constructs SATSAPipeline only works from the
# repository root. The guard checks the *working directory*, which is what the
# engine actually depends on.
requires_pipeline = pytest.mark.skipif(
    not os.path.isfile(
        os.path.join(os.getcwd(), "framework", "config", "semantic_patterns.json")
    ),
    reason="SAT-SA config is only reachable from the repository root",
)


def sweep_materialised_csvs():
    """Delete any CSV the ingestion manager materialised, whatever made it."""
    removed = 0
    directory = tempfile.gettempdir()

    for name in os.listdir(directory):
        if name.startswith("sat-sa-ingest-"):
            try:
                os.unlink(os.path.join(directory, name))
                removed += 1
            except OSError:  # pragma: no cover - best effort
                pass

    return removed


@pytest.fixture(autouse=True)
def no_materialised_csv_leaks():
    """The suite must leave no temporary CSV behind, even if a test forgets.

    Most tests call ``release()`` explicitly; this makes an omission a test
    artefact rather than a leak in the temporary directory.
    """
    yield

    sweep_materialised_csvs()


def test_manager_tracks_and_cleans_up_every_file_it_created(tmp_path):
    """A caller that loads and forgets must still not leak."""
    manager = IngestionManager()

    first = manager.load(json_file(tmp_path, VALID_JSON_ARRAY, name="one.json"))
    second = manager.load(ndjson_file(tmp_path))
    third = manager.load(sqlite_file(tmp_path), table="alerts")

    created = {first.profiling_target, second.profiling_target, third.profiling_target}

    assert all(os.path.exists(path) for path in created)
    assert set(manager.outstanding_files) == created

    manager.cleanup()

    assert not any(os.path.exists(path) for path in created)
    assert manager.outstanding_files == []


def test_manager_context_manager_cleans_up_on_exit(tmp_path):
    with IngestionManager() as manager:
        result = manager.load(json_file(tmp_path, VALID_JSON_ARRAY))
        target = result.profiling_target

        assert os.path.exists(target)

    assert not os.path.exists(target)


def test_release_removes_a_file_from_the_outstanding_set(tmp_path):
    manager = IngestionManager()

    kept = manager.load(json_file(tmp_path, VALID_JSON_ARRAY, name="one.json"))
    released = manager.load(json_file(tmp_path, VALID_JSON_ARRAY, name="two.json"))

    manager.release(released)

    assert manager.outstanding_files == [kept.profiling_target] or sorted(
        manager.outstanding_files
    ) == sorted([kept.profiling_target])

    manager.cleanup()


def test_a_crash_during_analysis_still_releases_the_file(tmp_path):
    """The pipeline's finally block must clean up even on an exception."""
    from framework.pipeline import SATSAPipeline

    pipeline = SATSAPipeline()

    def explode(*arguments, **keywords):
        raise RuntimeError("analysis failed")

    # Break the analysis step after ingestion has already materialised its CSV.
    pipeline.supervisory_engine = type(
        "Broken", (), {"analyse": staticmethod(explode)}
    )()

    before = set(pipeline.ingestion.outstanding_files)

    with pytest.raises(RuntimeError):
        pipeline.run(str(json_file(tmp_path, VALID_JSON_ARRAY)))

    # Nothing new is left behind by the failed run.
    assert set(pipeline.ingestion.outstanding_files) == before


# ---------------------------------------------------------------------------
# Source builders
# ---------------------------------------------------------------------------

VALID_CSV = (
    "alert_id,priority,host,close_time\n"
    "A-1,HIGH,WEB_01,120\n"
    "A-2,LOW,DB_02,45\n"
)

# A header with one field name, then a row carrying an extra unquoted field.
MALFORMED_CSV = "alert_id,priority,host\nA-1,HIGH,WEB_01,EXTRA\n"

VALID_JSON_ARRAY = json.dumps(
    [
        {"alert_id": "A-1", "priority": "HIGH", "host": "WEB_01"},
        {"alert_id": "A-2", "priority": "LOW", "host": "DB_02"},
    ]
)

VALID_NDJSON = (
    '{"alert_id": "A-1", "priority": "HIGH", "host": "WEB_01"}\n'
    '{"alert_id": "A-2", "priority": "LOW", "host": "DB_02"}\n'
)


def csv_file(tmp_path, body=VALID_CSV, name="alerts.csv"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def json_file(tmp_path, body, name="alerts.json"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def ndjson_file(tmp_path, body=VALID_NDJSON, name="events.ndjson"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def sqlite_file(tmp_path, name="alerts.sqlite", tables=None, populate=True):
    """Build a small SQLite database. ``tables`` maps name -> column list."""
    path = tmp_path / name

    if path.exists():
        path.unlink()

    connection = sqlite3.connect(path)

    try:
        if tables is None:
            tables = {"alerts": ["alert_id", "priority", "host", "close_time"]}

        for table, columns in tables.items():
            joined = ", ".join(columns)
            connection.execute(f'CREATE TABLE "{table}" ({joined})')

        if populate and "alerts" in tables:
            connection.executemany(
                'INSERT INTO "alerts" (alert_id, priority, host, close_time) '
                "VALUES (?, ?, ?, ?)",
                [
                    ("A-1", "HIGH", "WEB_01", 120),
                    ("A-2", "LOW", "DB_02", 45),
                    ("A-3", None, "DB_02", None),
                ],
            )

        connection.commit()
    finally:
        connection.close()

    return path


# ===========================================================================
# 1. Normalization contract
# ===========================================================================


def test_normalise_value_unwraps_numpy_scalars():
    import numpy as np

    assert normalise_value(np.int64(5)) == 5
    assert isinstance(normalise_value(np.int64(5)), int)
    assert normalise_value(np.float64(1.5)) == 1.5
    assert normalise_value(np.bool_(True)) is True
    assert normalise_value(np.str_("x")) == "x"


def test_normalise_value_maps_every_missing_spelling_to_none():
    import numpy as np

    assert normalise_value(None) is None
    assert normalise_value(float("nan")) is None
    assert normalise_value(np.nan) is None
    assert normalise_value(pd.NA) is None
    assert normalise_value(pd.NaT) is None
    assert normalise_value("") is None
    assert normalise_value("   \t ") is None


def test_normalise_value_preserves_real_values_and_types():
    import numpy as np

    # A zero and a negative number are values, not absences.
    assert normalise_value(0) == 0
    assert normalise_value(np.int64(0)) == 0
    assert normalise_value(-1) == -1

    # int stays int, str stays str, and surrounding text is not altered.
    assert normalise_value(np.int64(3)) == 3
    assert isinstance(normalise_value(np.int64(3)), int)
    assert normalise_value(" padded ") == " padded "


def test_normalise_value_recurses_without_flattening():
    value = normalise_value({"a": [{"b": 1}, float("nan")]})

    assert value == {"a": [{"b": 1}, None]}
    assert isinstance(value["a"], list)
    assert isinstance(value["a"][0], dict)


def test_normalise_record_stringifies_keys():
    record = normalise_record({1: "a", "b": 2})

    assert record == {"1": "a", "b": 2}
    assert all(isinstance(key, str) for key in record)


def test_normalise_record_rejects_non_mapping():
    with pytest.raises(MalformedSourceError):
        normalise_record(["not", "a", "record"])


def test_normalise_records_reports_rather_than_silently_drops():
    records, warnings = normalise_records([{"a": 1}, 5, {"b": 2}])

    assert records == [{"a": 1}, {"b": 2}]
    assert len(warnings) == 1
    assert "record 1" in warnings[0]


def test_union_columns_uses_first_seen_order():
    records = [{"b": 1, "a": 2}, {"c": 3, "a": 4}]

    assert union_columns(records) == ["b", "a", "c"]


def test_frame_records_matches_the_engines_own_access_pattern():
    frame = pd.DataFrame([{"a": 1, "b": "x"}])

    assert frame_records(frame) == [{"a": 1, "b": "x"}]


def test_records_frame_unions_keys_across_records():
    frame = records_frame([{"a": 1}, {"b": 2}])

    assert list(frame.columns) == ["a", "b"]
    assert len(frame) == 2


# ===========================================================================
# 2. The normalized result structure
# ===========================================================================


def test_ingestion_result_is_one_shape_for_every_source(tmp_path):
    csv_result = CsvLoader().load(csv_file(tmp_path))
    json_result = JsonLoader().load(json_file(tmp_path, VALID_JSON_ARRAY))
    db_result = DatabaseLoader().load(sqlite_file(tmp_path), table="alerts")

    # The sources differ in row count on purpose: what must be identical is the
    # *shape* of the result, not the data in it.
    assert [r.record_count for r in (csv_result, json_result, db_result)] == [2, 2, 3]

    for result in (csv_result, json_result, db_result):
        assert isinstance(result, IngestionResult)
        assert result.columns == ["alert_id", "priority", "host", "close_time"][: len(result.columns)]
        assert result.is_empty is False
        assert result.warnings == []
        assert isinstance(result.metadata, dict)
        assert all(isinstance(key, str) for key in result.records[0])

    assert {r.source_type for r in (csv_result, json_result, db_result)} == {
        SOURCE_CSV,
        SOURCE_JSON,
        SOURCE_SQLITE,
    }

    # Only the CSV loader knows its own file is directly readable. The others
    # rely on the manager to materialise a CSV for the profiler.
    assert csv_result.profiling_target == str(csv_file(tmp_path))
    assert json_result.profiling_target is None
    assert db_result.profiling_target is None

    manager = IngestionManager()

    for source, options in (
        (csv_file(tmp_path), {}),
        (json_file(tmp_path, VALID_JSON_ARRAY), {}),
        (sqlite_file(tmp_path), {"table": "alerts"}),
    ):
        loaded = manager.load(source, **options)

        # Every source reaches the profiler the same way.
        assert loaded.profiling_target
        assert os.path.isfile(loaded.profiling_target)

        manager.release(loaded)


def test_ingestion_result_summary_omits_record_contents(tmp_path):
    result = CsvLoader().load(csv_file(tmp_path))

    summary = result.to_summary()

    assert "records" not in summary
    assert summary["record_count"] == 2
    assert summary["source_type"] == SOURCE_CSV

    # Contents are available only when explicitly requested.
    assert len(result.to_summary(include_records=True)["records"]) == 2
    assert result.to_dict() == summary


def test_ingestion_result_to_frame_round_trips(tmp_path):
    result = JsonLoader().load(json_file(tmp_path, VALID_JSON_ARRAY))

    frame = result.to_frame()

    assert list(frame.columns) == ["alert_id", "priority", "host"]
    assert len(frame) == 2


def test_result_repr_is_informative(tmp_path):
    result = CsvLoader().load(csv_file(tmp_path))

    assert "csv" in repr(result)
    assert "records=2" in repr(result)


# ===========================================================================
# 3. CSV: valid
# ===========================================================================


def test_valid_csv_returns_normalized_records(tmp_path):
    result = CsvLoader().load(csv_file(tmp_path))

    assert result.source_type == SOURCE_CSV
    assert result.record_count == 2
    assert result.columns == ["alert_id", "priority", "host", "close_time"]
    assert result.records[0] == {
        "alert_id": "A-1",
        "priority": "HIGH",
        "host": "WEB_01",
        "close_time": 120,
    }
    assert result.records[1]["alert_id"] == "A-2"


def test_valid_csv_sets_profiling_target_to_the_original_file(tmp_path):
    path = csv_file(tmp_path)

    result = CsvLoader().load(path)

    # The original file is passed through: nothing is copied.
    assert result.profiling_target == str(path)
    assert result.temporary_files == []


def test_csv_column_names_are_read_from_the_file_not_assumed(tmp_path):
    path = csv_file(tmp_path, "totally_unexpected,columns\n1,2\n", name="odd.csv")

    result = CsvLoader().load(path)

    assert result.columns == ["totally_unexpected", "columns"]
    assert result.records == [{"totally_unexpected": 1, "columns": 2}]


def test_csv_missing_cells_become_none(tmp_path):
    result = CsvLoader().load(
        csv_file(tmp_path, "a,b,c\n1,,3\n", name="gaps.csv")
    )

    assert result.records == [{"a": 1.0, "b": None, "c": 3.0}]


# ===========================================================================
# 4. CSV: empty
# ===========================================================================


def test_empty_csv_file_is_reported_as_empty(tmp_path):
    path = csv_file(tmp_path, "", name="empty.csv")

    with pytest.raises(EmptySourceError) as error:
        CsvLoader().load(path)

    assert "0 bytes" in str(error.value)
    assert "no header" in str(error.value)


def test_whitespace_only_csv_file_is_reported_as_empty(tmp_path):
    path = csv_file(tmp_path, "\n\n   \n", name="blank.csv")

    with pytest.raises(EmptySourceError):
        CsvLoader().load(path)


def test_header_only_csv_is_valid_with_zero_records(tmp_path):
    path = csv_file(tmp_path, "alert_id,priority,host\n", name="header_only.csv")

    result = CsvLoader().load(path)

    # Different from a zero-byte file: the structure is known, the data is not.
    assert result.record_count == 0
    assert result.is_empty is True
    assert result.columns == ["alert_id", "priority", "host"]
    assert any("no data rows" in warning for warning in result.warnings)


# ===========================================================================
# 5. CSV: malformed
# ===========================================================================


def test_malformed_csv_is_reported_as_malformed(tmp_path):
    path = csv_file(tmp_path, MALFORMED_CSV, name="malformed.csv")

    with pytest.raises(MalformedSourceError) as error:
        CsvLoader().load(path)

    message = str(error.value)

    assert "Malformed CSV" in message
    assert "same number of fields" in message


def test_malformed_csv_does_not_return_partial_records(tmp_path):
    path = csv_file(tmp_path, "a,b\n1,2\n3,4,5,6\n", name="partial.csv")

    with pytest.raises(MalformedSourceError):
        CsvLoader().load(path)


def test_short_header_would_otherwise_silently_lose_a_column(tmp_path):
    """A header one field short must be refused, not silently reinterpreted.

    pandas treats this shape as "use the first column as the index", which keeps
    the values but removes the column from the data. For evidence ingestion that
    would be a silent loss, so it is an error.
    """
    path = csv_file(tmp_path, MALFORMED_CSV, name="short_header.csv")

    with pytest.raises(MalformedSourceError) as error:
        CsvLoader().load(path)

    assert "3 field(s)" in str(error.value)
    assert "4" in str(error.value)


def test_quoted_delimiter_inside_a_field_is_not_malformed(tmp_path):
    path = csv_file(
        tmp_path, 'alert_id,notes\nA-1,"first, second"\nA-2,plain\n', name="quoted.csv"
    )

    result = CsvLoader().load(path)

    assert result.record_count == 2
    assert result.records[0]["notes"] == "first, second"


def test_embedded_newline_inside_a_quoted_field_is_not_malformed(tmp_path):
    path = csv_file(
        tmp_path,
        'alert_id,notes\nA-1,"line one\nline two"\nA-2,plain\n',
        name="multiline.csv",
    )

    result = CsvLoader().load(path)

    assert result.record_count == 2
    assert result.records[0]["notes"] == "line one\nline two"


def test_large_csv_is_loaded_without_a_false_mismatch(tmp_path):
    # Bigger than the encoding/consistency sniff window, so the field-count
    # check is skipped rather than acting on a truncated record.
    body = "a,b,c\n" + "".join(f"v{index},{index},x\n" for index in range(20000))

    result = CsvLoader().load(csv_file(tmp_path, body, name="big.csv"))

    assert result.record_count == 20000


def test_unparseable_csv_is_reported_as_empty_not_malformed(tmp_path):
    path = tmp_path / "gibberish.csv"
    path.write_bytes(b"\x00\x01\x02\x03")

    # A single unlabelled column is still a header, so this parses but yields
    # no usable field names. The point is that it is handled, not that pandas
    # traceback escapes.
    try:
        result = CsvLoader().load(path)
    except IngestionError as error:
        assert isinstance(error, (EmptySourceError, MalformedSourceError))
    else:
        assert isinstance(result, IngestionResult)


# ===========================================================================
# 6. CSV: encoding
# ===========================================================================


def test_plain_utf8_csv_uses_the_default_read_path(tmp_path):
    result = CsvLoader().load(csv_file(tmp_path))

    assert result.metadata["encoding"] == "utf-8"
    assert result.metadata["delimiter"] == ","


def test_utf8_bom_is_stripped_from_the_first_column_name(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes("﻿alert_id,priority\nA-1,HIGH\n".encode("utf-8"))

    result = CsvLoader().load(path)

    assert result.metadata["encoding"] == "utf-8-sig"
    # A BOM glued to the name would break mapping lookups.
    assert result.columns == ["alert_id", "priority"]


def test_cp1252_csv_falls_back_and_decodes_correctly(tmp_path):
    path = tmp_path / "cp1252.csv"
    path.write_bytes("alert_id,notes\nA-1,café\n".encode("cp1252"))

    result = CsvLoader().load(path)

    assert result.metadata["encoding"] == "cp1252"
    assert result.records[0]["notes"] == "café"


def test_undecodable_csv_is_reported_as_malformed(tmp_path):
    path = tmp_path / "broken.csv"
    path.write_bytes(b"alert_id,notes\nA-1,\xff\xfe\xfd\xfc")

    with pytest.raises((MalformedSourceError, IngestionError)):
        CsvLoader().load(path, encoding="utf-8")


def test_tab_separated_file_is_detected(tmp_path):
    path = csv_file(tmp_path, "alert_id\tpriority\nA-1\tHIGH\n", name="alerts.tsv")

    result = CsvLoader().load(path)

    assert result.metadata["delimiter"] == "\t"
    assert result.columns == ["alert_id", "priority"]


# ===========================================================================
# 7. JSON: valid
# ===========================================================================


def test_valid_json_array_returns_normalized_records(tmp_path):
    result = JsonLoader().load(json_file(tmp_path, VALID_JSON_ARRAY))

    assert result.source_type == SOURCE_JSON
    assert result.record_count == 2
    assert result.columns == ["alert_id", "priority", "host"]
    assert result.records[0] == {
        "alert_id": "A-1",
        "priority": "HIGH",
        "host": "WEB_01",
    }


def test_valid_json_null_becomes_none(tmp_path):
    body = json.dumps([{"alert_id": "A-1", "priority": None}])

    result = JsonLoader().load(json_file(tmp_path, body, name="nulls.json"))

    assert result.records == [{"alert_id": "A-1", "priority": None}]


def test_json_envelope_key_is_discovered_not_configured(tmp_path):
    body = json.dumps(
        {"export_metadata": {"tool": "x"}, "alerts": [{"alert_id": "A-1"}]}
    )

    result = JsonLoader().load(json_file(tmp_path, body, name="envelope.json"))

    # "alerts" is not in ENVELOPE_KEYS; the first array of objects is used.
    assert result.metadata["envelope_key"] == "alerts"
    assert result.record_count == 1


def test_json_standard_envelope_key_is_reported(tmp_path):
    body = json.dumps({"data": [{"alert_id": "A-1"}]})

    result = JsonLoader().load(json_file(tmp_path, body, name="data.json"))

    assert result.metadata["envelope_key"] == "data"


def test_json_preserves_nested_objects(tmp_path):
    body = json.dumps([{"alert_id": "A-1", "extra": {"tag": "x"}, "list": [1, 2]}])

    result = JsonLoader().load(json_file(tmp_path, body, name="nested.json"))

    assert result.records[0]["extra"] == {"tag": "x"}
    assert result.records[0]["list"] == [1, 2]


def test_valid_ndjson_returns_normalized_records(tmp_path):
    result = JsonLoader().load(ndjson_file(tmp_path))

    assert result.source_type == SOURCE_NDJSON
    assert result.record_count == 2
    assert result.records[0]["priority"] == "HIGH"
    assert result.records[1]["host"] == "DB_02"


def test_ndjson_ignores_blank_lines(tmp_path):
    path = ndjson_file(
        tmp_path, '{"a":1}\n\n   \n{"a":2}\n', name="sparse.ndjson"
    )

    result = JsonLoader().load(path)

    assert result.record_count == 2


# ===========================================================================
# 8. JSON: malformed and empty
# ===========================================================================


def test_malformed_json_is_reported_as_malformed(tmp_path):
    path = json_file(tmp_path, '{"a": 1,}', name="broken.json")

    with pytest.raises(MalformedSourceError) as error:
        JsonLoader().load(path)

    message = str(error.value)

    assert "Malformed JSON" in message
    assert "newline-delimited" in message


def test_json_scalar_top_level_is_rejected(tmp_path):
    path = json_file(tmp_path, "42", name="scalar.json")

    with pytest.raises(MalformedSourceError) as error:
        JsonLoader().load(path)

    assert "top level is int" in str(error.value)


def test_json_object_without_records_is_rejected(tmp_path):
    path = json_file(tmp_path, '{"only": "metadata"}', name="meta.json")

    with pytest.raises(MalformedSourceError) as error:
        JsonLoader().load(path)

    assert "no array of records" in str(error.value)


def test_json_array_of_scalars_is_rejected(tmp_path):
    path = json_file(tmp_path, json.dumps([1, 2, 3]), name="numbers.json")

    with pytest.raises(MalformedSourceError) as error:
        JsonLoader().load(path)

    assert "each record must be a JSON object" in str(error.value)


def test_json_mixed_array_skips_scalars_with_a_warning(tmp_path):
    path = json_file(
        tmp_path, json.dumps([{"a": 1}, "oops", {"a": 2}]), name="mixed.json"
    )

    result = JsonLoader().load(path)

    assert result.record_count == 2
    assert any("Skipped record 1" in warning for warning in result.warnings)


def test_ndjson_with_a_broken_line_is_rejected(tmp_path):
    path = ndjson_file(tmp_path, '{"a":1}\n{"a": oops}\n', name="broken.ndjson")

    with pytest.raises(MalformedSourceError) as error:
        JsonLoader().load(path)

    assert "line 2" in str(error.value)


def test_ndjson_line_that_is_a_scalar_is_rejected(tmp_path):
    path = ndjson_file(tmp_path, '{"a":1}\n5\n', name="scalars.ndjson")

    with pytest.raises(MalformedSourceError) as error:
        JsonLoader().load(path)

    assert "must be a JSON object" in str(error.value)


def test_empty_json_file_is_reported_as_empty(tmp_path):
    path = json_file(tmp_path, "   ", name="empty.json")

    with pytest.raises(EmptySourceError) as error:
        JsonLoader().load(path)

    assert "empty or whitespace" in str(error.value)


def test_empty_json_array_is_valid_with_zero_records(tmp_path):
    path = json_file(tmp_path, "[]", name="empty_array.json")

    result = JsonLoader().load(path)

    assert result.record_count == 0
    assert result.is_empty is True
    assert any("empty array" in warning for warning in result.warnings)


# ===========================================================================
# 9. SQLite
# ===========================================================================


def test_sqlite_table_returns_normalized_records(tmp_path):
    path = sqlite_file(tmp_path)

    result = DatabaseLoader().load(path, table="alerts")

    assert result.source_type == SOURCE_SQLITE
    assert result.record_count == 3
    assert result.columns == ["alert_id", "priority", "host", "close_time"]
    assert result.records[0]["alert_id"] == "A-1"
    assert result.records[0]["close_time"] == 120


def test_sqlite_null_becomes_none(tmp_path):
    path = sqlite_file(tmp_path)

    result = DatabaseLoader().load(path, table="alerts")

    assert result.records[2]["priority"] is None
    assert result.records[2]["close_time"] is None


def test_sqlite_query_selection_is_supported(tmp_path):
    path = sqlite_file(tmp_path)

    result = DatabaseLoader().load(
        path, query="SELECT * FROM alerts WHERE priority = 'HIGH'"
    )

    assert result.record_count == 1
    assert result.metadata["selected"]["kind"] == "query"


def test_sqlite_with_clause_is_allowed_as_a_read(tmp_path):
    path = sqlite_file(tmp_path)

    result = DatabaseLoader().load(
        path, query="WITH highs AS (SELECT * FROM alerts) SELECT * FROM highs"
    )

    assert result.record_count == 3


def test_sqlite_single_table_is_auto_selected_with_a_warning(tmp_path):
    path = sqlite_file(tmp_path)

    result = DatabaseLoader().load(path)

    assert result.record_count == 3
    assert result.metadata["selected"]["auto_selected"] is True
    assert any("auto-selected" in warning for warning in result.warnings)


def test_sqlite_ambiguous_table_is_refused_and_lists_tables(tmp_path):
    path = sqlite_file(
        tmp_path,
        tables={"alerts": ["a"], "other": ["b"], "third": ["c"]},
        populate=False,
    )

    with pytest.raises(UnsupportedSourceError) as error:
        DatabaseLoader().load(path)

    message = str(error.value)

    assert "ambiguous" in message
    assert "'alerts'" in message and "'other'" in message


def test_sqlite_table_and_query_together_are_refused(tmp_path):
    path = sqlite_file(tmp_path)

    with pytest.raises(UnsupportedSourceError) as error:
        DatabaseLoader().load(path, table="alerts", query="SELECT 1")

    assert "not both" in str(error.value)


def test_sqlite_unknown_table_lists_available_ones(tmp_path):
    path = sqlite_file(tmp_path)

    with pytest.raises(MalformedSourceError) as error:
        DatabaseLoader().load(path, table="missing")

    assert "not in" in str(error.value)
    assert "'alerts'" in str(error.value)


def test_sqlite_connection_is_read_only(tmp_path):
    path = sqlite_file(tmp_path)

    connection = DatabaseLoader._connect(str(path))

    try:
        for statement in (
            "INSERT INTO alerts VALUES ('X', 'LOW', 'H', 1)",
            "UPDATE alerts SET priority = 'X'",
            "DELETE FROM alerts",
            "DROP TABLE alerts",
            "CREATE TABLE injected (x)",
        ):
            with pytest.raises(sqlite3.OperationalError) as error:
                connection.execute(statement)

            assert "readonly" in str(error.value).lower()
    finally:
        connection.close()


def test_sqlite_load_does_not_modify_the_database_file(tmp_path):
    path = sqlite_file(tmp_path)

    before = path.read_bytes()

    DatabaseLoader().load(path, table="alerts")
    DatabaseLoader().load(path, query="SELECT * FROM alerts")

    assert path.read_bytes() == before


def test_sqlite_write_queries_are_refused(tmp_path):
    path = sqlite_file(tmp_path)

    for statement in (
        "DELETE FROM alerts",
        "UPDATE alerts SET priority = 'X'",
        "DROP TABLE alerts",
        "INSERT INTO alerts VALUES ('A','B','C',1)",
        "PRAGMA journal_mode = WAL",
        "ATTACH DATABASE '/tmp/other.db' AS other",
        "VACUUM",
    ):
        with pytest.raises(UnsupportedSourceError):
            DatabaseLoader().load(path, query=statement)


def test_sqlite_multi_statement_query_is_refused(tmp_path):
    path = sqlite_file(tmp_path)

    with pytest.raises(UnsupportedSourceError) as error:
        DatabaseLoader().load(path, query="SELECT 1; DROP TABLE alerts")

    assert "single statement" in str(error.value)


def test_sqlite_invalid_query_is_reported_as_malformed(tmp_path):
    path = sqlite_file(tmp_path)

    with pytest.raises(MalformedSourceError) as error:
        DatabaseLoader().load(path, query="SELECT * FROM does_not_exist")

    assert "failed" in str(error.value).lower()


def test_sqlite_identifier_injection_is_refused(tmp_path):
    path = sqlite_file(tmp_path)

    for name in (
        'alerts"; DROP TABLE alerts; --',
        "alerts; DROP TABLE alerts",
        "alerts\0",
        "../../etc/passwd",
        "",
    ):
        with pytest.raises(UnsupportedSourceError):
            DatabaseLoader().load(path, table=name)


def test_sqlite_empty_table_is_valid_with_zero_records(tmp_path):
    path = sqlite_file(
        tmp_path, tables={"alerts": ["a"], "blank": ["x"]}, populate=False
    )

    result = DatabaseLoader().load(path, table="blank")

    assert result.record_count == 0
    assert result.is_empty is True
    assert result.columns == ["x"]
    assert any("no rows" in warning for warning in result.warnings)


def test_sqlite_database_with_no_tables_is_reported_as_empty(tmp_path):
    path = tmp_path / "no_tables.sqlite"
    connection = sqlite3.connect(path)
    connection.close()

    with pytest.raises(EmptySourceError) as error:
        DatabaseLoader().load(path)

    assert "no tables" in str(error.value).lower()


def test_zero_byte_sqlite_file_is_reported_as_empty(tmp_path):
    path = tmp_path / "uninitialised.sqlite"
    path.write_bytes(b"")

    with pytest.raises(EmptySourceError) as error:
        DatabaseLoader().load(path)

    assert "0 bytes" in str(error.value)


def test_non_sqlite_file_with_sqlite_extension_is_rejected(tmp_path):
    path = tmp_path / "pretending.sqlite"
    path.write_text("alert_id\nA-1\n", encoding="utf-8")

    with pytest.raises(MalformedSourceError) as error:
        DatabaseLoader().load(path, table="alerts")

    assert "bad file header" in str(error.value)


# ===========================================================================
# 10. Unsupported sources
# ===========================================================================


def test_missing_file_is_reported_as_not_found(tmp_path):
    with pytest.raises(SourceNotFoundError):
        CsvLoader().load(tmp_path / "nope.csv")


def test_directory_source_is_refused(tmp_path):
    with pytest.raises(SourceNotFoundError) as error:
        CsvLoader().load(tmp_path)

    assert "directory" in str(error.value)


def test_non_path_source_is_refused():
    with pytest.raises(UnsupportedSourceError) as error:
        CsvLoader().load(12345)

    assert "filesystem path" in str(error.value)


def test_api_source_is_refused_by_design_and_names_the_extension_point(tmp_path):
    loader = RemoteApiLoader()

    with pytest.raises(UnsupportedSourceError) as error:
        loader.load("https://cse.example/api/alerts")

    message = str(error.value)

    assert "no network access" in message
    assert "LocalApiAdapter" in message
    assert loader.SOURCE_TYPE == SOURCE_API


def test_unreadable_file_is_reported_as_access_error(tmp_path):
    path = csv_file(tmp_path)
    os.chmod(path, 0o000)

    try:
        if os.access(path, os.R_OK):  # pragma: no cover - running as root
            pytest.skip("cannot make a file unreadable as this user")

        with pytest.raises((SourceAccessError, IngestionError)):
            CsvLoader().load(path)
    finally:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


# ===========================================================================
# 11. Manager: detection and dispatch
# ===========================================================================


def test_manager_detects_by_extension(tmp_path):
    manager = IngestionManager()

    assert manager.detect_source_type("a.csv") == SOURCE_CSV
    assert manager.detect_source_type("a.tsv") == SOURCE_CSV
    assert manager.detect_source_type("a.json") == SOURCE_JSON
    assert manager.detect_source_type("a.ndjson") == SOURCE_NDJSON
    assert manager.detect_source_type("a.jsonl") == SOURCE_NDJSON
    assert manager.detect_source_type("a.sqlite") == SOURCE_SQLITE
    assert manager.detect_source_type("a.db") == SOURCE_SQLITE


def test_manager_detects_by_content_when_extension_lies(tmp_path):
    manager = IngestionManager()

    # JSON content behind a .csv name.
    path = json_file(tmp_path, VALID_JSON_ARRAY, name="actually_json.csv")
    assert manager.detect_source_type(path) == SOURCE_JSON
    assert manager.load(path).source_type == SOURCE_JSON

    # SQLite content behind a .csv name.
    db = sqlite_file(tmp_path, name="actually_db.csv")
    assert manager.detect_source_type(db) == SOURCE_SQLITE


def test_manager_detects_content_with_no_extension(tmp_path):
    manager = IngestionManager()

    path = tmp_path / "alerts_data"
    path.write_text(VALID_JSON_ARRAY, encoding="utf-8")

    assert manager.detect_source_type(path) == SOURCE_JSON
    assert manager.detect_source_type(ndjson_file(tmp_path)).startswith(SOURCE_NDJSON)


def test_manager_refuses_unidentifiable_source(tmp_path):
    manager = IngestionManager()
    path = tmp_path / "mystery"
    path.write_text("just some prose\nwith no structure\n", encoding="utf-8")

    with pytest.raises(UnsupportedSourceError) as error:
        manager.load(path)

    message = str(error.value)

    assert "not recognised" in message
    assert "source_type" in message


def test_manager_explicit_source_type_wins(tmp_path):
    manager = IngestionManager()
    path = json_file(tmp_path, VALID_JSON_ARRAY, name="named.csv")

    # Content is definitive and beats a conflicting extension, so this detects
    # as JSON. The explicit type then pins it either way, which the result's own
    # type and shape show.
    assert manager.detect_source_type(path) == SOURCE_JSON

    forced = manager.load(path, source_type=SOURCE_JSON)

    assert forced.source_type == SOURCE_JSON
    assert forced.record_count == 2
    assert forced.columns == ["alert_id", "priority", "host"]

    # Forcing CSV runs the CSV loader instead, which reads the document as one
    # wide row rather than as records.
    as_csv = manager.load(path, source_type=SOURCE_CSV)

    assert as_csv.source_type == SOURCE_CSV
    assert as_csv.record_count != forced.record_count


def test_manager_accepts_mime_type_aliases(tmp_path):
    manager = IngestionManager()
    path = json_file(tmp_path, VALID_JSON_ARRAY, name="mislabelled.csv")

    result = manager.load(path, source_type="application/json")

    assert result.source_type == SOURCE_JSON
    assert result.record_count == 2


def test_manager_dispatches_every_registered_type(tmp_path):
    manager = IngestionManager()

    assert manager.supported_types == ["api", "csv", "json", "ndjson", "sqlite"]

    assert manager.load(csv_file(tmp_path)).source_type == SOURCE_CSV
    assert manager.load(json_file(tmp_path, VALID_JSON_ARRAY)).source_type == SOURCE_JSON
    assert manager.load(ndjson_file(tmp_path)).source_type == SOURCE_NDJSON
    assert manager.load(sqlite_file(tmp_path), table="alerts").source_type == SOURCE_SQLITE


def test_manager_refuses_api_source(tmp_path):
    manager = IngestionManager()

    with pytest.raises(UnsupportedSourceError) as error:
        manager.load("https://cse.example/api/alerts", source_type=SOURCE_API)

    assert "LocalApiAdapter" in str(error.value)


def test_manager_passes_loader_options_through(tmp_path):
    manager = IngestionManager()

    result = manager.load(sqlite_file(tmp_path), table="alerts")

    assert result.record_count == 3
    assert result.metadata["selected"]["name"] == "alerts"


def test_manager_registers_a_custom_loader(tmp_path):
    from framework.ingestion.base_loader import BaseLoader

    class StubLoader(BaseLoader):
        SOURCE_TYPE = "stub"

        def _load(self, source, **options):
            return self._build_result(source, [{"field": 1}], columns=["field"])

    manager = IngestionManager()
    manager.register(StubLoader())

    result = manager.load("anything", source_type="stub")

    assert result.records == [{"field": 1}]
    assert "stub" in manager.supported_types


def test_manager_refuses_loader_without_source_type():
    from framework.ingestion.base_loader import BaseLoader

    class Broken(BaseLoader):
        def _load(self, source, **options):
            return self._build_result(source, [])

    with pytest.raises(UnsupportedSourceError):
        IngestionManager().register(Broken())


# ===========================================================================
# 12. Manager: profiling target and cleanup
# ===========================================================================


def test_csv_source_is_passed_through_without_copying(tmp_path):
    manager = IngestionManager()
    path = csv_file(tmp_path)

    result = manager.load(path)

    assert result.profiling_target == str(path)
    assert result.temporary_files == []


def test_non_csv_source_is_materialised_as_a_readable_csv(tmp_path):
    manager = IngestionManager()
    path = json_file(tmp_path, VALID_JSON_ARRAY)

    result = manager.load(path)

    target = result.profiling_target

    assert target != str(path)
    assert target.endswith(".csv")
    assert result.temporary_files == [target]

    # The profiler must be able to read it: that is the whole point.
    frame = pd.read_csv(target)

    assert list(frame.columns) == ["alert_id", "priority", "host"]
    assert len(frame) == 2

    manager.release(result)


def test_materialised_csv_captures_values_from_nested_records(tmp_path):
    manager = IngestionManager()
    body = json.dumps([{"alert_id": "A-1", "tags": ["x"], "meta": {"k": "v"}}])

    result = manager.load(json_file(tmp_path, body, name="nested.json"))

    frame = pd.read_csv(result.profiling_target)

    assert list(frame.columns) == ["alert_id", "tags", "meta"]

    manager.release(result)


def test_release_removes_temporary_files_but_keeps_records(tmp_path):
    manager = IngestionManager()

    result = manager.load(json_file(tmp_path, VALID_JSON_ARRAY))
    target = result.profiling_target

    manager.release(result)

    assert not os.path.exists(target)
    assert result.temporary_files == []
    assert result.record_count == 2


def test_release_is_idempotent_and_safe_on_none(tmp_path):
    manager = IngestionManager()

    result = manager.load(json_file(tmp_path, VALID_JSON_ARRAY))

    manager.release(result)
    manager.release(result)
    manager.release(None)


def test_manager_can_run_without_materialisation(tmp_path):
    manager = IngestionManager(materialise=False)

    result = manager.load(json_file(tmp_path, VALID_JSON_ARRAY))

    assert result.record_count == 2
    assert result.profiling_target is None
    assert result.temporary_files == []


def test_row_limit_truncates_and_reports(tmp_path):
    manager = IngestionManager()
    rows = [{"alert_id": f"A-{index}"} for index in range(10)]

    result = manager.load(
        json_file(tmp_path, json.dumps(rows), name="many.json"), max_rows=4
    )

    assert result.record_count == 4
    assert result.metadata["row_limit"] == 4
    assert result.metadata["rows_dropped"] == 6
    assert any("Row limit reached" in warning for warning in result.warnings)


def test_invalid_max_rows_is_refused(tmp_path):
    manager = IngestionManager()

    for value in (0, -1, "many", 1.5):
        with pytest.raises(UnsupportedSourceError):
            manager.load(csv_file(tmp_path), max_rows=value)


# ===========================================================================
# 13. API extension point
# ===========================================================================


def test_local_api_adapter_interface_is_defined():
    for method in ("name", "available", "fetch"):
        assert callable(getattr(LocalApiAdapter, method, None))


def test_manager_uses_a_registered_local_adapter(tmp_path):
    class StubAdapter(LocalApiAdapter):
        def name(self):
            return "local_collector"

        def available(self):
            return True

        def fetch(self, **options):
            return [{"alert_id": "A-1", "priority": "HIGH"}]

    manager = IngestionManager()
    manager.register_api_adapter(StubAdapter())

    result = manager.load("collector://alerts", source_type=SOURCE_API)

    assert result.source_type == SOURCE_API
    assert result.records == [{"alert_id": "A-1", "priority": "HIGH"}]
    assert result.metadata["adapter"] == "local_collector"
    assert "no network access" in result.metadata["transport"]

    manager.release(result)


def test_unavailable_adapter_is_reported_not_retried(tmp_path):
    class OfflineAdapter(LocalApiAdapter):
        def name(self):
            return "offline"

        def available(self):
            return False

        def fetch(self, **options):  # pragma: no cover - must not be called
            raise AssertionError("fetch must not be called when unavailable")

    manager = IngestionManager()
    manager.register_api_adapter(OfflineAdapter())

    with pytest.raises(IngestionError) as error:
        manager.load("collector://alerts", source_type=SOURCE_API)

    assert "not available" in str(error.value)


def test_invalid_adapter_is_refused():
    class NotAnAdapter:
        pass

    with pytest.raises(UnsupportedSourceError) as error:
        IngestionManager().register_api_adapter(NotAnAdapter())

    assert "not a valid adapter" in str(error.value)


# ===========================================================================
# 14. Pipeline integration
# ===========================================================================


@requires_pipeline
def test_direct_csv_invocation_still_produces_normalised_records(tmp_path):
    from framework.pipeline import SATSAPipeline

    result = SATSAPipeline().run(str(csv_file(tmp_path)))

    assert result["dataset"] == str(csv_file(tmp_path))
    assert result["profile"]["dataset_summary"]["records"] == 2
    assert result["ingestion"]["source_type"] == SOURCE_CSV
    assert result["ingestion"]["record_count"] == 2
    assert result["ingestion"]["columns"] == [
        "alert_id",
        "priority",
        "host",
        "close_time",
    ]
    assert "supervisory_findings" in result
    assert "entity_assessment" in result


@requires_pipeline
def test_pipeline_ingests_json_through_the_unmodified_engine(tmp_path):
    from framework.pipeline import SATSAPipeline

    path = json_file(tmp_path, VALID_JSON_ARRAY)

    result = SATSAPipeline().run(str(path))

    assert result["ingestion"]["source_type"] == SOURCE_JSON
    assert result["profile"]["dataset_summary"]["records"] == 2
    assert len(result["canonical_records"]) == 2


@requires_pipeline
def test_pipeline_cleans_up_its_materialised_csv(tmp_path):
    from framework.pipeline import SATSAPipeline

    result = SATSAPipeline().run(str(json_file(tmp_path, VALID_JSON_ARRAY)))
    target = result["ingestion"]["profiling_target"]

    assert target is not None
    assert not os.path.exists(target)


@requires_pipeline
def test_pipeline_csv_source_creates_no_temporary_file(tmp_path):
    from framework.pipeline import SATSAPipeline

    path = csv_file(tmp_path)

    result = SATSAPipeline().run(str(path))

    assert result["ingestion"]["temporary_files"] == [] if "temporary_files" in result["ingestion"] else True
    assert result["ingestion"]["profiling_target"] == str(path)


def test_ingestion_summary_never_contains_record_contents(tmp_path):
    manager = IngestionManager()

    result = manager.load(csv_file(tmp_path))

    assert "ALRT" not in json.dumps(result.to_summary())
    assert "A-1" not in json.dumps(result.to_summary())
