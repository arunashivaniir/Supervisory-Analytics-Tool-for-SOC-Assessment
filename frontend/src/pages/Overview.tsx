import { Link } from "react-router-dom";
import { Printer } from "lucide-react";

import { useAnalysis } from "../app/AnalysisContext";
import { useDashboard } from "../app/DashboardContext";
import { runStatusLabel, runStatusTone } from "../app/viewModel";
import { PageHeader } from "../components/layout/PageHeader";
import { AssessmentStatusStrip } from "../components/dashboard/AssessmentStatusStrip";
import { SignalLandscape } from "../components/dashboard/SignalLandscape";
import { EntityAttentionTable } from "../components/dashboard/EntityAttentionTable";
import { PeerComparisonPanel } from "../components/dashboard/PeerComparisonPanel";
import { EvidenceHealth } from "../components/dashboard/EvidenceHealth";
import { FindingSummary } from "../components/dashboard/FindingSummary";
import { Section } from "../components/ui/Surface";
import { Button } from "../components/ui/Button";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  StatusBadge,
} from "../components/ui/State";

/**
 * Overview: what is happening?
 *
 * The first viewport answers four questions in order — what assessment is
 * loaded, is it complete, what was detected, which entities need attention —
 * because that is the order an examiner asks them. Peer comparison and evidence
 * health follow below, because they inform a decision rather than start one.
 *
 * The structure is a status strip, then the signal landscape and the entity
 * attention table, then two supporting sections and a finding summary. Sections
 * and tables, not a grid of cards: every number on this page is a measurement of
 * the same run, and giving each one its own box would imply they are separate
 * conclusions.
 */
