import { useEffect, useState } from "react";

import { useAnalysis } from "../app/AnalysisContext";
import {
  anomalyModelStatus,
  anomalyVerdictCounts,
  capabilityScopes,
  countByFamily,
  scopeRows,
  unifiedFindings,
} from "../app/selectors";
import { Caveat, PageHeader, Section } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { EmptyState, MetricBlock } from "../components/ui/Metric";
import { StatusBadge } from "../components/ui/StatusBadge";
import {
  DataTable,
  HeadCell,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "../components/ui/DataTable";
import { DataRow, Token } from "../components/ui/DataDisplay";
import { fetchAnalysisList, exportUrl, fullExportUrl } from "../services/api";
import { datasetName, formatCount, optionalText } from "../lib/formatters";
import { SIGNAL_FAMILIES, anomalyVerdict, capabilityStatus } from "../lib/status";
import type { AnalysisState } from "../types/pipeline";

/**
 * The record of what was assessed and what came out.
 *
 * A document view, not a judgement. Every count on this page is a count the
 * pipeline reported, and every sentence is either the backend's own text or a
 * statement about what the record contains. There is no overall score, no
 * grade and no verdict, because the pipeline does not produce one and a
 * report implying otherwise would misrepresent the assessment.
 */
export function ReportsPage() {
  const { analysis, result, running, analysisError } = useAnalysis();

  if (!result || !analysis) {
    return (
      <div className="py-10">
        <PageHeader title="Reports" />
        {analysisError ? (
          <Caveat tone="caution">{analysisError}</Caveat>
        ) : running ? (
          <Caveat>The assessment is still being produced.</Caveat>
        ) : (
          <EmptyState
            title="No assessment loaded"
            description="Choose a dataset to produce an assessment."
          />
        )}
      </div>
    );
  }

  const findings = unifiedFindings(result);
  const rows = scopeRows(result);
  const scopes = capabilityScopes(result);
  const familyCounts = countByFamily(findings);
  const counts = anomalyVerdictCounts(result);
  const modelStatus = anomalyModelStatus(result);

  return (
    <>
      <PageHeader
        title="Reports"
        subject={datasetName(result.dataset)}
        meta={`${formatCount(
          result.ingestion.record_count,
        )} records assessed · run ${analysis.job_id.slice(0, 8)}`}
        description="A printable record of the assessment: what was assessed, the evidence states reached, the signals reported, and the limitations that apply to all of it."
        actions={
          <div className="flex items-center gap-2">
            <a href={exportUrl(analysis.job_id)} download>
              <Button variant="secondary">Export JSON</Button>
            </a>
            <Button onClick={() => window.print()}>Print or save as PDF</Button>
          </div>
        }
      />

      <Caveat className="mb-5">
        This page reproduces the assessment record. It does not grade, score
        or rank the assessed organisation, and it does not combine the counts
        below into a single measure. A low finding count is not a good result:
        it can also mean the evidence was insufficient to report anything.
      </Caveat>

      <Card className="mb-5">
        <div className="grid grid-cols-2 gap-x-8 px-5 py-4">
          <div>
            <DataRow
              label="Dataset"
              value={<Token>{optionalText(result.ingestion.source)}</Token>}
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
          <div>
            <DataRow
              label="Assessment scopes"
              value={<span className="tabular">{formatCount(rows.length)}</span>}
            />
            <DataRow
              label="Signals reported"
              value={
                <span className="tabular">{formatCount(findings.length)}</span>
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
            <DataRow
              label="Run"
              value={<Token>{analysis.job_id}</Token>}
            />
          </div>
        </div>
      </Card>

      <Section
        title="Signal families"
        description="Counts as the pipeline reported them, by family. The families are independent and are not summed into a total judgement."
      >
        <div className="grid grid-cols-4 gap-3">
          {SIGNAL_FAMILIES.map((family) => (
            <MetricBlock
              key={family.id}
              label={family.label}
              value={familyCounts[family.id] ?? 0}
              context={family.description}
            />
          ))}
        </div>
      </Section>

      <Section
        title="Evidence states"
        description="Capability states across the assessed scopes, as the pipeline counted them."
      >
        <Card>
          <DataTable>
            <TableHead>
              <HeadCell>Capability</HeadCell>
              <HeadCell align="right">Available</HeadCell>
              <HeadCell align="right">Insufficient evidence</HeadCell>
              <HeadCell align="right">Not assessed</HeadCell>
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
          </DataTable>
        </Card>
      </Section>

      <Section
        title="Anomaly verdicts"
        description="Recorded, not interpreted. A verdict is a distance from a reference population, not a severity."
      >
        <Card>
          <DataTable>
            <TableHead>
              <HeadCell>Verdict</HeadCell>
              <HeadCell align="right">Scopes</HeadCell>
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
          </DataTable>
        </Card>
      </Section>

      <Section
        title="Assessed scopes"
        description="Each scope the record covers, with the evidence states and signals attached to it."
      >
        <Card>
          <DataTable>
            <TableHead>
              <HeadCell>Scope</HeadCell>
              <HeadCell align="right">Records</HeadCell>
              <HeadCell>Evidence states</HeadCell>
              <HeadCell align="right">Signals</HeadCell>
            </TableHead>
            <TableBody>
              {rows.map((row) => {
                const scope = scopes.find(
                  (item) => item.assessment_id === row.assessment_id,
                );

                return (
                  <TableRow key={row.assessment_id}>
                    <TableCell>
                      <Token>{row.assessment_id}</Token>
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
                      {
                        findings.filter(
                          (item) => item.assessment_id === row.assessment_id,
                        ).length
                      }
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </DataTable>
        </Card>
      </Section>

      {result.anomaly_findings.limitations.length > 0 ? (
        <Section
          title="Limitations"
          description="The constraints that apply to this assessment as a whole."
        >
          <Card>
            <ul className="list-inside list-disc space-y-1.5 px-5 py-4 text-[13px] leading-relaxed text-text-secondary">
              {result.anomaly_findings.limitations.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </Card>
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
    return (
      <Caveat tone="caution">
        The run listing could not be read: {error}
      </Caveat>
    );
  }

  if (runs === null) {
    return (
      <Card>
        <EmptyState
          title="Reading the run listing"
          description="One moment."
        />
      </Card>
    );
  }

  if (runs.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No runs recorded"
          description="Analyses produced on this machine will be listed here."
        />
      </Card>
    );
  }

  return (
    <Card>
      <DataTable>
        <TableHead>
          <HeadCell>Run</HeadCell>
          <HeadCell>Dataset</HeadCell>
          <HeadCell>State</HeadCell>
          <HeadCell>Exports</HeadCell>
        </TableHead>
        <TableBody>
          {[...runs].reverse().map((item) => (
            <TableRow key={item.job_id}>
              <TableCell>
                <Token>
                  {item.job_id.slice(0, 8)}
                  {item.job_id === currentJobId ? " · current" : ""}
                </Token>
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
                  <span className="text-xs text-text-tertiary italic">
                    {item.status === "error"
                      ? "Not produced"
                      : "Available once the run completes"}
                  </span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
    </Card>
  );
}
