"""Phase 1 tests: canonical contract + Pipeline 1/2 foundation.

Categories (per the Phase 1 brief):

A. Canonical field presence
B. Pipeline role detection
C. Alias mapping (ServiceNow / Jira / Splunk / generic headers)
D. Ambiguous mapping
E. Mapping collision
F. Low-confidence mapping
G. Timestamp normalization
H. Invalid chronology
I. Severity normalization
J. Alert -> Case relationship
K. Case -> Workflow relationship
L. Orphan cases
M. Unmatched alerts
N. Provenance preservation
O. Backward compatibility

Rule under test throughout: wrong mapping is worse than unmapped.
"""

from __future__ import annotations

import json
import os

import pytest

from framework.canonical import decisions as mapping_decisions
from framework.canonical import normalize as values
from framework.canonical import roles as dataset_roles
from framework.canonical import validate as package_validation
from framework.canonical.contract import (
    AMBIGUOUS,
    INVALID,
    LOW_CONFIDENCE,
    MAPPED,
    UNMAPPED,
    check_against_mappings,
    concept_names,
    required_for_role,
)
from framework.canonical.package import build_canonical_package
from framework.intelligence.semantic_inference import SemanticInference
from framework.mapping.schema_mapper import SchemaMapper

PATTERNS = "framework/config/semantic_patterns.json"
MAPPINGS = "framework/config/mappings.json"
SCHEMA = "framework/canonical/canonical_schema.json"


def _engine():
    return SemanticInference(PATTERNS)


def _mappings():
    with open(MAPPINGS) as handle:
        return json.load(handle)


def _profile(*headers):
    """A minimal profiler-shaped schema for decision tests."""

    return {
        "columns": [
            {
                "column_name": name,
                "category": "categorical",
                "sample_values": [],
            }
            for name in headers
        ]
    }


def _decide(*headers):
    from framework.assessment.entity_context import build_column_name_index
    from framework.mapping.schema_mapper import SchemaMapper

    profile = _profile(*headers)
    candidates = _engine().infer_with_candidates(profile)
    # Production passes the mapper guard; the helper must too, or
    # guard-dependent states (INVALID) can never be observed here.
    guard = SchemaMapper(MAPPINGS, SCHEMA).validate_mapping
    decided = mapping_decisions.decide_mappings(
        profile["columns"], candidates, _mappings(),
        build_column_name_index(profile), guard,
    )

    return {item["source_field"]: item for item in decided["decisions"]}


def _write_csv(tmp_path, name, header, rows):
    path = os.path.join(str(tmp_path), name)

    with open(path, "w", newline="") as handle:
        handle.write(",".join(header) + "\n")

        for row in rows:
            handle.write(",".join(row) + "\n")

    return path


def _package_for(path):
    from framework.pipeline import SATSAPipeline

    return SATSAPipeline().run(path)["canonical_package"]


# ---------------------------------------------------------------------------
# A. Canonical field presence
# ---------------------------------------------------------------------------


class TestCanonicalFieldPresence:
    def test_new_concepts_resolve_to_schema_paths(self):
        """Every contract concept has a canonical_path in mappings.json."""

        assert check_against_mappings(_mappings()) == []

    def test_pipeline_domains_are_declared(self):
        names = set(concept_names())

        for concept in (
            "ALERT_ID", "EVENT_ID", "TRIGGERED_AT", "ALERT_NAME",
            "THREAT_CATEGORY", "SECURITY_SEVERITY", "ASSET_IDENTIFIER",
            "ASSET_TYPE", "NETWORK_ZONE", "SOURCE_SYSTEM",
            "CASE_ID", "CASE_ALERT_ID", "ACKNOWLEDGED_AT", "CLOSED_AT",
            "ANALYST_ID", "ESCALATION_LEVEL", "ESCALATION_STATUS",
            "CLOSURE_DISPOSITION", "INVESTIGATION_NOTES",
            "WORKFLOW_CASE_ID", "WORKFLOW_EVENT_AT", "WORKFLOW_EVENT_TYPE",
            "WORKFLOW_ACTOR", "WORKFLOW_TIER",
            "ASSET_CRITICALITY", "EXPECTED_TELEMETRY",
        ):
            assert concept in names, concept

    def test_schema_holds_the_new_sections(self):
        with open(SCHEMA) as handle:
            schema = json.load(handle)

        assert set(schema["case_context"]) == {
            "case_id", "alert_id", "acknowledged_at", "closed_at",
            "analyst_id", "escalation_level", "closure_disposition",
            "investigation_notes",
        }
        assert set(schema["workflow_context"]) == {
            "case_id", "event_at", "event_type", "actor", "tier",
        }
        assert schema["alert_context"]["alert_id"] is None
        assert schema["asset_context"]["network_zone"] is None
        assert schema["monitoring_context"]["expected_telemetry"] is None

    def test_required_fields_are_declared_per_role(self):
        assert "ALERT_ID" in required_for_role("ALERTS")
        assert "CASE_ID" in required_for_role("CASES")
        assert "WORKFLOW_CASE_ID" in required_for_role("WORKFLOW_EVENTS")
        assert required_for_role("UNKNOWN") == []


