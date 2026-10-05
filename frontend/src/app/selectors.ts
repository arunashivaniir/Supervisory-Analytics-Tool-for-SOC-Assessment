/**
 * Projections of a pipeline result for display.
 *
 * Every function here is a rearrangement: it groups, filters, counts what the
 * backend already produced, or resolves a label. None of them judges, ranks,
 * scores, thresholds, or infers. If a value is not in the result, these
 * functions cannot produce it.
 *
 * Counting is the one arithmetic performed, and only ever over arrays the
 * backend emitted: a scope's finding count is the length of that scope's own
 * `findings` array. That is a projection of a stated fact, not a measurement.
 */

import {
  NOT_AVAILABLE,
  capabilityTally,
  entityLabel,
  entityResolved,
  periodLabel,
  periodResolved,
  verdictTotal,
} from "../lib/formatters";
import { SIGNAL_FAMILIES, type SignalFamilyId } from "../lib/status";
import type {
  AnomalyScopeResult,
  AnomalyVerdict,
  AssessmentScope,
  BenchmarkScope,
  CanonicalContractEntry,
  CanonicalMappingDecision,
  CanonicalMappingState,
  Capability,
  CapabilityScope,
  CapabilityStatus,
  CohortTierDefinition,
  CollectionBenchmarkMetric,
  ExecutionGapFinding,
  FindingIdentity,
  MetricBenchmark,
  MetricDefinition,
  NegativeSpaceFinding,
  OperationalPatternFinding,
  PeerBenchmark,
  PeerCohort,
  PipelineResult,
  ScopeIdentity,
} from "../types/pipeline";

/** Scope identity plus its record count, for table rows and detail pages. */
export interface ScopeRow extends ScopeIdentity {
  metadata?: Record<string, unknown>;
}

export function scopeRows(result: PipelineResult | null): ScopeRow[] {
  if (!result) {
    return [];
  }

  return result.assessment.scopes.map((scope: AssessmentScope) => ({
    assessment_id: scope.assessment_id,
    entity: scope.entity,
    period: scope.period,
    record_count: scope.record_count,
  }));
}

export function findScopeRow(
  rows: ScopeRow[],
  assessmentId: string | null,
): ScopeRow | null {
  if (!assessmentId) {
    return null;
  }

  return rows.find((row) => row.assessment_id === assessmentId) ?? null;
}

/** The distinct entity labels present, for a filter. Unresolved first. */
export function entityOptions(rows: ScopeRow[]): string[] {
  const labels = new Set<string>();

  for (const row of rows) {
    labels.add(
      entityResolved(row.entity)
        ? (row.entity.name ?? row.entity.id ?? NOT_AVAILABLE)
        : "Entity not identified",
    );
  }

  return [...labels].sort((a, b) => a.localeCompare(b));
}

export function periodOptions(rows: ScopeRow[]): string[] {
  const labels = new Set<string>();

  for (const row of rows) {
    labels.add(periodResolved(row.period) ? periodLabel(row.period) : "Period not determined");
  }

  return [...labels].sort((a, b) => a.localeCompare(b));
}

/**
 * Every finding across the four signal families, tagged with the family it came
 * from.
 *
 * The union is what makes the Findings screen complete: a row exists here if
 * and only if a finding exists in the pipeline result, so the screen cannot
 * display a finding the backend did not report, and cannot hide one it did.
 */
export interface UnifiedFinding {
  /** Stable key for selection and React identity. */
  key: string;
  family: SignalFamilyId;
  familyLabel: string;
  /** The pipeline's own finding object, passed through untouched. */
  finding: FindingIdentity;
  indicator: string;
  reason: string;
  assessment_id: string;
  entity: ScopeRow["entity"];
  period: ScopeRow["period"];
  /** The status the backend gave this specific finding. */
  status: string | null;
  evidenceConcepts: string[];
  /** Index within its family, used to address the original typed object. */
  familyIndex: number;
}