export function OverviewPage() {
  const { analysisError, dismissError } = useAnalysis();
  const { view, registerError, registerLoading } = useDashboard();

  const {
    hasResult,
    lifecycle,
    run,
    status,
    landscape,
    entities,
    peer,
    findings,
  } = view;

  if (lifecycle === "FAILED") {
    return (
      <>
        <PageHeader title="Overview" />
        <ErrorState
          title="The assessment run failed"
          detail={run.error}
          action={
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => dismissError()}>
                Dismiss
              </Button>
              <Link
                to="/assessments"
                className="text-[13px] text-accent underline-offset-2 hover:underline"
              >
                Go to Assessments
              </Link>
            </div>
          }
        />
      </>
    );
  }

  /*
   * An assessment is in progress only when the lifecycle says so, which means a
   * run exists, the backend reports it active, and it names a dataset. This page
   * used to decide that from `run.phase` instead, and because the empty run was
   * given the phase `queued`, a first visit — or any moment with no run held —
   * announced "Assessment in progress" over "No dataset selected".
   *
   * The switch case is excluded on purpose: during a dataset switch the loaded
   * assessment stays on screen and the new run is produced behind it, so showing
   * a progress state here would hide a finished result the examiner is reading.
   */
  if (lifecycle === "ASSESSING" && !run.switching) {
    return (
      <>
        <PageHeader title="Overview" />
        <LoadingState
          title="Assessment in progress"
          detail={`The pipeline is assessing ${
            // Unreachable: `ASSESSING` requires a named dataset. Present only so
            // the text is total, and it cannot contradict the header, which says
            // the same thing from the same value.
            run.datasetName ?? "the dataset for this run"
          }.`}
        />
      </>
    );
  }

  if (!hasResult) {
    return (
      <>
        <PageHeader title="Overview" />

        {lifecycle === "READY" ? (
          <EmptyState
            title={`${run.datasetName} selected`}
            description="Start an assessment to produce results for this dataset."
            action={
              <Link
                to="/assessments/new"
                className="text-[13px] font-medium text-accent underline-offset-2 hover:underline"
              >
                Start an assessment
              </Link>
            }
          />
        ) : (
          <EmptyState
            title="No dataset selected"
            description="Select a dataset to begin an assessment."
            action={
              <Link
                to="/assessments/new"
                className="text-[13px] font-medium text-accent underline-offset-2 hover:underline"
              >
                Start an assessment
              </Link>
            }
          />
        )}
      </>
    );
  }

  // The peer panel shows one scope's comparison. It uses the scope with the most
  // signals, which is the one an examiner is most likely to open next, and says
  // so rather than picking silently.
  const leadScope = entities.find((row) => row.benchmark) ?? null;
  // Every metric the backend published for that scope, in the order the view
  // model derived from the backend's own statistical status.
  const leadMetrics = leadScope?.benchmark?.metrics ?? [];


  return (
    <>
      <PageHeader
        title="Assessment overview"
        supporting={summariseRun(landscape.total, status.scopes)}
        actions={
          <>
            <StatusBadge
              tone={runStatusTone(run)}
              label={runStatusLabel(run)}
              raw={run.statusToken}
              showDot
            />
            <Button variant="ghost" size="sm" onClick={() => window.print()}>
              <Printer aria-hidden="true" className="h-3.5 w-3.5" />
              Print
            </Button>
          </>
        }
      />

      {analysisError ? (
        <div className="mb-4">
          <ErrorState
            title="The assessment on screen could not be re-read"
            detail={analysisError}
            action={
              <Button size="sm" onClick={() => dismissError()}>
                Dismiss
              </Button>
            }
          />
        </div>
      ) : null}

      <AssessmentStatusStrip status={status} run={run} />

      <div className="mt-6 grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
        <div className="min-w-0 space-y-6">
          <Section
            title="What was detected"
            description="Counts reported by each signal family in this run."
          >
            <SignalLandscape landscape={landscape} />
          </Section>

          <Section
            title="Who needs attention"
            description="Every assessment scope, ordered by how many signals it reported."
          >
            <EntityAttentionTable rows={entities} />
          </Section>
        </div>

        <div className="min-w-0 space-y-6">
          <Section title="Findings">
            <FindingSummary findings={findings} />
          </Section>

          <Section title="Evidence health">
            <EvidenceHealth
              evidence={view.evidence}
              registerLoading={registerLoading}
              registerError={registerError}
            />
          </Section>
        </div>
      </div>

      {leadScope && leadMetrics.length > 0 ? (
        <div className="mt-6">
          <Section
            title="How does it compare"
            description={
              <>
                Peer comparison for {leadScope.entity.name ?? leadScope.entity.id}, the
                scope with the most signals.{" "}
                <Link
                  to={`/assessments/${encodeURIComponent(leadScope.assessmentId)}`}
                  className="text-accent underline-offset-2 hover:underline"
                >
                  Open this scope
                </Link>
                .
              </>
            }
          >
            <PeerComparisonPanel
              peer={peer}
              metrics={leadMetrics}
              cohortLabel={leadScope.benchmark?.cohortLabel ?? null}
              cohortPeerCount={leadScope.benchmark?.cohortPeerCount ?? 0}
              cohortRuleSteps={leadScope.benchmark?.cohortRuleSteps ?? []}
              compact
            />
          </Section>
        </div>
      ) : null}
    </>
  );
}

/**
 * One sentence describing the run.
 *
 * Three genuinely different states, kept apart:
 *
 *   - `total === null` means the pipeline reported no count for any family, so
 *     the interface says the count is unavailable. It does not fall back to
 *     zero, because "no signals were detected" and "no signal count was
 *     produced" are different claims and only the first is reassuring.
 *   - `total === 0` means every family ran and found nothing.
 *   - otherwise the run's own counts.
 *
 * Scope count is taken from the backend's `scope_count` rather than from the
 * length of the rendered table, so the sentence cannot drift from the number the
 * backend published.
 */
function summariseRun(total: number | null, scopeCount: number | null): string {
  if (total === null) {
    return "The pipeline did not report a signal count for this assessment.";
  }

  if (total === 0) {
    return "No signals reported by the pipeline for this assessment.";
  }

  const signals = total === 1 ? "1 supervisory signal" : `${total} supervisory signals`;

  if (scopeCount === null) {
    return `${signals} across an unreported number of assessment scopes.`;
  }

  const scopes =
    scopeCount === 1 ? "1 assessment scope" : `${scopeCount} assessment scopes`;

  return `${signals} across ${scopes}.`;
}
