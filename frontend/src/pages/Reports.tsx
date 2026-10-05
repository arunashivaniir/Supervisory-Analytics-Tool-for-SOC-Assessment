import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import { useDashboard } from "../app/DashboardContext";
import {
  anomalyModelStatus,
  anomalyVerdictCounts,
  benchmarkScope,
  capabilityScopes,
  scopeRows,
} from "../app/selectors";
import { PageHeader } from "../components/layout/PageHeader";
import { Button } from "../components/ui/Button";
import {
  DataRow,
  Frame,
  Note,
  Section,
} from "../components/ui/Surface";
import {
  HeadCell,
  HeadRow,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableScroller,
} from "../components/ui/Table";
import {
  EmptyState,
  LimitationNote,
  LoadingRows,
  LoadingState,
  StatusBadge,
} from "../components/ui/State";
import { fetchAnalysisList, exportUrl, fullExportUrl } from "../services/api";
import { datasetName, formatCount, optionalText } from "../lib/formatters";
import {
  SIGNAL_FAMILIES,
  anomalyVerdict,
  capabilityStatus,
} from "../lib/status";
import type { AnalysisState } from "../types/pipeline";

/**
 * The record of what was assessed and what came out.
 *
 * A document view, not a judgement. Every count on this page is a count the
 * pipeline reported, and every sentence is either the backend's own text or a
 * statement about what the record contains. There is no overall score, no grade
 * and no verdict, because the pipeline does not produce one and a report implying
 * otherwise would misrepresent the assessment.
 *
 * Deliberately no charts. A chart on this page would have to choose an axis and a
 * scale, and every choice of that kind on a formal record is an argument the
 * backend did not make. The counts are the record; they are printed as counts.
 */
