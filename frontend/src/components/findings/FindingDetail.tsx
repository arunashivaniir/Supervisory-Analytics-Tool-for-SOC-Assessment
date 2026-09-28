import type { ReactNode } from "react";

import type { UnifiedFinding } from "../../app/selectors";
import { cn } from "../../lib/cn";
import { formatNumber, optionalText } from "../../lib/formatters";
import { BackendProse, ConceptList, DataRow, Token } from "../ui/DataDisplay";
import type {
  AnomalyFinding,
  ExecutionGapFinding,
  NegativeSpaceFinding,
  OperationalPatternFinding,
} from "../../types/pipeline";

/**
 * The complete finding, as the pipeline reported it.
 *
 * Each family has its own payload, so each is rendered from its own fields
 * rather than forced through a common shape. Nothing is summarised or
 * reworded: the reason, the evidence and the record reference are shown as the
 * backend wrote them.
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
      <IdentityRows finding={finding} />

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
    </div>
  );
}

function IdentityRows({ finding }: { finding: UnifiedFinding }) {
  const reference = finding.finding.record_reference;

  return (
    <dl className="divide-y divide-border/70">
      <DataRow
        label="Assessment"
        value={<Token>{finding.assessment_id}</Token>}
      />
      <DataRow
        label="Evidence concepts"
        value={<ConceptList concepts={finding.evidenceConcepts} collapsed={8} />}
      />
      {reference && Object.keys(reference).length > 0 ? (
        <DataRow
          label="Record reference"
          value={
            <span className="text-xs text-text-secondary">
              {Object.entries(reference)
                .filter(([, value]) => value !== null && value !== undefined)
                .map(([key, value]) => `${key}: ${String(value)}`)
                .join(" · ")}
            </span>
          }
        />
      ) : null}
    </dl>
  );
}

function ExecutionGapDetail({ finding }: { finding: ExecutionGapFinding }) {
  const evidence = Object.entries(finding.evidence ?? {});

  return (
    <div className="flex flex-col gap-3">
      <BackendProse>{finding.reason}</BackendProse>

      <div>
        <div className="section-label mb-1.5">Rule</div>
        <dl className="divide-y divide-border/70">
          <DataRow
            label="Rule"
            value={
              <span className="text-[13px]">
                {finding.rule_name}{" "}
                <span className="font-mono micro text-text-tertiary">
                  {finding.rule_id}
                </span>
              </span>
            }
          />
          <DataRow label="Capability" value={finding.capability} />
        </dl>
      </div>

      {evidence.length > 0 ? (
        <div>
          <div className="section-label mb-1.5">Submitted evidence</div>
          <EvidenceTable evidence={evidence} />
        </div>
      ) : null}
    </div>
  );
}

function NegativeSpaceDetail({ finding }: { finding: NegativeSpaceFinding }) {
  const summary = finding.evidence_summary ?? {};

  return (
    <div className="flex flex-col gap-3">
      <BackendProse>{finding.reason}</BackendProse>

      <div>
        <div className="section-label mb-1.5">Expectation</div>
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
        <div className="section-label mb-1.5">Evidence summary</div>
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
      <BackendProse>{finding.reason}</BackendProse>

      <div>
        <div className="section-label mb-1.5">Pattern</div>
        <dl className="divide-y divide-border/70">
          <DataRow
            label="Pattern"
            value={
              <span className="text-[13px]">
                {finding.pattern_name}{" "}
                <span className="font-mono micro text-text-tertiary">
                  {finding.pattern_id}
                </span>
              </span>
            }
          />
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
          <div className="section-label mb-1.5">Evidence</div>
          <EvidenceTable evidence={evidence} />
        </div>
      ) : null}

      {finding.is_not_a_control_failure ? (
        <p className="rounded-[8px] border border-border bg-subtle px-3 py-2 text-xs leading-relaxed text-text-secondary">
          {finding.is_not_a_control_failure}
        </p>
      ) : null}
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
      <BackendProse>{finding.reason}</BackendProse>

      {payload.narrative ? (
        <p className="text-xs font-medium leading-relaxed text-text">
          {payload.narrative}
        </p>
      ) : null}

      {payload.explanation ? (
        <p className="text-xs leading-relaxed text-text-secondary">
          {payload.explanation}
        </p>
      ) : null}

      <dl className="divide-y divide-border/70">
        <DataRow
          label="Model version"
          value={<Token>{optionalText(payload.model_version)}</Token>}
        />
        <DataRow
          label="Feature schema"
          value={<Token>{optionalText(payload.feature_schema_version)}</Token>}
        />
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
    </div>
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
