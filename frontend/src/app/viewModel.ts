/**
 * The dashboard view model: one projection of backend output, built once and
 * read by every screen.
 *
 * Why this exists
 * ---------------
 * Five screens all need the same handful of answers: how many records, how many
 * scopes, how many signals of each family, which entities reported signals, is
 * peer comparison meaningful, is the evidence trustworthy. Computing those once
 * per run instead of once per card is what stops the interface from issuing
 * competing requests and presenting competing numbers.
 *
 * What it is allowed to do
 * ------------------------
 * Read backend fields. Arrange them. Count entries in arrays the backend
 * produced. Nothing else.
 *
 * Specifically it does NOT compute a percentile, a median, a deviation, a
 * severity, a rank or a score. Every one of those arrives from
 * `framework/pipeline.py` and is passed through untouched, including when the
 * pipeline declined to produce it: `null` stays `null` and is rendered as an
 * honest unavailable state rather than being coerced to zero.
 *
 * The one derived judgement is `primaryFamily`, which names the family a scope
 * reported most signals in. It is a maximum over counts the backend published,
 * used only to order a table, and it returns null when a scope reported nothing
 * or when two families tie, so it can never imply a backend did not state.
 */

import type { Tone } from "../lib/status";
import type {
  AnalysisState,
  BenchmarkScope,
  EntityRef,
  MetricBenchmark,
  MaybeNumber,
  PeerBenchmark,
  PeriodRef,
  PipelineResult,
} from "../types/pipeline";
import {
  SIGNAL_FAMILIES,
  directionLabel,
  type SignalFamilyId,
} from "../lib/status";

// ---------------------------------------------------------------- vocabulary

/**
 * One signal family, with the count the backend published for it.
 *
 * `count` is `null` when the pipeline produced no count for that family at all,
 * which is different from a count of zero: zero means the layer ran and found
 * nothing, null means the layer did not report.
 */
export interface SignalFamilyCount {
  id: SignalFamilyId;
  /** "Execution Gaps" */
  label: string;
  /** "Execution Gap" */
  singular: string;
  count: number | null;
  /** The result key this count came from, for the record. */
  sourceKey: string;
}

// ------------------------------------------------------------------ run state

/**
 * The phase of the run the interface is describing.
 *
 * `idle` is the state of holding *no run at all*: nothing has been started, and
 * nothing has been adopted from the service. It is a state in its own right
 * rather than an absence of one, because the three phases that follow each make
 * a claim about work — that work is waiting, that work is happening, that work
 * finished or broke. The interface has no basis for any of those claims until a
 * run exists, so it says `idle` and the screens say nothing is selected.
 *
 * `idle` used to be expressed as `queued`, because the type had no member for
 * it. That made "no run" indistinguishable from "a run is waiting to start",
 * which is what let the Overview claim an assessment was in progress while no
 * dataset had ever been chosen. The distinction is not cosmetic: `queued` tells
 * an examiner the pipeline is busy, and it is not.
 */
export type RunPhase =
  | "idle"
  | "queued"
  | "running"
  | "complete"
  | "failed";

export interface RunView {
  jobId: string | null;
  datasetPath: string | null;
  /** The dataset's file name, which is what an examiner recognises it by. */
  datasetName: string | null;
  phase: RunPhase;
  /** The backend's own status token, never rewritten. */
  statusToken: string;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
  log: string[];
  /** True when a replacement run is in flight behind a loaded assessment. */
  switching: boolean;
  /** The dataset being assessed instead, while `switching`. */
  pendingDatasetName: string | null;
  /** The run being waited on instead, while `switching`. */
  pendingJobId: string | null;
}

// -------------------------------------------------------------- status strip

/**
 * The four numbers in the status strip.
 *
 * Every field is nullable and stays null when the backend did not report it.
 */
export interface StatusStripView {
  records: number | null;
  scopes: number | null;
  signals: number | null;
  /** Distinct entities the backend resolved, when it could. */
  entities: number | null;
  /** Scopes whose entity the backend could not resolve. */
  unresolvedScopes: number | null;
  recordsAvailable: boolean;
  modelStatus: string | null;
  modelReason: string | null;
}

// --------------------------------------------------------- signal landscape

export interface SignalLandscapeView {
  families: SignalFamilyCount[];
  /** Sum of the families the backend counted. Null if none were counted. */
  total: number | null;
  /** True when the pipeline reported a total of exactly zero. */
  empty: boolean;
}

