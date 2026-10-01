/**
 * TypeScript mirrors of the SAT-SA pipeline result.
 *
 * Every interface here corresponds to a key or a nested structure that
 * `SATSAPipeline.run` actually returns. These types describe the backend; they
 * do not extend it. Nothing in this file introduces a field the pipeline does
 * not produce, and nothing marks a field optional unless the pipeline can
 * genuinely omit it.
 *
 * The distinction that matters throughout this application:
 *
 *   - a value that is a number is a measurement
 *   - `null` means the pipeline resolved the field but found nothing
 *   - a status string is the backend's own state, not a UI judgement
 *
 * Nothing in the frontend may collapse those three into each other.
 */

/** JSON representation of a value the pipeline produced but JSON cannot hold. */
export interface Unrepresentable {
  __unrepresentable__: true;
  python_type: string | null;
  reason?: string;
}

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

/** A number that may legitimately be absent. */
export type MaybeNumber = number | null;

/** A string that may legitimately be absent. */
export type MaybeString = string | null;

// ---------------------------------------------------------------- transport

export type AnalysisStatus = "processing" | "complete" | "error";

export interface OmittedKey {
  key: string;
  reason: string;
}

export interface AnalysisState {
  job_id: string;
  dataset: string;
  status: AnalysisStatus;
  created_at: string;
  started_at: MaybeString;
  finished_at: MaybeString;
  log: string[];
  error?: string;
  error_detail?: string;
  result?: PipelineResult | null;
  omitted_keys?: OmittedKey[];
  full_export_available?: boolean;
}

export interface DatasetEntry {
  path: string;
  filename: string;
  directory: string;
  size_bytes: number;
  modified: number;
}

export interface HealthState {
  status: string;
  pipeline_available: boolean;
  pipeline_error: MaybeString;
  retained_analyses: number;
}

// ------------------------------------------------------------ scope identity

/**
 * Entity and period resolution. Both carry `available: false` and an
 * `unavailable_reason` when the evidence did not permit resolution. The
 * interface must show that reason rather than displaying the placeholder
 * identifier as though it were a real entity.
 */
export type EntityRef = {
  id: MaybeString;
  name: MaybeString;
  confidence: MaybeNumber;
  available: boolean;
  source: MaybeString;
  method: MaybeString;
  unavailable_reason: MaybeString;
}

export type PeriodRef = {
  label: MaybeString;
  start: MaybeString;
  end: MaybeString;
  confidence: MaybeNumber;
  available: boolean;
  granularity: MaybeString;
  source: MaybeString;
  method: MaybeString;
  label_precision: MaybeString;
  inherited: boolean;
  unavailable_reason: MaybeString;
}

export interface ScopeIdentity {
  assessment_id: string;
  entity: EntityRef;
  period: PeriodRef;
  record_count: number;
}

export interface SourceRef {
  id: MaybeString;
  type: MaybeString;
  evidence_id: MaybeString;
}

// --------------------------------------------------------------- assessment

export interface ColumnResolution {
  identifier_column?: MaybeString;
  identifier_concept?: MaybeString;
  identifier_confidence?: number;
  name_column?: MaybeString;
  name_concept?: MaybeString;
  name_confidence?: number;
  candidates?: string[];
  ambiguous?: boolean;
  method?: MaybeString;
  reason?: MaybeString;
  period_column?: MaybeString;
  period_concept?: MaybeString;
  period_confidence?: number;
  timestamp_column?: MaybeString;
  timestamp_concept?: MaybeString;
  timestamp_confidence?: number;
  period_candidates?: string[];
  timestamp_candidates?: string[];
}

export interface ResolutionSummary {
  available: boolean;
  distinct_entities?: number;
  unresolved_scopes?: number;
  column_resolution: ColumnResolution;
}

export interface AssessmentScope extends ScopeIdentity {
  source: SourceRef;
  metadata: Record<string, Json>;
}

export interface AssessmentResult {
  source: SourceRef;
  scopes: AssessmentScope[];
  scope_count: number;
  record_count: number;
  entity_resolution: ResolutionSummary;
  period_resolution: ResolutionSummary;
  metadata: Record<string, Json>;
}

