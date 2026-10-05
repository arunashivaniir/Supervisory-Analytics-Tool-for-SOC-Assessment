"""Phase 2 tests: scalable ingestion + large-data execution foundation.

A. Existing small CSV behaviour unchanged (full pipeline, known counts)
B. Large CSV schema discovery
C. Large CSV row counting
D. Large CSV bounded sampling
E. Column projection (columns, limit, offset, filters)
F. JSON compatibility (document loader untouched)
G. NDJSON handling (scan + loader)
H. Malformed input handling
I. Provenance preservation (file order == sample order)
J. Canonical package compatibility (scan vs records)
K. Bounded record retrieval (cap, paging coverage)
L. Generated 100K dataset (scan package vs manifest)
M. Generated 1M dataset (scan package vs manifest)

The 5M scale is benchmark-only (benchmarks/bench_phase2.py), never
part of the unit suite.
"""

from __future__ import annotations

import csv
import json
import os

import pytest

from framework.canonical.package import (
    build_canonical_package,
    build_canonical_package_scan,
)
from framework.ingestion.paths import (
    LARGE,
    SMALL,
    select_execution_mode,
)
from framework.ingestion.scan import ScanError, open_scan
from framework.intelligence.semantic_inference import SemanticInference
from framework.mapping.schema_mapper import SchemaMapper
from framework.profiling.dataset_profiler import DatasetProfiler
from framework.profiling.scan_profiler import profile_scan

PATTERNS = "framework/config/semantic_patterns.json"
MAPPINGS = "framework/config/mappings.json"
SCHEMA = "framework/canonical/canonical_schema.json"
SCALE_DIR = "data/scale"
SCALE_100K = os.path.join(SCALE_DIR, "scale_100000.csv")
SCALE_1M = os.path.join(SCALE_DIR, "scale_1000000.csv")


def _manifest(path):
    with open(os.path.splitext(path)[0] + ".manifest.json") as handle:
        return json.load(handle)


def _require_scale(path):
    if not os.path.isfile(path):
        pytest.skip("scale fixture absent (generate it): %s" % path)


def _legacy_profile(path):
    return DatasetProfiler().profile(path)


def _profile_equal(fast, legacy):
    """Profile equality on everything semantic inference consumes."""

    assert fast["dataset_summary"] == legacy["dataset_summary"]

    fast_cols = {c["column_name"]: c for c in fast["columns"]}
    legacy_cols = {c["column_name"]: c for c in legacy["columns"]}

    assert set(fast_cols) == set(legacy_cols)

    for name, legacy_col in legacy_cols.items():
        fast_col = fast_cols[name]

        assert fast_col["category"] == legacy_col["category"], name
        assert fast_col["unique_values"] == legacy_col["unique_values"], name
        assert fast_col["null_values"] == legacy_col["null_values"], name

        if "sample_values" in legacy_col:
            assert fast_col.get("sample_values") == (
                legacy_col["sample_values"]
            ), name


# ---------------------------------------------------------------------------
# A. Existing small CSV behaviour unchanged
# ---------------------------------------------------------------------------


class TestSmallPathUnchanged:
    def test_controlled_counts_are_stable(self):
        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run("dataset_execution_gap_controlled.csv")

        assert result["execution_gap_findings"]["finding_count"] == 2
        assert result["negative_space_findings"]["finding_count"] == 1
        assert result["ingestion"]["record_count"] == 8
        assert "execution_mode" not in result["ingestion"]["metadata"]

    def test_small_files_select_small_path(self):
        assert select_execution_mode(
            "dataset_execution_gap_controlled.csv"
        ) == SMALL
        assert select_execution_mode("data.csv") == SMALL

    def test_json_always_selects_small_path(self, tmp_path):
        path = os.path.join(str(tmp_path), "big_but_json.json")

        with open(path, "w") as handle:
            handle.write("[" + " " * (70 * 1024 * 1024) + "]")

        assert select_execution_mode(path) == SMALL

    def test_explicit_override_wins(self):
        assert select_execution_mode(
            "dataset_execution_gap_controlled.csv", override="large"
        ) == LARGE
        assert select_execution_mode(
            SCALE_1M, override="small"
        ) == SMALL

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError):
            select_execution_mode("data.csv", override="sideways")


