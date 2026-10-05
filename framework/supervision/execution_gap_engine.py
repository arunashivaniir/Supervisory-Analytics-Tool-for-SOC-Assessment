"""Per-scope execution-gap orchestration.

Responsibility split, which keeps this from becoming a parallel framework:

``CapabilityEvaluator`` / ``EvidenceIndex``
    resolves *which canonical concept lives in which source column* for one
    assessment scope, and with what mapping confidence. That resolution is
    already per-scope, concept-based and free of hardcoded column names.

``ExecutionGapEngine`` (this module)
    reads the per-record values of those already-resolved concepts and runs the
    configured rules over them.

The engine therefore never re-implements semantic mapping and never names a
source column: the only column names it uses are the ones the capability layer
resolved, which is what makes a column rename transparent to it.

Scope discipline
----------------
Records are evaluated strictly within one :class:`AssessmentScope`. Nothing is
pooled across CSEs or periods, and every finding carries ``assessment_id``,
entity, period and both a scope-relative and a source-record index so it can be
traced back to the submitted row.

Relationship to the existing supervisory output
-----------------------------------------------
Findings produced here are written to ``result["execution_gap_findings"]`` only.
They deliberately do not enter ``result["supervisory_findings"]``, because that
value feeds ``AttentionScorer``, which maps a finding ``severity`` onto an
attention score. Routing evidence-backed execution gaps through it would convert
them into risk scores, which is explicitly a later phase. These findings carry no
``severity`` field for the same reason.

The legacy ``evaluate(records, context)`` entry point is retained for the
existing :class:`SupervisoryEngine`. It returns an empty list, which is exactly
what the previous implementation returned in practice: it searched for raw
source column names on canonical records and therefore never matched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from framework.supervision.execution_gap_detector import ExecutionGapDetector
from framework.supervisory.rules.execution_gap_rules import ExecutionGapCatalogue


class ExecutionGapEngine:
    """Evaluates execution-gap rules independently within each assessment scope."""

    def __init__(
        self,
        catalogue: Optional[ExecutionGapCatalogue] = None,
        detector: Optional[ExecutionGapDetector] = None,
    ) -> None:

        self.catalogue = catalogue or ExecutionGapCatalogue()

        self.detector = detector or ExecutionGapDetector(
            registry=self.catalogue.registry
        )

    # -- concept resolution -------------------------------------------------

    def build_concept_values(
        self,
        records: Sequence[Mapping[str, Any]],
        evidence_index,
    ) -> List[Dict[str, Any]]:
        """Resolve each record's canonical concept values.

        Delegates to :meth:`EvidenceIndex.concept_values`, which is the single
        place source column names are translated into concept values. Keeping
        one implementation is what guarantees the execution-gap and
        negative-space layers read the same evidence the same way.
        """

        return evidence_index.concept_values(records)

    # -- scope evaluation ---------------------------------------------------

    def evaluate_scope(
        self,
        scope,
        records: Sequence[Mapping[str, Any]],
        evidence_index,
    ) -> Dict[str, Any]:
        """Evaluate every rule over every record in a single scope."""

        concept_values = self.build_concept_values(records, evidence_index)

        findings: List[Dict[str, Any]] = []

        evaluations: List[Dict[str, Any]] = []

        state_counts: Dict[str, int] = {}

        for position, values in enumerate(concept_values):

            for evaluation in self.detector.evaluate(values):

                state_counts[evaluation.state] = (
                    state_counts.get(evaluation.state, 0) + 1
                )

                if not evaluation.is_finding:
                    continue

                findings.append(
                    self._build_finding(evaluation, scope, position)
                )

            evaluations.append(
                {
                    "record_position": position,
                    "states": [
                        evaluation.state
                        for evaluation in self.detector.evaluate(values)
                    ],
                }
            )

        return {
            "assessment_id": scope.assessment_id,
            "entity": scope.entity.to_dict(),
            "period": scope.period.to_dict(),
            "record_count": scope.record_count,
            "findings": findings,
            "evaluation_state_counts": state_counts,
        }

    def evaluate_collection(
        self,
        collection,
        profile: Mapping[str, Any],
        semantic_results: Optional[Sequence[Mapping[str, Any]]] = None,
        capability_evaluator=None,
    ) -> Dict[str, Any]:
        """Evaluate every scope independently and summarise the result.

        The summary counts findings and evaluation states only. It never
        aggregates evidence into a score, and it never pools scopes.
        """

        from framework.capability.capability_evaluator import (
            CapabilityEvaluator,
        )

        evaluator = capability_evaluator or CapabilityEvaluator()

        scope_payloads: List[Dict[str, Any]] = []

        findings: List[Dict[str, Any]] = []

        for scope in collection:

            records = scope.records

            evidence_index = evaluator.build_evidence_index(
                records, profile, semantic_results
            )

            payload = self.evaluate_scope(scope, records, evidence_index)

            scope_payloads.append(payload)

            findings.extend(payload["findings"])

        return {
            "rule_ids": [rule.rule_id for rule in self.catalogue.rules],
            "capability_ids": sorted(
                {rule.capability for rule in self.catalogue.rules}
            ),
            "scope_count": len(scope_payloads),
            "scopes": scope_payloads,
            "finding_count": len(findings),
            "findings": findings,
            "unavailable_rules": [
                rule.to_dict() for rule in self.catalogue.unavailable_rules
            ],
        }

    # -- finding construction ----------------------------------------------

    def _build_finding(
        self,
        evaluation,
        scope,
        position: int,
    ) -> Dict[str, Any]:
        """Assemble a finding that is fully traceable to its evidence.

        Only the concepts the rule declares are carried, and only their
        submitted values, so a finding cannot leak unrelated fields from the
        source record.
        """

        rule = self.catalogue.registry.get(evaluation.rule_id)

        try:
            source_index = scope.record_indices[position]
        except (AttributeError, IndexError):
            source_index = None

        return {
            "indicator": rule.indicator if rule else evaluation.rule_id,
            "capability": rule.capability if rule else None,
            "status": rule.status if rule else "POTENTIAL_EXECUTION_GAP",
            "rule_id": evaluation.rule_id,
            "rule_name": rule.name if rule else None,
            "reason": evaluation.reason,
            "evidence": dict(evaluation.evidence),
            "evidence_concepts": list(rule.evidence_concepts) if rule else [],
            "record_reference": {
                "record_position": position,
                "source_record_index": source_index,
            },
            "assessment_id": scope.assessment_id,
            "entity": scope.entity.to_dict(),
            "period": scope.period.to_dict(),
        }

    # -- legacy entry point -------------------------------------------------

    def evaluate(self, records, context) -> List[Dict[str, Any]]:
        """Legacy entry point retained for :class:`SupervisoryEngine`.

        The previous implementation inspected raw source column names on
        records the pipeline supplies in canonical form, so it never produced a
        finding for any dataset in the repository. It also applied arbitrary
        word-count and closure-time thresholds. Both are removed.

        Evidence-backed execution gaps are reported through
        ``result["execution_gap_findings"]``, which does not feed the attention
        scorer.
        """

        return []

    def __repr__(self) -> str:
        return (
            f"ExecutionGapEngine(rules={len(self.catalogue.rules)}, "
            f"unavailable={len(self.catalogue.unavailable_rules)})"
        )
