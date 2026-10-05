"""
SAT-SA assessment scope layer.

A generic, schema-agnostic model for data that spans multiple Critical Sector
Entities and multiple assessment periods. It partitions an ingested dataset
into ``(entity, period)`` assessment scopes so the existing analytical engine
can be applied per scope without duplicating any analytical logic.

Modules
-------

* :mod:`framework.assessment.entity_context` - which CSE a record belongs to.
* :mod:`framework.assessment.period` - which assessment period it covers.
* :mod:`framework.assessment.scope` - scopes, the collection, and the builder.

Typical use::

    from framework.assessment import AssessmentScopeBuilder

    builder = AssessmentScopeBuilder()
    collection = builder.build(
        records=ingestion.records,
        profile=profile,
        source_id=ingestion.source,
        source_type=ingestion.source_type,
    )

    for scope in collection.for_entity("CSE-001"):
        analyse(scope.records)   # the same analytical engine, per scope

Nothing in this package performs analysis, and nothing here hardcodes a column
name, a CSE name, a date column or a customer schema. Entity and period columns
are discovered by the existing ``SemanticInference`` engine using
``framework/config/assessment_scope_patterns.json``.

Scope is a foundation only. Peer benchmarking, trend analysis and the dashboard
are deliberately not implemented here.
"""

from framework.assessment.entity_context import (
    DEFAULT_CONFIG_FILE,
    UNKNOWN_ENTITY,
    EntityColumnResolution,
    EntityContext,
    EntityContextResolver,
    load_scope_config,
)

from framework.assessment.period import (
    UNKNOWN_PERIOD,
    VALID_GRANULARITIES,
    PeriodColumnResolution,
    PeriodContext,
    PeriodResolver,
    parse_timestamp,
)

from framework.assessment.scope import (
    AssessmentCollection,
    AssessmentScope,
    AssessmentScopeBuilder,
)

__all__ = [
    "DEFAULT_CONFIG_FILE",
    "UNKNOWN_ENTITY",
    "UNKNOWN_PERIOD",
    "VALID_GRANULARITIES",
    "AssessmentCollection",
    "AssessmentScope",
    "AssessmentScopeBuilder",
    "EntityColumnResolution",
    "EntityContext",
    "EntityContextResolver",
    "PeriodColumnResolution",
    "PeriodContext",
    "PeriodResolver",
    "load_scope_config",
    "parse_timestamp",
]
