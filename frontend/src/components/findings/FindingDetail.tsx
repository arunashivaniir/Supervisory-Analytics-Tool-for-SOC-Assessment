import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { UnifiedFinding } from "../../app/selectors";
import { cn } from "../../lib/cn";
import { formatNumber, optionalText } from "../../lib/formatters";
import { ConceptList, DataRow, Token } from "../ui/DataDisplay";
import { StatusBadge } from "../ui/StatusBadge";
import { signalStatus } from "../../lib/status";
import { AlertCaseChain } from "./AlertCaseChain";
import type {
  AnomalyFinding,
  ExecutionGapFinding,
  NegativeSpaceFinding,
  OperationalPatternFinding,
} from "../../types/pipeline";

/**
 * The complete finding, as the pipeline reported it.
 *
 * Hierarchy follows the examiner's questions: title and signal type,
 * why it was identified, what was expected, what was observed,
 * which records support it, and where the source evidence lives.
 * Each family renders its own payload fields rather than being forced
 * through a common shape. Nothing is summarised or reworded: the
 * reason, the evidence and the record reference are shown as the
 * backend wrote them, with technical rule metadata secondary.
 */
export function FindingDetail({
  finding,
  compact = false,
}: {
  finding: UnifiedFinding;
  compact?: boolean;
}) {
  const payload = finding.finding;

  return (
    <div className={cn("flex flex-col", compact ? "gap-2" : "gap-3")}>
      <FindingHeader finding={finding} />

      <WhyFlagged finding={finding} />

      {finding.family === "execution_gap" ? (
        <ExecutionGapDetail finding={payload as unknown as ExecutionGapFinding} />
      ) : null}

      {finding.family === "negative_space" ? (
        <NegativeSpaceDetail finding={payload as unknown as NegativeSpaceFinding} />
      ) : null}

      {finding.family === "operational_pattern" ? (
        <OperationalPatternDetail
          finding={payload as unknown as OperationalPatternFinding}
        />
      ) : null}

      {finding.family === "anomaly" ? (
        <AnomalyDetail finding={finding} />
      ) : null}

      <div>
        <div className="section-label mb-1.5">Related records</div>
        <AlertCaseChain finding={finding} />
      </div>

      <SourceRecord finding={finding} />

      {!compact ? (
        <Link
          to={`/evidence?finding=${encodeURIComponent(finding.key)}`}
          className="text-xs font-medium text-accent underline-offset-2 hover:underline"
        >
          View Evidence
        </Link>
      ) : null}
    </div>
  );
}

/**
 * Title, signal type and finding state.
 *
 * The state distinguishes a confirmed analytical finding from layers
 * that could not evaluate: a status the backend did not report renders
 * as not reported, never as a default.
 */
function FindingHeader({ finding }: { finding: UnifiedFinding }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-text">
          {finding.indicator}
        </span>
        <StatusBadge tone="info" label={finding.familyLabel} showDot={false} />
        {finding.status ? (
          <StatusBadge
            tone={signalStatus(finding.status).tone}
            label={signalStatus(finding.status).label}
            raw={finding.status}
          />
        ) : (
          <span className="text-xs text-text-tertiary italic">
            State not reported
          </span>
        )}
      </div>
      {finding.evidenceConcepts.length > 0 ? (
        <ConceptList concepts={finding.evidenceConcepts} collapsed={8} />
      ) : null}
    </div>
  );
}

/**
 * Why this finding exists, in the backend's own words.
 *
 * First on every finding, because an examiner triages on the reason before
 * the payload. The text is the pipeline's `reason` verbatim, never a
 * paraphrase.
 */
function WhyFlagged({ finding }: { finding: UnifiedFinding }) {
  return (
    <div className="rounded-[8px] border border-border bg-subtle/50 px-3 py-2.5">
      <div className="section-label">Why was this flagged?</div>
      <p className="mt-1 text-[13px] leading-relaxed text-text">
        {finding.reason}
      </p>
    </div>
  );
}

/**
 * The source record behind a finding.
 *
 * The pipeline points at source records through `record_reference`: whatever
 * keys it carried (record position, source index, alert or case identifiers,
 * timestamps) are shown as stated. A key the submission did not carry is
 * said to be unavailable, never filled in. The complete per-record payload
 * is not carried by the interface; it is in the full export for this run.
 */