export function unifiedFindings(
  result: PipelineResult | null,
): UnifiedFinding[] {
  if (!result) {
    return [];
  }

  const all: UnifiedFinding[] = [];

  result.execution_gap_findings.findings.forEach(
    (finding: ExecutionGapFinding, index: number) => {
      all.push({
        key: `execution_gap:${index}`,
        family: "execution_gap",
        familyLabel: "Execution Gap",
        finding: finding as unknown as FindingIdentity,
        indicator: finding.indicator,
        reason: finding.reason,
        assessment_id: finding.assessment_id,
        entity: finding.entity,
        period: finding.period,
        status: finding.status ?? null,
        evidenceConcepts: finding.evidence_concepts ?? [],
        familyIndex: index,
      });
    },
  );

  result.negative_space_findings.findings.forEach(
    (finding: NegativeSpaceFinding, index: number) => {
      all.push({
        key: `negative_space:${index}`,
        family: "negative_space",
        familyLabel: "Negative Space",
        finding: finding as unknown as FindingIdentity,
        indicator: finding.indicator,
        reason: finding.reason,
        assessment_id: finding.assessment_id,
        entity: finding.entity,
        period: finding.period,
        status: finding.status ?? null,
        evidenceConcepts: finding.evidence_concepts ?? [],
        familyIndex: index,
      });
    },
  );

  result.operational_pattern_findings.findings.forEach(
    (finding: OperationalPatternFinding, index: number) => {
      all.push({
        key: `operational_pattern:${index}`,
        family: "operational_pattern",
        familyLabel: "Operational Pattern",
        finding: finding as unknown as FindingIdentity,
        indicator: finding.indicator,
        reason: finding.reason,
        assessment_id: finding.assessment_id,
        entity: finding.entity,
        period: finding.period,
        status: finding.status ?? null,
        evidenceConcepts: finding.evidence_concepts ?? [],
        familyIndex: index,
      });
    },
  );

  result.anomaly_findings.findings.forEach((finding, index) => {
    all.push({
      key: `anomaly:${index}`,
      family: "anomaly",
      familyLabel: "Anomaly",
      finding: finding as unknown as FindingIdentity,
      indicator: finding.indicator,
      reason: finding.reason,
      assessment_id: finding.assessment_id,
      entity: finding.entity,
      period: finding.period,
      status: finding.verdict ?? null,
      evidenceConcepts: finding.evidence_concepts ?? [],
      familyIndex: index,
    });
  });

  return all;
}

/** Findings belonging to one assessment scope. */
export function findingsForScope(
  findings: UnifiedFinding[],
  assessmentId: string,
): UnifiedFinding[] {
  return findings.filter((item) => item.assessment_id === assessmentId);
}

export function countByFamily(findings: UnifiedFinding[]): Record<string, number> {
  const counts: Record<string, number> = {};

  for (const family of SIGNAL_FAMILIES) {
    counts[family.id] = 0;
  }

  for (const item of findings) {
    counts[item.family] = (counts[item.family] ?? 0) + 1;
  }

  return counts;
}

/** A count of the backend's own reported findings, or null when not reported. */
export function familyFindingCount(
  result: PipelineResult | null,
  family: SignalFamilyId,
): number | null {
  if (!result) {
    return null;
  }

  switch (family) {
    case "execution_gap":
      return result.execution_gap_findings.finding_count;
    case "negative_space":
      return result.negative_space_findings.finding_count;
    case "operational_pattern":
      return result.operational_pattern_findings.finding_count;
    case "anomaly":
      return result.anomaly_findings.findings.length;
    default:
      return null;
  }
}

// --------------------------------------------------------------- capabilities

export interface CapabilityPosture {
  capability: Capability;
  status: CapabilityStatus;
}

export function capabilityScopes(
  result: PipelineResult | null,
): CapabilityScope[] {
  return result?.capability_assessment.scopes ?? [];
}

export function capabilitiesForScope(
  result: PipelineResult | null,
  assessmentId: string | null,
): CapabilityPosture[] {
  if (!result || !assessmentId) {
    return [];
  }

  const scope = capabilityScopes(result).find(
    (item) => item.assessment_id === assessmentId,
  );

  if (!scope) {
    return [];
  }

  // Ordered by the backend's own capability_ids, so the display order is the
  // pipeline's and not a list maintained here.
  const order = new Map(
    result.capability_assessment.capability_ids.map((id, index) => [id, index]),
  );

  return [...scope.capabilities]
    .sort(
      (a, b) =>
        (order.get(a.capability_id) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(b.capability_id) ?? Number.MAX_SAFE_INTEGER),
    )
    .map((capability) => ({
      capability,
      status: capability.status,
    }));
}

