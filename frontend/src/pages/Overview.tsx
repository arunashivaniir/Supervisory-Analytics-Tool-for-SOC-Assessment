import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import {
  anomalyModelStatus,
  anomalyVerdictCounts,
  countByFamily,
  datasetCapabilitySummary,
  familyFindingCount,
  scopeRows,
  unifiedFindings,
} from "../app/selectors";
import { Caveat, PageHeader, Section } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { DataTable, HeadCell, TableBody, TableCell, TableHead, TableRow, UnresolvedCell } from "../components/ui/DataTable";
import { EmptyState } from "../components/ui/Metric";
import { StatusBadge, NotAvailable } from "../components/ui/StatusBadge";
import {
  formatCount,
  entityLabel,
  entityResolved,
  periodLabel,
  periodResolved,
  verdictTotal,
} from "../lib/formatters";
import {
  SIGNAL_FAMILIES,
  capabilityStatus,
  humanise,
  signalStatus,
} from "../lib/status";
import { VerdictDistribution } from "../components/charts/VerdictDistribution";

/**
 * The supervisory picture.
 *
 * Four figures, one attention table, one distribution, one evidence posture.
 * Every number is a count of something the pipeline reported, and each one
 * says what it counts.
 */
export function OverviewPage() {
  const { result, analysisError, running, analysis } = useAnalysis();
  const navigate = useNavigate();

  const findings = useMemo(() => unifiedFindings(result), [result]);
  const rows = useMemo(() => scopeRows(result), [result]);
  const familyCounts = useMemo(() => countByFamily(findings), [findings]);
  const verdictCounts = useMemo(() => anomalyVerdictCounts(result), [result]);
  const capabilitySummary = useMemo(() => datasetCapabilitySummary(result), [result]);
  const modelStatus = anomalyModelStatus(result);

  const totalSignals = findings.length;

  if (!result) {
    return (
      <div className="py-10">
        <PageHeader title="Assessment Overview" />
        {analysisError ? (
          <Caveat tone="caution">{analysisError}</Caveat>
        ) : running ? (
          <Caveat>
            The assessment is still being produced. Nothing is displayed until
            the pipeline has finished, so this screen cannot show a partial
            analysis.
          </Caveat>
        ) : analysis ? (
          <Caveat tone="caution">
            The run finished without producing a result.
          </Caveat>
        ) : (
          <EmptyState
            title="No assessment loaded"
            description="Choose a dataset to produce an assessment."
          />
        )}
      </div>
    );
  }

  const recordCount = result.assessment.record_count;
  const scopeCount = result.assessment.scope_count;

  return (
    <>
      <PageHeader
        title="Assessment Overview"
        subject={result.dataset.split("/").pop()}
        meta={`${formatCount(recordCount)} records · ${formatCount(scopeCount)} assessment ${
          scopeCount === 1 ? "scope" : "scopes"
        }`}
      />

      <div className="grid grid-cols-4 gap-3">
        <Metric
          label="Records"
          value={formatCount(recordCount)}
          context="Records read by the ingestion layer"
        />
        <Metric
          label="Assessment scopes"
          value={formatCount(scopeCount)}
          context={
            result.assessment.entity_resolution.available &&
            result.assessment.period_resolution.available
              ? "Entity and period both resolved from the evidence"
              : "Scope model resolution is limited by the evidence"
          }
        />
        <Metric
          label="Supervisory signals"
          value={
            totalSignals === 0 ? (
              "0"
            ) : (
              formatCount(totalSignals)
            )
          }
          context={
            totalSignals === 0
              ? "The pipeline reported no findings in any of the four signal families"
              : "Findings reported across execution gap, negative space, operational pattern and anomaly"
          }
        />
        <Metric
          label="Model status"
          value={
            modelStatus ? (
              <StatusBadge
                tone={signalStatus(modelStatus.status).tone}
                label={signalStatus(modelStatus.status).label}
                raw={modelStatus.status}
              />
            ) : (
              <NotAvailable />
            )
          }
          context={
            modelStatus?.reason
              ? modelStatus.reason
              : "Isolation Forest availability, as reported by the anomaly layer"
          }
        />
      </div>

      <Section
        title="Supervisory attention"
        description="Assessment scopes in the order the pipeline produced them. Select a scope to review its signals and evidence."
      >
        <Card>
          {rows.length === 0 ? (
            <EmptyState
              title="No assessment scopes"
              description="The pipeline produced no assessment scopes for this dataset."
            />
          ) : (
            <DataTable>
              <TableHead>
              <HeadCell>Entity</HeadCell>
              <HeadCell>Period</HeadCell>
              <HeadCell align="right">Records</HeadCell>
              {SIGNAL_FAMILIES.map((family) => (
                <HeadCell key={family.id} align="right">
                  {family.singular}
                </HeadCell>
              ))}
              <HeadCell align="right">Review</HeadCell>
          </TableHead>
              <TableBody>
                {rows.map((row) => {
                  const scopeSignals = findings.filter(
                    (item) => item.assessment_id === row.assessment_id,
                  );
                  const perFamily = countByFamily(scopeSignals);

                  return (
                    <TableRow
                      key={row.assessment_id}
                      onClick={() =>
                        navigate(`/assessments/${encodeURIComponent(row.assessment_id)}`)
                      }
                    >
                      <TableCell>
                        {entityResolved(row.entity) ? (
                          entityLabel(row.entity)
                        ) : (
                          <UnresolvedCell reason={row.entity.unavailable_reason}>
                            Entity not identified
                          </UnresolvedCell>
                        )}
                      </TableCell>
                      <TableCell>
                        {periodResolved(row.period) ? (
                          periodLabel(row.period)
                        ) : (
                          <UnresolvedCell reason={row.period.unavailable_reason}>
                            Period not determined
                          </UnresolvedCell>
                        )}
                      </TableCell>
                      <TableCell align="right" className="tabular">
                        {formatCount(row.record_count)}
                      </TableCell>
                      {SIGNAL_FAMILIES.map((family) => (
                        <TableCell key={family.id} align="right">
                          <FamilyCount count={perFamily[family.id] ?? 0} />
                        </TableCell>
                      ))}
                      <TableCell align="right">
                        <span className="text-xs font-medium text-accent">
                          Review
                        </span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </DataTable>
          )}
        </Card>
      </Section>

      <div className="mt-7 grid grid-cols-2 gap-4">
        <Section
          title="Signal distribution"
          description="Findings reported by each signal family. The families are reported separately by the pipeline and are not combined into a single measure."
          className="mt-0"
        >
          <Card>
            <div className="px-4 py-3">
              <FamilyBreakdown
                result={result}
                familyCounts={familyCounts}
                total={totalSignals}
              />
            </div>
          </Card>
        </Section>

        <Section
          title="Anomaly verdicts"
          description="Verdicts the offline model reported across assessment scopes."
          className="mt-0"
        >
          <Card>
            <div className="px-4 py-3">
              {verdictTotal(verdictCounts) === 0 ? (
                <EmptyState
                  title="No verdict distribution"
                  description="The anomaly layer did not return a verdict count for this dataset."
                />
              ) : (
                <>
                  <VerdictDistribution counts={verdictCounts} />
                  <p className="mt-3 micro leading-relaxed text-text-tertiary">
                    A verdict describes distance from the reference population.
                    It is not a severity, and it does not by itself indicate a
                    control failure.
                  </p>
                </>
              )}
            </div>
          </Card>
        </Section>
      </div>

      <Section
        title="Evidence posture"
        description="Capability evidence availability across all assessment scopes, as summarised by the pipeline. These are evidence states, not risk ratings."
      >
        <Card>
          {capabilitySummary === null ? (
            <EmptyState
              title="No capability summary"
              description="The pipeline returned no capability assessment for this dataset."
            />
          ) : (
            <DataTable>
              <TableHead>
              <HeadCell>Capability</HeadCell>
              <HeadCell align="right">Available</HeadCell>
              <HeadCell align="right">Insufficient evidence</HeadCell>
              <HeadCell align="right">Not assessed</HeadCell>
          </TableHead>
              <TableBody>
                {capabilitySummary.capabilities.map((item) => (
                  <TableRow key={item.capability_id}>
                    <TableCell>
                      {capabilityName(result, item.capability_id)}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      <StatusCount
                        count={item.available_scopes}
                        status="AVAILABLE"
                      />
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      <StatusCount
                        count={item.insufficient_evidence_scopes}
                        status="INSUFFICIENT_EVIDENCE"
                      />
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      <StatusCount
                        count={item.not_assessed_scopes}
                        status="NOT_ASSESSED"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </DataTable>
          )}
        </Card>
        <Caveat className="mt-2.5">
          A capability with insufficient evidence has not been shown to be
          weak; the submitted data did not carry what the assessment needs. A
          capability that was not assessed was not judged at all.
        </Caveat>
      </Section>
    </>
  );
}

function Metric({
  label,
  value,
  context,
}: {
  label: string;
  value: React.ReactNode;
  context: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col justify-between rounded-[10px] border border-border bg-surface px-4 py-3">
      <span className="section-label">{label}</span>
      <div className="mt-2">
        <div className="text-2xl font-semibold leading-none tracking-[-0.01em] text-text">
          {value}
        </div>
        <p className="mt-1.5 micro leading-snug text-text-secondary">
          {context}
        </p>
      </div>
    </div>
  );
}


/**
 * A per-scope family count.
 *
 * Zero is shown as a muted `0`, not as a dash. The distinction matters: a
 * family that examined the scope and found nothing is not the same as a family
 * that could not examine it.
 */
function FamilyCount({ count }: { count: number }) {
  if (count === 0) {
    return <span className="tabular text-text-tertiary">0</span>;
  }

  return <span className="tabular font-medium text-text">{count}</span>;
}

function StatusCount({
  count,
  status,
}: {
  count: number;
  status: string;
}) {
  if (count === 0) {
    return <span className="text-text-tertiary">0</span>;
  }

  const presentation = capabilityStatus(status);

  return (
    <span
      className="font-medium"
      style={{ color: `var(--color-${presentation.tone === "positive" ? "positive" : presentation.tone === "caution" ? "caution" : "neutral-tone"})` }}
    >
      {count}
    </span>
  );
}

/** The pipeline's own name for a capability, falling back to its identifier. */
function capabilityName(
  result: NonNullable<ReturnType<typeof useAnalysis>["result"]>,
  capabilityId: string,
): string {
  for (const scope of result.capability_assessment.scopes) {
    const match = scope.capabilities.find(
      (item) => item.capability_id === capabilityId,
    );

    if (match) {
      return match.name;
    }
  }

  return humanise(capabilityId);
}

function FamilyBreakdown({
  result,
  familyCounts,
  total,
}: {
  result: NonNullable<ReturnType<typeof useAnalysis>["result"]>;
  familyCounts: Record<string, number>;
  total: number;
}) {
  return (
    <ul className="flex flex-col gap-2.5">
      {SIGNAL_FAMILIES.map((family) => {
        const reported = familyFindingCount(result, family.id);
        const count = familyCounts[family.id] ?? 0;

        return (
          <li key={family.id} className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[13px] text-text">{family.label}</div>
              <div className="mt-0.5 micro leading-snug text-text-tertiary">
                {family.description}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="tabular text-[13px] font-medium text-text">
                {count}
              </div>
              {reported !== null && reported !== count ? (
                <div
                  className="micro text-text-tertiary"
                  title="The pipeline's own finding_count for this family"
                >
                  of {formatCount(reported)}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
      <li className="flex items-center justify-between gap-4 border-t border-border pt-2.5">
        <span className="text-[13px] font-medium text-text">Total</span>
        <span className="tabular text-[13px] font-medium text-text">
          {total === 0 ? "0" : formatCount(total)}
        </span>
      </li>
    </ul>
  );
}