function SourceRecord({ finding }: { finding: UnifiedFinding }) {
  const reference = finding.finding.record_reference;
  const entries =
    reference && typeof reference === "object"
      ? Object.entries(reference).filter(
          ([, value]) => value !== null && value !== undefined,
        )
      : [];

  // Curated first: the identifiers and timestamps an examiner reaches for.
  // Anything else the backend attached follows, in the backend's own order.
  const preferred = [
    "alert_id",
    "case_id",
    "severity",
    "opened_at",
    "closed_at",
    "timestamp",
    "time_to_close",
    "asset",
    "analyst",
    "escalation",
    "disposition",
    "record_position",
    "source_record_index",
  ];

  const ordered = [...entries].sort(([a], [b]) => {
    const rank = (key: string) => {
      const index = preferred.indexOf(key);
      return index === -1 ? preferred.length : index;
    };

    return rank(a) - rank(b);
  });

  return (
    <div>
      <div className="section-label mb-1.5">Source record</div>
      {ordered.length === 0 ? (
        <p className="text-xs text-text-tertiary italic">
          Not available in submission. The pipeline attached no record
          reference to this finding.
        </p>
      ) : (
        <dl className="divide-y divide-border/70">
          {ordered.map(([key, value]) => (
            <DataRow
              key={key}
              label={key.replace(/_/g, " ")}
              value={
                typeof value === "object" && value !== null ? (
                  <code className="font-mono micro">
                    {JSON.stringify(value)}
                  </code>
                ) : (
                  <span className="font-mono text-xs">{String(value)}</span>
                )
              }
            />
          ))}
        </dl>
      )}
    </div>
  );
}

function ExecutionGapDetail({ finding }: { finding: ExecutionGapFinding }) {
  const evidence = Object.entries(finding.evidence ?? {});

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="section-label mb-1.5">Expected condition</div>
        <dl className="divide-y divide-border/70">
          <DataRow label="Rule" value={finding.rule_name} />
          <DataRow label="Capability" value={finding.capability} />
          <DataRow
            label="Required evidence"
            value={<ConceptList concepts={finding.evidence_concepts ?? []} collapsed={8} />}
          />
        </dl>
      </div>

      {evidence.length > 0 ? (
        <div>
          <div className="section-label mb-1.5">Observed condition</div>
          <EvidenceTable evidence={evidence} />
        </div>
      ) : (
        <p className="text-xs text-text-tertiary italic">
          No supporting source records were returned for this finding.
        </p>
      )}

      <TechnicalDetails>
        <DataRow
          label="Rule ID"
          value={<Token>{optionalText(finding.rule_id)}</Token>}
        />
        <DataRow label="Assessment" value={<Token>{finding.assessment_id}</Token>} />
      </TechnicalDetails>
    </div>
  );
}

function NegativeSpaceDetail({ finding }: { finding: NegativeSpaceFinding }) {
  const summary = finding.evidence_summary ?? {};

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="section-label mb-1.5">Expected condition</div>
        <dl className="divide-y divide-border/70">
          <DataRow label="Statement" value={finding.expectation?.statement} />
          <DataRow label="Basis" value={optionalText(finding.expectation?.basis)} />
          <DataRow
            label="Expected evidence"
            value={<ConceptList concepts={finding.expectation?.expected_evidence ?? []} />}
          />
          {Array.isArray(finding.expectation?.why_expected) &&
          finding.expectation.why_expected.length > 0 ? (
            <DataRow
              label="Why expected"
              value={
                <ul className="list-inside list-disc text-xs text-text-secondary">
                  {finding.expectation.why_expected.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              }
            />
          ) : null}
        </dl>
      </div>

      <div>
        <div className="section-label mb-1.5">Observed condition</div>
        <dl className="divide-y divide-border/70">
          {Object.entries(summary)
            .filter(([, value]) => typeof value !== "object" || value === null)
            .map(([key, value]) => (
              <DataRow
                key={key}
                label={key.replace(/_/g, " ")}
                value={
                  typeof value === "number" ? (
                    <span className="tabular">{value}</span>
                  ) : (
                    (value as ReactNode) ?? optionalText(null)
                  )
                }
              />
            ))}
        </dl>
      </div>

      <TechnicalDetails>
        <DataRow
          label="Rule ID"
          value={<Token>{optionalText(finding.rule_id)}</Token>}
        />
        <DataRow label="Assessment" value={<Token>{finding.assessment_id}</Token>} />
      </TechnicalDetails>
    </div>
  );
}