/** The backend's scope-wide tally of capability states. */
export function capabilityTallyForScope(
  result: PipelineResult | null,
  assessmentId: string | null,
): { status: CapabilityStatus; count: number }[] {
  if (!result || !assessmentId) {
    return [];
  }

  const scope = capabilityScopes(result).find(
    (item) => item.assessment_id === assessmentId,
  );

  return capabilityTally(scope?.status_counts);
}

/** Dataset-wide capability tally, as the pipeline summarised it. */
export function datasetCapabilitySummary(result: PipelineResult | null) {
  if (!result) {
    return null;
  }

  return result.capability_assessment.summary;
}

// -------------------------------------------------------------------- anomaly

export function anomalyScopeResults(
  result: PipelineResult | null,
): AnomalyScopeResult[] {
  return result?.anomaly_findings.scope_results ?? [];
}

export function anomalyForScope(
  result: PipelineResult | null,
  assessmentId: string | null,
): AnomalyScopeResult | null {
  if (!result || !assessmentId) {
    return null;
  }

  return (
    anomalyScopeResults(result).find(
      (item) => item.assessment_id === assessmentId,
    ) ?? null
  );
}

export function anomalyVerdictCounts(result: PipelineResult | null) {
  return result?.anomaly_findings.verdict_counts ?? {};
}

export function anomalyVerdictTotal(result: PipelineResult | null): number {
  return verdictTotal(anomalyVerdictCounts(result));
}

export function anomalyVerdictsInUse(result: PipelineResult | null): AnomalyVerdict[] {
  const counts = anomalyVerdictCounts(result);

  return (Object.keys(counts) as AnomalyVerdict[]).filter(
    (verdict) => (counts[verdict] ?? 0) > 0,
  );
}

export function anomalyModelStatus(result: PipelineResult | null) {
  return result?.anomaly_findings.anomaly_model_status ?? null;
}

export function anomalyFeatureSchema(result: PipelineResult | null) {
  return result?.anomaly_findings.feature_schema ?? null;
}

export function anomalyLimitations(result: PipelineResult | null): string[] {
  return result?.anomaly_findings.limitations ?? [];
}

/** How many features a scope's vector actually had, as the backend reported. */
export function availableFeatureCount(
  scope: AnomalyScopeResult | null,
): number | null {
  if (!scope) {
    return null;
  }

  return scope.features.filter((feature) => feature.available).length;
}

// ------------------------------------------------------- entity attention

/**
 * The backend's entity attention entry for a scope, if one names it.
 *
 * The attention scorer groups by resolved entity name, so the match is on
 * the scope's entity name or id. Null when no entry names this scope:
 * the interface then says "not reported" rather than showing another
 * scope's score or a zero that could read as a clean result.
 */
export interface ScopeAttention {
  score: number;
  level: string;
  indicators: string[];
  recordsAnalyzed: number;
  confidence: number | null;
}

export function attentionForScope(
  result: PipelineResult | null,
  row: ScopeRow,
): ScopeAttention | null {
  if (!result) {
    return null;
  }

  const names = [row.entity.name, row.entity.id].filter(
    (value): value is string => Boolean(value),
  );

  const entry = result.entity_assessment.find((item) =>
    names.includes(item.entity),
  );

  if (!entry) {
    return null;
  }

  return {
    score: entry.attention_score,
    level: entry.risk_level,
    indicators: entry.risk_indicators.map((item) => String(item)),
    recordsAnalyzed: entry.records_analyzed,
    confidence:
      typeof entry.entity_confidence === "number"
        ? entry.entity_confidence
        : null,
  };
}

/** Eligible analytical checks per family, for evidence-based empty states. */export function eligibleCheckCounts(
  result: PipelineResult | null,
): Record<string, number> {
  if (!result) {
    return {};
  }

  return {
    execution_gap: result.execution_gap_findings.rule_ids.length,
    negative_space: result.negative_space_findings.rule_ids.length,
    operational_pattern:
      result.operational_pattern_findings.pattern_ids.length,
  };
}

