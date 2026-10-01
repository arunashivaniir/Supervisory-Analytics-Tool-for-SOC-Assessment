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
  CanonicalContractEntry,
  CanonicalMappingDecision,
  CanonicalMappingState,
  Capability,
  CapabilityScope,
  CapabilityStatus,
  ExecutionGapFinding,
  FindingIdentity,
  NegativeSpaceFinding,
  OperationalPatternFinding,
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

/**
 * Peer context for one scope: the distribution this scope sits in.
 *
 * The peer population is the assessment's own scopes — same package,
 * same pipeline, same counting basis (reported signal counts). Median,
 * range and the scope's deviation are arithmetic over those counts,
 * never a judgement. Null when fewer than two scopes exist: a
 * population of one cannot be compared with itself.
 */
export interface PeerContext {
  population: number;
  basis: string;
  median: number;
  min: number;
  max: number;
  entityCount: number;
  deviation: number;
}

export function peerContext(
  result: PipelineResult | null,
  assessmentId: string,
): PeerContext | null {
  if (!result) {
    return null;
  }

  const findings = unifiedFindings(result);
  const rows = scopeRows(result);

  if (rows.length < 2) {
    return null;
  }

  const counts = rows.map(
    (row) => findingsForScope(findings, row.assessment_id).length,
  );
  const mine = findingsForScope(findings, assessmentId).length;
  const sorted = [...counts].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1
      ? sorted[mid]
      : (sorted[mid - 1] + sorted[mid]) / 2;

  return {
    population: rows.length,
    basis: `reported signal counts across ${rows.length} scopes in this assessment`,
    median,
    min: sorted[0],
    max: sorted[sorted.length - 1],
    entityCount: mine,
    deviation: mine - median,
  };
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
