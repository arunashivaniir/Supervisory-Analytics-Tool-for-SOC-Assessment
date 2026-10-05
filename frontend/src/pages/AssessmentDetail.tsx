import { useEffect, useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { useAnalysis } from "../app/AnalysisContext";
import { useDashboard } from "../app/DashboardContext";
import { useInvestigation } from "../app/InvestigationContext";
import { unifiedFindings, type UnifiedFinding } from "../app/selectors";
import {
  entityLabel,
  formatCount,
  periodLabel,
} from "../lib/formatters";
import { signalStatus } from "../lib/status";
import { PageHeader } from "../components/layout/PageHeader";
import { InvestigationTrail } from "../components/dashboard/InvestigationTrail";
import { PeerComparisonPanel } from "../components/dashboard/PeerComparisonPanel";
import { ScopeEvidenceSummary } from "../components/dashboard/EvidenceHealth";
import { FindingTable } from "../components/findings/FindingTable";
import { DetailDrawer } from "../components/ui/DetailDrawer";
import {
  BackendProse,
  ConceptList,
  DataRow,
  Frame,
  Note,
  Section,
} from "../components/ui/Surface";
import { Button } from "../components/ui/Button";
import {
  EmptyState,
  ErrorState,
  LimitationNote,
  LoadingState,
  StatusBadge,
} from "../components/ui/State";

/**
 * One entity's assessment scope.
 *
 * This is the working screen of the product. Everything an examiner needs about
 * one scope is here, in the order they need it: what the backend resolved about
 * this scope, what it detected, how it compares to peers, and what evidence
 * exists behind those statements.
 *
 * The finding list is the same component the Findings screen uses, filtered to
 * this scope, so a finding looks and reads identically wherever it is opened
 * from. That is the point of routing through the shared projection rather than
 * building a second one.
 */
export function AssessmentDetailPage() {
  const { assessmentId } = useParams<{ assessmentId: string }>();
  const navigate = useNavigate();
  const { analysis, result, running } = useAnalysis();
  const { view } = useDashboard();
  const { openFinding, activeFinding, closeFinding, setAssessmentId } =
    useInvestigation();

  const findings = useMemo(() => unifiedFindings(result), [result]);

  const scope = useMemo(
    () =>
      view.entities.find((entity) => entity.assessmentId === assessmentId) ??
      null,
    [view.entities, assessmentId],
  );

  const scopeFindings = useMemo(
    () => findings.filter((item) => item.assessment_id === assessmentId),
    [findings, assessmentId],
  );

  // The scope being read is part of the investigation thread, so the trail and
  // any finding opened from elsewhere agree on which scope is in view.
  useEffect(() => {
    setAssessmentId(assessmentId ?? null);
  }, [assessmentId, setAssessmentId]);

  if (analysis?.status === "error") {
    return (
      <>
        <PageHeader title="Assessment scope" />
        <ErrorState
          title="The assessment run failed"
          detail={analysis.error}
          action={
            <Button variant="primary" onClick={() => navigate("/")}>
              Back to overview
            </Button>
          }
        />
      </>
    );
  }

  if (!view.hasResult) {
    return running ? (
      <LoadingState
        title="Assessment in progress"
        detail="This scope opens once the pipeline completes."
      />
    ) : (
      <EmptyState
        title="No assessment loaded"
        description="Run an assessment before opening a scope."
        action={
          <Link
            to="/assessments"
            className="text-[13px] font-medium text-accent underline-offset-2 hover:underline"
          >
            Go to Assessments
          </Link>
        }
      />
    );
  }

  if (!scope) {
    return (
      <>
        <PageHeader title="Assessment scope" />
        <EmptyState
          title="That scope is not in this assessment"
          description={
            <>
              The loaded run produced {formatCount(view.status.scopes ?? null)}{" "}
              scopes, and none of them is{" "}
              <span className="font-mono text-[12px]">{assessmentId}</span>. It
              may belong to a different run.
            </>
          }
          action={
            <Link
              to="/assessments"
              className="text-[13px] font-medium text-accent underline-offset-2 hover:underline"
            >
              See the scopes in this assessment
            </Link>
          }
        />
      </>
    );
  }

  const entityText = entityLabel(scope.entity);
  const periodText = periodLabel(scope.period);
  // Every metric the backend published for this scope, in the view model's
  // backend-derived order, so this screen and Overview agree.
  const scopeMetrics = scope.benchmark?.metrics ?? [];
  const limitationForScope = scopeFindings
    .map((item) => findingLimitations(item))
    .flat()
    .filter((value, index, all) => all.indexOf(value) === index);

  return (
    <>
      <InvestigationTrail entityAssessmentId={scope.assessmentId} />

      <PageHeader
        title={scope.resolved ? entityText : "Scope with an unidentified entity"}
        supporting={
          <>
            {scope.resolved ? null : (
              <span className="text-caution">
                The pipeline could not resolve an entity for this scope.{" "}
              </span>
            )}
            {scope.period.available ? (
              <>Assessed over {periodText}. </>
            ) : (
              <>The pipeline could not determine a period for this scope. </>
            )}
            {formatCount(scope.recordCount)} records in scope.
          </>
        }
        actions={
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(-1)}
            >
              <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
              Back
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate("/findings")}
            >
              All findings
            </Button>
          </>
        }
      />

      <div className="mt-5 grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,320px)]">
        <div className="min-w-0 space-y-6">
          <Section
            title="What was detected in this scope"
            description="Findings the pipeline reported for this scope, across every signal family."
          >
            <FindingTable
              findings={scopeFindings}
              onOpen={openFinding}
              selectedKey={activeFinding?.key ?? null}
              emptyDescription="No signal family reported a finding for this scope. That is a statement about this scope, not about the assessment as a whole."
              showEntity={false}
            />
          </Section>

          {scope.benchmark ? (
            <Section
              title="How this scope compares"
              description="Measured against the peers the backend selected, using the backend's own statistics."
            >
              <PeerComparisonPanel
                peer={view.peer}
                metrics={scopeMetrics}
                cohortLabel={scope.benchmark.cohortLabel}
                cohortPeerCount={scope.benchmark.cohortPeerCount}
                cohortRuleSteps={scope.benchmark.cohortRuleSteps}
              />
            </Section>
          ) : (
            <Section title="How this scope compares">
              <Note tone="neutral">
                {view.peer.unavailableReason ??
                  "The pipeline published no peer benchmark for this assessment."}
              </Note>
            </Section>
          )}
        </div>

        <div className="min-w-0 space-y-6">
          <Section title="Evidence behind this scope">
            <ScopeEvidenceSummary {...scope.evidence} />
            <p className="mt-3 text-[13px]">
              <Link
                to="/evidence"
                className="text-accent underline-offset-2 hover:underline"
              >
                Open the evidence register
              </Link>
            </p>
          </Section>

          <Section title="Scope detail">
            <Frame>
              <DataRow
                label="Entity"
                value={
                  scope.resolved ? (
                    entityText
                  ) : (
                    <span className="italic text-text-tertiary">
                      Entity not identified
                    </span>
                  )
                }
              />
              <DataRow
                label="Period"
                value={
                  scope.period.available ? (
                    periodText
                  ) : (
                    <span className="italic text-text-tertiary">
                      period not determined
                    </span>
                  )
                }
              />
              <DataRow
                label="Records in scope"
                value={formatCount(scope.recordCount)}
              />
              <DataRow
                label="Signals reported"
                value={formatCount(scope.signals)}
              />
              {scope.attention.kind === "risk_band" ? (
                <DataRow
                  label="Backend risk band"
                  value={
                    <StatusBadge
                      tone={scope.attention.tone}
                      label={scope.attention.label}
                    />
                  }
                />
              ) : null}
              <DataRow
                label="Assessment id"
                value={scope.assessmentId}
                mono
              />
            </Frame>
          </Section>

          {limitationForScope.length > 0 ? (
            <Section title="Stated limitations">
              <ul className="min-w-0 space-y-1.5">
                {limitationForScope.map((limitation) => (
                  <li key={limitation}>
                    <LimitationNote>{limitation}</LimitationNote>
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
        </div>
      </div>

      <FindingDrawer
        finding={activeFinding}
        onClose={closeFinding}
        onOpenEvidence={() => navigate("/evidence")}
      />
    </>
  );
}

/**
 * The backend's own caveats about one finding, if it stated any.
 *
 * Read from the finding rather than from the run, because a limitation that
 * applies to one finding must not be widened into a statement about the scope.
 */
function findingLimitations(finding: UnifiedFinding): string[] {
  const raw = finding.finding as Record<string, unknown>;

  const candidates = [
    raw.explanation_limitations,
    raw.is_not_a_control_failure,
    (raw.explanation as { limitations?: unknown } | undefined)?.limitations,
  ];

  const out: string[] = [];

  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      out.push(...candidate.map(String));
    } else if (typeof candidate === "string" && candidate.trim()) {
      out.push(candidate.trim());
    }
  }

  return out;
}

function FindingDrawer({
  finding,
  onClose,
  onOpenEvidence,
}: {
  finding: UnifiedFinding | null;
  onClose: () => void;
  onOpenEvidence: () => void;
}) {
  if (!finding) {
    return null;
  }

  const status = signalStatus(finding.status);
  const raw = finding.finding as Record<string, unknown>;
  const concepts = finding.evidenceConcepts;

  return (
    <DetailDrawer
      open
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
      title={finding.indicator}
      subtitle={
        <>
          {finding.familyLabel} finding in{" "}
          {entityLabel(finding.entity)} &middot; {periodLabel(finding.period)}
        </>
      }
    >
      <div className="min-w-0 space-y-4">
        <Frame>
          <DataRow label="Family" value={finding.familyLabel} />
          <DataRow label="Indicator" value={finding.indicator} />
          <DataRow
            label="Status"
            value={
              <StatusBadge
                tone={status.tone}
                label={status.label}
                raw={finding.status}
              />
            }
          />
          <DataRow label="Assessment id" value={finding.assessment_id} mono />
        </Frame>

        <div>
          <p className="section-label">Why the pipeline reported this</p>
          <div className="mt-1.5">
            <BackendProse>
              {typeof raw.reason === "string" ? raw.reason : finding.reason}
            </BackendProse>
          </div>
        </div>

        {concepts.length > 0 ? (
          <div>
            <p className="section-label">Evidence concepts</p>
            <div className="mt-1.5">
              <ConceptList concepts={concepts} />
            </div>
          </div>
        ) : null}

        <p>
          <Button variant="secondary" size="sm" onClick={onOpenEvidence}>
            Review the evidence register
          </Button>
        </p>
      </div>
    </DetailDrawer>
  );
}