// ---------------------------------------------------------- review samples

/**
 * A prioritised manual-review sample, derived deterministically from
 * reported findings.
 *
 * PROVISIONAL (Phase 3A): the backend exposes no formal review ranking
 * yet, so this orders findings by transparent rules only — findings
 * that point at a source record first, execution gaps and negative
 * space before other families, converging signals (several findings
 * citing one record) next, then stable identifier order. Every rank
 * is explainable from the fields shown beside it. Never severity
 * alone: the pipeline reports no severity for these signals.
 */
export interface ReviewSample {
  rank: number;
  finding: UnifiedFinding;
  /** Why this sample is here, in one sentence built from its fields. */
  why: string;
  /** Other findings citing the same record, if any. */
  converged: UnifiedFinding[];
  recordLabel: string | null;
}

const REVIEW_FAMILY_RANK: Record<string, number> = {
  execution_gap: 0,
  negative_space: 1,
  operational_pattern: 2,
  anomaly: 3,
};

function recordKeyOf(finding: UnifiedFinding): string | null {
  const reference = finding.finding.record_reference;

  if (!reference || typeof reference !== "object") {
    return null;
  }

  const position =
    reference.record_position ?? reference.source_record_index ?? null;

  if (position === null || position === undefined) {
    return null;
  }

  return `${finding.assessment_id}#${String(position)}`;
}

function recordLabelOf(finding: UnifiedFinding): string | null {
  const reference = finding.finding.record_reference;

  if (!reference || typeof reference !== "object") {
    return null;
  }

  const parts: string[] = [];

  for (const key of [
    "alert_id",
    "case_id",
    "record_position",
    "source_record_index",
  ]) {
    const value = reference[key];

    if (value !== null && value !== undefined && value !== "") {
      parts.push(`${key.replace(/_/g, " ")} ${String(value)}`);
    }
  }

  return parts.length > 0 ? parts.join(" · ") : null;
}

function whyFor(
  finding: UnifiedFinding,
  convergedCount: number,
): string {
  const bits: string[] = [finding.familyLabel];

  if (finding.evidenceConcepts.length > 0) {
    bits.push(`evidence: ${finding.evidenceConcepts.slice(0, 3).join(", ")}`);
  }

  if (convergedCount > 0) {
    bits.push(
      `${convergedCount + 1} signals converge on this record`,
    );
  }

  return `${finding.reason} (${bits.join(" · ")})`;
}

export function reviewSamples(
  findings: UnifiedFinding[],
  limit = 8,
): ReviewSample[] {
  const byRecord = new Map<string, UnifiedFinding[]>();

  for (const item of findings) {
    const key = recordKeyOf(item);

    if (key) {
      const group = byRecord.get(key) ?? [];
      group.push(item);
      byRecord.set(key, group);
    }
  }

  const ordered = [...findings].sort((a, b) => {
    const aRef = recordKeyOf(a) !== null ? 0 : 1;
    const bRef = recordKeyOf(b) !== null ? 0 : 1;

    if (aRef !== bRef) {
      return aRef - bRef;
    }

    const aFam = REVIEW_FAMILY_RANK[a.family] ?? 9;
    const bFam = REVIEW_FAMILY_RANK[b.family] ?? 9;

    if (aFam !== bFam) {
      return aFam - bFam;
    }

    const aConv = (aRef === 0 ? (byRecord.get(recordKeyOf(a)!)?.length ?? 1) : 1);
    const bConv = (bRef === 0 ? (byRecord.get(recordKeyOf(b)!)?.length ?? 1) : 1);

    if (aConv !== bConv) {
      return bConv - aConv;
    }

    return a.indicator.localeCompare(b.indicator);
  });

  return ordered.slice(0, limit).map((finding, index) => {
    const key = recordKeyOf(finding);
    const converged = key
      ? (byRecord.get(key) ?? []).filter((item) => item.key !== finding.key)
      : [];

    return {
      rank: index + 1,
      finding,
      why: whyFor(finding, converged.length),
      converged,
      recordLabel: recordLabelOf(finding),
    };
  });
}