export function ReportsPage() {
  const { analysis, result, running, analysisError } = useAnalysis();
  const { view } = useDashboard();

  if (!result || !analysis) {
    return (
      <>
        <PageHeader title="Reports" />

        {analysisError ? (
          <Note tone="caution">{analysisError}</Note>
        ) : running ? (
          <LoadingState
            title="Assessment in progress"
            detail="The record is written once the pipeline completes."
          />
        ) : (
          <EmptyState
            title="No assessment loaded"
            description="Choose a dataset to produce an assessment."
          />
        )}
      </>
    );
  }

  const rows = scopeRows(result);
  const scopes = capabilityScopes(result);
  const counts = anomalyVerdictCounts(result);
  const modelStatus = anomalyModelStatus(result);
  const limitations = view.limitations;

  return (
    <>
      <PageHeader
        title="Reports"
        supporting={
          <>
            {datasetName(result.dataset)} ·{" "}
            {formatCount(result.ingestion.record_count)} records assessed · run{" "}
            <span className="font-mono text-[12px]">
              {analysis.job_id.slice(0, 8)}
            </span>
            . A printable record of the assessment: what was assessed, the
            evidence states reached, the signals reported, and the limitations
            that apply to all of it.
          </>
        }
        actions={
          <>
            <a href={exportUrl(analysis.job_id)} download>
              <Button variant="secondary" size="sm">
                Export JSON
              </Button>
            </a>
            <Button variant="primary" size="sm" onClick={() => window.print()}>
              Print or save as PDF
            </Button>
          </>
        }
      />

      <div className="mb-5">
        <Note>
          This page reproduces the assessment record. It does not grade, score or
          rank the assessed organisation, and it does not combine the counts below
          into a single measure. A low finding count is not a good result: it can
          also mean the evidence was insufficient to report anything.
        </Note>
      </div>

      <Section
        title="The record"
        description="What was read, and the state the run finished in."
      >
        <Frame>
          <div className="grid grid-cols-1 gap-x-8 px-4 py-3 md:grid-cols-2">
            <div className="min-w-0">
              <DataRow
                label="Dataset"
                value={<Mono>{optionalText(result.ingestion.source)}</Mono>}
              />
              <DataRow
                label="Read as"
                value={optionalText(result.ingestion.source_type)}
              />
              <DataRow
                label="Records"
                value={
                  <span className="tabular">
                    {formatCount(result.ingestion.record_count)}
                  </span>
                }
              />
              <DataRow
                label="Columns"
                value={
                  <span className="tabular">
                    {formatCount(result.ingestion.column_count)}
                  </span>
                }
              />
            </div>

            <div className="min-w-0">
              <DataRow
                label="Assessment scopes"
                value={<span className="tabular">{formatCount(rows.length)}</span>}
              />
              <DataRow
                label="Signals reported"
                value={
                  <span className="tabular">{formatCount(view.findings.total)}</span>
                }
              />
              <DataRow
                label="Anomaly model"
                value={
                  modelStatus ? (
                    <StatusBadge
                      tone={capabilityStatus(modelStatus.status).tone}
                      label={capabilityStatus(modelStatus.status).label}
                      raw={modelStatus.status}
                    />
                  ) : (
                    optionalText(null)
                  )
                }
              />
              <DataRow label="Run" value={<Mono>{analysis.job_id}</Mono>} />
            </div>
          </div>
        </Frame>
      </Section>

      <Section
        title="Signal families"
        description="Counts as the pipeline reported them, by family. The families are independent and are not summed into a total judgement."
      >
        <Frame>
          <TableScroller>
            <TableHead>
              <HeadRow>
                <HeadCell width="22%">Family</HeadCell>
                <HeadCell width="9%" align="right">
                  Reported
                </HeadCell>
                <HeadCell>What it measures</HeadCell>
              </HeadRow>
            </TableHead>

            <TableBody>
              {SIGNAL_FAMILIES.map((family) => {
                const published = view.findings.families.find(
                  (entry) => entry.id === family.id,
                );

                return (
                  <TableRow key={family.id}>
                    <TableCell className="font-medium">{family.label}</TableCell>
                    <TableCell align="right" className="tabular">
                      {published?.count === null || published === undefined ? (
                        <span className="text-text-tertiary italic">
                          Not reported
                        </span>
                      ) : (
                        formatCount(published.count)
                      )}
                    </TableCell>
                    <TableCell className="text-[13px] text-text-secondary">
                      {family.description}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </TableScroller>
        </Frame>
      </Section>

      <Section
        title="Evidence states"
        description="Capability states across the assessed scopes, as the pipeline counted them."
      >
        <Frame>
          <TableScroller>
            <TableHead>
              <HeadRow>
                <HeadCell>Capability</HeadCell>
                <HeadCell align="right">Available</HeadCell>
                <HeadCell align="right">Insufficient evidence</HeadCell>
                <HeadCell align="right">Not assessed</HeadCell>
              </HeadRow>
            </TableHead>

            <TableBody>
              {result.capability_assessment.summary.capabilities.map((item) => (
                <TableRow key={item.capability_id}>
                  <TableCell>{item.capability_id}</TableCell>
                  <TableCell align="right" className="tabular">
                    {formatCount(item.available_scopes)}
                  </TableCell>
                  <TableCell align="right" className="tabular">
                    {formatCount(item.insufficient_evidence_scopes)}
                  </TableCell>
                  <TableCell align="right" className="tabular">
                    {formatCount(item.not_assessed_scopes)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </TableScroller>
        </Frame>
      </Section>

      <Section
        title="Anomaly verdicts"
        description="Recorded, not interpreted. A verdict is a distance from a reference population, not a severity."
      >
        <Frame>
          <TableScroller>
            <TableHead>
              <HeadRow>
                <HeadCell>Verdict</HeadCell>
                <HeadCell align="right">Scopes</HeadCell>
              </HeadRow>
            </TableHead>

            <TableBody>
              {Object.entries(counts).map(([verdict, count]) => {
                const presentation = anomalyVerdict(verdict);

                return (
                  <TableRow key={verdict}>
                    <TableCell>
                      <StatusBadge
                        tone={presentation.tone}
                        label={presentation.label}
                        raw={verdict}
                      />
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatCount(count)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </TableScroller>
        </Frame>
      </Section>

      <Section
        title="Assessed scopes"
        description="Each scope the record covers, with the evidence states and signals attached to it."
      >
        <Frame>
          <TableScroller>
            <TableHead>
              <HeadRow>
                <HeadCell>Scope</HeadCell>
                <HeadCell align="right">Records</HeadCell>
                <HeadCell>Evidence states</HeadCell>
                <HeadCell align="right">Signals</HeadCell>
                <HeadCell>Peer cohort</HeadCell>
              </HeadRow>
            </TableHead>

            <TableBody>
              {rows.map((row) => {
                const scope = scopes.find(
                  (item) => item.assessment_id === row.assessment_id,
                );
                const entity = view.entities.find(
                  (item) => item.assessmentId === row.assessment_id,
                );

                return (
                  <TableRow key={row.assessment_id}>
                    <TableCell>
                      <Link
                        to={`/assessments/${encodeURIComponent(row.assessment_id)}`}
                        className="text-accent underline-offset-2 hover:underline"
                      >
                        {entity?.resolved
                          ? (entity.entity.name ?? entity.entity.id)
                          : "Scope with an unidentified entity"}
                      </Link>
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatCount(row.record_count)}
                    </TableCell>
                    <TableCell className="text-xs text-text-secondary">
                      {scope
                        ? `${scope.status_counts.AVAILABLE ?? 0} available, ${
                            scope.status_counts.INSUFFICIENT_EVIDENCE ?? 0
                          } insufficient, ${
                            scope.status_counts.NOT_ASSESSED ?? 0
                          } not assessed`
                        : optionalText(null)}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatCount(entity?.signals ?? 0)}
                    </TableCell>
                    <TableCell className="text-xs text-text-secondary">
                      <ReportCohort assessmentId={row.assessment_id} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </TableScroller>
        </Frame>
      </Section>

      {limitations.length > 0 ? (
        <Section
          title="Limitations"
          description="The constraints the backend states for this assessment as a whole."
        >
          <ul className="min-w-0 space-y-1.5">
            {limitations.map((line) => (
              <li key={line}>
                <LimitationNote>{line}</LimitationNote>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section
        title="Runs on this machine"
        description="Analyses produced locally. Exports carry the run identifier, so a printed record can be matched back to the analysis that produced it."
      >
        <SavedRuns currentJobId={analysis.job_id} />
      </Section>
    </>
  );
}

/** A value the backend supplied verbatim, in the typeface it supplied it in. */
function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12px]">{children}</span>;
}

/**
 * The cohort a scope was compared with, as the record states it.
 *
 * A record that printed only the findings would leave a reader to assume the
 * comparisons were drawn against the entity's own sector, so the cohort and its
 * size travel with the scope. A scope with no cohort says so with the backend's
 * reason instead of being left blank.
 */
function ReportCohort({ assessmentId }: { assessmentId: string }) {
  const { result } = useAnalysis();
  const cohort = benchmarkScope(result, assessmentId)?.cohort ?? null;

  if (!cohort) {
    return <span className="italic text-text-tertiary">Not reported</span>;
  }

  if (cohort.cohort_id === null) {
    return (
      <span className="italic text-text-tertiary">
        {cohort.not_available_reason ?? "No cohort"}
      </span>
    );
  }

  return (
    <span>
      {cohort.label} · {cohort.peer_count} peer
      {cohort.peer_count === 1 ? "" : "s"}
    </span>
  );
}

/** The run history the adapter retains, exactly as it reports it. */
function SavedRuns({ currentJobId }: { currentJobId: string }) {
  const [runs, setRuns] = useState<AnalysisState[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    fetchAnalysisList()
      .then((body) => {
        if (active) {
          setRuns(body);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      });

    return () => {
      active = false;
    };
  }, [currentJobId]);

  if (error) {
    return <Note tone="caution">The run listing could not be read: {error}</Note>;
  }

  if (runs === null) {
    return <LoadingRows />;
  }

  if (runs.length === 0) {
    return (
      <EmptyState
        title="No runs recorded"
        description="Analyses produced on this machine will be listed here."
      />
    );
  }

  return (
    <Frame>
      <TableScroller>
        <TableHead>
          <HeadRow>
            <HeadCell width="16%">Run</HeadCell>
            <HeadCell>Dataset</HeadCell>
            <HeadCell width="14%">State</HeadCell>
            <HeadCell width="16%">Exports</HeadCell>
          </HeadRow>
        </TableHead>

        <TableBody>
          {[...runs].reverse().map((item) => (
            <TableRow key={item.job_id}>
              <TableCell>
                <Mono>
                  {item.job_id.slice(0, 8)}
                  {item.job_id === currentJobId ? " · current" : ""}
                </Mono>
              </TableCell>
              <TableCell className="text-xs">{datasetName(item.dataset)}</TableCell>
              <TableCell>
                <StatusBadge
                  tone={
                    item.status === "complete"
                      ? "positive"
                      : item.status === "error"
                        ? "critical"
                        : "neutral"
                  }
                  label={item.status}
                  raw={item.status}
                />
              </TableCell>
              <TableCell>
                {item.status === "complete" ? (
                  <span className="flex items-center gap-3 text-xs">
                    <a
                      href={exportUrl(item.job_id)}
                      download
                      className="text-accent underline-offset-2 hover:underline"
                    >
                      Aggregate
                    </a>
                    <a
                      href={fullExportUrl(item.job_id)}
                      download
                      className="text-accent underline-offset-2 hover:underline"
                    >
                      Full
                    </a>
                  </span>
                ) : (
                  <span className="text-xs italic text-text-tertiary">
                    {item.status === "error"
                      ? "Not produced"
                      : "Available once the run completes"}
                  </span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </TableScroller>
    </Frame>
  );
}