function OperationalPatternDetail({
  finding,
}: {
  finding: OperationalPatternFinding;
}) {
  const evidence = Object.entries(finding.evidence ?? {});
  const population = Object.entries(finding.population ?? {});

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="section-label mb-1.5">Expected condition</div>
        <dl className="divide-y divide-border/70">
          <DataRow label="Pattern" value={finding.pattern_name} />
          <DataRow label="Method" value={finding.method} />
          <DataRow label="Capability" value={finding.capability} />
          {population.length > 0 ? (
            <DataRow
              label="Population"
              value={
                <span className="text-xs text-text-secondary">
                  {population
                    .map(
                      ([key, value]) =>
                        `${key.replace(/_/g, " ")}: ${String(value)}`,
                    )
                    .join(" · ")}
                </span>
              }
            />
          ) : null}
        </dl>
      </div>

      {evidence.length > 0 ? (
        <div>
          <div className="section-label mb-1.5">Observed condition</div>
          <EvidenceTable evidence={evidence} />
        </div>
      ) : (
        <p className="text-xs text-text-tertiary italic">
          No supporting source records were returned for this finding.
        </p>
      )}

      {finding.is_not_a_control_failure ? (
        <p className="rounded-[8px] border border-border bg-subtle px-3 py-2 text-xs leading-relaxed text-text-secondary">
          {finding.is_not_a_control_failure}
        </p>
      ) : null}

      <TechnicalDetails>
        <DataRow
          label="Pattern ID"
          value={<Token>{optionalText(finding.pattern_id)}</Token>}
        />
        <DataRow label="Assessment" value={<Token>{finding.assessment_id}</Token>} />
      </TechnicalDetails>
    </div>
  );
}

function AnomalyDetail({ finding }: { finding: UnifiedFinding }) {
  // An anomaly finding carries the detector's own prose. Both fields are
  // nullable: the finding record is built from the scope payload, so a scope the
  // detector gave no narrative for produces a finding with neither.
  const payload = finding.finding as unknown as AnomalyFinding;

  return (
    <div className="flex flex-col gap-3">
      <div className="section-label">Analytical basis</div>
      {payload.narrative ? (
        <p className="text-xs font-medium leading-relaxed text-text">
          {payload.narrative}
        </p>
      ) : (
        <p className="text-xs text-text-tertiary italic">
          The detector wrote no narrative for this scope.
        </p>
      )}

      {payload.explanation ? (
        <p className="text-xs leading-relaxed text-text-secondary">
          {payload.explanation}
        </p>
      ) : null}

      <dl className="divide-y divide-border/70">
        <DataRow
          label="Anomaly score"
          value={
            payload.anomaly_score === null ? (
              <span className="text-text-tertiary italic">Not produced</span>
            ) : (
              <span className="tabular">
                {formatNumber(payload.anomaly_score, 4)}
              </span>
            )
          }
        />
      </dl>

      {Array.isArray(payload.limitations) && payload.limitations.length > 0 ? (
        <ul className="list-inside list-disc space-y-0.5 micro leading-relaxed text-text-tertiary">
          {payload.limitations.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}

      <TechnicalDetails>
        <DataRow
          label="Model version"
          value={<Token>{optionalText(payload.model_version)}</Token>}
        />
        <DataRow
          label="Feature schema"
          value={<Token>{optionalText(payload.feature_schema_version)}</Token>}
        />
      </TechnicalDetails>
    </div>
  );
}

/**
 * Rule, pattern and model identifiers: secondary to the examiner's
 * questions, available on demand rather than as the headline.
 */
function TechnicalDetails({ children }: { children: ReactNode }) {
  return (
    <details className="rounded-[8px] border border-border bg-subtle/50 px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-text-secondary">
        Technical details
      </summary>
      <dl className="mt-1 divide-y divide-border/70">{children}</dl>
    </details>
  );
}

/** A two-column key/value table for a backend evidence object. */
function EvidenceTable({
  evidence,
}: {
  evidence: [string, unknown][];
}) {
  return (
    <div className="overflow-hidden rounded-[8px] border border-border">
      <table className="w-full text-xs">
        <tbody className="divide-y divide-border">
          {evidence.map(([key, value]) => (
            <tr key={key}>
              <th
                scope="row"
                className="w-[42%] bg-subtle px-2.5 py-1.5 text-left font-medium text-text-secondary"
              >
                {key}
              </th>
              <td className="px-2.5 py-1.5 text-text">
                {typeof value === "object" && value !== null ? (
                  <code className="font-mono micro">
                    {JSON.stringify(value)}
                  </code>
                ) : (
                  String(value)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