# ---------------------------------------------------------------------------
# B. Pipeline role detection
# ---------------------------------------------------------------------------


class TestPipelineRoleDetection:
    def test_alert_schema_detects_alerts(self):
        package = _decide("alert_id", "severity", "triggered_at", "host")

        role = dataset_roles.detect_role(list(package.values()))

        assert role["role"] == "ALERTS"

    def test_case_schema_detects_cases(self):
        package = _decide(
            "case_id", "case_alert", "acknowledged_at", "closed_at",
            "analyst", "closure",
        )

        role = dataset_roles.detect_role(list(package.values()))

        assert role["role"] == "CASES"

    def test_workflow_schema_detects_workflow_events(self):
        package = _decide(
            "workflow_case", "event_type", "event_at", "actor",
        )

        role = dataset_roles.detect_role(list(package.values()))

        assert role["role"] == "WORKFLOW_EVENTS"

    def test_asset_schema_detects_assets(self):
        # Bare 'criticality' is deliberately unmatchable (project
        # convention: asset-qualified names only, so severity-shaped
        # values can never steer it to SECURITY_SEVERITY).
        package = _decide("asset", "asset_criticality", "asset_type")

        role = dataset_roles.detect_role(list(package.values()))

        assert role["role"] == "ASSETS"

    def test_thin_schema_is_unknown(self):
        package = _decide("cse", "period", "random_field")

        role = dataset_roles.detect_role(list(package.values()))

        assert role["role"] == "UNKNOWN"

    def test_explicit_role_is_respected(self):
        package = _decide("alert_id", "severity")

        role = dataset_roles.detect_role(
            list(package.values()), explicit_role="CASES"
        )

        assert role["role"] == "CASES"
        assert "Explicit" in role["reason"]

    def test_unknown_explicit_role_is_unknown(self):
        package = _decide("alert_id", "severity")

        role = dataset_roles.detect_role(
            list(package.values()), explicit_role="SIEM"
        )

        assert role["role"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# C. Alias mapping across vendor header styles
# ---------------------------------------------------------------------------


class TestAliasMapping:
    def test_servicenow_style_headers(self):
        package = _decide(
            "number", "priority", "short_description", "opened_at",
            "resolved_at", "assignment_group", "caller_id",
        )

        assert package["priority"]["canonical_concept"] == "SECURITY_SEVERITY"
        assert package["resolved_at"]["canonical_concept"] == "CLOSED_AT"
        # Unrelated fields stay unmapped however familiar they look.
        assert package["short_description"]["mapping_state"] == UNMAPPED
        assert package["assignment_group"]["mapping_state"] == UNMAPPED
        assert package["caller_id"]["mapping_state"] == UNMAPPED

    def test_jira_style_headers(self):
        package = _decide(
            "issue_key", "summary", "status", "resolution", "assignee",
        )

        assert package["assignee"]["canonical_concept"] == "ANALYST_ID"
        assert package["summary"]["mapping_state"] == UNMAPPED
        assert package["status"]["mapping_state"] == UNMAPPED

    def test_splunk_style_headers(self):
        package = _decide("_time", "src", "dest", "severity", "signature")

        assert package["severity"]["canonical_concept"] == "SECURITY_SEVERITY"
        assert package["src"]["mapping_state"] == UNMAPPED
        assert package["dest"]["mapping_state"] == UNMAPPED

    def test_generic_alias_variants(self):
        package = _decide(
            "alertid", "caseid", "ticket_id", "ack_time", "close_time",
        )

        assert package["alertid"]["canonical_concept"] == "ALERT_ID"
        assert package["caseid"]["canonical_concept"] == "CASE_ID"
        assert package["ticket_id"]["canonical_concept"] == "CASE_ID"
        assert package["ack_time"]["canonical_concept"] == "ACKNOWLEDGED_AT"

    def test_similar_but_unrelated_names_do_not_map(self):
        package = _decide(
            "reopened_date", "severity_score_note", "event_count",
        )

        assert package["reopened_date"]["mapping_state"] == UNMAPPED
        assert package["event_count"]["mapping_state"] == UNMAPPED


# ---------------------------------------------------------------------------
# D. Ambiguous mapping
# ---------------------------------------------------------------------------


class TestAmbiguousMapping:
    def test_close_margin_is_ambiguous_and_unapplied(self):
        from framework.assessment.entity_context import (
            build_column_name_index,
        )

        profile = _profile("some_field")
        candidates = {
            "some_field": [
                {"concept": "CLOSED_AT", "confidence": 0.55},
                {"concept": "ACKNOWLEDGED_AT", "confidence": 0.50},
            ]
        }
        decided = mapping_decisions.decide_mappings(
            profile["columns"], candidates, _mappings(),
            build_column_name_index(profile),
        )
        decision = decided["decisions"][0]

        assert decision["mapping_state"] == AMBIGUOUS
        assert decision["applied"] is False
        assert len(decision["candidate_mappings"]) == 2

    def test_clear_margin_is_mapped(self):
        from framework.assessment.entity_context import (
            build_column_name_index,
        )

        profile = _profile("some_field")
        candidates = {
            "some_field": [
                {"concept": "CLOSED_AT", "confidence": 0.80},
                {"concept": "ACKNOWLEDGED_AT", "confidence": 0.50},
            ]
        }
        decided = mapping_decisions.decide_mappings(
            profile["columns"], candidates, _mappings(),
            build_column_name_index(profile),
        )
        decision = decided["decisions"][0]

        assert decision["mapping_state"] == MAPPED
        assert decision["applied"] is True

    def test_ambiguous_field_is_not_projected(self, tmp_path):
        """The renamed-patterns lesson: a blocked field stays unmapped."""

        mapper = SchemaMapper(MAPPINGS, SCHEMA)
        record = {"some_field": "2026-01-02"}
        semantic = [
            {
                "source_column": "some_field",
                "canonical_concept": "CLOSED_AT",
                "confidence": 0.55,
            }
        ]
        decisions = [
            {
                "source_field": "some_field",
                "source_column": "some_field",
                "canonical_concept": "CLOSED_AT",
                "canonical_path": "case_context.closed_at",
                "confidence": 0.55,
                "mapping_state": AMBIGUOUS,
                "reason": "test",
                "candidate_mappings": [],
                "applied": False,
            }
        ]

        canonical = mapper.map_record(record, semantic, decisions)

        assert canonical["case_context"]["closed_at"] is None


# ---------------------------------------------------------------------------
# E. Mapping collision
# ---------------------------------------------------------------------------


class TestMappingCollision:
    def test_two_fields_one_slot_keeps_the_stronger(self):
        from framework.assessment.entity_context import (
            build_column_name_index,
        )

        profile = _profile("alert_id", "alert_number")
        candidates = {
            "alert_id": [{"concept": "ALERT_ID", "confidence": 0.75}],
            "alert_number": [{"concept": "ALERT_ID", "confidence": 0.60}],
        }
        decided = mapping_decisions.decide_mappings(
            profile["columns"], candidates, _mappings(),
            build_column_name_index(profile),
        )
        by_field = {
            item["source_field"]: item for item in decided["decisions"]
        }

        assert by_field["alert_id"]["applied"] is True
        assert by_field["alert_number"]["mapping_state"] == AMBIGUOUS
        assert by_field["alert_number"]["applied"] is False
        assert decided["collisions"][0]["canonical_path"] == (
            "alert_context.alert_id"
        )
        assert decided["collisions"][0]["winner"] == "alert_id"

    def test_same_slot_aliases_do_not_collide(self):
        """TRIGGERED_AT shares the EVENT_TIMESTAMP slot by design."""

        package = _decide("triggered_at")

        assert package["triggered_at"]["applied"] is True
        assert package["triggered_at"]["canonical_path"] == (
            "alert_context.timestamp"
        )


# ---------------------------------------------------------------------------
# F. Low-confidence mapping
# ---------------------------------------------------------------------------


class TestLowConfidenceMapping:
    def test_weak_match_is_flagged_but_applied(self):
        from framework.assessment.entity_context import (
            build_column_name_index,
        )

        profile = _profile("some_field")
        candidates = {
            "some_field": [{"concept": "CLOSED_AT", "confidence": 0.50}]
        }
        decided = mapping_decisions.decide_mappings(
            profile["columns"], candidates, _mappings(),
            build_column_name_index(profile),
        )
        decision = decided["decisions"][0]

        assert decision["mapping_state"] == LOW_CONFIDENCE
        assert decision["applied"] is True

    def test_below_threshold_is_unmapped(self):
        package = _decide("department")

        assert package["department"]["mapping_state"] == UNMAPPED


# ---------------------------------------------------------------------------
# G. Timestamp normalization
# ---------------------------------------------------------------------------


class TestTimestampNormalization:
    def test_valid_iso_is_preserved_with_zone(self):
        parsed = values.parse_timestamp("2026-01-02T15:04:05+02:00")

        assert parsed["canonical"] == "2026-01-02T15:04:05+02:00"
        assert parsed["tz_aware"] is True
        assert parsed["original"] == "2026-01-02T15:04:05+02:00"

    def test_zulu_suffix_parses(self):
        parsed = values.parse_timestamp("2026-01-02T15:04:05Z")

        assert parsed["canonical"] is not None
        assert parsed["tz_aware"] is True

    def test_naive_is_assumed_utc_and_flagged(self):
        parsed = values.parse_timestamp("2026-01-02 15:04:05")

        assert parsed["canonical"] == "2026-01-02T15:04:05+00:00"
        assert parsed["tz_aware"] is False
        assert parsed["naive_assumed_utc"] is True

    def test_garbage_is_an_error_never_a_guess(self):
        for bad in ("not-a-date", "2026-13-45", 120, None, True, ""):
            parsed = values.parse_timestamp(bad)

            assert parsed["canonical"] is None, bad
            assert parsed["parse_error"] is True, bad


# ---------------------------------------------------------------------------
# H. Invalid chronology
# ---------------------------------------------------------------------------


class TestInvalidChronology:
    def test_ack_before_trigger_is_flagged(self):
        violations = values.check_chronology(
            "2026-01-02T10:00:00+00:00",
            "2026-01-02T09:00:00+00:00",
            "2026-01-02T11:00:00+00:00",
        )

        assert len(violations) == 1
        assert "acknowledged_at < triggered_at" in violations[0]["pair"]

    def test_close_before_ack_is_flagged(self):
        violations = values.check_chronology(
            "2026-01-02T10:00:00+00:00",
            "2026-01-02T12:00:00+00:00",
            "2026-01-02T11:00:00+00:00",
        )

        assert len(violations) == 1
        assert "closed_at < acknowledged_at" in violations[0]["pair"]

    def test_sane_order_is_quiet(self):
        violations = values.check_chronology(
            "2026-01-02T10:00:00+00:00",
            "2026-01-02T10:30:00+00:00",
            "2026-01-02T11:00:00+00:00",
        )

        assert violations == []

    def test_missing_instants_do_not_imply_violations(self):
        assert values.check_chronology(None, None, None) == []
        assert values.check_chronology(
            "2026-01-02T10:00:00+00:00", None, None
        ) == []


# ---------------------------------------------------------------------------
# I. Severity normalization
# ---------------------------------------------------------------------------


class TestSeverityNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Critical", "CRITICAL"),
            ("CRITICAL", "CRITICAL"),
            ("critical", "CRITICAL"),
            ("Sev1", "CRITICAL"),
            ("P1", "CRITICAL"),
            ("High", "HIGH"),
            ("Medium", "MEDIUM"),
            ("Low", "LOW"),
            ("p4", "LOW"),
        ],
    )
    def test_known_vocabularies(self, raw, expected):
        outcome = values.normalize_severity(raw)

        assert outcome["canonical"] == expected
        assert outcome["original"] == raw
        assert outcome["known"] is True

    def test_unknown_is_kept_never_defaulted(self):
        outcome = values.normalize_severity("SUPERBAD")

        assert outcome["canonical"] is None
        assert outcome["original"] == "SUPERBAD"
        assert outcome["known"] is False

    def test_escalation_and_disposition_vocabularies(self):
        assert values.normalize_escalation_status("YES")["canonical"] == (
            "ESCALATED"
        )
        assert values.normalize_escalation_status("no")["canonical"] == (
            "NOT_ESCALATED"
        )
        assert values.normalize_closure_disposition("FP")["canonical"] == (
            "FALSE_POSITIVE"
        )
        assert values.normalize_closure_disposition("mystery")["known"] is (
            False
        )