// ------------------------------------------------------------ entity rows

/**
 * What the backend published for one scope's evidence coverage.
 *
 * `available`, `insufficient` and `notAssessed` are the three capability states
 * the pipeline emits. The view model does not reduce them to a single verdict;
 * the component chooses how to present the triple.
 */
export interface ScopeEvidenceView {
  available: number;
  insufficient: number;
  notAssessed: number;
  /** True when the backend said no capability was assessable here. */
  nothingAssessable: boolean;
}

export type AttentionKind = "risk_band" | "signals" | "quiet";

export interface AttentionView {
  kind: AttentionKind;
  label: string;
  tone: Tone;
  /** What the label is derived from, shown as the cell's secondary line. */
  detail: string;
}

/** One assessment scope as the entity attention table needs it. */
export interface EntityAttentionRow {
  assessmentId: string;
  /**
   * The scope's position in the backend's own `assessment.scopes` array.
   *
   * Carried so a screen can choose the backend's order instead of the priority
   * order. The two are different questions — "which scope should I open next" and
   * "which scopes does this assessment cover" — and answering them with one sort
   * would quietly answer the second in terms of the first.
   */
  order: number;
  entity: EntityRef;
  period: PeriodRef;
  recordCount: number;
  /** Total signals across all four families, tallied from the findings arrays. */
  signals: number;
  byFamily: Record<SignalFamilyId, number>;
  /** The family with strictly the most signals, or null on a tie or silence. */
  primaryFamily: SignalFamilyId | null;
  attention: AttentionView;
  evidence: ScopeEvidenceView;
  /** The scope's peer benchmark, when the backend benchmarked this scope. */
  benchmark: ScopeBenchmarkSummary | null;
  /** True when the backend resolved this scope's entity. */
  resolved: boolean;
}

// ---------------------------------------------------------- peer comparison

/**
 * One metric as the peer comparison presents it.
 *
 * The fields are the backend's. `separated` is not a statistic: it reports
 * whether the backend computed a standardised deviation at all, which is false
 * exactly when every comparable scope reported the same value.
 */
export interface PeerMetricView {
  metricId: string;
  label: string;
  direction: string;
  measureType: string;
  /** "Higher is the less favourable value" / "…more favourable". */
  directionLabel: string;
  observed: MaybeNumber;
  observedIsRate: boolean;
  metricStatus: string;
  notEvaluableReason: string | null;
  median: MaybeNumber;
  percentile: MaybeNumber;
  percentileStatus: string;
  /** The scope's position in the cohort, when the backend ranked it. */
  rank: MaybeNumber;
  rankStatus: string;
  baselineStatus: string;
  baselineReason: string;
  cohortSize: number;
  peerCount: number;
  /**
   * False when the backend could not compute a standardised deviation, which is
   * its way of saying every comparable scope reported the same value.
   */
  separated: boolean;
  /** The backend's own sentence for an uncomputable statistic, verbatim. */
  separationReason: string | null;
  deviationBand: string;
  modifiedZScore: MaybeNumber;
  statisticalStatus: string;
  /** The backend's interpretation of the observation, verbatim or null. */
  interpretation: string | null;
  distribution: {
    count: number;
    minimum: MaybeNumber;
    q1: MaybeNumber;
    median: MaybeNumber;
    q3: MaybeNumber;
    maximum: MaybeNumber;
    iqr: MaybeNumber;
    mad: MaybeNumber;
  };
}

/** Peer comparison for one scope. */
export interface ScopeBenchmarkSummary {
  assessmentId: string;
  entityName: string | null;
  periodLabel: string | null;
  cohortLabel: string | null;
  cohortStatus: string;
  cohortPeerCount: number;
  cohortRuleSteps: string[];
  metrics: PeerMetricView[];
}

export interface PeerComparisonView {
  available: boolean;
  /** The backend's reason, when it declined to benchmark. */
  unavailableReason: string | null;
  scopeCount: number;
  /** One row per scope, in the backend's order. */
  scopes: ScopeBenchmarkSummary[];
  /** The collection-level metric, when the backend published one. */
  collection: CollectionBenchmarkView | null;
  limitations: string[];
  /** Metric labels the backend offered, in catalogue order. */
  metricCatalogue: Array<{ metricId: string; label: string }>;
  baselinePolicy: { minPeers: number; robustMinPeers: number } | null;
}

