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
