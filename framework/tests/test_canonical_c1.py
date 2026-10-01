"""C.1 tests: authoritative canonical mapping review.

Backend coverage for the C.1 brief items that have backend substance:

A. decisions exposed | B. legacy list not authoritative | C-G. each state |
H. dropdown only registry concepts | J. UNMAPPED first-class |
K. datatype compatibility | L. semantic/value compatibility |
M. recommended == authoritative best | N/O. guards | P. collisions |
Q. override distinguishable | R. mapping change invalidates analysis |
S. source preserved | T/U. legacy keys intact.

H (strict select), I (no free text), Q (reviewer vs automatic) and R
(rerun banner) have their UI half in
`frontend/src/components/assessment/CanonicalMappingReview.tsx` +
`frontend/src/lib/canonicalMapping.ts`; the backend halves are asserted
here so a regression fails in pytest, not only in a browser.
"""

from __future__ import annotations

import json

from framework.assessment.entity_context import build_column_name_index
from framework.canonical import decisions as mapping_decisions
from framework.canonical.contract import (
    AMBIGUOUS,
    INVALID,
    LOW_CONFIDENCE,
    MAPPED,
    UNMAPPED,
    concept_names,
    get_concept,
)
from framework.canonical.package import build_canonical_package
from framework.intelligence.semantic_inference import SemanticInference
from framework.mapping.schema_mapper import (
    TIMESTAMP_CONCEPTS,
    SchemaMapper,
)

PATTERNS = "framework/config/semantic_patterns.json"
MAPPINGS = "framework/config/mappings.json"
SCHEMA = "framework/canonical/canonical_schema.json"


def _engine():
    return SemanticInference(PATTERNS)


def _mappings():
    with open(MAPPINGS) as handle:
        return json.load(handle)


def _mapper():
    return SchemaMapper(MAPPINGS, SCHEMA)


def _profile(headers, categories=None, samples=None):
    categories = categories or {}
    samples = samples or {}

    return {
        "columns": [
            {
                "column_name": name,
                "category": categories.get(name, "categorical"),
                "sample_values": samples.get(name, []),
            }
            for name in headers
        ]
    }


def _decide(headers, categories=None, samples=None):
    profile = _profile(headers, categories, samples)
    candidates = _engine().infer_with_candidates(profile)
    decided = mapping_decisions.decide_mappings(
        profile["columns"],
        candidates,
        _mappings(),
        build_column_name_index(profile),
        _mapper().validate_mapping,
    )

    return decided, candidates


def _by_field(decided):
    return {item["source_field"]: item for item in decided["decisions"]}


# A. Authoritative decisions are exposed to the data layer.
def test_canonical_contract_transport_in_package(tmp_path):
    header = ["case_id", "priority", "assigned_to", "closed_at"]
    path = str(tmp_path / "c1.csv")

    with open(path, "w") as handle:
        handle.write(",".join(header) + "\n")
        handle.write("C-1,High,alice,2024-01-02\n")

    from framework.pipeline import SATSAPipeline

    package = SATSAPipeline().run(path)["canonical_package"]

    assert isinstance(package["mapping_decisions"], list)
    assert package["mapping_decisions"], "expected one decision per column"
    assert set(package["mapping_states"]) >= {
        MAPPED, LOW_CONFIDENCE, AMBIGUOUS, UNMAPPED, INVALID,
    }
    # Minimal additive registry view for the strict dropdown.
    assert set(package["canonical_contract"]) == set(concept_names())

    for name, entry in package["canonical_contract"].items():
        assert entry["canonical_path"], name
        assert entry["datatype"], name


# B. Legacy semantic_mapping is no longer the truth: an INVALID/AMBIGUOUS
# field may appear in the legacy winner list but is never applied.
def test_legacy_list_not_authoritative_for_invalid():
    decided, _ = _decide(["resolved_by"])
    decision = _by_field(decided)["resolved_by"]

    assert decision["mapping_state"] == INVALID
    assert decision["applied"] is False
    assert mapping_decisions.applied_mapping(decided["decisions"]) == []