export interface CollectionBenchmarkView {
  label: string;
  observed: MaybeNumber;
  metricStatus: string;
  scopeCount: number;
  evaluatedScopeCount: number;
  notEvaluableScopeCount: number;
  note: string;
}

// --------------------------------------------------------------- evidence

export interface EvidenceHealthView {
  /** Submissions the register holds. */
  total: number;
  verified: number;
  mismatch: number;
  missing: number;
  /** Submissions the trust layer's analysis gate refuses. */
  blocked: number;
  /** True when `blocked` and `mismatch` can overlap; they are not a partition. */
  categoriesOverlap: true;
}

// ----------------------------------------------------------------- findings

export interface FindingSummaryView {
  total: number;
  families: SignalFamilyCount[];
  /** The single largest family, when one is strictly largest. */
  dominant: SignalFamilyId | null;
  empty: boolean;
}

export interface AnomalyView {
  modelStatus: string;
  modelReason: string | null;
  verdicts: Array<{ verdict: string; count: number }>;
  /** The verdict count the backend reported as POTENTIAL. */
  potentialCount: number;
  notEvaluableCount: number;
  limitations: string[];
  featureSchemaVersion: string | null;
  modelVersion: string | null;
}

// ------------------------------------------------------------ the whole thing

/**
 * Everything the five screens read. Assembled once from one pipeline result and
 * one run state, and shared through `DashboardProvider`.
 */
export interface DashboardViewModel {
  /** True when a completed pipeline result is loaded. */
  hasResult: boolean;
  run: RunView;
  /**
   * The one authoritative answer to "what is the assessment doing".
   *
   * Screens branch on this rather than on `run.phase`, so no screen can read a
   * busy phase without also proving a run exists to be busy.
   */
  lifecycle: AssessmentLifecycle;
  status: StatusStripView;
  landscape: SignalLandscapeView;
  entities: EntityAttentionRow[];
  peer: PeerComparisonView;
  evidence: EvidenceHealthView | null;
  findings: FindingSummaryView;
  anomaly: AnomalyView | null;
  capability: {
    scopeCount: number;
    assessableInstances: number;
  };
  /** Backend-stated constraints on the assessment, verbatim. */
  limitations: string[];
  /** Result keys the pipeline produced that the adapter did not transport. */
  omittedKeys: Array<{ key: string; reason: string }>;
}

// ------------------------------------------------------------------ builders

const EMPTY_RUN: RunView = {
  jobId: null,
  datasetPath: null,
  datasetName: null,
  // Not "queued". There is no run here to queue. See `RunPhase`.
  phase: "idle",
  statusToken: "none",
  createdAt: null,
  startedAt: null,
  finishedAt: null,
  error: null,
  log: [],
  switching: false,
  pendingDatasetName: null,
  pendingJobId: null,
};

function fileName(path: string | null | undefined): string | null {
  if (!path) {
    return null;
  }

  const base = path.split("/").pop() ?? path;

  return base.length > 0 ? base : null;
}

/**
 * A run the interface is waiting on instead of the one on screen.
 *
 * Carried whole so the run view can name the run and the dataset together.
 * A pending run with no job id is not a run at all, so it is treated as absent
 * rather than half-present.
 */
export interface PendingRunShape {
  jobId: string;
  dataset: string;
}

export function buildRunView(
  analysis: AnalysisState | null,
  switching: boolean,
  pending: PendingRunShape | null,
): RunView {
  const pendingJobId = pending?.jobId ?? null;

  if (!analysis) {
    return {
      ...EMPTY_RUN,
      switching: switching && pendingJobId !== null,
      pendingDatasetName: fileName(pending?.dataset),
      pendingJobId,
    };
  }

  // A run is only *identified* once it has a job id to poll and a dataset to
  // name. The backend reporting a run as active is not on its own enough to
  // describe work as happening: an unidentifiable run cannot be polled to a
  // conclusion, cannot be shown to belong to a dataset, and cannot be waited
  // for. So the two active phases below are only reachable by a run that
  // carries both. This is the invariant enforced at its source, rather than
  // left to each screen to remember.
  const identified = analysis.job_id.length > 0 && fileName(analysis.dataset) !== null;

  const phase: RunPhase =
    analysis.status === "complete"
      ? "complete"
      : analysis.status === "error"
        ? "failed"
        : !identified
          ? "idle"
          : analysis.started_at
            ? "running"
            : "queued";

  return {
    jobId: analysis.job_id,
    datasetPath: analysis.dataset,
    datasetName: fileName(analysis.dataset),
    phase,
    statusToken: analysis.status,
    createdAt: analysis.created_at,
    startedAt: analysis.started_at,
    finishedAt: analysis.finished_at,
    error: analysis.error ?? null,
    log: analysis.log ?? [],
    switching: switching && pendingJobId !== null,
    pendingDatasetName: fileName(pending?.dataset),
    pendingJobId,
  };
}

