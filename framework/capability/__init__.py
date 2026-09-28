"""
SAT-SA capability layer.

The eight SOC capabilities named in the SIH problem statement, assessed against
the evidence a Critical Sector Entity actually submitted:

    SUBMITTED EVIDENCE
            |
            v
    CANONICAL EVIDENCE      (existing concepts only)
            |
            v
    8 SOC CAPABILITIES
            |
            v
    WHAT CAN ACTUALLY BE ASSESSED?

This is **not** a risk model. It answers one question per capability, and the
answer is an evidence state:

* ``AVAILABLE`` -- enough evidence submitted to assess the capability
* ``INSUFFICIENT_EVIDENCE`` -- some evidence, incomplete for a meaningful assessment
* ``NOT_ASSESSED`` -- no meaningful evidence submitted

None of these is a risk verdict. ``NOT_ASSESSED`` is not low risk and
``INSUFFICIENT_EVIDENCE`` is not high risk. The layer produces no severity, no
score and no finding, and it never converts missing data into a security
finding. Existing detectors remain solely responsible for findings.

Every capability is evaluated per :class:`framework.assessment.scope.AssessmentScope`,
so a multi-CSE, multi-period dataset gets an independent assessment per scope and
is never pooled.

Typical use::

    from framework.capability import CapabilityEvaluator, CapabilityRegistry

    evaluator = CapabilityEvaluator(CapabilityRegistry())
    result = evaluator.evaluate_collection(assessment, profile, semantic_mapping)

    for context in result["scopes"][0]["capabilities"]:
        if context["is_assessable"]:
            ...   # later analytic phases consume this; not this phase

Peer benchmarking, trend analysis, the dashboard, new risk scoring and new
detectors are deliberately **not** implemented here.
"""

from framework.capability.capability_context import (
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_NOT_ASSESSED,
    VALID_STATUSES,
    CapabilityContext,
)

from framework.capability.capability_registry import (
    DEFAULT_CAPABILITY_CONFIG,
    DEFAULT_MAPPINGS_CONFIG,
    DEFAULT_SCHEMA_CONFIG,
    REQUIRED_CAPABILITIES,
    CapabilityDefinition,
    CapabilityRegistry,
    CapabilityRegistryError,
    EvidenceRequirement,
)

from framework.capability.capability_evaluator import (
    DEFAULT_CAPABILITY_PATTERNS,
    CapabilityEvaluator,
    EvidenceIndex,
    is_populated,
)

__all__ = [
    "DEFAULT_CAPABILITY_CONFIG",
    "DEFAULT_CAPABILITY_PATTERNS",
    "DEFAULT_MAPPINGS_CONFIG",
    "DEFAULT_SCHEMA_CONFIG",
    "REQUIRED_CAPABILITIES",
    "STATUS_AVAILABLE",
    "STATUS_INSUFFICIENT_EVIDENCE",
    "STATUS_NOT_ASSESSED",
    "VALID_STATUSES",
    "CapabilityContext",
    "CapabilityDefinition",
    "CapabilityEvaluator",
    "CapabilityRegistry",
    "CapabilityRegistryError",
    "EvidenceIndex",
    "EvidenceRequirement",
    "is_populated",
]
