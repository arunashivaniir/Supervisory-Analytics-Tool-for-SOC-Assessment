"""Schema-level mapping decisions for SAT-SA Phase 1.

``SemanticInference`` scores columns; this module turns those scores into
decisions. One decision per source field, made once per submission schema
and then applied to every record — never rediscovered per row.

The governing rule is that a wrong mapping is worse than an unmapped
column:

* candidates closer than ``AMBIGUITY_MARGIN`` leave the field AMBIGUOUS
  and unapplied, however slightly one of them leads;
* two fields claiming one canonical slot is a collision: the stronger
  claim wins, the other is demoted to AMBIGUOUS, never silently merged;
* candidates sharing one canonical slot (e.g. TRIGGERED_AT and the
  legacy EVENT_TIMESTAMP) are merged, not treated as rivals;
* anything below ``APPLY_THRESHOLD`` stays UNMAPPED;
* a concept the mapper cannot write is INVALID;
* a candidate the mapper's own guard rejects (e.g. an actor column as
  a timestamp) is INVALID, however high it scored.

Decisions are additive metadata. The legacy ``semantic_mapping`` list
``[{source_column, canonical_concept, confidence}]`` is unchanged, and
``applied_mapping()`` reproduces exactly the entries the v4 pipeline
would have applied, minus ambiguous ones.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from framework.canonical.contract import (
    AMBIGUOUS,
    AMBIGUITY_MARGIN,
    APPLY_THRESHOLD,
    INVALID,
    LOW_CONFIDENCE,
    MAPPED,
    MAPPED_MIN_CONFIDENCE,
    UNMAPPED,
)

# A candidate the mapper cannot write. Recorded, never applied.
_UNKNOWN_PATH = None


def decide_mappings(
    columns: Sequence[Mapping[str, Any]],
    candidates_by_column: Mapping[str, List[Dict[str, Any]]],
    mappings: Mapping[str, Any],
    name_index: Mapping[str, str],
    guard: Optional[Callable[[str, str, Any], bool]] = None,
) -> Dict[str, Any]:
    """Decide one mapping per source field.

    ``candidates_by_column`` maps lowercased column name -> scored
    candidates ``[{concept, confidence}]`` sorted best-first (see
    ``SemanticInference.infer_with_candidates``). ``name_index`` maps
    lowercased names back to their original spelling for provenance.
    ``guard`` is the mapper's ``validate_mapping``: candidates it
    rejects are recorded INVALID, never applied.
    """

    decisions: List[Dict[str, Any]] = []

    for column in columns:
        original = column.get("column_name")

        if not isinstance(original, str) or not original:
            continue

        lowered = original.lower()
        candidates = list(candidates_by_column.get(lowered, []))

        decisions.append(
            _decide_one(
                original, lowered, candidates, mappings, name_index, guard
            )
        )

    collisions = _resolve_collisions(decisions)

    return {"decisions": decisions, "collisions": collisions}


def _decide_one(
    original: str,
    lowered: str,
    candidates: List[Dict[str, Any]],
    mappings: Mapping[str, Any],
    name_index: Mapping[str, str],
    guard: Optional[Callable[[str, str, Any], bool]],
) -> Dict[str, Any]:
    spelled = name_index.get(lowered, original)

    # The mapper's own guard rejects incompatible semantics (actor
    # columns as timestamps and the like) regardless of score. A
    # rejected best candidate invalidates the field: falling through to
    # a weaker candidate would launder the same confusion.
    rejected = [
        item["concept"]
        for item in candidates
        if guard is not None
        and not _guard_allows(guard, item["concept"], lowered)
    ]

    usable = [
        item for item in candidates if item["concept"] not in rejected
    ]

    # Drop candidates the mapper cannot write, but remember them: a
    # concept inference names that has no canonical_path is a
    # configuration error, not a quiet miss.
    invalid = [
        item for item in usable if _path_for(item["concept"], mappings) is None
    ]
    usable = [
        item for item in usable if _path_for(item["concept"], mappings) is not None
    ]

    candidate_view = [
        {
            "concept": item["concept"],
            "canonical_path": _path_for(item["concept"], mappings),
            "confidence": item["confidence"],
        }
        for item in candidates
    ]

    if not usable:
        if rejected:
            return _decision(
                spelled, lowered, rejected[0], None,
                candidates[0]["confidence"], INVALID, candidate_view,
                reason=(
                    "The mapper's guard rejects '%s' as '%s'; "
                    "incompatible semantics are rejected, never "
                    "re-ranked." % (spelled, rejected[0])
                ),
            )

        if invalid:
            best = invalid[0]
            return _decision(
                spelled, lowered, best["concept"], None,
                best["confidence"], INVALID, candidate_view,
                reason=(
                    "Inference named '%s' but it has no canonical_path in "
                    "mappings.json, so there is nowhere to write it."
                    % best["concept"]
                ),
            )

        return _decision(
            spelled, lowered, None, None, 0.0, UNMAPPED, candidate_view,
            reason="No candidate reached the apply threshold.",
        )

    # Merge candidates that share one canonical slot: aliases for one
    # field are agreement, not rivalry.
    by_path: Dict[Any, Dict[str, Any]] = {}

    for item in usable:
        path = _path_for(item["concept"], mappings)

        current = by_path.get(path)

        if current is None or item["confidence"] > current["confidence"]:
            by_path[path] = item

    ranked = sorted(
        by_path.values(), key=lambda item: item["confidence"], reverse=True
    )
    best = ranked[0]
    path = _path_for(best["concept"], mappings)

    if len(ranked) > 1:
        runner = ranked[1]
        margin = round(best["confidence"] - runner["confidence"], 2)

        if margin < AMBIGUITY_MARGIN:
            return _decision(
                spelled, lowered, best["concept"], path,
                best["confidence"], AMBIGUOUS, candidate_view,
                reason=(
                    "'%s' (%.2f) and '%s' (%.2f) both plausibly explain "
                    "this field (margin %.2f < %.2f). Left unmapped "
                    "rather than guessed."
                    % (
                        best["concept"], best["confidence"],
                        runner["concept"], runner["confidence"],
                        margin, AMBIGUITY_MARGIN,
                    )
                ),
            )

    if best["confidence"] >= MAPPED_MIN_CONFIDENCE:
        state = MAPPED
        reason = "Clear best candidate at or above %.2f." % MAPPED_MIN_CONFIDENCE
    else:
        state = LOW_CONFIDENCE
        reason = (
            "Applied as v4 would apply it (at or above %.2f) but flagged: "
            "below the %.2f mapped threshold."
            % (APPLY_THRESHOLD, MAPPED_MIN_CONFIDENCE)
        )

    return _decision(
        spelled, lowered, best["concept"], path,
        best["confidence"], state, candidate_view, reason=reason,
    )


def _resolve_collisions(
    decisions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Demote all but the strongest claim on each canonical slot.

    Mutates the losing decisions to AMBIGUOUS (applied False) and returns
    a collision record per contested slot. Deterministic: higher
    confidence wins, ties break on source field name.
    """

    by_path: Dict[str, List[Dict[str, Any]]] = {}

    for decision in decisions:
        if not decision["applied"] or not decision["canonical_path"]:
            continue

        by_path.setdefault(decision["canonical_path"], []).append(decision)

    collisions = []

    for path, claimants in by_path.items():
        if len(claimants) < 2:
            continue

        ordered = sorted(
            claimants,
            key=lambda item: (-item["confidence"], item["source_field"]),
        )
        winner = ordered[0]

        for loser in ordered[1:]:
            loser["mapping_state"] = AMBIGUOUS
            loser["applied"] = False
            loser["reason"] = (
                "Collision on '%s': '%s' (%.2f) outscored this field "
                "(%.2f). Left unmapped rather than merged."
                % (
                    path, winner["source_field"], winner["confidence"],
                    loser["confidence"],
                )
            )

        collisions.append(
            {
                "canonical_path": path,
                "winner": winner["source_field"],
                "losers": [item["source_field"] for item in ordered[1:]],
            }
        )

    return collisions