// ------------------------------------------------------- peer benchmarking
//
// Projections over the backend-authoritative `peer_benchmark` result. Every
// function here returns a value the backend already produced. None of them
// computes a median, a Z-score, a percentile, a rank or a cohort, and none of
// them decides which cohort would be appropriate: that is the backend's
// resolver, and its decision is rendered rather than re-made here.
//
// The React-computed peer context this module used to carry compared raw
// finding counts inside the browser. That conflated a count with a rate, so a
// larger submission looked worse purely for being larger, and it compared
// scopes across periods. Both defects are removed by reading the contract
// below instead.

export function peerBenchmark(result: PipelineResult | null): PeerBenchmark | null {
  return result?.peer_benchmark ?? null;
}

/** True when the backend produced a peer comparison for this assessment. */
export function peerBenchmarkAvailable(result: PipelineResult | null): boolean {
  return peerBenchmark(result)?.available === true;
}

/**
 * Why the layer produced nothing, if it did.
 *
 * A run with no peer comparison is a different state from a run with a peer
 * comparison in which every cohort was too small, and the two are reported
 * separately so an empty screen can say which one it is showing.
 */
export function peerBenchmarkUnavailableReason(
  result: PipelineResult | null,
): string | null {
  const benchmark = peerBenchmark(result);

  if (!benchmark || benchmark.available) {
    return null;
  }

  return benchmark.unavailable_reason ?? "Peer benchmarking produced no result for this assessment";
}

/** One scope's benchmark record, or null when the backend has none for it. */
export function benchmarkScope(
  result: PipelineResult | null,
  assessmentId: string,
): BenchmarkScope | null {
  const benchmark = peerBenchmark(result);

  return benchmark?.scopes.find((scope) => scope.assessment_id === assessmentId) ?? null;
}

/** Every benchmarked scope, ordered as the backend ordered it. */
export function benchmarkScopes(result: PipelineResult | null): BenchmarkScope[] {
  return peerBenchmark(result)?.scopes ?? [];
}

/** One metric benchmark for a scope, or null when the backend has none. */
export function metricBenchmark(
  result: PipelineResult | null,
  assessmentId: string,
  metricId: string,
): MetricBenchmark | null {
  const scope = benchmarkScope(result, assessmentId);

  return scope?.benchmarks.find((entry) => entry.metric_id === metricId) ?? null;
}

/** The metric benchmarks for a scope, in the backend's catalogue order. */
export function metricBenchmarks(
  result: PipelineResult | null,
  assessmentId: string,
): MetricBenchmark[] {
  return benchmarkScope(result, assessmentId)?.benchmarks ?? [];
}

/** The declared metric catalogue, for labels and definitions. */
export function benchmarkMetricCatalogue(
  result: PipelineResult | null,
): MetricDefinition[] {
  return peerBenchmark(result)?.metric_catalogue ?? [];
}

/**
 * Metric benchmarks for every scope, keyed by assessment id.
 *
 * Used by the cross-scope screens, which show one metric across the cohort
 * rather than one cohort across metrics.
 */
export function benchmarkMatrix(
  result: PipelineResult | null,
): Record<string, MetricBenchmark[]> {
  const matrix: Record<string, MetricBenchmark[]> = {};

  for (const scope of benchmarkScopes(result)) {
    matrix[scope.assessment_id] = scope.benchmarks;
  }

  return matrix;
}

/** The backend's cohort for a scope, or null when there is none. */
export function peerCohort(
  result: PipelineResult | null,
  assessmentId: string,
): PeerCohort | null {
  return benchmarkScope(result, assessmentId)?.cohort ?? null;
}

/** The collection-level anomaly incidence the backend reported. */
export function collectionBenchmark(
  result: PipelineResult | null,
): CollectionBenchmarkMetric | null {
  return peerBenchmark(result)?.collection_metrics ?? null;
}

/**
 * The configured cohort hierarchy, most specific first.
 *
 * Published so a screen can show which cohort was aimed for and which was
 * reached, rather than only the one that was used.
 */