// --------------------------------------------------------------- capability

/**
 * The only three capability states the pipeline emits. They describe evidence
 * availability, not performance, and must never be presented as risk levels.
 */
export type CapabilityStatus = "AVAILABLE" | "INSUFFICIENT_EVIDENCE" | "NOT_ASSESSED";

export interface EvidenceDetailItem {
  canonical_path: string;
  concept: string;
  tier: string;
  role: string;
  discoverable: boolean;
  satisfied: boolean;
  source_column?: MaybeString;
  [key: string]: Json | undefined;
}

export interface Capability {
  capability_id: string;
  name: string;
  status: CapabilityStatus;
  is_assessable: boolean;
  has_partial_evidence: boolean;
  confidence: MaybeNumber;
  coverage: MaybeNumber;
  evidence_available: string[];
  evidence_missing: string[];
  indicator_categories: string[];
  explanation: string;
  evidence_detail: EvidenceDetailItem[];
}

export interface CapabilityScope extends ScopeIdentity {
  capabilities: Capability[];
  status_counts: Partial<Record<CapabilityStatus, number>>;
}

export interface CapabilitySummaryItem {
  capability_id: string;
  available_scopes: number;
  insufficient_evidence_scopes: number;
  not_assessed_scopes: number;
}

export interface CapabilityAssessment {
  capability_ids: string[];
  scope_count: number;
  scopes: CapabilityScope[];
  summary: {
    scope_count: number;
    assessable_capability_instances: number;
    capabilities: CapabilitySummaryItem[];
  };
}

// ------------------------------------------------------------------ findings

/**
 * The four signal families the pipeline reports. These strings come from the
 * result keys themselves; the union exists so a missing family is a type
 * error rather than a silently absent filter.
 */
export type SignalFamily =
  | "execution_gap"
  | "negative_space"
  | "operational_pattern"
  | "anomaly";

export type RecordReference = {
  record_position?: number;
  source_record_index?: number;
  [key: string]: Json | undefined;
}

/** Shared identity every finding carries. */
export interface FindingIdentity {
  indicator: string;
  assessment_id: string;
  entity: EntityRef;
  period: PeriodRef;
  evidence_concepts?: string[];
  record_reference?: RecordReference;
  reason: string;
  /**
   * Finding payloads carry further backend fields the interface does not
   * model. They are left untyped on purpose: unknown extra data is visible as
   * unknown, where a `Json` index signature would claim more than is known.
   */
  [key: string]: unknown;
}

export interface ExecutionGapFinding extends FindingIdentity {
  capability: string;
  status: string;
  rule_id: string;
  rule_name: string;
  evidence: Record<string, Json>;
  record_reference: RecordReference;
}

export interface NegativeSpaceFinding extends FindingIdentity {
  capability: string;
  status: string;
  absence_state: string;
  rule_id: string;
  rule_name: string;
  expectation: {
    trigger: string;
    expected_evidence: string[];
    basis: string;
    statement: string;
    why_expected: string[];
  };
  evidence_summary: Record<string, Json>;
  record_reference: RecordReference;
}

export interface OperationalPatternFinding extends FindingIdentity {
  status: string;
  pattern_type: string;
  capability: string;
  pattern_id: string;
  pattern_name: string;
  method: string;
  population: Record<string, Json>;
  evidence: Record<string, Json>;
  why_review_might_be_warranted?: string[];
  explanation_limitations?: string[];
  is_not_a_control_failure?: string;
  evidence_concepts: string[];
  record_reference: RecordReference;
}

// ------------------------------------------------------------------- anomaly

/**
 * The three anomaly verdicts. A verdict is a statement about distance from a
 * reference population, never a severity and never a control failure.
 */
export type AnomalyVerdict =
  | "POTENTIAL_OPERATIONAL_ANOMALY"
  | "NO_ANOMALY"
  | "NOT_EVALUABLE";

export interface AnomalyModelStatus {
  status: string;
  reason: MaybeString;
}

export interface AnomalyFeatureValue {
  feature_id: string;
  value: MaybeNumber;
  available: boolean;
  source_concepts: string[];
}