# ---------------------------------------------------------------------------
# J/K/L/M. Relationships over real pipeline runs
# ---------------------------------------------------------------------------


ALERT_CASE_HEADER = ["alert_id", "severity", "case_id", "case_alert"]


def _alert_case_rows():
    return [
        ["A-1", "CRITICAL", "C-1", "A-1"],
        ["A-2", "HIGH", "C-2", "A-2"],
        ["A-3", "MEDIUM", "C-3", "A-999"],
        ["A-4", "LOW", "", ""],
    ]


class TestAlertCaseRelationships:
    def test_linked_orphan_and_unmatched(self, tmp_path):
        path = _write_csv(
            tmp_path, "alerts_cases.csv", ALERT_CASE_HEADER,
            _alert_case_rows(),
        )
        package = _package_for(path)
        relationships = package["relationships"]

        assert relationships["alerts"] == 4
        assert relationships["cases"] == 3
        assert relationships["linked_cases"]["count"] == 2
        assert relationships["orphan_cases"]["count"] == 1
        assert relationships["orphan_cases"]["sample"] == ["C-3"]
        # A-3 names a missing alert and A-4 names none: exactly those two.
        assert relationships["alerts_without_case"]["count"] == 2
        assert relationships["alerts_without_case"]["sample"] == [
            "A-3", "A-4",
        ]
        assert relationships["alert_case_assessable"] is True

    def test_orphan_case_issue(self, tmp_path):
        path = _write_csv(
            tmp_path, "alerts_cases.csv", ALERT_CASE_HEADER,
            _alert_case_rows(),
        )
        package = _package_for(path)
        codes = package_validation.issue_codes(package["validation"]["issues"])

        assert codes["ORPHAN_CASE"] == 1

    def test_unmatched_alerts_are_info_not_findings(self, tmp_path):
        path = _write_csv(
            tmp_path, "alerts_cases.csv", ALERT_CASE_HEADER,
            _alert_case_rows(),
        )
        package = _package_for(path)
        issues = package["validation"]["issues"]
        unmatched = [i for i in issues if i["code"] == "UNMATCHED_ALERT"]

        assert len(unmatched) == 1
        assert unmatched[0]["severity"] == "info"