/**
 * The assessment lifecycle, as one authoritative answer.
 *
 * Every screen asks the same question — is there an assessment, is one being
 * produced, did one fail — and previously each asked it differently. Six screens
 * read `running` from the analysis context while the Overview and the header read
 * `run.phase`, so two parts of one page could disagree about whether an
 * assessment was in progress. That disagreement is the defect this replaces: the
 * states are derived here, once, and every screen reads the same value.
 *
 *   NO_DATASET  nothing selected, no run, no result
 *   READY       a dataset is known, but no run has been started and none is
 *               being waited on
 *   ASSESSING   a run the examiner explicitly started, which the backend
 *               reports as active, for a dataset the interface can name
 *   COMPLETE    a finished result is loaded
 *   FAILED      the run the interface was waiting on did not complete
 *
 * Cancelling a switch and a run that is refused are *transitions*, not resting
 * states, and so have no member here: `cancelPending` drops the pending run, and
 * a refused run never becomes one, so both land on the resting state the loaded
 * assessment already described. That is why neither can strand the interface in
 * `ASSESSING`.
 */
export type AssessmentLifecycle =
  | "NO_DATASET"
  | "READY"
  | "ASSESSING"
  | "COMPLETE"
  | "FAILED";

/**
 * Derive the lifecycle.
 *
 * The order is deliberate. A run being waited on is checked first, because a
 * switch keeps the previous result on screen and would otherwise report
 * `COMPLETE` while a new run was in flight. Then the run on screen, then the
 * result, then a failure, and only then the two states that describe having
 * nothing.
 *
 * `ASSESSING` is unreachable unless all of the following hold, which is the
 * whole point: there is a run, the backend's own token says it is active, it has
 * a job id to poll, and it has a dataset to name. Drop any one and the answer is
 * not `ASSESSING`.
 */
export function assessmentLifecycle(
  run: RunView,
  hasResult: boolean,
): AssessmentLifecycle {
  // A switch run is the run being waited on: it was explicitly requested, and
  // the pending run is held with the job id needed to follow it to completion.
  if (run.pendingJobId !== null) {
    return "ASSESSING";
  }

  const active =
    run.statusToken === "processing" &&
    (run.phase === "queued" || run.phase === "running") &&
    run.jobId !== null &&
    run.datasetName !== null;

  if (active) {
    return "ASSESSING";
  }

  if (hasResult) {
    return "COMPLETE";
  }

  if (run.phase === "failed") {
    return "FAILED";
  }

  // A dataset the interface can name, with no run started against it. Distinct
  // from `NO_DATASET` because the examiner has chosen something.
  if (run.jobId !== null || run.datasetName !== null) {
    return "READY";
  }

  return "NO_DATASET";
}

/** True only when a run is genuinely in flight. Never a phase check alone. */
export function isAssessing(run: RunView, hasResult: boolean): boolean {
  return assessmentLifecycle(run, hasResult) === "ASSESSING";
}

/** Status text for the header. Reads the backend's own token. */
export function runStatusLabel(run: RunView): string {
  if (run.switching) {
    // A switch is an assessment run, so it is labelled the same way any other
    // run in progress is. The dataset field next to it keeps showing what is
    // loaded, and the pending file is shown separately, so the two are never
    // confused. The dataset-switching check watches for this word to know a
    // replacement is being produced behind the loaded assessment.
    return "Assessing";
  }

  // No run has been loaded at all. This is a different state from a run that is
  // queued, and the difference matters: "queued" describes work that exists,
  // "no analysis" describes the absence of any work. Collapsing the two would
  // tell an examiner a pipeline is busy when nothing has been submitted. The
  // `idle` phase reaches the same answer through the switch below, so the two
  // routes cannot disagree.
  if (!run.jobId) {
    return "No analysis";
  }

  switch (run.phase) {
    case "idle":
      return "No analysis";
    case "queued":
      return "Queued";
    case "running":
      return "Processing";
    case "complete":
      return "Analysis complete";
    case "failed":
      return "Error";
    default:
      return "No analysis";
  }
}