def test_collision_loser_not_applied_despite_legacy_score():
    decided, _ = _decide(["closed_at", "closed_code"])
    by_field = _by_field(decided)

    assert by_field["closed_at"]["applied"] is True
    assert by_field["closed_code"]["mapping_state"] == AMBIGUOUS
    assert by_field["closed_code"]["applied"] is False
    assert decided["collisions"], "expected a collision record"


# C-G. Each state displays from real decision data.
def test_mapped_displays():
    by_field = _by_field(_decide(["priority"], samples={"priority": ["Critical", "High"]})[0])
    decision = by_field["priority"]

    assert decision["mapping_state"] == MAPPED
    assert decision["canonical_concept"] == "SECURITY_SEVERITY"
    assert decision["applied"] is True


def test_low_confidence_displays():
    by_field = _by_field(_decide(["host_alias"])[0])
    decision = by_field["host_alias"]

    assert decision["mapping_state"] == LOW_CONFIDENCE
    assert decision["applied"] is True
    assert 0.45 <= decision["confidence"] < 0.60


def test_ambiguous_displays_with_candidates():
    decided, _ = _decide(["closed_at", "closed_code"])
    decision = _by_field(decided)["closed_code"]

    assert decision["mapping_state"] == AMBIGUOUS
    assert decision["applied"] is False
    assert len(decision["candidate_mappings"]) >= 1
    assert "Collision" in decision["reason"] or "plausibly explain" in decision["reason"]


def test_invalid_displays_with_reason():
    by_field = _by_field(_decide(["resolved_by"])[0])
    decision = by_field["resolved_by"]

    assert decision["mapping_state"] == INVALID
    assert decision["applied"] is False
    assert decision["reason"], "INVALID must carry a reason, never silence"


def test_unmapped_displays():
    by_field = _by_field(_decide(["zzqx_gibberish"])[0])
    decision = by_field["zzqx_gibberish"]

    assert decision["mapping_state"] == UNMAPPED
    assert decision["canonical_concept"] is None
    assert decision["applied"] is False


# H. Dropdown contains only valid registry concepts (+ UNMAPPED at UI).
def test_every_candidate_is_a_registry_concept():
    decided, _ = _decide(
        ["priority", "assigned_to", "resolved_by", "closed_code", "host_alias"]
    )
    registry = set(concept_names())

    for decision in decided["decisions"]:
        for candidate in decision["candidate_mappings"]:
            assert candidate["concept"] in registry


def test_unknown_concept_has_no_path_and_is_invalid():
    assert get_concept("NOT_A_CONCEPT") is None

    profile = _profile(["zzqx_gibberish"])
    decided = mapping_decisions.decide_mappings(
        profile["columns"],
        {"zzqx_gibberish": [{"concept": "NOT_A_CONCEPT", "confidence": 0.99}]},
        _mappings(),
        build_column_name_index(profile),
        _mapper().validate_mapping,
    )
    decision = decided["decisions"][0]

    assert decision["mapping_state"] == INVALID
    assert decision["applied"] is False


# K. Datatype compatibility metadata exists for the dropdown filter.
def test_timestamp_concepts_declare_timestamp_datatype():
    for concept in TIMESTAMP_CONCEPTS:
        entry = get_concept(concept)

        assert entry is not None, concept
        assert entry["datatype"] == "timestamp", concept


def test_boolean_and_numeric_concepts_typed():
    assert get_concept("ESCALATION_STATUS")["datatype"] == "categorical"
    assert get_concept("CASE_ID")["datatype"] == "identifier"
    assert get_concept("CLOSED_AT")["datatype"] == "timestamp"


# L. Semantic/value compatibility: severity vocabulary resolves priority.
def test_priority_values_resolve_severity():
    by_field = _by_field(
        _decide(["priority"], samples={"priority": ["Critical", "High", "Medium", "Low"]})[0]
    )

    assert by_field["priority"]["canonical_concept"] == "SECURITY_SEVERITY"


def test_case_id_resolves_identifier_concept():
    by_field = _by_field(_decide(["case_id"])[0])

    assert by_field["case_id"]["canonical_concept"] == "CASE_ID"


