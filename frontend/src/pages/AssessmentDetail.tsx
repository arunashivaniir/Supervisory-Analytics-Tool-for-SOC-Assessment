import { useMemo, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import {
  anomalyFeatureSchema,
  anomalyForScope,
  anomalyLimitations,
  anomalyModelStatus,
  capabilitiesForScope,
  capabilityTallyForScope,
  findingsForScope,
  scopeRows,
  unifiedFindings,
} from "../app/selectors";
import { Caveat, PageHeader, Section } from "../components/layout/PageHeader";
import { Card, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/Metric";
import { StatusBadge, NotAvailable } from "../components/ui/StatusBadge";
import { ConceptList, DataRow, Token } from "../components/ui/DataDisplay";
import { FindingDetail } from "../components/findings/FindingDetail";
import { AnomalyIntelligence } from "../components/anomaly/AnomalyIntelligence";
import {
  formatCount,
  entityLabel,
  entityResolved,
  periodLabel,
  periodResolved,
} from "../lib/formatters";
import { SIGNAL_FAMILIES, capabilityStatus, signalStatus } from "../lib/status";
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
  const { result, running, analysisError } = useAnalysis();

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
            {formatCount(scope.record_count)} records analysed · scope{" "}
            <span className="font-mono">{scope.assessment_id}</span>
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

      <div className="grid grid-cols-3 gap-3">
        <SummaryTile
          label="Records analysed"
          value={formatCount(scope.record_count)}
          context="Records the scope builder assigned to this scope"
        />
        <SummaryTile
          label="Evidence status"
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
        <SummaryTile
          label="Signals detected"
          value={
            scopeFindings.length === 0 ? (
              "0"
            ) : (
              formatCount(scopeFindings.length)
            )
          }
          context="Findings the pipeline reported for this scope across all four families"
        />
      </div>

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
        title="Supervisory signals"
        description="Every finding the pipeline reported for this scope, grouped by the layer that produced it."
      >
        {scopeFindings.length === 0 ? (
          <Card>
            <EmptyState
              title="No signals reported for this scope"
              description="The four signal layers examined this scope and returned no findings. This is not by itself an indication that the scope's controls are effective."
            />
          </Card>
        ) : (
          <div className="flex flex-col gap-4">
            {SIGNAL_FAMILIES.map((family) => {
              const familyFindings = scopeFindings.filter(
                (item) => item.family === family.id,
              );

              return (
                <SignalGroup
                  key={family.id}
                  title={family.label}
                  description={family.description}
                  findings={familyFindings}
                />
              );
            })}
          </div>
        )}
      </Section>

      <Section
        title="Anomaly intelligence"
        description="What the offline model reported for this scope."
      >
        <AnomalyIntelligence
          scope={anomaly}
          modelStatus={modelStatus}
          featureSchema={schema}
          limitations={anomalyLimitations(result)}
        />
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
}: {
  title: string;
  description: string;
  findings: UnifiedFinding[];
}) {
  if (findings.length === 0) {
    return (
      <Card>
        <CardHeader title={title} description={description} />
        <p className="px-4 py-3 text-xs text-text-tertiary italic">
          No findings reported in this family for this scope.
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
              <FindingDetail finding={item} compact />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