WORKFLOW_HEADER = ["case_id", "closed_at", "event_case", "event_type"]


class TestCaseWorkflowRelationships:
    def test_events_join_cases(self, tmp_path):
        path = _write_csv(
            tmp_path,
            "cases_events.csv",
            WORKFLOW_HEADER,
            [
                ["C-1", "2026-01-03", "", ""],
                ["C-2", "2026-01-04", "", ""],
                ["", "", "C-1", "acknowledged"],
                ["", "", "C-1", "escalated"],
                ["", "", "C-9", "closed"],
            ],
        )
        package = _package_for(path)
        relationships = package["relationships"]

        assert relationships["cases"] == 2
        assert relationships["workflow_events"] == 3
        assert relationships["orphan_workflow_cases"]["count"] == 1
        assert relationships["orphan_workflow_cases"]["sample"] == ["C-9"]
        assert relationships["workflow_assessable"] is True

    def test_orphan_workflow_issue(self, tmp_path):
        path = _write_csv(
            tmp_path,
            "cases_events.csv",
            WORKFLOW_HEADER,
            [
                ["C-1", "2026-01-03", "", ""],
                ["", "", "C-9", "closed"],
            ],
        )
        package = _package_for(path)
        codes = package_validation.issue_codes(package["validation"]["issues"])

        assert codes["ORPHAN_WORKFLOW_EVENT"] == 1

    def test_impossible_chronology_is_an_error(self, tmp_path):
        path = _write_csv(
            tmp_path,
            "cases_time.csv",
            ["case_id", "triggered_at", "acknowledged_at", "closed_at"],
            [
                ["C-1", "2026-01-02T10:00:00", "2026-01-02T09:00:00",
                 "2026-01-02T11:00:00"],
            ],
        )
        package = _package_for(path)
        issues = package["validation"]["issues"]
        chrono = [i for i in issues if i["code"] == "IMPOSSIBLE_CHRONOLOGY"]

        assert len(chrono) == 1
        assert chrono[0]["severity"] == "error"


