"""
SAT-SA capability context.

The result of asking, for one assessment scope, "can this SOC capability be
assessed from the evidence this CSE actually submitted?"

Three states, and the distinction between them is the whole point:

``AVAILABLE``
    Enough relevant evidence was submitted to perform the intended capability
    assessment. This says nothing about how well the CSE performed.

``INSUFFICIENT_EVIDENCE``
    Some relevant evidence exists, but it is incomplete for a meaningful
    assessment. This is a statement about the *submission*, not about risk.

``NOT_ASSESSED``
    No meaningful evidence for this capability was submitted.

**No state is a risk verdict.** ``NOT_ASSESSED`` is not low risk and
``INSUFFICIENT_EVIDENCE`` is not high risk. A missing-evidence state must never
be turned into a supervisory finding by this layer, and the context object has
no field in which such a finding could be expressed. Severity, risk level and
attention score live in ``supervisory_findings`` and ``entity_assessment``,
which are produced by the existing detectors and are left untouched.

Two numbers, two meanings
-------------------------

``coverage``
    Evidence coverage: the fraction of the capability's *declared* evidence
    requirements that the submission satisfies. It measures the completeness of
    the evidence package. It is not a risk score and a low value does not mean
    a weak SOC.

``confidence``
    Confidence in the evidence *resolution*: derived from the semantic mapping
    confidence of the concepts that satisfied the requirements, so it inherits
    the existing mapping engine's confidence rather than inventing a new one.
    It says how sure SAT-SA is about what the submitted columns mean, not how
    good the CSE is.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

STATUS_AVAILABLE = "AVAILABLE"
STATUS_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
STATUS_NOT_ASSESSED = "NOT_ASSESSED"

VALID_STATUSES = (
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_NOT_ASSESSED,
)

# Reporting order, most to least assessable.
STATUS_ORDER = VALID_STATUSES


class CapabilityContext:
    """The evidence-aware assessment state of one capability in one scope."""

    def __init__(
        self,
        capability_id: str,
        name: str,
        status: str,
        confidence: float,
        coverage: float,
        evidence_available: Sequence[str],
        evidence_missing: Sequence[str],
        indicator_categories: Sequence[str],
        explanation: str,
        evidence_detail: Optional[Sequence[Mapping[str, Any]]] = None,
        undiscoverable_evidence: Sequence[str] = (),
        minimum_evidence: Optional[Mapping[str, int]] = None,
        assessment_id: Optional[str] = None,
        entity: Optional[Mapping[str, Any]] = None,
        period: Optional[Mapping[str, Any]] = None,
    ) -> None:

        if status not in VALID_STATUSES:
            raise ValueError(
                f"invalid capability status {status!r}; expected one of "
                f"{VALID_STATUSES}"
            )

        self.capability_id = capability_id
        self.name = name
        self.status = status
        self.confidence = float(confidence)
        self.coverage = float(coverage)
        self.evidence_available: List[str] = list(evidence_available)
        self.evidence_missing: List[str] = list(evidence_missing)
        self.indicator_categories: List[str] = list(indicator_categories)
        self.explanation = explanation
        self.evidence_detail: List[Dict[str, Any]] = [dict(item) for item in (evidence_detail or [])]
        self.undiscoverable_evidence: List[str] = list(undiscoverable_evidence)
        self.minimum_evidence: Dict[str, int] = dict(minimum_evidence or {})
        self.assessment_id = assessment_id
        self.entity = dict(entity) if entity else {}
        self.period = dict(period) if period else {}

    @property
    def is_assessable(self) -> bool:
        """True only for AVAILABLE.

        Kept as a distinct property so callers cannot read a low risk number
        where they meant a statement about evidence.
        """

        return self.status == STATUS_AVAILABLE

    @property
    def has_partial_evidence(self) -> bool:
        return self.status == STATUS_INSUFFICIENT_EVIDENCE

    def to_dict(self) -> Dict[str, Any]:

        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "status": self.status,
            "is_assessable": self.is_assessable,
            "has_partial_evidence": self.has_partial_evidence,
            "confidence": round(self.confidence, 4),
            "coverage": round(self.coverage, 4),
            "evidence_available": list(self.evidence_available),
            "evidence_missing": list(self.evidence_missing),
            "indicator_categories": list(self.indicator_categories),
            "explanation": self.explanation,
            "evidence_detail": [dict(item) for item in self.evidence_detail],
            "undiscoverable_evidence": list(self.undiscoverable_evidence),
            "minimum_evidence": dict(self.minimum_evidence),
            "assessment_id": self.assessment_id,
            "entity": dict(self.entity),
            "period": dict(self.period),
        }

    def __repr__(self) -> str:

        return (
            f"CapabilityContext({self.capability_id!r}, "
            f"status={self.status!r}, coverage={round(self.coverage, 3)})"
        )
