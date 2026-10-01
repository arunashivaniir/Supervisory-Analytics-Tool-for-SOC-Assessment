import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import { useAssessmentBuilder } from "../app/AssessmentBuilder";
import {
  anomalyModelStatus,
  anomalyVerdictCounts,
  attentionForScope,
  capabilityTallyForScope,
  countByFamily,
  datasetCapabilitySummary,
  eligibleCheckCounts,
  familyFindingCount,
  findingsForScope,
  periodOptions,
  reviewSamples,
  scopeRows,
  unifiedFindings,
} from "../app/selectors";
import { Caveat, PageHeader, Section } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
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
  integrityStatus,
  signalStatus,
} from "../lib/status";
import {
  entryForDataset,
  formatRunTime,
  shortHash,
  useEvidenceRegister,
} from "../services/evidenceRegister";
import type { EvidenceIntegrity } from "../types/evidence";
import type {
  AnalysisStatus,
  PipelineResult,
} from "../types/pipeline";
import { VerdictDistribution } from "../components/charts/VerdictDistribution";
import { SelectFilter, TextFilter } from "../components/ui/Filters";
import { ReviewBadge } from "../components/findings/ReviewControl";
import { useFindingReviews } from "../app/reviews";

/**
 * The supervisory picture.
 *
 * Four figures, one attention table, one distribution, one evidence posture.
 * Every number is a count of something the pipeline reported, and each one
 * says what it counts.
 */
