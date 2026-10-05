"""Deterministic peer cohort selection.

A peer cohort is the set of assessment scopes a target may fairly be compared
with. Getting this wrong is the single easiest way to make a benchmark say
something true of the arithmetic and false of the organisation, so the rules
are deliberately narrow and the selection is fully auditable.

THE THREE TIERS, MOST SPECIFIC FIRST
====================================

  1. same period + evidenced sector + entity class + size band
  2. same period + evidenced sector + entity class
  3. same period

Tier 3 is the floor and never widens past the period. Two CSEs assessed over
different periods were observed under different operating conditions, so a
comparison between them measures the difference in the periods.

METADATA IS EVIDENCED OR IT DOES NOT EXIST
===========================================

Sector, entity class and size band are not derived from a dataset column, a
name pattern, a country or a default. They exist only when a supervisory
authority has recorded them for an entity id in
``framework/config/peer_benchmark.json``.

This has a visible consequence the interface must render honestly: with no
recorded attributes, tiers 1 and 2 are unavailable and tier 3 is the cohort.
The result says so in words rather than presenting a same-period cohort as a
sector-matched one.

SELF-EXCLUSION
==============

The target is removed from its own cohort. A benchmark that included the
target in the median it was compared against would damp its own deviation and
make an outlier look ordinary.

DETERMINISM
===========

Cohort membership is ordered by assessment id, so two runs over the same
submission produce byte-identical cohorts. There is no sampling and no set
iteration order in the output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: The attributes that narrow a cohort, in the order the tiers consume them.
COHORT_ATTRIBUTES = ("sector", "entity_class", "size_band")

SELF_EXCLUDED = "SELF_EXCLUDED"
NO_ELIGIBLE_PEERS = "NO_ELIGIBLE_PEERS"
METADATA_UNAVAILABLE = "METADATA_UNAVAILABLE"


class BenchmarkConfigError(Exception):
    """The peer benchmarking configuration is not usable as written."""


class CohortTier:
    """One rung of the cohort hierarchy."""

    def __init__(self, definition: Mapping[str, Any]) -> None:

        if "tier" not in definition or "tier_id" not in definition:
            raise BenchmarkConfigError(
                "a cohort tier must declare both 'tier' and 'tier_id'"
            )

        self.tier = int(definition["tier"])
        self.tier_id = str(definition["tier_id"])
        self.label = str(definition.get("label") or self.tier_id)
        self.requires = tuple(
            str(name) for name in (definition.get("requires") or ())
        )
        self.selection_rule = list(definition.get("selection_rule") or ())

        for name in self.requires:
            if name not in COHORT_ATTRIBUTES:
                raise BenchmarkConfigError(
                    f"cohort tier {self.tier_id!r} requires unknown attribute "
                    f"{name!r}; known attributes are {COHORT_ATTRIBUTES}"
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_id": self.tier_id,
            "label": self.label,
            "requires": list(self.requires),
            "selection_rule": list(self.selection_rule),
        }


class PeerCohortResolver:
    """Chooses the cohort a target is benchmarked against.

    Constructed from the shipped configuration. ``entity_attributes`` maps an
    entity id to the attributes a supervisory authority has recorded for it;
    an entity absent from that mapping, or present with a ``None`` value,
    simply has no evidenced attribute.
    """

    def __init__(
        self,
        tiers: Sequence[CohortTier],
        entity_attributes: Mapping[str, Mapping[str, Any]],
    ) -> None:

        self.tiers = sorted(tiers, key=lambda tier: tier.tier)

        if not self.tiers:
            raise BenchmarkConfigError(
                "peer benchmarking requires at least one cohort tier"
            )

        self.entity_attributes: Dict[str, Dict[str, Any]] = {
            str(entity_id): {
                name: attributes.get(name)
                for name in COHORT_ATTRIBUTES
            }
            for entity_id, attributes in entity_attributes.items()
        }

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, definition: Mapping[str, Any]) -> "PeerCohortResolver":
        tiers = [CohortTier(item) for item in definition.get("cohort_tiers") or ()]

        attributes = definition.get("entity_attributes") or {}
        entries = attributes.get("entries") if isinstance(attributes, Mapping) else attributes

        return cls(tiers, entries or {})

    # -- attribute evidence -------------------------------------------------

    def evidenced_attributes(self, entity_id: Optional[str]) -> Dict[str, Any]:
        """Attributes actually recorded for ``entity_id``.

        A value of ``None`` is reported as ``None`` rather than omitted, so a
        screen can distinguish "no attribute recorded" from "this attribute
        does not apply".
        """

        if entity_id is None:
            return {name: None for name in COHORT_ATTRIBUTES}

        recorded = self.entity_attributes.get(str(entity_id), {})

        return {name: recorded.get(name) for name in COHORT_ATTRIBUTES}

    # -- resolution ---------------------------------------------------------

    def resolve(
        self,
        target: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Resolve the cohort for ``target`` against ``candidates``.

        Every candidate that survived the wider analysis carries a resolved
        period label and an entity id. Candidates with an unresolved period
        are never eligible, because a cohort whose members are not known to
        share the target's period is not a same-period cohort.
        """

        target_period = target.get("period_label")
        target_entity = target.get("entity_id")

        target_attributes = self.evidenced_attributes(target_entity)

        same_period = [
            candidate
            for candidate in candidates
            if candidate.get("period_label") == target_period
            and candidate.get("period_label") is not None
        ]

        unresolved_period = [
            candidate
            for candidate in candidates
            if candidate.get("period_label") is None
        ]

        evaluations: List[Dict[str, Any]] = []

        for tier in self.tiers:

            missing = [
                name
                for name in tier.requires
                if target_attributes.get(name) is None
            ]

            if missing:
                evaluations.append(
                    {
                        **tier.to_dict(),
                        "status": METADATA_UNAVAILABLE,
                        "peer_count": 0,
                        "excluded_self": False,
                        "member_assessment_ids": [],
                        "not_available_reason": (
                            "no evidenced "
                            + ", ".join(missing)
                            + " recorded for this entity, so a "
                            + f"{tier.tier_id} cohort cannot be selected "
                            "without inventing that attribute"
                        ),
                    }
                )
                continue

            members = [
                candidate
                for candidate in same_period
                if candidate.get("assessment_id") != target.get("assessment_id")
            ]

            matched: List[Mapping[str, Any]] = []

            for candidate in members:

                candidate_attributes = self.evidenced_attributes(
                    candidate.get("entity_id")
                )

                if all(
                    candidate_attributes.get(name) == target_attributes.get(name)
                    for name in tier.requires
                ):
                    matched.append(candidate)

            ordered = sorted(
                matched, key=lambda item: str(item.get("assessment_id") or "")
            )

            evaluations.append(
                {
                    **tier.to_dict(),
                    "status": "SELECTED" if ordered else NO_ELIGIBLE_PEERS,
                    "peer_count": len(ordered),
                    "excluded_self": True,
                    "member_assessment_ids": [
                        str(item.get("assessment_id")) for item in ordered
                    ],
                    "not_available_reason": (
                        None
                        if ordered
                        else "no other scope in this assessment shared the "
                        "selected period and evidenced attributes"
                    ),
                }
            )

        selected = next(
            (item for item in evaluations if item["status"] == "SELECTED"), None
        )

        return {
            "cohort_id": (
                selected["tier_id"] if selected is not None else None
            ),
            "tier": selected["tier"] if selected is not None else None,
            "label": selected["label"] if selected is not None else None,
            "status": selected["status"] if selected is not None else NO_ELIGIBLE_PEERS,
            "member_assessment_ids": (
                selected["member_assessment_ids"] if selected is not None else []
            ),
            "peer_count": selected["peer_count"] if selected is not None else 0,
            "selection_rule": (
                selected["selection_rule"] if selected is not None else []
            ),
            "selection_rule_steps": list(
                evaluations[-1]["selection_rule"] if evaluations else []
            ),
            "target_attributes": target_attributes,
            "tiers_evaluated": evaluations,
            "same_period_candidate_count": len(same_period),
            "unresolved_period_scope_count": len(unresolved_period),
            "excluded_assessment_ids": [
                str(target.get("assessment_id"))
            ]
            if target.get("assessment_id") is not None
            else [],
            "not_available_reason": (
                None
                if selected is not None
                else "this assessment produced no peer scope sharing the "
                "target's period, so no cohort could be formed"
            ),
        }

    # -- reporting ----------------------------------------------------------

    def describe_hierarchy(self) -> List[Dict[str, Any]]:
        """The configured hierarchy, for publication with every result.

        A reader must be able to see which cohort was aimed for and which was
        actually reached, not only the one that was used.
        """

        return [tier.to_dict() for tier in self.tiers]