export function runStatusTone(run: RunView): Tone {
  if (run.switching) {
    return "info";
  }

  switch (run.phase) {
    case "queued":
    case "running":
      return "info";
    case "complete":
      return "positive";
    case "failed":
      return "critical";
    default:
      return "neutral";
  }
}

/** The moment an examiner would name as "the run". */
export function runTimestamp(run: RunView): string | null {
  return run.finishedAt ?? run.startedAt ?? run.createdAt;
}

/**
 * Each family's count, read from the key the pipeline wrote it to.
 *
 * The anomaly family has no `finding_count`; its findings array is the count.
 * That is a length of a backend array, not a tally the interface invented.
 */
function familyCounts(result: PipelineResult): SignalFamilyCount[] {
  const anomaly = result.anomaly_findings;

  const counts: Record<SignalFamilyId, number | null> = {
    execution_gap: result.execution_gap_findings?.finding_count ?? null,
    negative_space: result.negative_space_findings?.finding_count ?? null,
    operational_pattern:
      result.operational_pattern_findings?.finding_count ?? null,
    anomaly: anomaly?.findings ? anomaly.findings.length : null,
  };

  return SIGNAL_FAMILIES.map((family) => ({
    id: family.id,
    label: family.label,
    singular: family.singular,
    count: counts[family.id],
    sourceKey: family.key,
  }));
}

export function buildLandscape(result: PipelineResult): SignalLandscapeView {
  const families = familyCounts(result);
  const known = families.filter(
    (family): family is SignalFamilyCount & { count: number } =>
      family.count !== null,
  );

  const total =
    known.length === 0 ? null : known.reduce((sum, f) => sum + f.count, 0);

  return { families, total, empty: total === 0 };
}

function buildStatusStrip(result: PipelineResult): StatusStripView {
  const landscape = buildLandscape(result);
  const anomaly = result.anomaly_findings;

  return {
    records: result.assessment?.record_count ?? null,
    scopes: result.assessment?.scope_count ?? null,
    signals: landscape.total,
    entities:
      result.assessment?.entity_resolution?.available === true
        ? (result.assessment.entity_resolution.distinct_entities ?? null)
        : null,
    unresolvedScopes:
      result.assessment?.entity_resolution?.available === true
        ? (result.assessment.entity_resolution.unresolved_scopes ?? null)
        : null,
    recordsAvailable: (result.assessment?.record_count ?? 0) > 0,
    modelStatus: anomaly?.anomaly_model_status?.status ?? null,
    modelReason: anomaly?.anomaly_model_status?.reason ?? null,
  };
}

/**
 * Whether a metric's value reads as a proportion. Presentation only.
 *
 * Derived from what the backend published rather than from a list of metric
 * ids: the catalogue declares every metric as a share of a denominator and the
 * engine publishes the `numerator` and `denominator` that produced the value,
 * so a metric with both present is a rate and an absolute count arrives without
 * them. That keeps formatting correct for a metric the catalogue adds later,
 * which an id list would silently get wrong.
 */
function isRateMetric(entry: MetricBenchmark): boolean {
  return (
    typeof entry.numerator === "number" &&
    typeof entry.denominator === "number" &&
    entry.denominator > 0
  );
}