# ---------------------------------------------------------------------------
# N. Provenance preservation
# ---------------------------------------------------------------------------


class TestProvenancePreservation:
    def test_original_spelling_survives_lowering(self):
        package = _decide("Alert_ID", "Priority")

        assert package["Alert_ID"]["source_field"] == "Alert_ID"
        assert package["Alert_ID"]["source_column"] == "alert_id"
        assert package["Alert_ID"]["canonical_concept"] == "ALERT_ID"

    def test_mixed_case_records_still_project(self):
        mapper = SchemaMapper(MAPPINGS, SCHEMA)
        record = {"Priority": "HIGH", "Hostname": "WEB-1"}
        semantic = [
            {
                "source_column": "priority",
                "canonical_concept": "SECURITY_SEVERITY",
                "confidence": 0.75,
            },
            {
                "source_column": "hostname",
                "canonical_concept": "ASSET_IDENTIFIER",
                "confidence": 0.75,
            },
        ]

        canonical = mapper.map_record(record, semantic)

        assert canonical["alert_context"]["severity"] == "HIGH"
        assert canonical["asset_context"]["asset_id"] == "WEB-1"

    def test_normalization_keeps_originals(self):
        outcome = values.normalize_severity("Sev1")

        assert outcome == {
            "canonical": "CRITICAL",
            "original": "Sev1",
            "known": True,
        }

    def test_package_carries_provenance(self, tmp_path):
        path = _write_csv(
            tmp_path, "alerts_cases.csv", ALERT_CASE_HEADER,
            _alert_case_rows(),
        )
        package = _package_for(path)

        assert package["package_version"] == "1"
        assert package["source_dataset"] == path
        assert package["provenance"]["record_count"] == 4
        assert package["provenance"]["naive_timestamp_policy"] == (
            "assumed_utc"
        )


