/**
 * Evidence integrity, exactly as the evidence trust layer reported it.
 *
 * Every field here is a field the backend returned. In particular:
 *
 * * no digest is computed in the browser. `registered_sha256` is the value the
 *   manifest recorded at registration; `expected_sha256` and `observed_sha256`
 *   are the two sides of the comparison the trust layer performed. Showing a
 *   digest here means displaying a comparison someone else made.
 * * no status is interpreted. `VERIFIED`, `INTEGRITY_FAILED`, `MISSING` and
 *   `UNAVAILABLE` are the trust layer's own tokens, passed through, and the
 *   colour of a badge comes from `lib/status.ts` rather than from a decision
 *   made in this file or in the component that renders it.
 * * `analysis.permitted` is the trust layer's own analysis gate, not a policy
 *   applied by the interface.
 */

/** The trust layer's status tokens. */
export type IntegrityStatusToken =
  | "VERIFIED"
  | "INTEGRITY_FAILED"
  | "MISSING"
  | "UNAVAILABLE";

/** One subject's integrity comparison: a preserved original, or a working copy. */
export interface IntegrityComparison {
  status: IntegrityStatusToken;
  /** Repository-relative path, or null when the subject was not examined. */
  path: string | null;
  expected_sha256: string | null;
  observed_sha256: string | null;
  detail: string;
}

/** One file registered in a submission's manifest. */
export interface EvidenceManifestFile {
  name: string;
  stored_name: string;
  relative_path: string;
  size: number;
  sha256: string;
  modified_at: string | null;
  content_type: string;
  role: string;
  location: string;
}

/** One entry in a submission's chain of custody, as recorded at intake. */
export interface EvidenceCustodyEvent {
  action: string;
  actor: string | null;
  detail: string | null;
  occurred_at: string | null;
}

/**
 * Provenance as recorded at registration.
 *
 * Fields that were not supplied are listed in `unavailable_fields` rather than
 * filled with a placeholder, so "not stated at submission" stays visible and
 * cannot be read as a value of zero or of empty.
 */
export interface EvidenceProvenance {
  schema_version?: string;
  evidence_id: string;
  received_at?: string;
  status?: string;
  original_filename: string | null;
  file_size: number | null;
  sha256: string | null;
  package_type: string | null;
  source_identifier: string | null;
  assessment_period: string | null;
  submitted_by: string | null;
  received_channel: string | null;
  unavailable_fields: string[];
  custody_events: EvidenceCustodyEvent[];
  metadata: Record<string, unknown>;
}

/** Whether the trust layer permits this evidence to be analysed. */
export interface EvidenceAnalysisGate {
  permitted: boolean;
  blocked_reason: string | null;
  target_path: string | null;
}

/** One registered evidence submission. */
export interface EvidenceIntegrity {
  evidence_id: string;
  registered_at: string | null;
  hash_algorithm: string | null;
  manifest_schema_version: string | null;
  originals_read_only: boolean | null;
  file_count: number | null;
  total_size: number | null;
  source: {
    filename: string | null;
    stored_name: string | null;
    size_bytes: number | null;
    content_type: string | null;
    modified_at: string | null;
  };
  /** The digest the manifest registered, against which both copies are compared. */
  registered_sha256: string | null;
  /** The preserved original: the file as submitted. */
  original: IntegrityComparison;
  /** The controlled working copy: what a downstream analysis layer may read. */
  working: IntegrityComparison;
  /** One status for the submission, reduced from the two subjects above. */
  overall_status: IntegrityStatusToken;
  analysis: EvidenceAnalysisGate;
  provenance: EvidenceProvenance | null;
  files: EvidenceManifestFile[];
}