export function buildPeerMetric(entry: MetricBenchmark): PeerMetricView {
  const rate = isRateMetric(entry);

  return {
    metricId: entry.metric_id,
    label: entry.label,
    direction: entry.direction,
    measureType: entry.measure_type,
    directionLabel: directionLabel(entry.direction),
    observed: entry.observed_value,
    observedIsRate: rate,
    metricStatus: entry.metric_status,
    notEvaluableReason: entry.not_evaluable_reason,
    median: entry.peer_distribution?.median ?? null,
    percentile: entry.percentile,
    percentileStatus: entry.percentile_status,
    rank: entry.rank_of_observed,
    rankStatus: entry.rank_status,
    baselineStatus: entry.baseline_status,
    baselineReason: entry.baseline_reason,
    cohortSize: entry.cohort_size,
    peerCount: entry.peer_count,
    // The backend's own signal. NOT_COMPUTABLE here is exactly the zero-spread
    // case, and it carries the sentence explaining why.
    separated: entry.statistical_status === "COMPUTED",
    separationReason: entry.statistical_not_computable_reason,
    deviationBand: entry.deviation_band,
    modifiedZScore: entry.modified_z_score,
    statisticalStatus: entry.statistical_status,
    interpretation: entry.interpretation,
    distribution: {
      count: entry.peer_distribution?.count ?? 0,
      minimum: entry.peer_distribution?.minimum ?? null,
      q1: entry.peer_distribution?.q1 ?? null,
      median: entry.peer_distribution?.median ?? null,
      q3: entry.peer_distribution?.q3 ?? null,
      maximum: entry.peer_distribution?.maximum ?? null,
      iqr: entry.peer_distribution?.iqr ?? null,
      mad: entry.peer_distribution?.mad ?? null,
    },
  };
}

function summariseScope(scope: BenchmarkScope): ScopeBenchmarkSummary {
  return {
    assessmentId: scope.assessment_id,
    entityName: scope.entity_name ?? scope.entity_id ?? null,
    periodLabel: scope.period_label,
    cohortLabel: scope.cohort?.label ?? null,
    cohortStatus: scope.cohort?.status ?? "",
    cohortPeerCount: scope.cohort?.peer_count ?? 0,
    cohortRuleSteps: scope.cohort?.selection_rule_steps ?? [],
    metrics: orderPeerMetrics(
      (scope.benchmarks ?? []).map(buildPeerMetric),
    ),
  };
}

/**
 * Order a scope's metrics for display: the ones the backend could compute a
 * standardised deviation for come first, then the ones where the peer cohort had
 * no spread. Within each group the backend's catalogue order is preserved, so
 * the order reflects the backend's own judgement about which comparisons carry
 * information rather than a preference written into the interface.
 *
 * Overview, Assessments and Assessment Detail all call this, so a metric sits in
 * the same position on every screen.
 */
export function orderPeerMetrics(metrics: PeerMetricView[]): PeerMetricView[] {
  const separable = metrics.filter((metric) => metric.separated);
  const tied = metrics.filter((metric) => !metric.separated);
  return [...separable, ...tied];
}

export function buildPeerView(
  benchmark: PeerBenchmark | null | undefined,
): PeerComparisonView {
  if (!benchmark) {
    return {
      available: false,
      unavailableReason:
        "The pipeline produced no peer benchmark for this assessment.",
      scopeCount: 0,
      scopes: [],
      collection: null,
      limitations: [],
      metricCatalogue: [],
      baselinePolicy: null,
    };
  }

  const collection = benchmark.collection_metrics;

  return {
    available: benchmark.available,
    unavailableReason: benchmark.unavailable_reason ?? null,
    scopeCount: benchmark.scope_count ?? benchmark.scopes?.length ?? 0,
    scopes: (benchmark.scopes ?? []).map(summariseScope),
    collection: collection
      ? {
          label: collection.label,
          observed: collection.observed_value,
          metricStatus: collection.metric_status,
          scopeCount: collection.scope_count,
          evaluatedScopeCount: collection.evaluated_scope_count,
          notEvaluableScopeCount: collection.not_evaluable_scope_count,
          note: collection.note,
        }
      : null,
    limitations: benchmark.limitations ?? [],
    metricCatalogue: (benchmark.metric_catalogue ?? []).map((metric) => ({
      metricId: metric.metric_id,
      label: metric.label,
    })),
    baselinePolicy: benchmark.baseline_policy
      ? {
          minPeers: benchmark.baseline_policy.min_peers_for_baseline,
          robustMinPeers: benchmark.baseline_policy.robust_min_peers,
        }
      : null,
  };
}