# ---------------------------------------------------------------------------
# O. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_legacy_mapping_shape_is_unchanged(self, tmp_path):
        path = _write_csv(
            tmp_path, "alerts_cases.csv", ALERT_CASE_HEADER,
            _alert_case_rows(),
        )

        from framework.pipeline import SATSAPipeline

        result = SATSAPipeline().run(path)

        for entry in result["semantic_mapping"]:
            assert set(entry) == {
                "source_column", "canonical_concept", "confidence",
            }

    def test_established_mappings_still_resolve(self):
        package = _decide(
            "priority", "hostname", "escalation_status",
            "investigation_notes", "threat_type",
        )

        assert package["priority"]["canonical_concept"] == "SECURITY_SEVERITY"
        assert package["hostname"]["canonical_concept"] == "ASSET_IDENTIFIER"
        assert (
            package["escalation_status"]["canonical_concept"]
            == "ESCALATION_STATUS"
        )
        assert (
            package["investigation_notes"]["canonical_concept"]
            == "INVESTIGATION_EVIDENCE"
        )
        assert package["threat_type"]["canonical_concept"] == "THREAT_CATEGORY"

    def test_closed_by_never_becomes_a_timestamp(self):
        package = _decide("closed_by", "resolved_by")

        assert package["closed_by"]["mapping_state"] == INVALID
        assert package["closed_by"]["applied"] is False
        assert package["resolved_by"]["mapping_state"] == INVALID

    def test_guard_also_blocks_record_projection(self):
        mapper = SchemaMapper(MAPPINGS, SCHEMA)
        record = {"closed_by": "Alice"}
        semantic = [
            {
                "source_column": "closed_by",
                "canonical_concept": "CLOSED_AT",
                "confidence": 0.9,
            }
        ]

        canonical = mapper.map_record(record, semantic)

        assert canonical["case_context"]["closed_at"] is None