export interface UnavailableFeature {
  feature_id: string;
  reason: string;
}

export interface FeatureSchema {
  feature_schema_version: string;
  model_version: string;
  feature_ids: string[];
  schema_fingerprint: string;
  features: Json;
}

/**
 * How the reference population looked for one feature, as recorded when the
 * model was trained.
 *
 * Two states, kept apart: the statistics exist, or they were never recorded. An
 * absent distribution is not a distribution of zeroes.
 */
export type AnomalyReferenceSummary =
  | {
      available: false;
      note: string;
    }
  | {
      available: true;
      minimum: MaybeNumber;
      p10: MaybeNumber;
      median: MaybeNumber;
      p90: MaybeNumber;
      maximum: MaybeNumber;
      mean: MaybeNumber;
      standard_deviation: MaybeNumber;
    };

/** One feature as the model saw it: the observed value beside the reference. */
export interface AnomalyProfileRow {
  feature_id: string;
  observed_value: MaybeNumber;
  available: boolean;
  source_concepts: string[];
  reference_summary: AnomalyReferenceSummary;
  distance_from_reference_median: MaybeNumber;
  unavailable_reason?: string;
}

/**
 * The model's own account of one verdict.
 *
 * This is an object, not a sentence: the prose the detector wrote
 * (``narrative``, ``explanation``) sits beside the numbers it was based on
 * (``feature_profile``) and beside its statement of what the score means
 * (``score_semantics``). All of it is the backend's wording; none of it is
 * paraphrased here.
 */
export interface AnomalyExplanation {
  assessment_id: string;
  entity: EntityRef;
  period: PeriodRef;
  verdict: AnomalyVerdict;
  model_type: string;
  model_version: string;
  feature_schema_version: string;
  anomaly_score: MaybeNumber;
  feature_profile: AnomalyProfileRow[];
  narrative: string;
  explanation: string;
  evidence_concepts: string[];
  limitations: string[];
  score_semantics: string;
}

export interface AnomalyScopeResult extends ScopeIdentity {
  record_count: number;
  verdict: AnomalyVerdict;
  reason: string;
  anomaly_score: MaybeNumber;
  feature_schema_version: string;
  model_version: string;
  features: AnomalyFeatureValue[];
  feature_schema: FeatureSchema;
  unavailable_features: UnavailableFeature[];
  explanation: AnomalyExplanation;
  evidence_concepts: string[];
  limitations: string[];
}

/**
 * An anomaly finding.
 *
 * Declared field by field rather than extending ``ScopeIdentity``, because the
 * detector emits the identity fields but not ``record_count``: a finding
 * identifies a scope, it does not restate the scope's size.
 */
export interface AnomalyFinding {
  indicator: string;
  verdict: AnomalyVerdict;
  assessment_id: string;
  entity: EntityRef;
  period: PeriodRef;
  reason: string;
  anomaly_score: MaybeNumber;
  features: AnomalyFeatureValue[];
  evidence_concepts: string[];
  model_version: string;
  feature_schema_version: string;
  /** The detector's prose, or null when it wrote none for this scope. */
  explanation: MaybeString;
  narrative: MaybeString;
  limitations: string[];
}

export interface AnomalyFindings {
  anomaly_model_status: AnomalyModelStatus;
  verdict_counts: Partial<Record<AnomalyVerdict, number>>;
  scope_count: number;
  scope_results: AnomalyScopeResult[];
  findings: AnomalyFinding[];
  feature_schema: FeatureSchema;
  limitations: string[];
}

export type AnomalyVerdictCounts = Partial<Record<AnomalyVerdict, number>>;

// ----------------------------------------------------- signal family results

export interface UnavailableRule {
  rule_id: string;
  name: string;
  capability: string;
  status: string;
  required_evidence_ideal?: string[];
  missing_evidence?: string[];
  why_not_implemented?: string[];
  would_require?: string[];
}

export interface SignalScope extends ScopeIdentity {
  findings: Json[];
  [key: string]: unknown;
}

export interface ExecutionGapResult {
  rule_ids: string[];
  capability_ids: string[];
  scope_count: number;
  scopes: SignalScope[];
  finding_count: number;
  findings: ExecutionGapFinding[];
  unavailable_rules: UnavailableRule[];
}