# ---------------------------------------------------------------------------
# B/C. Schema discovery and row counting
# ---------------------------------------------------------------------------


class TestScanDiscovery:
    def test_schema_matches_header_order(self):
        _require_scale(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            with open(SCALE_100K, newline="") as handle:
                header = next(csv.reader(handle))

            assert scan.columns == header

    def test_row_count_is_exact(self):
        _require_scale(SCALE_100K)

        manifest = _manifest(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            assert scan.count() == manifest["rows"]


# ---------------------------------------------------------------------------
# D/E. Bounded sampling and projection
# ---------------------------------------------------------------------------


class TestBoundedAccess:
    def test_samples_are_deterministic(self):
        _require_scale(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            first = scan.sample(25)
            second = scan.sample(25)

        assert first == second
        assert len(first) == 25
        assert first[0]["alert_id"] == "A-0000001"

    def test_projection_respects_limit_offset(self):
        _require_scale(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            page_one = scan.project(["alert_id"], limit=10, offset=0)
            page_two = scan.project(["alert_id"], limit=10, offset=10)

        assert len(page_one) == 10
        assert len(page_two) == 10
        first_ids = [row["alert_id"] for row in page_one]
        second_ids = [row["alert_id"] for row in page_two]
        assert not set(first_ids) & set(second_ids)

    def test_projection_cap_binds(self):
        _require_scale(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            rows = scan.project(["alert_id"], limit=50000)

        assert len(rows) == 10000

    def test_filters_select(self):
        _require_scale(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            critical = scan.project(
                ["alert_id", "severity"],
                limit=10000,
                filters=[("severity", "eq", "CRITICAL")],
            )
            assert critical
            assert all(
                row["severity"] == "CRITICAL" for row in critical
            )
            assert scan.count_where([("severity", "eq", "CRITICAL")]) >= (
                len(critical)
            )


# ---------------------------------------------------------------------------
# F/G. JSON compatibility and NDJSON scans
# ---------------------------------------------------------------------------


class TestJsonHandling:
    def test_json_document_uses_record_path(self, tmp_path):
        from framework.ingestion.ingestion_manager import IngestionManager

        path = os.path.join(str(tmp_path), "doc.json")
        payload = [
            {"alert_id": "A-1", "priority": "HIGH"},
            {"alert_id": "A-2", "priority": "LOW"},
        ]

        with open(path, "w") as handle:
            json.dump(payload, handle)

        result = IngestionManager().load(path)

        assert result.record_count == 2
        assert select_execution_mode(path) == SMALL

    def test_ndjson_scans_and_loads(self, tmp_path):
        from framework.ingestion.ingestion_manager import IngestionManager

        path = os.path.join(str(tmp_path), "events.ndjson")

        with open(path, "w") as handle:
            for index in range(50):
                handle.write(
                    json.dumps(
                        {"alert_id": "A-%d" % index, "priority": "HIGH"}
                    )
                    + "\n"
                )

        with open_scan(path, source_type="ndjson") as scan:
            assert scan.count() == 50
            assert "alert_id" in scan.columns

        result = IngestionManager().load(path)

        assert result.record_count == 50


# ---------------------------------------------------------------------------
# H. Malformed input handling
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_missing_file_is_a_scan_error(self):
        with pytest.raises(ScanError):
            open_scan("no_such_file.csv")

    def test_unscannable_type_is_a_scan_error(self, tmp_path):
        path = os.path.join(str(tmp_path), "doc.json")

        with open(path, "w") as handle:
            json.dump([{"a": 1}], handle)

        with pytest.raises(ScanError):
            open_scan(path)

    def test_unknown_filter_column_is_a_scan_error(self):
        with open_scan("dataset_execution_gap_controlled.csv") as scan:
            with pytest.raises(ScanError):
                scan.project(["nope"], limit=5)

    def test_unknown_filter_operator_is_a_scan_error(self):
        with open_scan("dataset_execution_gap_controlled.csv") as scan:
            with pytest.raises(ScanError):
                scan.project(
                    ["alert_id"], limit=5,
                    filters=[("alert_id", "matches", "A-1")],
                )

    def test_quoted_commas_parse_like_the_record_path(self, tmp_path):
        """A quoted delimiter must never shift columns silently.

        Column-shift is the worst evidence failure: values land under
        the wrong headers with no error. The scan pins RFC-4180 quoting
        (as pandas does) and this test locks it with embedded commas,
        quotes and newlines.
        """

        path = os.path.join(str(tmp_path), "quoted.csv")

        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["alert_id", "note", "severity"])
            writer.writerow(["A-1", "Root cause, host reimaged.", "HIGH"])
            writer.writerow(["A-2", 'Said "hello", then closed.', "LOW"])
            writer.writerow(["A-3", "Line one\nline two.", "MEDIUM"])

        with open(path, newline="") as handle:
            expected = list(csv.DictReader(handle))

        with open_scan(path) as scan:
            got = scan.project(["alert_id", "note", "severity"], limit=10)

        assert got == expected


# ---------------------------------------------------------------------------
# I. Provenance preservation
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_sample_order_is_file_order(self):
        _require_scale(SCALE_100K)

        with open(SCALE_100K, newline="") as handle:
            expected = [
                row["alert_id"]
                for _, row in zip(
                    range(500), csv.DictReader(handle)
                )
            ]

        with open_scan(SCALE_100K) as scan:
            got = [
                row["alert_id"]
                for row in scan.project(["alert_id"], limit=500)
            ]

        assert got == expected

    def test_streaming_covers_every_row_once(self):
        _require_scale(SCALE_100K)

        manifest = _manifest(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            seen = sum(
                1 for _ in scan.iter_rows(["alert_id"], batch=20000)
            )

        assert seen == manifest["rows"]


# ---------------------------------------------------------------------------
# J. Canonical package compatibility (scan vs records)
# ---------------------------------------------------------------------------


class TestPackageCompatibility:
    def _record_package(self, path):
        from framework.assessment.entity_context import (
            build_column_name_index,
        )
        from framework.canonical.package import build_canonical_package
        from framework.ingestion.ingestion_manager import IngestionManager

        engine = SemanticInference(PATTERNS)

        with open(MAPPINGS) as handle:
            mappings = json.load(handle)

        ingestion = IngestionManager().load(path)
        profile = _legacy_profile(ingestion.profiling_target)

        mapper = SchemaMapper(MAPPINGS, SCHEMA)
        package = build_canonical_package(
            path, profile, engine, mappings, ingestion.records,
            guard=mapper.validate_mapping,
        )
        IngestionManager().release(ingestion)

        return package

    def _scan_package(self, path):
        from framework.canonical.package import (
            build_canonical_package_scan,
        )

        engine = SemanticInference(PATTERNS)

        with open(MAPPINGS) as handle:
            mappings = json.load(handle)

        mapper = SchemaMapper(MAPPINGS, SCHEMA)

        with open_scan(path) as scan:
            from framework.profiling.scan_profiler import profile_scan

            profile = profile_scan(scan)

            return build_canonical_package_scan(
                path, profile, engine, mappings, scan,
                guard=mapper.validate_mapping,
            )

    def test_profiles_agree(self):
        with open_scan("dataset_execution_gap_controlled.csv") as scan:
            from framework.profiling.scan_profiler import profile_scan

            fast = profile_scan(scan)

        _profile_equal(
            fast, _legacy_profile("dataset_execution_gap_controlled.csv")
        )

    def test_profiles_agree_on_noisy_data(self):
        with open_scan("dataset_noisy.csv") as scan:
            from framework.profiling.scan_profiler import profile_scan

            fast = profile_scan(scan)

        _profile_equal(fast, _legacy_profile("dataset_noisy.csv"))

    def test_packages_agree(self):
        path = "dataset_execution_gap_controlled.csv"
        record_package = self._record_package(path)
        scan_package = self._scan_package(path)

        assert (
            scan_package["mapping_states"]
            == record_package["mapping_states"]
        )
        assert (
            scan_package["detected_role"]
            == record_package["detected_role"]
        )
        assert (
            scan_package["relationships"] == record_package["relationships"]
        )
        assert (
            scan_package["validation"]["issue_counts"]
            == record_package["validation"]["issue_counts"]
        )


# ---------------------------------------------------------------------------
# K. Bounded record retrieval
# ---------------------------------------------------------------------------


class TestBoundedRetrieval:
    def test_paging_covers_without_overlap(self):
        _require_scale(SCALE_100K)

        manifest = _manifest(SCALE_100K)
        seen = set()

        with open_scan(SCALE_100K) as scan:
            for offset in range(0, manifest["rows"], 10000):
                page = scan.project(["alert_id"], limit=10000, offset=offset)

                for row in page:
                    if row["alert_id"] is not None:
                        seen.add(row["alert_id"])

        # 50k alerts + 100 exact-duplicate rows collapse to 50k distinct.
        assert len(seen) == manifest["alerts"]

    def test_evidence_lookup_by_key(self):
        _require_scale(SCALE_100K)

        with open_scan(SCALE_100K) as scan:
            rows = scan.project(
                ["alert_id", "severity", "asset_id"],
                limit=5,
                filters=[("alert_id", "eq", "A-0000042")],
            )

        assert len(rows) == 1
        assert rows[0]["alert_id"] == "A-0000042"
        assert rows[0]["severity"] in (
            "CRITICAL", "HIGH", "MEDIUM", "LOW", "URGENT",
        )


# ---------------------------------------------------------------------------
# L/M. Generated scale datasets vs ground truth
# ---------------------------------------------------------------------------


def _scan_package_of(path):
    from framework.canonical.package import (
        build_canonical_package_scan,
    )
    from framework.profiling.scan_profiler import profile_scan

    engine = SemanticInference(PATTERNS)

    with open(MAPPINGS) as handle:
        mappings = json.load(handle)

    mapper = SchemaMapper(MAPPINGS, SCHEMA)

    with open_scan(path) as scan:
        profile = profile_scan(scan)

        return build_canonical_package_scan(
            path, profile, engine, mappings, scan,
            guard=mapper.validate_mapping,
        )


class TestScaleDatasets:
    def test_100k_package_matches_manifest(self):
        _require_scale(SCALE_100K)

        manifest = _manifest(SCALE_100K)
        package = _scan_package_of(SCALE_100K)
        relationships = package["relationships"]

        assert package["provenance"]["record_count"] == manifest["rows"]
        assert relationships["alerts"] == manifest["alerts"]
        assert relationships["cases"] == manifest["cases"]
        assert relationships["workflow_events"] == (
            manifest["workflow_events"]
        )
        assert relationships["linked_cases"]["count"] == (
            manifest["linked_cases"]
        )
        assert relationships["orphan_cases"]["count"] == (
            manifest["orphan_cases"]
        )
        assert relationships["alerts_without_case"]["count"] == (
            manifest["alerts_without_case"]
        )

    def test_1m_package_matches_manifest(self):
        _require_scale(SCALE_1M)

        manifest = _manifest(SCALE_1M)
        package = _scan_package_of(SCALE_1M)
        relationships = package["relationships"]

        assert package["provenance"]["record_count"] == manifest["rows"]
        assert relationships["alerts"] == manifest["alerts"]
        assert relationships["cases"] == manifest["cases"]
        assert relationships["workflow_events"] == (
            manifest["workflow_events"]
        )
        assert relationships["linked_cases"]["count"] == (
            manifest["linked_cases"]
        )
        assert relationships["orphan_cases"]["count"] == (
            manifest["orphan_cases"]
        )
        assert relationships["alerts_without_case"]["count"] == (
            manifest["alerts_without_case"]
        )

    def test_scale_files_select_large_path(self):
        _require_scale(SCALE_1M)

        assert select_execution_mode(SCALE_1M) == LARGE