export function cohortHierarchy(
  result: PipelineResult | null,
): CohortTierDefinition[] {
  return peerBenchmark(result)?.cohort_hierarchy ?? [];
}

/** Benchmarks whose metric resolved to a rate, in catalogue order. */
export function computedBenchmarks(
  benchmarks: MetricBenchmark[],
): MetricBenchmark[] {
  return benchmarks.filter((entry) => entry.metric_status === "COMPUTED");
}

/**
 * Benchmarks whose deviation from the peer median is computable.
 *
 * A NOT_COMPUTABLE statistic is not hidden: it is a statement about the
 * cohort, and the screens that show deviations must be able to say why one is
 * missing.
 */
export function comparableDeviations(
  benchmarks: MetricBenchmark[],
): MetricBenchmark[] {
  return benchmarks.filter((entry) => entry.statistical_status === "COMPUTED");
}

/**
 * Benchmarks whose metric expresses evidence presence rather than
 * performance.
 *
 * The backend publishes `measure_type` for exactly this purpose: a coverage
 * metric describes how much of the submitted data carried a concept, and must
 * not be presented alongside contradiction rates as though it were one.
 */
export function evidenceObservationBenchmarks(
  benchmarks: MetricBenchmark[],
): MetricBenchmark[] {
  return benchmarks.filter((entry) => entry.measure_type === "evidence_observation");
}

/**
 * The scope ids in a cohort, resolved to display labels.
 *
 * Pure lookup: the ids come from the backend's resolver and the labels from
 * the assessment the backend resolved them against.
 */
export function cohortMembers(
  result: PipelineResult | null,
  assessmentId: string,
): Array<{ assessment_id: string; label: string }> {
  const cohort = peerCohort(result, assessmentId);

  if (!cohort) {
    return [];
  }

  const rows = scopeRows(result);

  return cohort.member_assessment_ids.map((id) => {
    const row = rows.find((candidate) => candidate.assessment_id === id);

    const entity = row?.entity ?? null;
    const period = row?.period ?? null;

    return {
      assessment_id: id,
      label: `${entityResolved(entity) ? entityLabel(entity) : "Entity not identified"} · ${
        periodResolved(period) ? periodLabel(period) : "period not determined"
      }`,
    };
  });
}

// ------------------------------------------------- canonical mapping review
// (C.1). Pure projections over the authoritative `canonical_package`.
// The legacy `mapping_report` bands are NOT authoritative and must not be
// used for mapping decisions.

export function canonicalDecisions(
  result: PipelineResult | null,
): CanonicalMappingDecision[] {
  return result?.canonical_package?.mapping_decisions ?? [];
}

export function canonicalContract(
  result: PipelineResult | null,
): Record<string, CanonicalContractEntry> {
  return result?.canonical_package?.canonical_contract ?? {};
}

export function canonicalStates(
  result: PipelineResult | null,
): Partial<Record<CanonicalMappingState, number>> {
  const decisions = canonicalDecisions(result);

  if (result?.canonical_package?.mapping_states) {
    return result.canonical_package.mapping_states;
  }

  const counts: Partial<Record<CanonicalMappingState, number>> = {};

  for (const decision of decisions) {
    counts[decision.mapping_state] = (counts[decision.mapping_state] ?? 0) + 1;
  }

  return counts;
}

/** Profile column category by lowercased column name, for dropdown context. */
export function profileCategoryByColumn(
  result: PipelineResult | null,
): Map<string, string> {
  const byColumn = new Map<string, string>();
  const profile = result?.profile as {
    columns?: Array<{ column_name?: string; category?: string }>;
  } | null;

  for (const column of profile?.columns ?? []) {
    if (typeof column?.column_name === "string") {
      byColumn.set(
        column.column_name.toLowerCase(),
        typeof column.category === "string" ? column.category : "",
      );
    }
  }

  const schemaColumns = result?.canonical_package?.schema?.columns ?? [];

  for (const column of schemaColumns) {
    if (typeof column?.column_name !== "string") {
      continue;
    }

    const lowered = column.column_name.toLowerCase();

    if (!byColumn.has(lowered) && typeof column.category === "string") {
      byColumn.set(lowered, column.category);
    }
  }

  return byColumn;
}