export interface NegativeSpaceResult {
  rule_ids: string[];
  capability_ids: string[];
  scope_count: number;
  scopes: SignalScope[];
  finding_count: number;
  findings: NegativeSpaceFinding[];
  absence_state_counts: Record<string, number>;
  unavailable_rules: UnavailableRule[];
}

export interface OperationalPatternResult {
  pattern_ids: string[];
  capability_ids: string[];
  methodology: Record<string, Json>;
  statistical_parameters: Record<string, Json>;
  scope_count: number;
  scopes: SignalScope[];
  finding_count: number;
  findings: OperationalPatternFinding[];
  pattern_status_counts: Record<string, number>;
  unavailable_patterns: UnavailableRule[];
}

// ------------------------------------------------------------------ profile

export interface IngestionSummary {
  source: string;
  source_type: string;
  record_count: number;
  column_count: number;
  columns: string[];
  [key: string]: Json | undefined;
}

export interface DatasetProfile {
  columns: Json;
  [key: string]: Json | undefined;
}

export interface MappingReport {
  dataset_columns: number;
  mapped_columns: number;
  unmapped_columns: string[];
  high_confidence: MappingEntry[];
  medium_confidence: MappingEntry[];
  low_confidence: MappingEntry[];
  overall_mapping_confidence: number;
}

export interface MappingEntry {
  source_column: string;
  canonical_concept: string;
  confidence: number;
}

// ------------------------------------------------- canonical mapping review
// (C.1). Authoritative Phase 1 decisions transported inside
// `canonical_package`. The legacy `semantic_mapping` / `mapping_report`
// keys are retained for compatibility but are NOT authoritative.

export type CanonicalMappingState =
  | "MAPPED"
  | "LOW_CONFIDENCE"
  | "AMBIGUOUS"
  | "UNMAPPED"
  | "INVALID";

export interface CanonicalCandidate {
  concept: string;
  canonical_path?: string | null;
  confidence: number;
}

export interface CanonicalMappingDecision {
  source_field: string;
  source_column: string;
  canonical_concept?: string | null;
  canonical_path?: string | null;
  confidence: number;
  mapping_state: CanonicalMappingState;
  reason: string;
  candidate_mappings: CanonicalCandidate[];
  applied: boolean;
}

export interface CanonicalContractEntry {
  canonical_path?: string | null;
  category?: string | null;
  pipeline?: string | null;
  datatype?: string | null;
  required?: boolean;
  cardinality?: string | null;
}

export interface CanonicalPackage {
  package_version?: string;
  source_dataset?: string;
  detected_role?: Record<string, Json>;
  canonical_contract?: Record<string, CanonicalContractEntry>;
  schema?: {
    columns?: Array<{ column_name?: string; category?: string }>;
  };
  mapping_decisions?: CanonicalMappingDecision[];
  mapping_collisions?: Array<{
    canonical_path?: string;
    winner?: string;
    losers?: string[];
  }>;
  mapping_states?: Partial<Record<CanonicalMappingState, number>>;
  provenance?: Record<string, Json>;
}

export interface EntityAssessmentEntry {
  entity: string;
  entity_confidence: number;
  entity_source: string;
  records_analyzed: number;
  attention_score: number;
  risk_level: string;
  risk_indicators: Json[];
}

// ------------------------------------------------------------------- result

/** The pipeline result as the adapter transports it. */
export interface PipelineResult {
  dataset: string;
  profile: DatasetProfile;
  ingestion: IngestionSummary;
  semantic_mapping: Json;
  mapping_report: MappingReport;
  canonical_package?: CanonicalPackage | null;
  dataset_context: Record<string, Json>;
  assessment: AssessmentResult;
  capability_assessment: CapabilityAssessment;
  execution_gap_findings: ExecutionGapResult;
  negative_space_findings: NegativeSpaceResult;
  operational_pattern_findings: OperationalPatternResult;
  anomaly_findings: AnomalyFindings;
  entity_assessment: EntityAssessmentEntry[];
  supervisory_findings: Json[];
}
