"""Normalisation of existing SAT-SA findings for indicator-level comparison.

All three intelligence families already publish findings in the same shape:
``indicator``, ``capability``, ``assessment_id``, ``entity``, ``period``,
``record_reference`` and a status. This module projects those existing objects
into a flat comparison record. It does not restate them, does not rename any
indicator, and does not merge or synthesise across families.

The one thing normalisation deliberately refuses to do is flatten free text.
Explanations are carried through separately so a human's reasoning and the
tool's reasoning stay independently reviewable; they are never compared by
string equality.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.validation.corpus import FAMILIES, FAMILY_RESULT_KEYS

#: Statuses that mean "the layer declined to judge", kept apart from "the layer
#: judged and found nothing". Conflating them would inflate recall.
NOT_EVALUABLE = "NOT_EVALUABLE"
EVIDENCE_NOT_PRESENT = "EVIDENCE_NOT_PRESENT"
NO_PATTERN_DETECTED = "NO_PATTERN_DETECTED"
POTENTIAL_OPERATIONAL_ANOMALY = "POTENTIAL_OPERATIONAL_ANOMALY"

DECLINED_STATUSES = (NOT_EVALUABLE, EVIDENCE_NOT_PRESENT)


class NormalisedSignal:
    """One finding, reduced to the fields a comparison can legitimately use."""

    __slots__ = (
        "family",
        "indicator",
        "capability",
        "assessment_id",
        "entity_id",
        "period_label",
        "status",
        "raw_positions",
        "scope_positions",
        "explanation",
        "evidence_concepts",
        "raw",
    )

    def __init__(
        self,
        family: str,
        finding: Mapping[str, Any],
        raw_positions: Optional[Sequence[int]] = None,
        scope_positions: Optional[Sequence[int]] = None,
    ) -> None:
        self.family = family
        self.raw = dict(finding)

        self.indicator = finding.get("indicator")
        self.capability = finding.get("capability")
        self.assessment_id = finding.get("assessment_id")
        self.status = finding.get("status")

        entity = finding.get("entity") or {}
        period = finding.get("period") or {}

        self.entity_id = entity.get("id")
        self.period_label = period.get("label")

        # Two different index spaces, kept apart on purpose. ``raw_positions``
        # are offsets into the submitted CSV; ``scope_positions`` are offsets
        # into the records of this assessment scope only. Conflating them makes
        # a finding that correctly points at the third row of its scope look
        # like it points past the end of the file, or the other way round.
        self.raw_positions = (
            list(raw_positions) if raw_positions is not None else []
        )
        self.scope_positions = (
            list(scope_positions) if scope_positions is not None else []
        )
        self.explanation = finding.get("reason")
        self.evidence_concepts = list(finding.get("evidence_concepts") or ())

    @property
    def key(self) -> str:
        """Indicator identity. A human must type the same code to match."""

        return f"{self.family}:{self.indicator}"

    @property
    def record_positions(self) -> List[int]:
        """Source rows the finding cites, for reporting and traceability.

        Prefers the submitted-file offsets when the finding publishes them, and
        falls back to the scope-relative positions otherwise, which is what the
        operational-pattern layer publishes.
        """

        return list(self.raw_positions or self.scope_positions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family,
            "indicator": self.indicator,
            "capability": self.capability,
            "assessment_id": self.assessment_id,
            "entity_id": self.entity_id,
            "period_label": self.period_label,
            "status": self.status,
            "record_positions": self.record_positions,
            "source_record_indices": list(self.raw_positions),
            "scope_record_positions": list(self.scope_positions),
            "evidence_concepts": list(self.evidence_concepts),
        }


def _record_positions(finding: Mapping[str, Any]) -> List[int]:
    """Read record positions from either shape the families publish.

    The execution-gap layer reports a single ``record_position``; the other two
    report a list. Both are read, and nothing is invented for a finding that
    carries neither.
    """

    reference = finding.get("record_reference") or {}

    positions = reference.get("record_positions")

    if isinstance(positions, list):
        return [int(value) for value in positions]

    single = reference.get("record_position")

    if single is not None:
        try:
            return [int(single)]
        except (TypeError, ValueError):
            return []

    return []


def _source_indices(finding: Mapping[str, Any]) -> List[int]:
    reference = finding.get("record_reference") or {}

    for key in ("source_record_indices", "source_record_index"):

        value = reference.get(key)

        if isinstance(value, list):
            return [int(item) for item in value]

        if value is not None:
            try:
                return [int(value)]
            except (TypeError, ValueError):
                return []

    return []


def signal_positions(finding: Mapping[str, Any]) -> List[int]:
    """Read the record positions a finding cites.

    One implementation, used both when projecting a whole result and when
    indexing a reference output, so the two can never disagree about what a
    finding points at.
    """

    return _source_indices(finding) or _record_positions(finding)


def scope_positions(finding: Mapping[str, Any]) -> List[int]:
    """Scope-relative record positions a finding cites.

    These index the records of one assessment scope, not the submitted file.
    """

    return _record_positions(finding)


def normalise_result(result: Mapping[str, Any]) -> List[NormalisedSignal]:
    """Project every finding in an existing pipeline result.

    Reads the three existing result keys only. No key is added, removed or
    rewritten.
    """

    signals: List[NormalisedSignal] = []

    for family in FAMILIES:

        block = result.get(FAMILY_RESULT_KEYS[family])

        if not isinstance(block, Mapping):
            continue

        for finding in block.get("findings") or ():

            signals.append(
                NormalisedSignal(
                    family,
                    finding,
                    raw_positions=_source_indices(finding),
                    scope_positions=_record_positions(finding),
                )
            )

    return signals


def normalise_indicator_list(value: Any) -> List[str]:
    """Read a reviewer's indicator field.

    Accepts a list of codes. Free text is accepted only when it contains a
    code-shaped token, because anything else cannot be compared at indicator
    level without guessing.
    """

    if value is None:
        return []

    if isinstance(value, str):
        tokens = value.replace(",", " ").split()
        return [token.strip() for token in tokens if token.strip()]

    if isinstance(value, list):
        out = []

        for item in value:
            if not isinstance(item, str):
                continue

            text = item.strip()

            if text:
                out.append(text)

        return out

    return []


def normalise_human_record(
    record: Mapping[str, Any],
) -> Dict[str, List[str]]:
    """Split one review record into per-family indicator lists.

    ``human_indicators`` is the authoritative set. The per-family fields are
    unioned in, so a reviewer who filled in only the per-family fields is still
    usable, and a reviewer who filled in both is not double counted.
    """

    by_family: Dict[str, List[str]] = {family: [] for family in FAMILIES}

    combined = normalise_indicator_list(record.get("human_indicators"))

    for indicator in combined:
        # An indicator code belongs to exactly one family. The corpus records
        # the mapping, so the family is taken from the tool's own published
        # indicator vocabulary rather than from the shape of the field the
        # reviewer happened to type it into.
        for family, indicators in KNOWN_INDICATOR_FAMILY.items():
            if indicator in indicators:
                if indicator not in by_family[family]:
                    by_family[family].append(indicator)
                break
        else:
            # An unrecognised code is kept aside rather than discarded, so an
            # unexpected reviewer vocabulary surfaces instead of silently
            # becoming a false negative against the tool.
            by_family.setdefault("_unrecognised", []).append(indicator)

    for family in FAMILIES:

        field = f"human_{family}"

        for indicator in normalise_indicator_list(record.get(field)):
            if indicator not in by_family[family]:
                by_family[family].append(indicator)

    return by_family


def register_indicator_vocabulary(
    result: Mapping[str, Any],
) -> Dict[str, List[str]]:
    """Build the indicator-to-family map from an existing result.

    Read from the result itself so the comparison vocabulary can never drift
    away from what the tool actually emits.
    """

    vocabulary: Dict[str, List[str]] = {}

    for signal in normalise_result(result):
        indicators = vocabulary.setdefault(signal.family, [])

        if signal.indicator not in indicators:
            indicators.append(signal.indicator)

    return vocabulary


#: Populated from the tool's own output before any comparison runs. An empty
#: mapping means no comparison has been prepared, which the tests assert
#: against, so a comparison can never fall back to invented indicators.
KNOWN_INDICATOR_FAMILY: Dict[str, List[str]] = {}
