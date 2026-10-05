"""Configuration-driven corpora for the offline anomaly layer.

Why generated corpora exist
----------------------------
An Isolation Forest cannot be trained on the dataset it will later describe, and
SAT-SA has no historical corpus of real SOC assessment scopes to train on. So
the MVP ships a generated one, labelled ``SYNTHETIC_REFERENCE_FOR_DEMONSTRATION``
in ``anomaly_model.json`` and recorded in the model metadata. It is not a
real-world baseline, not ground truth and not expert ground truth.

What the generator is allowed to know
-------------------------------------
Only the numbers in ``anomaly_model.json``. It never branches on a dataset
name, an entity name, a period label or a profile identity, and it has no idea
what verdict a profile should receive -- the expected verdicts live in the test
suite precisely so that no executable ML code contains an answer.

Why the reference population is varied rather than repeated
------------------------------------------------------------
An Isolation Forest partitions the space it is fitted on. If every reference
scope had the same vector, the model would learn one point, and every inference
would be "anomalous" or none would be. Each reference scope is therefore drawn
from the same continuous parameter ranges, so the population covers a region
and the model has to learn where a profile is *inside* that region.

Column names come from configuration
-----------------------------------
``corpus_schema.columns`` in ``anomaly_model.json`` holds the headers, so no
source-column literal appears in this package. The renamed-column variant is
this same generator with a different header map, which is what makes that
generalisation a property of semantic mapping rather than of a special case.
"""

from __future__ import annotations

import csv
import os
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from framework.ingestion.ingestion_manager import IngestionManager
from framework.intelligence.semantic_inference import SemanticInference
from framework.profiling.dataset_profiler import DatasetProfiler
from framework.assessment.scope import AssessmentScopeBuilder
from framework.capability.capability_evaluator import (
    CapabilityEvaluator,
    CapabilityRegistry,
)
from framework.ml.anomaly.feature_builder import AnomalyModelConfig


# The concept each optional column is expected to resolve to. Used only to
# verify that the generated corpus actually carries the evidence the feature
# schema requires, so a broken mapping is reported as a generation failure
# rather than surfacing later as a mysterious NOT_EVALUABLE.
CONCEPT_FOR_ROLE = {
    "severity": "SECURITY_SEVERITY",
    "asset": "ASSET_IDENTIFIER",
    "asset_criticality": "ASSET_CRITICALITY",
    "escalation": "ESCALATION_STATUS",
    "investigation": "INVESTIGATION_EVIDENCE",
}


class CorpusGenerationError(Exception):
    """The configured corpus cannot be generated as described."""


def _uniform(
    generator: random.Random, span: Mapping[str, Any], key: str = None
) -> float:
    bounds = span if key is None else span[key]

    return generator.uniform(
        float(bounds["minimum"]), float(bounds["maximum"])
    )


def _label(stem: str, index: int) -> str:
    return f"{stem}-{index:03d}"