export function buildAnomalyView(result: PipelineResult): AnomalyView | null {
  const anomaly = result.anomaly_findings;

  if (!anomaly) {
    return null;
  }

  const counts = anomaly.verdict_counts ?? {};

  const verdicts = Object.entries(counts)
    .map(([verdict, count]) => ({ verdict, count: count ?? 0 }))
    .sort((a, b) => b.count - a.count || a.verdict.localeCompare(b.verdict));

  const schema = anomaly.feature_schema;

  return {
    modelStatus: anomaly.anomaly_model_status?.status ?? "NOT_TRAINED",
    modelReason: anomaly.anomaly_model_status?.reason ?? null,
    verdicts,
    potentialCount: counts.POTENTIAL_OPERATIONAL_ANOMALY ?? 0,
    notEvaluableCount: counts.NOT_EVALUABLE ?? 0,
    limitations: anomaly.limitations ?? [],
    featureSchemaVersion: schema?.feature_schema_version ?? null,
    modelVersion: schema?.model_version ?? null,
  };
}

function evidenceForScope(
  result: PipelineResult,
  assessmentId: string,
): ScopeEvidenceView {
  const scope = (result.capability_assessment?.scopes ?? []).find(
    (entry) => entry.assessment_id === assessmentId,
  );

  const counts = scope?.status_counts ?? {};

  const available = counts.AVAILABLE ?? 0;
  const insufficient = counts.INSUFFICIENT_EVIDENCE ?? 0;
  const notAssessed = counts.NOT_ASSESSED ?? 0;

  return {
    available,
    insufficient,
    notAssessed,
    nothingAssessable:
      available === 0 && insufficient === 0 && notAssessed === 0,
  };
}

/**
 * The backend's own entity risk band, when one exists for this scope.
 *
 * `entity_assessment` groups by entity, and for some datasets the resolver
 * returns a single placeholder group rather than one per scope. Matching on the
 * resolved entity id and refusing to match on the placeholder is what keeps an
 * `UNKNOWN_ENTITY` row from being presented as a scope's own assessment.
 */
function backendRiskBand(
  result: PipelineResult,
  entity: EntityRef,
): { level: string; score: number; indicators: string[] } | null {
  if (!entity.available || !entity.id) {
    return null;
  }

  const entry = (result.entity_assessment ?? []).find(
    (candidate) =>
      candidate.entity === entity.id && candidate.entity !== "UNKNOWN_ENTITY",
  );

  if (!entry) {
    return null;
  }

  return {
    level: entry.risk_level,
    score: entry.attention_score,
    indicators: Array.isArray(entry.risk_indicators)
      ? entry.risk_indicators.map(String)
      : [],
  };
}

const RISK_TONE: Record<string, Tone> = {
  HIGH: "critical",
  MEDIUM: "caution",
  LOW: "positive",
};

function buildAttention(
  result: PipelineResult,
  entity: EntityRef,
  signals: number,
  primaryLabel: string | null,
): AttentionView {
  const band = backendRiskBand(result, entity);

  if (band) {
    return {
      kind: "risk_band",
      label: band.level.charAt(0) + band.level.slice(1).toLowerCase(),
      tone: RISK_TONE[band.level] ?? "neutral",
      detail: `Backend risk band, score ${band.score}`,
    };
  }

  if (signals === 0) {
    return {
      kind: "quiet",
      label: "No signals",
      tone: "neutral",
      detail: "No signal family reported a finding for this scope",
    };
  }

  return {
    kind: "signals",
    label: "Signals reported",
    tone: "caution",
    detail: primaryLabel
      ? `${signals} ${signals === 1 ? "signal" : "signals"}, mostly ${primaryLabel.toLowerCase()}`
      : `${signals} ${signals === 1 ? "signal" : "signals"} across two families`,
  };
}

/**
 * The entity attention rows, ordered by signal count then entity name.
 *
 * Ordering is presentation. The count it orders by is the backend's own
 * `finding_count` per family, tallied across a scope's findings.
 */
