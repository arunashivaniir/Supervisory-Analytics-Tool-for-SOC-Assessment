import { useMemo, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import {
  anomalyFeatureSchema,
  anomalyForScope,
  anomalyLimitations,
  anomalyModelStatus,
  attentionForScope,
  capabilitiesForScope,
  capabilityTallyForScope,
  countByFamily,
  eligibleCheckCounts,
  findingsForScope,
  peerContext,
  reviewSamples,
  scopeRows,
  unifiedFindings,
} from "../app/selectors";
import { Caveat, PageHeader, Section } from "../components/layout/PageHeader";
import { Card, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/Metric";
import { StatusBadge, NotAvailable } from "../components/ui/StatusBadge";
import { ConceptList, DataRow, Token } from "../components/ui/DataDisplay";
import { FindingDetail } from "../components/findings/FindingDetail";
import { AlertCaseChain } from "../components/findings/AlertCaseChain";
import { ReviewBadge } from "../components/findings/ReviewControl";
import { useFindingReviews } from "../app/reviews";
import { AnomalyIntelligence } from "../components/anomaly/AnomalyIntelligence";
import {
  formatCount,
  entityLabel,
  entityResolved,
  periodLabel,
  periodResolved,
} from "../lib/formatters";
import { capabilityStatus, signalStatus } from "../lib/status";
import type { UnifiedFinding } from "../app/selectors";
import type { CapabilityStatus } from "../types/pipeline";

/**
 * One assessment scope.
 *
 * Identity, evidence availability, the signals reported for this scope, and
 * the anomaly intelligence the model produced for it — in that order, so the
 * examiner sees what the evidence supports before what the model said about it.
 */
export function AssessmentDetailPage() {
  const { assessmentId = "" } = useParams();
  const { result, running, analysisError, analysis } = useAnalysis();
  const navigate = useNavigate();
  const { reviews } = useFindingReviews(analysis?.job_id ?? null);

  const decodedId = decodeURIComponent(assessmentId);

  const rows = useMemo(() => scopeRows(result), [result]);
  const findings = useMemo(() => unifiedFindings(result), [result]);
  const scope = useMemo(
    () => rows.find((row) => row.assessment_id === decodedId) ?? null,
    [rows, decodedId],
  );

  const capabilities = useMemo(
    () => capabilitiesForScope(result, decodedId),
    [result, decodedId],
  );
  const posture = useMemo(
    () => capabilityTallyForScope(result, decodedId),
    [result, decodedId],
  );
  const scopeFindings = useMemo(
    () => findingsForScope(findings, decodedId),
    [findings, decodedId],
  );
  const anomaly = useMemo(() => anomalyForScope(result, decodedId), [result, decodedId]);
  const modelStatus = anomalyModelStatus(result);
  const schema = anomalyFeatureSchema(result);
  const scopeAttention = useMemo(
    () => (result && scope ? attentionForScope(result, scope) : null),
    [result, scope],
  );
  const peers = useMemo(
    () => peerContext(result, decodedId),
    [result, decodedId],
  );
  const entitySamples = useMemo(
    () => reviewSamples(findings).filter((s) => s.finding.assessment_id === decodedId),
    [findings, decodedId],
  );
  const checkCounts = useMemo(() => eligibleCheckCounts(result), [result]);

  if (!result) {
    return (
      <div className="py-10">
        <PageHeader title="Assessment" />
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

  if (!scope) {
    return (
      <div className="py-10">
        <PageHeader title="Assessment" />
        <Caveat tone="caution">
          No assessment scope with the identifier{" "}
          <span className="font-mono">{decodedId}</span> exists in the current
          result. It may belong to a different dataset or a previous run.
        </Caveat>
        <p className="mt-3 text-xs">
          <Link to="/assessments" className="text-accent underline-offset-2 hover:underline">
            Return to assessments
          </Link>
        </p>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title={entityResolved(scope.entity) ? entityLabel(scope.entity) : "Entity not identified"}
        subject={
          periodResolved(scope.period)
            ? periodLabel(scope.period)
            : "Period not determined"
        }
        meta={
          <>
            Sector: Not available in submission ·{" "}
            {formatCount(scope.record_count)} records analysed · scope{" "}
            <span className="font-mono">{scope.assessment_id}</span> ·{" "}
            {scopeFindings.length > 0 ? (
              <span className="font-medium text-critical">Requires attention</span>
            ) : (
              "No supervisory signal identified in available evidence"
            )}
          </>
        }
      />

      {!entityResolved(scope.entity) || !periodResolved(scope.period) ? (
        <Caveat tone="caution" className="mb-5">
          This scope's identity was only partly resolved from the submitted
          evidence.
          {!entityResolved(scope.entity) && scope.entity.unavailable_reason
            ? ` Entity: ${scope.entity.unavailable_reason}.`
            : ""}
          {!periodResolved(scope.period) && scope.period.unavailable_reason
            ? ` Period: ${scope.period.unavailable_reason}.`
            : ""}
        </Caveat>
      ) : null}

      <div className="grid grid-cols-4 gap-3">
        <SummaryTile
          label="Supervisory indicator"
          value={
            scopeAttention ? (
              <span>
                {scopeAttention.score}{" "}
                <span className="text-sm font-medium text-text-secondary">
                  · {scopeAttention.level}
                </span>
              </span>
            ) : (
              <NotAvailable />
            )
          }
          context={
            scopeAttention
              ? "Backend attention score, a triage aid — not a verdict"
              : "The backend reported no attention entry for this scope"
          }
        />
        <SummaryTile
          label="Execution gaps"
          value={formatCount(countByFamily(scopeFindings).execution_gap ?? 0)}
          context="Findings contradicting an expected control"
        />
        <SummaryTile
          label="Negative space"
          value={formatCount(countByFamily(scopeFindings).negative_space ?? 0)}
          context="Expected evidence observed absent"
        />
        <SummaryTile
          label="Evidence coverage"
          value={
            posture.length === 0 ? (
              <NotAvailable />
            ) : (
              <span className="text-lg">
                {posture.find((entry) => entry.status === "AVAILABLE")?.count ?? 0}
                <span className="text-text-tertiary text-sm"> / {capabilities.length}</span>
              </span>
            )
          }
          context="Capabilities with available evidence, of those assessed for this scope"
        />
      </div>

      <Section
        title="Prioritised manual review"
        description="The records to inspect first for this entity, in the same provisional order as the Overview. Start here when opening the evidence."
      >
        {entitySamples.length === 0 ? (
          <Card>
            <EmptyState
              title="No review samples for this entity"
              description="None of this entity's findings points at a source record, or it has no findings. Read the signals below for the evidence that is available."
            />
          </Card>
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {entitySamples.map((sample) => (
                <li
                  key={sample.finding.key}
                  className="cursor-pointer px-4 py-2.5 transition-colors duration-75 hover:bg-subtle"
                  onClick={() =>
                    navigate(
                      `/findings?finding=${encodeURIComponent(sample.finding.key)}`,
                    )
                  }
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="tabular micro text-text-tertiary">
                      {sample.rank}
                    </span>
                    <span className="font-mono text-[13px] font-medium text-text">
                      {sample.finding.indicator}
                    </span>
                    <span className="micro text-text-tertiary">
                      {sample.finding.familyLabel}
                    </span>
                    <span className="ml-auto">
                      <ReviewBadge review={reviews[sample.finding.key] ?? null} />
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-text-secondary">
                    {sample.why}
                  </p>
                  <div className="mt-1.5">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        navigate(
                          `/evidence?finding=${encodeURIComponent(sample.finding.key)}`,
                        );
                      }}
                      className="text-xs font-medium text-accent underline-offset-2 hover:underline"
                    >
                      View Evidence
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </Section>

      <Section
        title="Capability evidence"
        description="Evidence availability for each capability, as the capability layer assessed it. An evidence state is not a performance judgement."
      >
        <Card>
          {capabilities.length === 0 ? (
            <EmptyState
              title="No capability assessment"
              description="The pipeline returned no capability evidence states for this scope."
            />
          ) : (
            <ul className="divide-y divide-border">
              {capabilities.map(({ capability, status }) => (
                <CapabilityRow
                  key={capability.capability_id}
                  name={capability.name}
                  status={status}
                  explanation={capability.explanation}
                  availableCount={capability.evidence_available.length}
                  missingCount={capability.evidence_missing.length}
                />
              ))}
            </ul>
          )}
        </Card>
        <Caveat className="mt-2.5">
          Insufficient evidence is not a control failure, and not assessed is
          not low risk. Both mean the submitted data did not permit a
          judgement.
        </Caveat>
      </Section>

      <Section
        title="Execution gaps"
        description="Contradictions between an expected control and the evidence submitted for it."
      >
        {scopeFindings.filter((item) => item.family === "execution_gap").length === 0 ? (
          <Card>
            <EmptyState
              title="No qualifying execution-gap findings identified"
              description="The execution-gap checks examined this scope and reported no contradictions. Where required evidence was unavailable the check is not evaluable rather than a finding — see the evidence coverage below."
            />
          </Card>
        ) : (
          <SignalGroup
            title="Execution gaps"
            description="Contradictions between an expected control and the evidence submitted for it."
            findings={scopeFindings.filter((item) => item.family === "execution_gap")}
          />
        )}
      </Section>

      <Section
        title="Negative space"
        description="Observable absence of evidence that a configured expectation says should be present."
      >
        {scopeFindings.filter((item) => item.family === "negative_space").length === 0 ? (
          <Card>
            <EmptyState
              title="No qualifying negative-space findings identified"
              description="The negative-space checks examined this scope and reported no observable absence. Absence of a finding is not proof of coverage."
            />
          </Card>
        ) : (
          <SignalGroup
            title="Negative space"
            description="Observable absence of evidence that a configured expectation says should be present."
            findings={scopeFindings.filter((item) => item.family === "negative_space")}
          />
        )}
      </Section>

      <Section
        title="Operational patterns"
        description="The shape of activity within this scope, judged against that scope's own population."
      >
        <SignalGroup
          title="Operational patterns"
          description="The shape of activity within this scope, judged against that scope's own population."
          findings={scopeFindings.filter((item) => item.family === "operational_pattern")}
          emptyTitle="No qualifying operational-pattern findings identified for this scope."
        />
      </Section>

      <Section
        title="Anomaly intelligence"
        description="What the offline model reported for this scope. An anomalous pattern is not a confirmed finding."
      >
        <AnomalyIntelligence
          scope={anomaly}
          modelStatus={modelStatus}
          featureSchema={schema}
          limitations={anomalyLimitations(result)}
        />
      </Section>

      <div className="mt-7 grid grid-cols-2 gap-4">
        <Section
          title="Peer context"
          description="This scope against the assessment's own scopes."
          className="mt-0"
        >
          {peers ? (
            <Card>
              <div className="px-4 py-3">
                <DataRow
                  label="Peer population"
                  value={`${peers.population} scopes in this assessment`}
                />
                <DataRow label="Comparison basis" value={peers.basis} />
                <DataRow
                  label="Peer median"
                  value={<span className="tabular">{peers.median} signals</span>}
                />
                <DataRow
                  label="Peer range"
                  value={
                    <span className="tabular">
                      {peers.min} – {peers.max} signals
                    </span>
                  }
                />
                <DataRow
                  label="This entity"
                  value={
                    <span className="tabular">
                      {peers.entityCount} signals (
                      {peers.deviation >= 0 ? "+" : ""}
                      {peers.deviation} vs median)
                    </span>
                  }
                />
              </div>
            </Card>
          ) : (
            <Card>
              <EmptyState
                title="Peer comparison unavailable for this assessment package"
                description="Fewer than two assessment scopes exist, so there is no peer population to compare against."
              />
            </Card>
          )}
        </Section>

        <Section
          title="Trend"
          description="How this entity's signals changed across assessments."
          className="mt-0"
        >
          <Card>
            <EmptyState
              title="Historical trend unavailable for this assessment package"
              description="A single assessment carries no history. Trend appears when multiple assessment periods are submitted."
            />
          </Card>
        </Section>
      </div>

      <Section
        title="Evidence coverage"
        description="What the submitted evidence permitted for this scope — the same posture the capability layer assessed, summarised."
      >
        <Card>
          <div className="px-4 py-3">
            <DataRow
              label="Records analysed"
              value={<span className="tabular">{formatCount(scope.record_count)}</span>}
            />
            <DataRow
              label="Canonical concepts resolved"
              value={
                <span className="tabular">
                  {formatCount(result.mapping_report.mapped_columns)} of{" "}
                  {formatCount(result.mapping_report.dataset_columns)}
                </span>
              }
            />
            <DataRow
              label="Execution-gap checks evaluated"
              value={
                <span className="tabular">
                  {formatCount(checkCounts.execution_gap ?? 0)}
                </span>
              }
            />
            <DataRow
              label="Negative-space checks evaluated"
              value={
                <span className="tabular">
                  {formatCount(checkCounts.negative_space ?? 0)}
                </span>
              }
            />
            <DataRow
              label="Findings generated"
              value={
                <span className="tabular">{formatCount(scopeFindings.length)}</span>
              }
            />
            <DataRow
              label="Evidence availability"
              value={
                posture.length === 0 ? (
                  <NotAvailable />
                ) : (
                  <span className="text-xs text-text-secondary">
                    {posture
                      .map(
                        (entry) =>
                          `${entry.count} ${capabilityStatus(entry.status).label.toLowerCase()}`,
                      )
                      .join(" · ")}
                  </span>
                )
              }
            />
          </div>
        </Card>
      </Section>
    </>
  );
}

function SummaryTile({
  label,
  value,
  context,
}: {
  label: string;
  value: ReactNode;
  context: string;
}) {
  return (
    <div className="flex flex-col justify-between rounded-[10px] border border-border bg-surface px-4 py-3">
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

function CapabilityRow({
  name,
  status,
  explanation,
  availableCount,
  missingCount,
}: {
  name: string;
  status: CapabilityStatus;
  explanation: string;
  availableCount: number;
  missingCount: number;
}) {
  const presentation = capabilityStatus(status);

  return (
    <li className="flex items-start justify-between gap-4 px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-text">{name}</span>
          <StatusBadge
            tone={presentation.tone}
            label={presentation.label}
            raw={status}
          />
        </div>
        <p className="mt-1 text-xs leading-relaxed text-text-secondary">
          {explanation}
        </p>
      </div>
      <div className="shrink-0 text-right micro text-text-tertiary">
        <div>{availableCount} evidence items present</div>
        {missingCount > 0 ? (
          <div className="mt-0.5">{missingCount} missing</div>
        ) : null}
      </div>
    </li>
  );
}

function SignalGroup({
  title,
  description,
  findings,
  emptyTitle,
}: {
  title: string;
  description: string;
  findings: UnifiedFinding[];
  emptyTitle?: string;
}) {
  const navigate = useNavigate();

  if (findings.length === 0) {
    return (
      <Card>
        <CardHeader title={title} description={description} />
        <p className="px-4 py-3 text-xs text-text-tertiary italic">
          {emptyTitle ?? "No findings reported in this family for this scope."}
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title={title}
        description={description}
        action={
          <span className="micro tabular text-text-secondary">
            {findings.length} finding{findings.length === 1 ? "" : "s"}
          </span>
        }
      />
      <ul className="divide-y divide-border">
        {findings.map((item) => (
          <li key={item.key} className="px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[13px] font-medium text-text">
                    {item.indicator}
                  </span>
                  {item.status ? (
                    <StatusBadge
                      tone={signalStatus(item.status).tone}
                      label={signalStatus(item.status).label}
                      raw={item.status}
                    />
                  ) : null}
                </div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-text">
                  {item.reason}
                </p>
              </div>
            </div>

            <div className="mt-2.5 grid grid-cols-2 gap-x-6 gap-y-0">
              <DataRow label="Assessment" value={<Token>{item.assessment_id}</Token>} />
              <DataRow
                label="Evidence concepts"
                value={<ConceptList concepts={item.evidenceConcepts} collapsed={4} />}
              />
            </div>

            <div className="mt-2">
              <AlertCaseChain finding={item} />
            </div>

            <div className="mt-2">
              <FindingDetail finding={item} compact />
            </div>

            <div className="mt-2">
              <button
                type="button"
                onClick={() =>
                  navigate(`/evidence?finding=${encodeURIComponent(item.key)}`)
                }
                className="text-xs font-medium text-accent underline-offset-2 hover:underline"
              >
                View Evidence
              </button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