class CorpusGenerator:
    """Builds CSV corpora and scopes from configuration alone."""

    def __init__(
        self,
        config: Optional[AnomalyModelConfig] = None,
        columns: Optional[Mapping[str, str]] = None,
    ) -> None:

        self.config = config or AnomalyModelConfig.load()

        schema = self.config.raw.get("corpus_schema") or {}

        if not schema:
            raise CorpusGenerationError(
                "anomaly_model.json must declare corpus_schema"
            )

        self.schema = dict(schema)
        self.columns = dict(columns or schema["columns"])

        for role in ("entity", "period", "record"):
            if role not in self.columns:
                raise CorpusGenerationError(
                    f"corpus_schema.columns is missing the {role!r} role"
                )

        self._note_bank = self._build_note_bank()

    # -- public API ---------------------------------------------------------

    def generate_reference(self) -> List[Dict[str, Any]]:
        """The reference population, as one corpus of many assessment scopes.

        Each scope is its own (entity, period) pair, so the reference
        population is genuinely a population of scopes rather than one dataset
        read as a single point.
        """

        settings = self.config.reference_corpus
        count = int(settings["scope_count"])
        stem = str(self.schema["entity_label_stem"])
        period_stem = str(self.schema["period_label_stem"])

        records: List[Dict[str, Any]] = []
        scopes: List[Dict[str, Any]] = []

        for index in range(1, count + 1):

            entity = _label(stem, index)
            period = _label(period_stem, 1)

            rows = self._labelled_scope(
                index, self._reference_profile(index), entity, period
            )

            records.extend(rows)

            scopes.append(
                {
                    "profile_id": "reference",
                    "entity": entity,
                    "period": period,
                    "record_count": len(rows),
                }
            )

        return [
            {
                "profile_id": str(settings["label"]),
                "records": records,
                "scopes": scopes,
            }
        ]

    def generate_controlled(self) -> List[Dict[str, Any]]:
        """One corpus per controlled profile, from its configured parameters."""

        profiles = self.config.controlled_corpus.get("profiles") or []

        stem = str(self.schema["entity_label_stem"])
        period_stem = str(self.schema["period_label_stem"])

        corpora: List[Dict[str, Any]] = []

        for index, profile in enumerate(profiles, start=1):

            entity = _label(stem, 900 + index)
            period = _label(period_stem, 1)

            rows = self._labelled_scope(
                index, profile, entity, period
            )

            corpora.append(
                {
                    "profile_id": str(profile["profile_id"]),
                    "description": str(profile.get("description", "")),
                    "records": rows,
                    "scopes": [
                        {
                            "profile_id": str(profile["profile_id"]),
                            "entity": entity,
                            "period": period,
                            "record_count": len(rows),
                        }
                    ],
                    "withheld_concepts": list(
                        profile.get("withhold_concepts") or ()
                    ),
                }
            )

        return corpora

    def generate_scope_isolation_grid(self) -> List[Dict[str, Any]]:
        """A two-by-two entity-by-period grid sharing one evidence pool.

        Each cell's evidence depends only on the cell, never on the other cells,
        so a pooled implementation would produce a different vector for a cell
        that appears alongside its neighbours than it does on its own.
        """

        settings = self.config.raw.get("scope_isolation") or {}

        if not settings:
            raise CorpusGenerationError(
                "anomaly_model.json must declare scope_isolation"
            )

        entity_count = int(settings["entity_count"])
        period_count = int(settings["period_count"])
        profiles = settings["profiles"]

        if not profiles:
            raise CorpusGenerationError(
                "scope_isolation declares no profiles"
            )

        corpora: List[Dict[str, Any]] = []

        # One row set per (entity, period) cell, keyed by cell so the generator
        # never has to reason about a name.
        cells: List[Tuple[str, str, List[Dict[str, Any]], Mapping[str, Any]]] = []

        for entity_index in range(1, entity_count + 1):
            for period_index in range(1, period_count + 1):

                profile = profiles[
                    (entity_index + period_index - 2) % len(profiles)
                ]

                entity = _label(self.schema["entity_label_stem"], entity_index)
                period = _label(
                    self.schema["period_label_stem"], period_index
                )

                rows = self._labelled_scope(
                    self._stable_seed(f"{entity_index}:{period_index}"),
                    profile,
                    entity,
                    period,
                )

                cells.append((entity, period, rows, profile))

        for entity, period, rows, profile in cells:

            corpora.append(
                {
                    "profile_id": "cell_{}_{}_{}".format(
                        profile.get("profile_id", "grid"),
                        entity,
                        period,
                    ),
                    "records": rows,
                    "scopes": [
                        {"profile_id": "grid", "entity": entity, "period": period}
                    ],
                }
            )

        return corpora

    def renamed(self, columns: Mapping[str, str]) -> "CorpusGenerator":
        """A generator emitting the same evidence under different headers."""

        return CorpusGenerator(self.config, columns=columns)

    def write_csv(self, records: Sequence[Mapping[str, Any]], path: str) -> str:
        """Write records to ``path``, creating parent directories."""

        if not records:
            raise CorpusGenerationError("refusing to write an empty corpus")

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with open(path, "w", newline="") as handle:

            writer = csv.DictWriter(handle, fieldnames=self.fieldnames())
            writer.writeheader()

            for record in records:
                writer.writerow(
                    {name: record.get(name, "") for name in self.fieldnames()}
                )

        return path

    def fieldnames(self) -> List[str]:
        """Column order for the generated CSV, from configuration."""

        return [
            self.columns["entity"],
            self.columns["period"],
            self.columns["record"],
            self.columns["severity"],
            self.columns["asset"],
            self.columns["asset_criticality"],
            self.columns["escalation"],
            self.columns["investigation"],
        ]

    # -- record generation --------------------------------------------------

    def _reference_profile(self, index: int) -> Dict[str, Any]:
        """One reference scope's parameters, coupled through a latent factor.

        The reference block in configuration declares the spans; this applies
        the ``operating_profile_factor`` couplings on top of them, so the
        population has the joint structure a real operating environment has
        rather than being a box of independent draws. A controlled profile is
        never passed through here: it states its own values and is judged
        against whatever structure the reference population has.
        """

        settings = dict(self.config.reference_corpus)

        factor_settings = self.config.raw.get("operating_profile_factor") or {}

        couplings = factor_settings.get("couplings") or {}

        if not couplings:
            return settings

        generator = random.Random(f"{self._base_seed()}:profile:{index}")

        factor = generator.uniform(
            float(factor_settings.get("minimum", 0.0)),
            float(factor_settings.get("maximum", 1.0)),
        )

        for name, coupling in couplings.items():

            value = float(coupling["intercept"]) + (
                float(coupling["coefficient"]) * factor
            )

            settings[name] = min(1.0, max(0.0, value))

        return settings

    def _labelled_scope(
        self,
        seed: Any,
        profile: Mapping[str, Any],
        entity: str,
        period: str,
    ) -> List[Dict[str, Any]]:
        """One scope's records, tagged with its entity, period and record ids.

        This is the only place identity is attached, and it is a pure function
        of the label it is handed. The generator has no opinion about what any
        label means.
        """

        rows = self._generate_scope(seed, profile)

        for position, row in enumerate(rows, start=1):
            row[self.columns["entity"]] = entity
            row[self.columns["period"]] = period
            row[self.columns["record"]] = (
                f"{entity}-{period}-{position:04d}"
            )

        return rows

    def _generate_scope(
        self, seed: Any, profile: Mapping[str, Any]
    ) -> List[Dict[str, Any]]:
        """One scope's records from one profile's parameters.

        Every magnitude is resolved once for the whole scope, before the first
        record is drawn. Resolving a range per record instead would make a
        configured scope-level range mean nothing: the scope would end up with
        whatever the sampling happened to average to, and two scopes declaring
        the same range would not be comparable.
        """

        generator = random.Random(f"{self._base_seed()}:{seed}")

        profile = self._resolve(profile, seed)

        withheld = set(profile.get("withhold_concepts") or ())

        record_count = self._record_count(generator, profile)

        distinct_assets = max(
            1, min(record_count, int(round(record_count * self._magnitude(generator, profile, "asset_count_ratio"))))
        )

        asset_pool = [
            f"{self.schema['entity_label_stem'][:3].lower()}-asset-{index:03d}"
            for index in range(1, int(self.schema["asset_pool_size"]) + 1)
        ]

        severities = list(self.schema["severity_values"])
        criticalities = list(self.schema["asset_criticality_values"])
        top_severity = self.config.vocabulary("severity_ordinal")
        criticality_map = self.config.vocabulary("criticality_ordinal")

        # Concentrated scopes reuse a small asset subset heavily, so the busiest
        # asset genuinely carries most of the scope.
        assets = [asset_pool[index % len(asset_pool)] for index in range(distinct_assets)]

        # Shared-vocabulary notes must never repeat the same stem combination
        # inside one scope, or two notes could cross the deterministic
        # repetition rule's similarity floor and that rule would report the
        # profile the anomaly layer is meant to own.
        seen_combinations: set = set()

        records: List[Dict[str, Any]] = []

        for position in range(record_count):

            record: Dict[str, Any] = {}

            severity = self._draw_severity(
                generator, severities, top_severity, profile
            )
            record[self.columns["severity"]] = severity

            # A weighted choice over the scope's asset subset is what produces a
            # high max-group share for a concentrated scope.
            record[self.columns["asset"]] = generator.choices(
                assets,
                weights=self._asset_weights(assets, generator, profile),
                k=1,
            )[0]

            record[self.columns["asset_criticality"]] = (
                self._draw_criticality(
                    generator, criticalities, criticality_map, profile
                )
            )

            record[self.columns["escalation"]] = self._draw_escalation(
                generator, profile
            )

            record[self.columns["investigation"]] = self._draw_investigation(
                generator, profile, seen_combinations
            )

            records.append(record)

        if withheld:
            self._withhold(records, withheld)

        self._enforce_completeness_floor(
            generator, records, profile, record_count
        )

        return records

    def _record_count(
        self, generator: random.Random, profile: Mapping[str, Any]
    ) -> int:
        """Records in a scope.

        The reference population declares a ``{minimum, maximum}`` span so its
        scopes differ in volume; a controlled profile declares a single count so
        the demonstration is reproducible to the record. Both are configuration;
        neither is chosen here.
        """

        declared = profile["records_per_scope"]

        if isinstance(declared, Mapping):
            return max(1, int(round(_uniform(generator, declared))))

        return max(1, int(declared))

    def _magnitude(
        self, generator: random.Random, profile: Mapping[str, Any], key: str
    ) -> float:
        """One tunable parameter, as a scalar or sampled from its span.

        The reference population declares ranges so its scopes genuinely differ;
        a controlled profile declares one value so the demonstration is exactly
        reproducible. Both forms are configuration, so the generator accepts
        either without deciding which a profile "should" use.
        """

        declared = profile[key]

        if isinstance(declared, Mapping):
            return _uniform(generator, declared)

        return float(declared)

    #: Profile keys that are resolved to a concrete scalar once per scope.
    #: The names match the keys configuration is expected to declare, so
    #: nothing here decides what a scope's operating character is.
    _SCOPE_MAGNITUDES = (
        "critical_severity_share",
        "high_or_above_severity_share",
        "asset_count_ratio",
        "asset_weight_skew",
        "asset_criticality_bias",
        "escalation_coverage",
        "escalation_positive_share",
        "investigation_coverage",
        "investigation_repetition",
        "investigation_shared_vocabulary",
        "evidence_completeness",
    )

    def _resolve(self, profile: Mapping[str, Any], seed: Any) -> Dict[str, Any]:
        """Replace every declared span with the single value this scope uses.

        A scope is one operating profile, so a range in configuration has to be
        interpreted once for the whole scope. Resolving per record instead
        would quietly change the meaning of the configuration: a span of
        0.0 to 0.45 sampled once per record yields an average near 0.225 rather
        than a scope-level target, and two scopes declaring identical spans
        would produce scopes that cannot be compared to each other. Resolving
        up front also means a scope is internally consistent, which is what
        makes the resulting feature vector a description of a single operating
        profile rather than an average of several.

        The scope's own seed keys the draws, so two scopes declaring the same
        span resolve to different values while one scope's generation stays
        reproducible.
        """

        resolved = dict(profile)
        generator = random.Random(f"{self._base_seed()}:resolve:{seed}")

        for key in self._SCOPE_MAGNITUDES:

            declared = profile.get(key)

            if isinstance(declared, Mapping):
                resolved[key] = _uniform(generator, declared)

        declared_records = profile.get("records_per_scope")

        if isinstance(declared_records, Mapping):
            resolved["records_per_scope"] = _uniform(generator, declared_records)

        return resolved

    def _asset_weights(
        self, assets: Sequence[str], generator: random.Random, profile
    ) -> List[float]:
        """Geometrically skewed per-asset weights, of a configured mildness.

        A uniform choice over the asset subset would give a flat distribution
        whatever the scope's asset ratio, and the concentration feature would
        then carry no information at all. But a steep skew would reproduce the
        concentration the operational-pattern layer already reports as a
        binomial tail, which would make the anomaly layer a restatement of an
        existing rule. The skew is therefore a configured, mild magnitude, and
        what it produces is an uneven distribution that is not unusual by
        chance -- the region a model can reason about.
        """

        skew = self._magnitude(generator, profile, "asset_weight_skew")

        return [max(0.05, skew ** index) for index in range(len(assets))]

    def _draw_severity(
        self,
        generator: random.Random,
        severities: Sequence[str],
        vocabulary: Mapping[str, float],
        profile: Mapping[str, Any],
    ) -> str:
        """Sample a severity honouring the critical share and the high share.

        Two independent draws rather than one weighted choice, so each
        configured share means what it says: the top band is taken at exactly
        its configured share, and the elevated remainder is drawn from the other
        bands.
        """

        critical = self._top_band(vocabulary)
        bands = list(vocabulary)

        high_share = self._magnitude(
            generator, profile, "high_or_above_severity_share"
        )
        critical_share = self._magnitude(
            generator, profile, "critical_severity_share"
        )

        if generator.random() < critical_share:
            return critical

        remaining_high = max(0.0, high_share - critical_share)

        if generator.random() < remaining_high:

            elevated = [band for band in bands if band != critical]

            if elevated:
                return generator.choice(elevated)

        return generator.choice(bands)

    def _top_band(self, vocabulary: Mapping[str, float]) -> str:
        """The highest band of an ordinal vocabulary."""

        return max(vocabulary, key=lambda band: float(vocabulary[band]))

    def _draw_criticality(
        self,
        generator: random.Random,
        values: Sequence[str],
        vocabulary: Mapping[str, float],
        profile: Mapping[str, Any],
    ) -> str:
        bias = self._magnitude(generator, profile, "asset_criticality_bias")

        ranked = sorted(
            values, key=lambda band: float(vocabulary.get(band, 0.0))
        )

        lower = ranked[: max(1, len(ranked) // 2)]
        upper = ranked[max(1, len(ranked) // 2) :]

        if not upper:
            return generator.choice(ranked)

        if generator.random() < bias:
            return generator.choice(upper)

        return generator.choice(lower)

    def _draw_escalation(
        self, generator: random.Random, profile: Mapping[str, Any]
    ) -> str:
        coverage = self._magnitude(generator, profile, "escalation_coverage")
        positive_share = self._magnitude(generator, profile, "escalation_positive_share")

        if generator.random() >= coverage:
            return ""

        if generator.random() < positive_share:
            return str(self.schema["escalation_positive_value"])

        return str(self.schema["escalation_negative_value"])

    def _draw_investigation(
        self,
        generator: random.Random,
        profile: Mapping[str, Any],
        seen_combinations: set = None,
    ) -> str:
        """One investigation note, in one of three configured modes.

        The three modes exist so that "repetitive" has more than one meaning.
        Exact template reuse is what the deterministic repetition rule already
        reports. Shared-vocabulary wording overlaps substantially without ever
        reaching that rule's similarity floor, so a profile built from it is
        invisible to the rule while remaining readable to the continuous
        similarity feature the model consumes.
        """

        coverage = self._magnitude(
            generator, profile, "investigation_coverage"
        )

        if generator.random() >= coverage:
            return ""

        templated = self._magnitude(
            generator, profile, "investigation_repetition"
        )
        shared = self._magnitude(
            generator, profile, "investigation_shared_vocabulary"
        )

        draw = generator.random()

        if draw < templated:
            return self._templated_note(generator, seen_combinations)

        if draw < templated + shared:
            return self._shared_note(generator, seen_combinations)

        return self._fresh_note(generator)

    def _note_pool(self) -> List[str]:
        return self._note_bank["pool"]

    def _templated_note(
        self, generator: random.Random, seen_combinations: set = None
    ) -> str:
        """One note taken from the template pool, never twice in a scope.

        Templates are exact copies, so two picks of the same template are two
        identical notes and the deterministic repetition rule groups them at a
        similarity of 1.0. Drawing without replacement inside a scope is what
        lets a controlled profile be repetitive without being a restatement of
        that rule: the repetition is visible as a lower mean similarity than
        free text would give, while no two notes are the same.

        When a scope wants more templated notes than the pool holds, the pool is
        exhausted and the note degrades to an independently written one. The
        repetition is then genuinely strong, and it is honest for the
        deterministic rule to report that profile: exceeding the pool is the
        situation the rule exists to find.
        """

        pool = self._note_pool()
        available = [
            template
            for template in pool
            if seen_combinations is None
            or ("template:" + template) not in seen_combinations
        ]

        if not available:
            return self._fresh_note(generator)

        template = generator.choice(available)

        if seen_combinations is not None:
            seen_combinations.add("template:" + template)

        return template

    def _shared_note(
        self, generator: random.Random, seen_combinations: set = None
    ) -> str:
        """A note assembled from a shared stem vocabulary.

        Several stems in common, so the scope's notes read as drawn from one
        limited vocabulary. The stem combination is never repeated inside a
        scope: two notes sharing every stem would reach a Jaccard similarity of
        about 0.9, which is above the floor at which the deterministic
        repetition rule groups records together, and that rule would then
        report a profile this layer is meant to own. Two notes sharing two of
        three stems sit near 0.5, comfortably below the floor, while still
        being unmistakably repetitive to a continuous similarity measure.
        """

        stems = self._note_bank["shared"]
        size = int(self.schema["shared_stem_count"])

        for _ in range(int(self.schema["shared_redraw_attempts"])):

            chosen = generator.sample(stems, min(size, len(stems)))
            key = frozenset(chosen)

            if seen_combinations is None or key not in seen_combinations:

                if seen_combinations is not None:
                    seen_combinations.add(key)

                return " ".join(chosen) + " ref " + str(
                    generator.randint(1, 99999)
                )

        # Ran out of distinct combinations. An independently written note is
        # the honest fallback: it is unrepetitive rather than quietly
        # duplicated.
        return self._fresh_note(generator)

    def _fresh_note(self, generator: random.Random) -> str:
        """A varied note.

        Drawn from a wide word bank with no deliberate repeated phrase, so its
        token overlap with any other fresh note is low. That is what lets a
        scope's repetition feature actually separate templated wording from
        individually-written wording.
        """

        bank = self._note_bank["fresh"]
        size = int(self.schema["note_fresh_word_count"])

        return " ".join(generator.sample(bank, min(size, len(bank))))

    def _withhold(
        self, records: List[Dict[str, Any]], withheld: Sequence[str]
    ) -> None:
        """Remove the named concepts' columns entirely from a scope.

        This models a scope whose evidence genuinely lacks a concept, which is
        the case that must be reported NOT_EVALUABLE rather than scored as zero.
        """

        for concept in withheld:

            role = _role_for_concept(concept)

            if role is None:
                raise CorpusGenerationError(
                    f"cannot withhold unknown concept: {concept}"
                )

            column = self.columns.get(role)

            if column is None:
                continue

            for record in records:
                record[column] = ""

    def _enforce_completeness_floor(
        self,
        generator: random.Random,
        records: List[Dict[str, Any]],
        profile: Mapping[str, Any],
        record_count: int,
    ) -> None:
        """Drop evidence at the configured rate, but never below the floor.

        The configured completeness target is applied by blanking a share of the
        cells. The floor matters: a reference scope missing a concept entirely
        is not usable as a training row, so the generator guarantees each
        required concept keeps at least as many populated values as the
        strictest feature that reads it.
        """

        target = self._magnitude(generator, profile, "evidence_completeness")

        blank_rate = max(0.0, 1.0 - target)

        if blank_rate <= 0.0:
            return

        for concept, role in CONCEPT_FOR_ROLE.items():

            if concept in (profile.get("withhold_concepts") or ()):
                continue

            column = self.columns.get(role)

            if column is None:
                continue

            positions = list(range(record_count))
            generator.shuffle(positions)

            to_blank = int(round(blank_rate * record_count))
            floor = self._concept_floor(concept)

            for position in positions[:to_blank]:
                records[position][column] = ""

            populated = sum(
                1 for record in records if record.get(column)
            )

            # Give the evidence back until the floor is met. Deterministic
            # because the position order is already shuffled by the seed.
            deficit = floor - populated

            if deficit > 0:
                for position in positions:
                    if deficit <= 0:
                        break
                    if not records[position][column]:
                        records[position][column] = (
                            self._default_for_concept(
                                concept, generator, profile
                            )
                        )
                        deficit -= 1

    def _default_for_concept(
        self,
        concept: str,
        generator: random.Random,
        profile: Mapping[str, Any],
    ) -> str:
        """A neutral, in-vocabulary value used to satisfy the floor."""

        if concept == "SECURITY_SEVERITY":
            return str(
                generator.choice(list(self.config.vocabulary("severity_ordinal")))
            )

        if concept == "ASSET_IDENTIFIER":
            return f"floor-asset-{generator.randint(1, 40):03d}"

        if concept == "ASSET_CRITICALITY":
            return str(
                generator.choice(
                    list(self.config.vocabulary("criticality_ordinal"))
                )
            )

        if concept == "ESCALATION_STATUS":
            return str(self.schema["escalation_negative_value"])

        return self._fresh_note(generator)

    def _concept_floor(self, concept: str) -> int:
        """The strictest minimum_records among features that read a concept."""

        floors = [
            feature.minimum_records
            for feature in self.config.features
            if concept in feature.source_concepts
        ]

        return max(floors) if floors else 1

    def _stable_seed(self, key: str) -> int:
        """A stable integer seed from a cell key.

        Python's ``hash`` is salted per process, so it cannot be used: the same
        grid must generate the same evidence on every run.
        """

        total = 0

        for character in key:
            total = (total * 131 + ord(character)) % 1000003

        return total

    def _base_seed(self) -> Any:
        return self.config.reference_corpus.get("random_state", 0)

    def _build_note_bank(self) -> Dict[str, List[str]]:
        """The three note vocabularies.

        ``pool``     complete templates, reused verbatim. This is what the
                     deterministic repetition rule already reports, so it is
                     kept rare in the reference population.
        ``shared``   stems that recur across many notes without any note being
                     repeated, giving overlap the deterministic rule's
                     similarity floor does not reach.
        ``fresh``    a wide bank of distinct words, so independently written
                     notes have genuinely low pairwise overlap. A narrow bank
                     here would make "fresh" wording as repetitive as the
                     templated mode and collapse the feature's range.
        """

        pool_size = int(self.schema["note_pool_size"])

        stems = [
            "reviewed queued alert and confirmed recurring pattern on endpoint",
            "matched known indicator and escalated to on call for guidance",
            "validated packet capture and closed after verification step",
            "inspected process list and found no further suspicious activity",
            "correlated with change window and marked as expected behaviour",
            "compared against baseline and observed no deviation from normal",
        ]

        pool = [stems[index % len(stems)] for index in range(pool_size)]

        shared = [
            "session token replay detected on the affected endpoint",
            "authentication handshake retried several times before success",
            "payload header checksum mismatch observed in transit",
            "queue latency threshold exceeded during the reporting window",
            "outbound connection attempted to an unapproved destination",
            "privilege boundary inspected and no escalation of rights seen",
            "certificate chain validated against the trusted store",
            "memory region contents sampled during the incident window",
            "file integrity baseline compared and no change detected",
            "process ancestry traced back to the initiating service",
            "network segment isolated pending further correlation",
            "log source rotated and earlier entries unavailable for review",
        ][: max(1, int(self.schema["shared_vocabulary_size"]))]

        fresh = (
            "analysed telemetry correlation during window and documented "
            "sequence of observations across affected components for review "
            "with stakeholders before closure recommendation submitted "
            "authentication handshake payload header checksum offset padding "
            "queue latency threshold segment window interval batch summary "
            "certificate chain privilege boundary memory region contents "
            "integrity baseline ancestry traced destination unapproved "
            "rotation earlier entries correlation sampling inspected "
            "validated compared observed deviation expected behaviour "
            "recurring pattern indicator matched guidance confirmation "
            "closure verification capturing packets scrutinising endpoints "
            "inventory topology ownership review retrospective calibration "
            "sensitivity tuning provisional annotated consolidated appendix "
            "worksheet ledger narrative"
        ).split()

        return {"pool": pool, "shared": shared, "fresh": fresh}


def _role_for_concept(concept: str) -> Optional[str]:
    for role, mapped in CONCEPT_FOR_ROLE.items():
        if mapped == concept:
            return role

    return None


# -- shared scope construction ------------------------------------------------


def build_scopes_from_records(
    records: Sequence[Mapping[str, Any]],
    source_id: str,
    config: Optional[AnomalyModelConfig] = None,
    expected_concepts: Optional[Sequence[str]] = None,
) -> Tuple[Any, Mapping[str, Any], Sequence[Mapping[str, Any]]]:
    """Run generated records through SAT-SA's own ingestion and scope model.

    There is no second ingestion path and no second scope model. The records go
    through ``IngestionManager``, ``DatasetProfiler``, ``SemanticInference`` and
    ``AssessmentScopeBuilder`` -- the same objects the pipeline uses -- so a
    generated corpus exercises exactly the path real evidence takes.

    ``expected_concepts`` narrows the check for a corpus that deliberately
    withholds a concept, such as the insufficient-evidence profile.

    Returns ``(collection, profile, semantic_results)``.
    """

    import tempfile

    settings = config or AnomalyModelConfig.load()

    with tempfile.TemporaryDirectory() as directory:

        path = os.path.join(directory, f"{source_id}.csv")

        fieldnames: List[str] = []

        for record in records:
            for name in record:
                if name not in fieldnames:
                    fieldnames.append(name)

        with open(path, "w", newline="") as handle:

            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()

            for record in records:
                writer.writerow(
                    {name: record.get(name, "") for name in fieldnames}
                )

        ingestion = IngestionManager().load(path)

        profile = DatasetProfiler().profile(ingestion.profiling_target)

        semantic_results = SemanticInference(
            settings.raw.get("semantic_patterns_path")
            or "framework/config/semantic_patterns.json"
        ).infer(profile)

        collection = AssessmentScopeBuilder().build(
            records=ingestion.records,
            profile=profile,
            semantic_results=semantic_results,
            source_id=source_id,
            source_type=ingestion.source_type,
        )

    _verify_concepts(
        collection, profile, semantic_results, expected_concepts
    )

    return collection, profile, semantic_results


def build_evidence_projections(
    collection,
    profile: Mapping[str, Any],
    semantic_results: Sequence[Mapping[str, Any]],
) -> List[Tuple[Any, List[Dict[str, Any]]]]:
    """Per-scope concept projections, via the existing EvidenceIndex."""

    evaluator = CapabilityEvaluator(CapabilityRegistry())

    projections: List[Tuple[Any, List[Dict[str, Any]]]] = []

    for scope in collection:

        index = evaluator.build_evidence_index(
            scope.records, profile, semantic_results
        )

        projections.append((scope, index.concept_values(scope.records)))

    return projections


def _verify_concepts(
    collection,
    profile: Mapping[str, Any],
    semantic_results: Sequence[Mapping[str, Any]],
    expected_concepts: Optional[Sequence[str]] = None,
) -> None:
    """Fail loudly if semantic mapping did not resolve the expected concepts.

    A generated corpus that does not resolve ``ESCALATION_STATUS`` would
    otherwise produce a feature builder that reports every scope as
    NOT_EVALUABLE, which looks like a model problem and is not one.
    """

    resolved = {
        mapping["source_column"]: mapping["canonical_concept"]
        for mapping in semantic_results
        if mapping.get("canonical_concept")
    }

    expected = (
        set(expected_concepts)
        if expected_concepts is not None
        else set(CONCEPT_FOR_ROLE.values())
    )

    missing = [
        concept
        for concept in sorted(expected)
        if concept not in set(resolved.values())
    ]

    if missing:

        raise CorpusGenerationError(
            "the generated corpus did not resolve these canonical concepts "
            f"through semantic mapping: {missing}. Resolved so far: "
            f"{sorted(set(resolved.values()))}"
        )