export function OverviewPage() {
  const { result, analysisError, running, analysis } = useAnalysis();
  const { datasets: packageDatasets } = useAssessmentBuilder();
  const navigate = useNavigate();
  const { items: evidenceItems } = useEvidenceRegister();

  const [search, setSearch] = useState("");
  const [period, setPeriod] = useState("all");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [sortKey, setSortKey] = useState<"signals" | "records" | "indicator" | "entity">("signals");
  const [expanded, setExpanded] = useState<string | null>(null);

  const { reviews } = useFindingReviews(analysis?.job_id ?? null);

  const findings = useMemo(() => unifiedFindings(result), [result]);
  const rows = useMemo(() => scopeRows(result), [result]);
  const familyCounts = useMemo(() => countByFamily(findings), [findings]);
  const verdictCounts = useMemo(() => anomalyVerdictCounts(result), [result]);
  const capabilitySummary = useMemo(() => datasetCapabilitySummary(result), [result]);
  const modelStatus = anomalyModelStatus(result);

  const totalSignals = findings.length;

  // Deterministic triage order: most signals first, then most records, then
  // the pipeline's own identifier. No score is computed; the order is a sort
  // over counts the pipeline reported.
  const attention = useMemo(
    () =>
      rows
        .map((row) => {
          const scopeSignals = findingsForScope(findings, row.assessment_id);
          return {
            row,
            signals: scopeSignals.length,
            perFamily: countByFamily(scopeSignals),
            attention: result ? attentionForScope(result, row) : null,
          };
        })
        .sort((a, b) =>
          b.signals !== a.signals
            ? b.signals - a.signals
            : b.row.record_count !== a.row.record_count
              ? b.row.record_count - a.row.record_count
              : a.row.assessment_id.localeCompare(b.row.assessment_id),
        ),
    [rows, findings, result],
  );

  const periods = useMemo(() => periodOptions(rows), [rows]);
  const samples = useMemo(() => reviewSamples(findings), [findings]);
  const checkCounts = useMemo(() => eligibleCheckCounts(result), [result]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();

    const filtered = attention.filter(({ row, signals }) => {
      if (attentionOnly && signals === 0) {
        return false;
      }

      if (period !== "all") {
        const label = periodResolved(row.period)
          ? periodLabel(row.period)
          : "Period not determined";

        if (label !== period) {
          return false;
        }
      }

      if (needle) {
        const entityText = entityResolved(row.entity)
          ? entityLabel(row.entity).toLowerCase()
          : "";
        const idText = row.assessment_id.toLowerCase();

        if (!entityText.includes(needle) && !idText.includes(needle)) {
          return false;
        }
      }

      return true;
    });

    const by = {
      signals: (a: (typeof attention)[number], b: (typeof attention)[number]) =>
        b.signals - a.signals ||
        b.row.record_count - a.row.record_count ||
        a.row.assessment_id.localeCompare(b.row.assessment_id),
      records: (a: (typeof attention)[number], b: (typeof attention)[number]) =>
        b.row.record_count - a.row.record_count ||
        b.signals - a.signals ||
        a.row.assessment_id.localeCompare(b.row.assessment_id),
      indicator: (a: (typeof attention)[number], b: (typeof attention)[number]) =>
        (b.attention?.score ?? -1) - (a.attention?.score ?? -1) ||
        b.signals - a.signals ||
        a.row.assessment_id.localeCompare(b.row.assessment_id),
      entity: (a: (typeof attention)[number], b: (typeof attention)[number]) => {
        const aLabel = entityResolved(a.row.entity) ? entityLabel(a.row.entity) : "";
        const bLabel = entityResolved(b.row.entity) ? entityLabel(b.row.entity) : "";
        return (
          aLabel.localeCompare(bLabel) ||
          a.row.assessment_id.localeCompare(b.row.assessment_id)
        );
      },
    };

    return [...filtered].sort(by[sortKey]);
  }, [attention, search, period, attentionOnly, sortKey]);

  const evidenceEntry = result
    ? entryForDataset(evidenceItems, result.dataset)
    : null;

  if (!result) {
    // A wizard package is not nothing: the examiner started an assessment
    // and has data selected. Say so, and send them back to the wizard —
    // never pretend the package does not exist.
    if (packageDatasets.length > 0 && !analysis && !running) {
      const names = packageDatasets
        .map((path) => path.split("/").pop() ?? path)
        .join(", ");

      return (
        <div className="py-10">
          <PageHeader title="Assessment Overview" />
          <Card>
            <EmptyState
              title="Assessment package ready for review"
              description={`${packageDatasets.length === 1 ? "1 dataset selected" : `${packageDatasets.length} datasets selected`} (${names}). Review roles, mapping and validation before running the supervisory analysis.`}
              action={
                <Button
                  variant="primary"
                  onClick={() => navigate("/assessments/new")}
                >
                  Continue in New Assessment
                </Button>
              }
            />
          </Card>
          <Caveat className="mt-2.5">
            No analysis has run yet, so there are no results to show. Each
            dataset is assessed independently — nothing is merged.
          </Caveat>
        </div>
      );
    }

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
            description="Start a New Assessment to select operational data, review what SAT-SA understood, and run the supervisory analysis."
            action={
              <Button
                variant="primary"
                onClick={() => navigate("/assessments/new")}
              >
                Start a New Assessment
              </Button>
            }
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

      <RunStrip
        status={analysis?.status ?? null}
        lastRun={analysis?.finished_at ?? analysis?.started_at ?? null}
        hash={evidenceItems === null ? null : (evidenceEntry?.registered_sha256 ?? null)}
        hashKnown={evidenceItems !== null}
        integrity={evidenceEntry?.overall_status ?? null}
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
        title="Entity attention"
        description="Assessment scopes with their supervisory indicator, signal counts and evidence state. Sector is not carried by the submitted evidence, so sector filtering is unavailable rather than guessed."
        action={
          <button
            type="button"
            onClick={() => {
              setAttentionOnly(true);
              document
                .getElementById("entity-attention-table")
                ?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className="rounded-[8px] bg-primary px-3 py-1.5 text-xs font-semibold text-white transition-opacity duration-100 hover:opacity-90"
          >
            Show entities requiring attention
          </button>
        }
      >
        {totalSignals === 0 ? (
          <AssessmentEmptyState
            recordCount={recordCount}
            mappedColumns={result.mapping_report.mapped_columns}
            checkCounts={checkCounts}
            capabilitySummary={capabilitySummary}
          />
        ) : null}
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <TextFilter
            label="Search"
            value={search}
            onChange={setSearch}
            placeholder="Entity or scope id"
            className="w-[240px]"
          />
          <SelectFilter
            label="Period"
            value={period}
            onChange={setPeriod}
            className="w-[220px]"
            options={[
              { value: "all", label: "All periods" },
              ...periods.map((label) => ({ value: label, label })),
            ]}
          />
          <label className="flex cursor-pointer items-center gap-2 pb-1.5 text-[13px] text-text-secondary">
            <input
              type="checkbox"
              checked={attentionOnly}
              onChange={(event) => setAttentionOnly(event.target.checked)}
              className="size-3.5 accent-[#0f766e]"
            />
            Requiring attention only
          </label>
          <div className="ml-auto text-xs text-text-tertiary">
            {visible.length} of {attention.length} shown
          </div>
        </div>
        <Card>
          <div id="entity-attention-table">
          {visible.length === 0 ? (
            <EmptyState
              title={attention.length === 0 ? "No assessment scopes" : "No scopes match these filters"}
              description={
                attention.length === 0
                  ? "The pipeline produced no assessment scopes for this dataset."
                  : "Adjust or clear the filters to see the remaining scopes."
              }
            />
          ) : (
            <DataTable>
              <TableHead>
              <HeadCell align="right">#</HeadCell>
              <SortHead label="Entity" active={sortKey === "entity"} onSort={() => setSortKey("entity")} />
              <HeadCell>Sector</HeadCell>
              <SortHead label="Indicator" active={sortKey === "indicator"} onSort={() => setSortKey("indicator")} />
              <HeadCell>Attention</HeadCell>
              <SortHead label="Records" align="right" active={sortKey === "records"} onSort={() => setSortKey("records")} />
              <SortHead label="Signals" align="right" active={sortKey === "signals"} onSort={() => setSortKey("signals")} />
              <HeadCell>Primary signal</HeadCell>
              <HeadCell>Evidence</HeadCell>
              <HeadCell align="right">Action</HeadCell>
          </TableHead>
              <TableBody>
                {visible.map(({ row, signals, perFamily, attention: scopeAttention }, index) => (
                    <TableRow
                      key={row.assessment_id}
                      onClick={() =>
                        navigate(`/assessments/${encodeURIComponent(row.assessment_id)}`)
                      }
                    >
                      <TableCell align="right" className="tabular text-text-tertiary">
                        {index + 1}
                      </TableCell>
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
                        <span className="text-text-tertiary italic">
                          Not available in submission
                        </span>
                      </TableCell>
                      <TableCell>
                        <IndicatorCell
                          attention={scopeAttention}
                          scopeId={row.assessment_id}
                          perFamily={perFamily}
                          expanded={expanded === row.assessment_id}
                          onToggle={() =>
                            setExpanded((current) =>
                              current === row.assessment_id ? null : row.assessment_id,
                            )
                          }
                        />
                      </TableCell>
                      <TableCell>
                        {signals > 0 ? (
                          <span className="text-xs font-medium text-critical">
                            Requires attention
                          </span>
                        ) : (
                          <span className="text-xs text-text-tertiary italic">
                            No signal identified
                          </span>
                        )}
                      </TableCell>
                      <TableCell align="right" className="tabular">
                        {formatCount(row.record_count)}
                      </TableCell>
                      <TableCell align="right">
                        <FamilyCount count={signals} />
                      </TableCell>
                      <TableCell>
                        <PrimarySignal perFamily={perFamily} />
                      </TableCell>
                      <TableCell>
                        <ScopeEvidence result={result} assessmentId={row.assessment_id} />
                      </TableCell>
                      <TableCell align="right">
                        <span className="text-xs font-medium text-accent">
                          Review
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </DataTable>
          )}
          </div>
        </Card>
        <Caveat className="mt-2.5">
          The indicator is the backend attention score, a triage aid — not a
          verdict. Expand it to see its components. A scope with no signals
          has not been shown to be effective.
        </Caveat>
      </Section>

      <Section
        title="Prioritised review"
        description="The alert and case records to inspect first, ordered by transparent rules: record references first, execution gaps and negative space before other families, converging signals next. Provisional ranking until the analytical queue engine lands in a later phase."
      >
        <Card>
          {samples.length === 0 ? (
            <EmptyState
              title="No review samples"
              description="The pipeline reported no findings to sample for this dataset."
            />
          ) : (
            <DataTable>
              <TableHead>
                <HeadCell align="right">Rank</HeadCell>
                <HeadCell>Alert / Case</HeadCell>
                <HeadCell>Entity</HeadCell>
                <HeadCell>Signal</HeadCell>
                <HeadCell>Why flagged</HeadCell>
                <HeadCell>Evidence</HeadCell>
                <HeadCell>Review</HeadCell>
              </TableHead>
              <TableBody>
                {samples.map((sample) => (
                  <TableRow
                    key={sample.finding.key}
                    onClick={() =>
                      navigate(
                        `/findings?finding=${encodeURIComponent(sample.finding.key)}`,
                      )
                    }
                  >
                    <TableCell align="right" className="tabular text-text-tertiary">
                      {sample.rank}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {sample.recordLabel ?? (
                        <span className="text-text-tertiary italic">
                          No record reference
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {entityResolved(sample.finding.entity) ? (
                        entityLabel(sample.finding.entity)
                      ) : (
                        <span className="text-text-tertiary italic">
                          Not identified
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-text-secondary">
                      {sample.finding.familyLabel}
                    </TableCell>
                    <TableCell className="max-w-[420px]">
                      <span className="line-clamp-2 text-xs leading-relaxed text-text-secondary">
                        {sample.why}
                      </span>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-text-secondary">
                      {sample.finding.evidenceConcepts.length > 0 ? (
                        `${sample.finding.evidenceConcepts.length} concept${sample.finding.evidenceConcepts.length === 1 ? "" : "s"}`
                      ) : (
                        <span className="text-text-tertiary italic">None recorded</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <ReviewBadge review={reviews[sample.finding.key] ?? null} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </DataTable>
          )}
        </Card>
      </Section>

      <div className="mt-7 grid grid-cols-2 gap-4">
        <Section
          title="Signal summary"
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
        title="Evidence status"
        description="Integrity of the submission, and capability evidence availability across all assessment scopes. These are evidence states, not risk ratings."
      >
        <EvidenceIntegrityStrip items={evidenceItems} />
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

/**
 * What was analysed, and whether the submission verified.
 *
 * One strip answering "what data am I looking at": the run state, when it
 * finished, the short digest of the registered submission when the dataset
 * matches one, and the integrity state the trust layer reported. Nothing
 * here is inferred: an unmatched dataset reads as not registered.
 */function RunStrip({
  status,
  lastRun,
  hash,
  hashKnown,
  integrity,
}: {
  status: AnalysisStatus | null;
  lastRun: string | null;
  hash: string | null;
  hashKnown: boolean;
  integrity: string | null;
}) {
  const statusLabel =
    status === "complete"
      ? "Analysis complete"
      : status === "processing"
        ? "Processing"
        : status === "error"
          ? "Error"
          : "No analysis";

  return (
    <dl className="mb-5 grid grid-cols-2 gap-3 rounded-[10px] border border-border bg-surface px-4 py-3 sm:grid-cols-4">
      <div className="min-w-0">
        <dt className="section-label">Analysis status</dt>
        <dd className="mt-1 text-[13px] font-medium text-text">{statusLabel}</dd>
      </div>
      <div className="min-w-0">
        <dt className="section-label">Last run</dt>
        <dd className="mt-1 text-[13px] text-text">
          {lastRun ? formatRunTime(lastRun) : "Not recorded"}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="section-label">Data hash</dt>
        <dd
          className="mt-1 font-mono text-[13px] text-text"
          title={hash ?? undefined}
        >
          {hashKnown ? shortHash(hash) : "Reading register…"}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="section-label">Evidence integrity</dt>
        <dd className="mt-1 text-[13px] text-text">
          {integrity ? (
            <StatusBadge
              tone={integrityStatus(integrity).tone}
              label={integrityStatus(integrity).label}
              raw={integrity}
              showDot={false}
            />
          ) : (
            <NotAvailable />
          )}
        </dd>
      </div>
    </dl>
  );
}

/**
 * The family with the most findings for a scope, ties broken by the
 * pipeline's own family order so the answer is stable. Zero findings is
 * stated as such, never translated into a judgement about the entity.
 */
function PrimarySignal({ perFamily }: { perFamily: Record<string, number> }) {
  let best: (typeof SIGNAL_FAMILIES)[number] | null = null;
  let bestCount = 0;

  for (const family of SIGNAL_FAMILIES) {
    const count = perFamily[family.id] ?? 0;

    if (count > bestCount) {
      best = family;
      bestCount = count;
    }
  }

  if (!best) {
    return (
      <span className="text-xs text-text-tertiary italic">
        No supervisory signal identified in available evidence
      </span>
    );
  }

  return (
    <span className="text-xs text-text">
      {best.singular}{" "}
      <span className="tabular text-text-tertiary">· {bestCount}</span>
    </span>
  );
}

/**
 * Evidence availability for one scope, from the capability tally.
 *
 * "Available" means at least one capability has available evidence;
 * "Partial" means none is available but some left insufficient evidence;
 * anything else is reported as not reported rather than as unavailable,
 * because a scope the capability layer did not assess has no evidence
 * state to show.
 */
function ScopeEvidence({
  result,
  assessmentId,
}: {
  result: PipelineResult;
  assessmentId: string;
}) {
  const tally = capabilityTallyForScope(result, assessmentId);
  const available =
    tally.find((entry) => entry.status === "AVAILABLE")?.count ?? 0;
  const insufficient =
    tally.find((entry) => entry.status === "INSUFFICIENT_EVIDENCE")?.count ??
    0;

  if (tally.length === 0) {
    return (
      <span className="text-xs text-text-tertiary italic">Not reported</span>
    );
  }

  if (available > 0) {
    return <span className="text-xs text-positive">Available</span>;
  }

  if (insufficient > 0) {
    return <span className="text-xs text-caution">Partial</span>;
  }

  return (
    <span className="text-xs text-text-tertiary italic">Not reported</span>
  );
}

/**
 * Submission integrity across the register: verified, digest mismatch,
 * and blocked from analysis. Rendered only once the register has answered;
 * while it loads the capability table below still stands on its own.
 */
function EvidenceIntegrityStrip({
  items,
}: {
  items: EvidenceIntegrity[] | null;
}) {
  if (items === null) {
    return null;
  }

  const verified = items.filter(
    (item) => item.overall_status === "VERIFIED",
  ).length;
  const mismatch = items.filter(
    (item) => item.overall_status === "INTEGRITY_FAILED",
  ).length;
  const blocked = items.filter((item) => !item.analysis.permitted).length;

  return (
    <div className="mb-3 flex flex-wrap gap-2">
      <span className="inline-flex items-center gap-1.5 rounded-[6px] border border-border bg-surface px-2 py-1 text-xs">
        <span className="text-text-tertiary">Verified</span>
        <span className="tabular font-medium text-text">{verified}</span>
      </span>
      <span className="inline-flex items-center gap-1.5 rounded-[6px] border border-border bg-surface px-2 py-1 text-xs">
        <span className="text-text-tertiary">Digest mismatch</span>
        <span className="tabular font-medium text-text">{mismatch}</span>
      </span>
      <span className="inline-flex items-center gap-1.5 rounded-[6px] border border-border bg-surface px-2 py-1 text-xs">
        <span className="text-text-tertiary">Blocked from analysis</span>
        <span className="tabular font-medium text-text">{blocked}</span>
      </span>
    </div>
  );
}

function SortHead({
  label,
  active,
  onSort,
  align = "left",
}: {
  label: string;
  active: boolean;
  onSort: () => void;
  align?: "left" | "right";
}) {
  return (
    <HeadCell align={align}>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onSort();
        }}
        title={`Sort by ${label}`}
        className={`underline-offset-2 hover:underline ${active ? "font-semibold text-text" : ""}`}
      >
        {label}
        {active ? " ↓" : ""}
      </button>
    </HeadCell>
  );
}

/**
 * The backend attention score with its decomposition, one click away.
 *
 * The score is a triage aid: severity-weighted by the legacy scorer,
 * shown beside the per-family signal counts it does not include, so
 * the examiner sees what it is made of before trusting it. Null means
 * no entry named this scope — stated, never zero-filled.
 */
function IndicatorCell({
  attention,
  scopeId,
  perFamily,
  expanded,
  onToggle,
}: {
  attention: { score: number; level: string; indicators: string[] } | null;
  scopeId: string;
  perFamily: Record<string, number>;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (!attention) {
    return (
      <span className="text-xs text-text-tertiary italic">Not reported</span>
    );
  }

  const tone =
    attention.level === "HIGH"
      ? "critical"
      : attention.level === "MEDIUM"
        ? "caution"
        : "neutral";

  return (
    <span className="block min-w-0">
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onToggle();
        }}
        aria-expanded={expanded}
        title="Show indicator components"
        className="flex items-center gap-1.5"
      >
        <span className="tabular text-[13px] font-semibold text-text">
          {attention.score}
        </span>
        <StatusBadge tone={tone} label={attention.level} showDot={false} />
      </button>
      {expanded ? (
        <span className="mt-1 block rounded-[6px] border border-border bg-subtle px-2 py-1.5">
          <span className="micro text-text-tertiary">
            Scope {scopeId} · per-family signals:{" "}
            {SIGNAL_FAMILIES.map(
              (family) => `${family.singular} ${perFamily[family.id] ?? 0}`,
            ).join(" · ")}
          </span>
          {attention.indicators.length > 0 ? (
            <span className="mt-1 block micro text-text-secondary">
              Risk indicators: {attention.indicators.join("; ")}
            </span>
          ) : (
            <span className="mt-1 block micro text-text-tertiary italic">
              No risk indicators reported for this scope.
            </span>
          )}
        </span>
      ) : null}
    </span>
  );
}

/**
 * An evidence-based empty state: what ran, what resolved, what that
 * produced. Shown when scopes exist but no findings do — the pipeline
 * working and finding nothing is information, not an error.
 */
function AssessmentEmptyState({
  recordCount,
  mappedColumns,
  checkCounts,
  capabilitySummary,
}: {
  recordCount: number;
  mappedColumns: number;
  checkCounts: Record<string, number>;
  capabilitySummary: {
    capabilities: Array<{
      available_scopes: number;
      insufficient_evidence_scopes: number;
      not_assessed_scopes: number;
    }>;
  } | null;
}) {
  const available = capabilitySummary
    ? capabilitySummary.capabilities.reduce(
        (total, item) => total + item.available_scopes,
        0,
      )
    : null;

  return (
    <Card className="mb-3">
      <div className="px-4 py-3">
        <p className="text-[13px] font-medium text-text">
          No qualifying supervisory findings identified in the submitted
          period.
        </p>
        <dl className="mt-2 grid grid-cols-2 gap-x-8 sm:grid-cols-3">
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Records analysed</dt>
            <dd className="tabular text-xs text-text">{formatCount(recordCount)}</dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Concepts resolved</dt>
            <dd className="tabular text-xs text-text">{formatCount(mappedColumns)}</dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Execution-gap checks</dt>
            <dd className="tabular text-xs text-text">{formatCount(checkCounts.execution_gap ?? 0)}</dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Negative-space checks</dt>
            <dd className="tabular text-xs text-text">{formatCount(checkCounts.negative_space ?? 0)}</dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Pattern checks</dt>
            <dd className="tabular text-xs text-text">{formatCount(checkCounts.operational_pattern ?? 0)}</dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Findings generated</dt>
            <dd className="tabular text-xs text-text">0</dd>
          </div>
        </dl>
        <p className="mt-2 text-xs leading-relaxed text-text-secondary">
          {available === null
            ? "No capability summary was reported for this dataset."
            : `${available} capability-scope assessment${available === 1 ? " was" : "s were"} evidence-available; the remainder were insufficient or not assessed.`}{" "}
          Absence of findings is not proof of security.
        </p>
      </div>
    </Card>
  );
}