def applied_mapping(
    decisions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Legacy-shape entries for applied decisions only.

    ``[{source_column, canonical_concept, confidence}]`` — the shape
    ``SchemaMapper.map_record`` and the v4 pipeline consume.
    """

    return [
        {
            "source_column": item["source_column"],
            "canonical_concept": item["canonical_concept"],
            "confidence": item["confidence"],
        }
        for item in decisions
        if item["applied"]
    ]


def _guard_allows(
    guard: Callable[[str, str, Any], bool],
    concept: str,
    lowered: str,
) -> bool:
    """Run the mapper guard at schema level (no record value involved)."""

    try:
        return bool(guard(concept, lowered, None))
    except Exception:
        return True


def _path_for(concept: str, mappings: Mapping[str, Any]) -> Any:
    entry = mappings.get(concept)

    if isinstance(entry, dict):
        return entry.get("canonical_path")

    return None


def _decision(
    spelled: str,
    lowered: str,
    concept: Any,
    path: Any,
    confidence: float,
    state: str,
    candidates: List[Dict[str, Any]],
    reason: str,
) -> Dict[str, Any]:
    return {
        "source_field": spelled,
        "source_column": lowered,
        "canonical_concept": concept,
        "canonical_path": path,
        "confidence": confidence,
        "mapping_state": state,
        "reason": reason,
        "candidate_mappings": candidates,
        "applied": state in (MAPPED, LOW_CONFIDENCE),
    }


def states_count(decisions: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """How many decisions reached each state (for reports and tests)."""

    counts = {state: 0 for state in (MAPPED, LOW_CONFIDENCE, AMBIGUOUS, UNMAPPED, INVALID)}

    for item in decisions:
        counts[item["mapping_state"]] = counts.get(item["mapping_state"], 0) + 1

    return counts