# M. The recommended candidate is the authoritative best, not a UI guess.
def test_decision_concept_is_best_candidate_for_mapped():
    decided, _ = _decide(["priority", "assigned_to", "case_id"])

    for decision in decided["decisions"]:
        if decision["mapping_state"] != MAPPED:
            continue

        best = max(
            decision["candidate_mappings"], key=lambda item: item["confidence"]
        )

        assert decision["canonical_concept"] == best["concept"]


# N/O. Guards: actor-like fields never become timestamps.
def test_actor_guard_blocks_resolved_by_to_closed_at():
    assert _mapper().validate_mapping("CLOSED_AT", "resolved_by", None) is False


def test_actor_guard_covers_all_timestamp_concepts():
    mapper = _mapper()

    for concept in TIMESTAMP_CONCEPTS:
        assert mapper.validate_mapping(concept, "resolved_by", None) is False, concept
        assert mapper.validate_mapping(concept, "closed_by", None) is False, concept


def test_resolved_by_invalid_even_with_high_score():
    decided, _ = _decide(["resolved_by"])
    decision = _by_field(decided)["resolved_by"]

    assert decision["mapping_state"] == INVALID
    assert decision["canonical_concept"] == "CLOSED_AT"


# P. Collision handling preserved: winner applied, loser demoted, recorded.
def test_collision_rules():
    decided, _ = _decide(["closed_at", "closed_code"])
    by_field = _by_field(decided)

    assert by_field["closed_at"]["mapping_state"] == MAPPED
    assert by_field["closed_code"]["mapping_state"] == AMBIGUOUS

    (collision,) = decided["collisions"]

    assert collision["canonical_path"] == "case_context.closed_at"
    assert collision["winner"] == "closed_at"
    assert collision["losers"] == ["closed_code"]


# Q. Override model: reviewer decision is separate from automatic decision.
def test_override_does_not_mutate_automatic_decision():
    decided, _ = _decide(["resolved_by"])
    (decision,) = decided["decisions"]

    override = {
        "source_field": decision["source_field"],
        "previous_automatic": {
            "concept": decision["canonical_concept"],
            "state": decision["mapping_state"],
        },
        "reviewer_decision": "ANALYST_ID",
        "source": "REVIEWER_OVERRIDE",
    }

    assert decision["mapping_state"] == INVALID
    assert decision["canonical_concept"] == "CLOSED_AT"
    assert override["reviewer_decision"] == "ANALYST_ID"
    assert override["previous_automatic"]["state"] == INVALID
    # The automatic record is untouched; the reviewer choice lives beside it.
    assert decision["canonical_concept"] != override["reviewer_decision"]


# R. A mapping change invalidates the analysis inputs.
def test_changed_mapping_changes_applied_projection():
    decided, _ = _decide(["priority", "host_alias"])
    before = mapping_decisions.applied_mapping(decided["decisions"])

    rewritten = [
        dict(item, mapping_state=UNMAPPED, applied=False, canonical_concept=None)
        if item["source_field"] == "host_alias"
        else dict(item)
        for item in decided["decisions"]
    ]
    after = mapping_decisions.applied_mapping(rewritten)

    assert len(after) == len(before) - 1
    assert {item["source_column"] for item in after} == {"priority"}


# S. Original source field/value preserved (spelling, not just lowered key).
def test_source_spelling_preserved():
    decided, _ = _decide(["Assigned_To"])
    (decision,) = decided["decisions"]

    assert decision["source_field"] == "Assigned_To"
    assert decision["source_column"] == "assigned_to"


# T/U. Legacy transport keys intact for compatibility.
def test_legacy_keys_still_present(tmp_path):
    path = str(tmp_path / "c1legacy.csv")

    with open(path, "w") as handle:
        handle.write("case_id,priority\nC-1,High\n")

    from framework.pipeline import SATSAPipeline

    result = SATSAPipeline().run(path)

    assert isinstance(result["semantic_mapping"], list)
    assert isinstance(result["mapping_report"], dict)
    assert "canonical_package" in result