export function buildEntityRows(result: PipelineResult): EntityAttentionRow[] {
  const families = SIGNAL_FAMILIES;

  const findingsByScope = new Map<
    string,
    { byFamily: Record<SignalFamilyId, number>; total: number }
  >();

  const bump = (assessmentId: string, family: SignalFamilyId) => {
    const entry = findingsByScope.get(assessmentId) ?? {
      byFamily: {
        execution_gap: 0,
        negative_space: 0,
        operational_pattern: 0,
        anomaly: 0,
      },
      total: 0,
    };

    entry.byFamily[family] += 1;
    entry.total += 1;
    findingsByScope.set(assessmentId, entry);
  };

  for (const family of families) {
    const key = family.key as keyof PipelineResult;
    const block = result[key] as
      | { findings?: Array<{ assessment_id: string }> }
      | undefined;

    for (const finding of block?.findings ?? []) {
      bump(finding.assessment_id, family.id);
    }
  }

  const benchmarkByScope = new Map(
    (result.peer_benchmark?.scopes ?? []).map((scope) => [
      scope.assessment_id,
      summariseScope(scope),
    ]),
  );

  const rows: EntityAttentionRow[] = (result.assessment?.scopes ?? []).map(
    (scope, order) => {
      const tallied = findingsByScope.get(scope.assessment_id);
      const byFamily = tallied?.byFamily ?? {
        execution_gap: 0,
        negative_space: 0,
        operational_pattern: 0,
        anomaly: 0,
      };
      const signals = tallied?.total ?? 0;

      let primaryFamily: SignalFamilyId | null = null;
      let best = 0;
      let tied = false;

      for (const family of families) {
        const count = byFamily[family.id];

        if (count > best) {
          best = count;
          primaryFamily = family.id;
          tied = false;
        } else if (count === best && count > 0) {
          tied = true;
        }
      }

      if (tied) {
        primaryFamily = null;
      }

      const primaryLabel = primaryFamily
        ? (families.find((family) => family.id === primaryFamily)?.singular ??
          null)
        : null;

      return {
        assessmentId: scope.assessment_id,
        order,
        entity: scope.entity,
        period: scope.period,
        recordCount: scope.record_count,
        signals,
        byFamily,
        primaryFamily,
        attention: buildAttention(result, scope.entity, signals, primaryLabel),
        evidence: evidenceForScope(result, scope.assessment_id),
        benchmark: benchmarkByScope.get(scope.assessment_id) ?? null,
        resolved: scope.entity.available,
      };
    },
  );

  return rows.sort(
    (a, b) =>
      b.signals - a.signals ||
      b.recordCount - a.recordCount ||
      (a.entity.id ?? "").localeCompare(b.entity.id ?? ""),
  );
}

export function buildFindingsSummary(
  result: PipelineResult,
): FindingSummaryView {
  const families = familyCounts(result);
  const known = families.filter(
    (family): family is SignalFamilyCount & { count: number } =>
      family.count !== null,
  );

  const total = known.reduce((sum, family) => sum + family.count, 0);

  let dominant: SignalFamilyId | null = null;
  let best = 0;
  let tied = false;

  for (const family of known) {
    if (family.count > best) {
      best = family.count;
      dominant = family.id;
      tied = false;
    } else if (family.count === best && best > 0) {
      tied = true;
    }
  }

  return { total, families, dominant: tied ? null : dominant, empty: total === 0 };
}

export function buildDashboardViewModel(
  analysis: AnalysisState | null,
  result: PipelineResult | null,
  evidence: EvidenceHealthView | null,
  switching: boolean,
  pending: PendingRunShape | null,
): DashboardViewModel {
  const run = buildRunView(analysis, switching, pending);
  const lifecycle = assessmentLifecycle(run, result !== null);

  if (!result) {
    return {
      hasResult: false,
      run,
      lifecycle,
      status: {
        records: null,
        scopes: null,
        signals: null,
        entities: null,
        unresolvedScopes: null,
        recordsAvailable: false,
        modelStatus: null,
        modelReason: null,
      },
      landscape: { families: [], total: null, empty: false },
      entities: [],
      peer: buildPeerView(null),
      evidence,
      findings: {
        total: 0,
        families: [],
        dominant: null,
        empty: false,
      },
      anomaly: null,
      capability: { scopeCount: 0, assessableInstances: 0 },
      limitations: [],
      omittedKeys: analysis?.omitted_keys ?? [],
    };
  }

  return {
    hasResult: true,
    run,
    lifecycle,
    status: buildStatusStrip(result),
    landscape: buildLandscape(result),
    entities: buildEntityRows(result),
    peer: buildPeerView(result.peer_benchmark),
    evidence,
    findings: buildFindingsSummary(result),
    anomaly: buildAnomalyView(result),
    capability: {
      scopeCount: result.capability_assessment?.summary?.scope_count ?? 0,
      assessableInstances:
        result.capability_assessment?.summary
          ?.assessable_capability_instances ?? 0,
    },
    limitations: [
      ...(result.peer_benchmark?.limitations ?? []),
      ...(result.anomaly_findings?.limitations ?? []),
    ],
    omittedKeys: analysis?.omitted_keys ?? [],
  };
}
