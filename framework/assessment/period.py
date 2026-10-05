"""
SAT-SA assessment scope: assessment period resolution.

This module answers one question: *which assessment period do these records
cover, and how do we know?*

Design rules this module exists to enforce
------------------------------------------

* **Explicit beats derived.** A declared assessment period column is always
  used as the label. Derivation is only a fallback for datasets that have no
  period column at all.
* **No silent calendar assumptions.** SAT-SA never assumes a dataset represents
  a calendar year. When a period is derived from record timestamps it reports
  the *observed range*, e.g. ``2026-01-01..2026-01-03``, and the ``granularity``
  field says so. Calendar bucketing (year / quarter / month) happens only when
  explicitly configured.
* **Unparseable is not a period.** A period column whose values are present but
  unreadable as dates yields a label with no invented bounds rather than a
  fabricated range.
* **Missing periods never crash.** A dataset with no period evidence reports
  ``UNKNOWN_PERIOD`` with ``available=False`` and a recorded reason, so the
  pipeline continues.
* **Deterministic and configurable.** Granularity is a configuration value, not
  an assumption buried in code; the label format is stable for a given input.

Period resolution order
-----------------------

1. **Explicit period column** discovered by the existing ``SemanticInference``
   engine from ``assessment_scope_patterns.json``. Label is the cell value.
   Bounds are set only when the label is a full ISO ``YYYY-MM-DD`` date, so no
   range is invented from an opaque label such as ``FY26``.
2. **Timestamp-derived period** when no explicit column exists. A time column is
   discovered the same way, and:
   * ``range`` (default) produces one period spanning the observed
     min/max record timestamps;
   * ``year`` / ``quarter`` / ``month`` bucket each record deterministically;
   * ``none`` disables derivation entirely.
3. **UNKNOWN_PERIOD** with the reason recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from framework.assessment.entity_context import (
    DEFAULT_CONFIG_FILE,
    PatternInference,
    build_column_name_index,
    load_scope_config,
    rank_candidates,
)

UNKNOWN_PERIOD = "UNKNOWN_PERIOD"

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

VALID_GRANULARITIES = ("none", "range", "year", "quarter", "month")

TIMESTAMP_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
)


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a timestamp without ever raising.

    Accepts ISO-8601 (including a trailing ``Z``) and a small set of explicit
    formats. Anything unparseable returns ``None``; the caller decides what an
    unreadable value means, which keeps date parsing out of the trust boundary.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return None

    text = str(value).strip()

    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None

    iso_candidate = text[:-1] + "+00:00" if text.endswith("Z") else text

    try:
        return datetime.fromisoformat(iso_candidate)
    except ValueError:
        pass

    for pattern in TIMESTAMP_FORMATS:

        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue

    return None


def quarter_label(moment: datetime) -> str:
    return f"{moment.year}-Q{(moment.month - 1) // 3 + 1}"


def month_label(moment: datetime) -> str:
    return f"{moment.year}-{moment.month:02d}"


def year_label(moment: datetime) -> str:
    return f"{moment.year}"


def bucket_label(moment: datetime, granularity: str) -> str:

    if granularity == "year":
        return year_label(moment)

    if granularity == "quarter":
        return quarter_label(moment)

    if granularity == "month":
        return month_label(moment)

    return moment.date().isoformat()


def _iso(moment: Optional[datetime]) -> Optional[str]:

    if moment is None:
        return None

    return moment.date().isoformat()


class PeriodColumnResolution:
    """Which source columns were chosen to establish a period, and why."""

    def __init__(self) -> None:

        self.period_column: Optional[str] = None
        self.period_concept: Optional[str] = None
        self.period_confidence: float = 0.0

        self.timestamp_column: Optional[str] = None
        self.timestamp_concept: Optional[str] = None
        self.timestamp_confidence: float = 0.0

        self.period_candidates: List[Dict[str, Any]] = []
        self.timestamp_candidates: List[Dict[str, Any]] = []

        self.ambiguous: bool = False
        self.reason: Optional[str] = None

    @property
    def has_explicit_period(self) -> bool:
        return self.period_column is not None

    @property
    def has_timestamp(self) -> bool:
        return self.timestamp_column is not None

    def to_dict(self) -> Dict[str, Any]:

        return {
            "period_column": self.period_column,
            "period_concept": self.period_concept,
            "period_confidence": self.period_confidence,
            "timestamp_column": self.timestamp_column,
            "timestamp_concept": self.timestamp_concept,
            "timestamp_confidence": self.timestamp_confidence,
            "period_candidates": list(self.period_candidates),
            "timestamp_candidates": list(self.timestamp_candidates),
            "ambiguous": self.ambiguous,
            "reason": self.reason,
        }


@dataclass
class PeriodContext:
    """Resolved assessment period for a single record or a whole scope."""

    label: str = UNKNOWN_PERIOD
    start: Optional[str] = None
    end: Optional[str] = None
    confidence: float = 0.0
    available: bool = False
    granularity: Optional[str] = None
    source: Optional[str] = None
    method: str = "unavailable"
    label_precision: Optional[str] = None
    inherited: bool = False
    unavailable_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:

        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "confidence": round(float(self.confidence), 4),
            "available": self.available,
            "granularity": self.granularity,
            "source": self.source,
            "method": self.method,
            "label_precision": self.label_precision,
            "inherited": self.inherited,
            "unavailable_reason": self.unavailable_reason,
        }


class PeriodResolver:
    """Resolve the assessment period for every record in a dataset.

    Parameters mirror the ``settings`` block of
    ``framework/config/assessment_scope_patterns.json`` and can be overridden
    per call site without editing configuration files.
    """

    def __init__(
        self,
        config_file: str = DEFAULT_CONFIG_FILE,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:

        axes, config_settings = load_scope_config(config_file)

        self.settings: Dict[str, Any] = dict(config_settings)

        if settings:
            self.settings.update(settings)

        self.min_confidence = float(self.settings.get("min_column_confidence", 0.45))

        self.period_concepts = list(self.settings.get("period_concepts", ["ASSESSMENT_PERIOD"]))
        self.timestamp_concepts = list(self.settings.get("timestamp_concepts", ["TIME_REFERENCE"]))

        self.derive_from_timestamps = bool(self.settings.get("derive_period_from_timestamps", True))

        granularity = str(self.settings.get("period_granularity", "range"))

        if granularity not in VALID_GRANULARITIES:
            raise ValueError(
                f"period_granularity must be one of {VALID_GRANULARITIES}, got {granularity!r}"
            )

        self.granularity = granularity

        period_axis = axes.get("period_label")
        timestamp_axis = axes.get("timestamp")

        self._period_engine = PatternInference(patterns=period_axis) if period_axis else None
        self._timestamp_engine = PatternInference(patterns=timestamp_axis) if timestamp_axis else None

    # -- column discovery -------------------------------------------------

    def _candidates_for(
        self,
        engine: Optional[PatternInference],
        concepts: Sequence[str],
        profile: Mapping[str, Any],
        name_index: Mapping[str, str],
    ) -> List[Dict[str, Any]]:

        if engine is None:
            return []

        wanted = set(concepts)

        mappings = [
            mapping
            for mapping in engine.infer(profile)
            if mapping.get("canonical_concept") in wanted
            and float(mapping.get("confidence", 0.0) or 0.0) >= self.min_confidence
        ]

        return rank_candidates(mappings, name_index)

    def resolve_columns(
        self,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> PeriodColumnResolution:
        """Choose the period and timestamp columns for a dataset profile.

        ``semantic_results`` are the existing engine's mappings. A column the
        main semantic pass already recognised as an event time is honoured as a
        timestamp source even if it is not a keyword match, so this layer
        reuses existing understanding instead of re-deriving it.
        """

        resolution = PeriodColumnResolution()

        name_index = build_column_name_index(profile)

        period_candidates = self._candidates_for(
            self._period_engine, self.period_concepts, profile, name_index
        )

        timestamp_candidates = self._candidates_for(
            self._timestamp_engine, self.timestamp_concepts, profile, name_index
        )

        resolution.period_candidates = period_candidates
        resolution.timestamp_candidates = timestamp_candidates

        if period_candidates:

            chosen = period_candidates[0]

            resolution.period_column = chosen["column"]
            resolution.period_concept = chosen["concept"]
            resolution.period_confidence = chosen["confidence"]

        timestamp_pool = list(timestamp_candidates)

        for mapping in semantic_results or []:

            concept = str(mapping.get("canonical_concept", "")).upper()

            if not any(token in concept for token in ("TIME", "TIMESTAMP", "DATE")):
                continue

            lowered = mapping.get("source_column")

            if not isinstance(lowered, str) or not lowered:
                continue

            original = name_index.get(lowered.lower(), lowered)

            if any(candidate["column"] == original for candidate in timestamp_pool):
                continue

            timestamp_pool.append(
                {
                    "column": original,
                    "concept": concept,
                    "confidence": float(mapping.get("confidence", 0.0) or 0.0),
                }
            )

        if timestamp_pool:
            timestamp_pool.sort(key=lambda item: (-item["confidence"], item["column"]))

            chosen = timestamp_pool[0]

            resolution.timestamp_column = chosen["column"]
            resolution.timestamp_concept = chosen["concept"]
            resolution.timestamp_confidence = chosen["confidence"]

        resolution.ambiguous = (
            len(period_candidates) > 1 or len(timestamp_pool) > 1
        )

        if resolution.ambiguous:

            columns = sorted(
                {candidate["column"] for candidate in period_candidates}
                | {candidate["column"] for candidate in timestamp_pool}
            )

            resolution.reason = (
                "several columns matched period or timestamp patterns "
                f"({', '.join(columns)}); selected deterministically by "
                "confidence then name"
            )

        elif not resolution.has_explicit_period and not resolution.has_timestamp:

            resolution.reason = (
                "no column matched the assessment-period or timestamp patterns "
                "in assessment_scope_patterns.json"
            )

        return resolution

    # -- value reading ----------------------------------------------------

    @staticmethod
    def _read(record: Mapping[str, Any], column: Optional[str]) -> Any:

        if not column or not isinstance(record, Mapping):
            return None

        if column in record:
            return record[column]

        lowered = column.lower()

        for key, value in record.items():

            if isinstance(key, str) and key.lower() == lowered:
                return value

        return None

    @staticmethod
    def _label_text(value: Any) -> Optional[str]:

        if value is None:
            return None

        if isinstance(value, float) and value != value:
            return None

        if isinstance(value, str):

            text = value.strip()

            if not text or text.lower() in {"nan", "nat", "none", "null"}:
                return None

            return text

        if isinstance(value, bool):
            return None

        return str(value).strip() or None

    # -- per-record resolution -------------------------------------------

    def _explicit_context(
        self,
        record: Mapping[str, Any],
        resolution: PeriodColumnResolution,
    ) -> Optional[PeriodContext]:

        label = self._label_text(self._read(record, resolution.period_column))

        if not label:
            return None

        start = end = None
        precision = "opaque"

        if ISO_DATE_PATTERN.match(label):

            parsed = parse_timestamp(label)

            if parsed is not None:

                start = end = _iso(parsed)
                precision = "day"

        return PeriodContext(
            label=label,
            start=start,
            end=end,
            confidence=resolution.period_confidence,
            available=True,
            granularity="explicit",
            source=resolution.period_column,
            method="explicit_column",
            label_precision=precision,
        )

    def _timestamp_of(
        self,
        record: Mapping[str, Any],
        resolution: PeriodColumnResolution,
    ) -> Optional[datetime]:

        for candidate in [resolution.timestamp_column] + [
            item["column"] for item in resolution.timestamp_candidates
        ]:

            parsed = parse_timestamp(self._read(record, candidate))

            if parsed is not None:
                return parsed

        return None

    def _unknown(
        self,
        reason: str,
        resolution: Optional[PeriodColumnResolution] = None,
    ) -> PeriodContext:

        return PeriodContext(
            label=UNKNOWN_PERIOD,
            available=False,
            method="unavailable",
            unavailable_reason=reason,
            source=resolution.period_column if resolution is not None else None,
        )

    def _derive(
        self,
        records: Sequence[Mapping[str, Any]],
        resolution: PeriodColumnResolution,
    ) -> List[PeriodContext]:
        """Derive a period for every record from timestamp columns."""

        if not self.derive_from_timestamps or self.granularity == "none":

            return [
                self._unknown(
                    "timestamp derivation disabled "
                    f"(period_granularity={self.granularity!r}, "
                    f"derive_period_from_timestamps={self.derive_from_timestamps})",
                    resolution,
                )
                for _ in records
            ]

        moments = [self._timestamp_of(record, resolution) for record in records]

        present = [moment for moment in moments if moment is not None]

        if not present:

            return [
                self._unknown(
                    f"timestamp column {resolution.timestamp_column!r} is present but "
                    "no value could be parsed as a date/time",
                    resolution,
                )
                for _ in records
            ]

        if self.granularity == "range":

            earliest = min(present)
            latest = max(present)
            label = f"{_iso(earliest)}..{_iso(latest)}"

            return [
                PeriodContext(
                    label=label,
                    start=_iso(earliest),
                    end=_iso(latest),
                    confidence=resolution.timestamp_confidence,
                    available=True,
                    granularity="range",
                    source=resolution.timestamp_column,
                    method="derived_from_timestamp_range",
                    label_precision="day",
                )
                if moment is not None
                else self._unknown(
                    f"record has no parseable value in {resolution.timestamp_column!r} "
                    "and no explicit period label",
                    resolution,
                )
                for moment in moments
            ]

        contexts: List[PeriodContext] = []

        for moment in moments:

            if moment is None:

                contexts.append(
                    self._unknown(
                        f"record has no parseable value in {resolution.timestamp_column!r} "
                        "and no explicit period label",
                        resolution,
                    )
                )

                continue

            contexts.append(
                PeriodContext(
                    label=bucket_label(moment, self.granularity),
                    start=_iso(moment),
                    end=_iso(moment),
                    confidence=resolution.timestamp_confidence,
                    available=True,
                    granularity=self.granularity,
                    source=resolution.timestamp_column,
                    method="derived_from_timestamp_bucket",
                    label_precision="day",
                )
            )

        return contexts

    def resolve_records(
        self,
        records: Sequence[Mapping[str, Any]],
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
        resolution: Optional[PeriodColumnResolution] = None,
    ) -> Tuple[List[PeriodContext], PeriodColumnResolution]:
        """Resolve the assessment period for every record in a dataset.

        Records carrying an explicit period label keep it. When a dataset
        declares several periods, an unlabelled record stays
        ``UNKNOWN_PERIOD`` rather than being assigned to a guessed period.
        """

        if resolution is None:
            resolution = self.resolve_columns(profile, semantic_results)

        if not records:
            return [], resolution

        if not resolution.has_explicit_period:

            return self._derive(records, resolution), resolution

        explicit: List[Optional[PeriodContext]] = [
            self._explicit_context(record, resolution)
            for record in records
        ]

        labels = {
            context.label
            for context in explicit
            if context is not None
        }

        if not labels:

            return self._derive(records, resolution), resolution

        single = len(labels) == 1

        contexts: List[PeriodContext] = []

        for context in explicit:

            if context is not None:
                contexts.append(context)
                continue

            if single:

                # The dataset declares exactly one assessment period, so an
                # unlabelled record in it belongs to that period. This is a
                # deterministic join on a single-valued declaration, and it is
                # flagged as inherited rather than presented as a direct read.
                template = next(
                    item for item in explicit if item is not None
                )

                contexts.append(
                    PeriodContext(
                        label=template.label,
                        start=template.start,
                        end=template.end,
                        confidence=template.confidence,
                        available=True,
                        granularity=template.granularity,
                        source=template.source,
                        method="explicit_column",
                        label_precision=template.label_precision,
                        inherited=True,
                    )
                )

                continue

            contexts.append(
                self._unknown(
                    f"dataset declares {len(labels)} assessment periods "
                    f"({', '.join(sorted(labels))}) and this record carries no "
                    f"value in {resolution.period_column!r}; period not guessed",
                    resolution,
                )
            )

        return contexts, resolution
