import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import { useDashboard } from "../app/DashboardContext";
import { useInvestigation } from "../app/InvestigationContext";
import type { UnifiedFinding } from "../app/selectors";
import { entityLabel, periodLabel } from "../lib/formatters";
import { SIGNAL_FAMILIES, signalStatus } from "../lib/status";
import { PageHeader } from "../components/layout/PageHeader";
import { InvestigationTrail } from "../components/dashboard/InvestigationTrail";
import { FindingTable } from "../components/findings/FindingTable";
import { DetailDrawer } from "../components/ui/DetailDrawer";
import {
  BackendProse,
  ConceptList,
  DataRow,
  Frame,
  Section,
} from "../components/ui/Surface";
import {
  SelectFilter,
  TextFilter,
  type SelectOption,
} from "../components/ui/Filters";
import {
  EmptyState,
  LimitationNote,
  LoadingState,
  StatusBadge,
} from "../components/ui/State";

/**
 * Findings: every finding in the loaded run.
 *
 * The backend's four signal families, in one list. The screen states the
 * backend's own total before it offers any filter, because a filtered count is
 * only meaningful against the count it started from.
 *
 * The drawer is where the finding is read. The list stays mounted behind it, so
 * reading a finding and then the next one does not lose the examiner's place in
 * the list or reset the filters.
 */
export function FindingsPage() {
  const { analysis, running } = useAnalysis();
  const { view } = useDashboard();
  const { findings, activeFinding, openFinding, closeFinding } =
    useInvestigation();
  const navigate = useNavigate();

  const [family, setFamily] = useState("all");
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");

  const options = useMemo(() => {
    const statuses = new Set<string>();

    for (const item of findings) {
      if (item.status) {
        statuses.add(item.status);
      }
    }

    return {
      family: [
        { value: "all", label: "All families" },
        ...SIGNAL_FAMILIES.map((entry) => ({ value: entry.id, label: entry.label })),
      ] satisfies SelectOption[],
      status: [
        { value: "all", label: "Any status" },
        ...[...statuses]
          .sort()
          .map((value) => ({ value, label: value })),
      ] satisfies SelectOption[],
    };
  }, [findings]);

  const filtered = useMemo(
    () =>
      findings.filter((item) => {
        if (family !== "all" && item.family !== family) {
          return false;
        }

        if (status !== "all" && item.status !== status) {
          return false;
        }

        if (query.trim()) {
          const needle = query.trim().toLowerCase();
          const haystack = `${item.indicator} ${item.reason} ${entityLabel(item.entity)}`.toLowerCase();

          if (!haystack.includes(needle)) {
            return false;
          }
        }

        return true;
      }),
    [findings, family, status, query],
  );

  if (analysis?.status === "error") {
    return (
      <>
        <PageHeader title="Findings" />
        <EmptyState
          title="The assessment run failed"
          description={analysis.error ?? "The pipeline reported an error."}
          action={
            <Link
              to="/"
              className="text-[13px] font-medium text-accent underline-offset-2 hover:underline"
            >
              Back to overview
            </Link>
          }
        />
      </>
    );
  }

  if (!view.hasResult) {
    return running ? (
      <LoadingState
        title="Assessment in progress"
        detail="Findings appear once the pipeline completes."
      />
    ) : (
      <EmptyState
        title="No assessment loaded"
        description="Run an assessment before reading findings."
        action={
          <Link
            to="/assessments/new"
            className="text-[13px] font-medium text-accent underline-offset-2 hover:underline"
          >
            Start an assessment
          </Link>
        }
      />
    );
  }

  const total = view.findings.total;

  return (
    <>
      <InvestigationTrail
        findingIndicator={activeFinding?.indicator ?? null}
      />

      <PageHeader
        title="Findings"
        supporting={
          <>
            {/*
              The total is stated as a number even when it is zero. "No findings"
              alone cannot be told apart from a count that was never
              transported, and telling those apart is the whole point of this
              screen: an examiner has to know whether the pipeline looked and
              found nothing, or whether nobody reported anything.
            */}
            {total === 0 ? (
              <>
                <span className="tabular font-medium text-text">0</span> findings
                reported by the pipeline for this assessment.
              </>
            ) : total === 1 ? (
              <>
                <span className="tabular font-medium text-text">1</span> finding
                reported by the pipeline across{" "}
                {SIGNAL_FAMILIES.length} signal families.
              </>
            ) : (
              <>
                <span className="tabular font-medium text-text">{total}</span>{" "}
                findings reported by the pipeline across {SIGNAL_FAMILIES.length}{" "}
                signal families.
              </>
            )}
          </>
        }
      />

      <Section
        title="All findings"
        description="Select a finding to read the pipeline's own account of it."
      >
        <div className="mb-3 flex min-w-0 flex-wrap items-end gap-x-3 gap-y-2">
          <TextFilter
            label="Search"
            value={query}
            onChange={setQuery}
            placeholder="Indicator, reason or entity"
            className="min-w-[220px] flex-1"
          />
          <SelectFilter
            label="Family"
            value={family}
            options={options.family}
            onChange={setFamily}
            hideLabel
          />
          <SelectFilter
            label="Status"
            value={status}
            options={options.status}
            onChange={setStatus}
            hideLabel
          />
        </div>

        <FindingTable
          findings={filtered}
          onOpen={openFinding}
          selectedKey={activeFinding?.key ?? null}
          emptyTitle={
            findings.length === 0
              ? "No findings reported"
              : "No findings match these filters"
          }
          emptyDescription={
            findings.length === 0
              ? "Every signal family ran for this assessment and reported zero findings. That is different from an assessment that did not run."
              : `${filtered.length} of ${findings.length} findings match. Clear a filter to see the rest.`
          }
        />

        <p className="mt-2 text-[11px] leading-relaxed text-text-tertiary">
          Findings are statements the pipeline made about the evidence supplied.
          They are not conclusions about conduct, and none of them is a control
          failure on its own.
        </p>
      </Section>

      <FindingDetailDrawer
        finding={activeFinding}
        onClose={closeFinding}
        onOpenScope={(assessmentId) =>
          navigate(`/assessments/${encodeURIComponent(assessmentId)}`)
        }
      />
    </>
  );
}

/**
 * The finding, read.
 *
 * The backend's wording throughout. `reason` is shown as prose because it is the
 * pipeline's explanation of itself; the structured fields beside it are what a
 * reader would otherwise have to take on trust.
 */
function FindingDetailDrawer({
  finding,
  onClose,
  onOpenScope,
}: {
  finding: UnifiedFinding | null;
  onClose: () => void;
  onOpenScope: (assessmentId: string) => void;
}) {
  if (!finding) {
    return null;
  }

  const raw = finding.finding as Record<string, unknown>;
  const status = signalStatus(finding.status);
  const limitations = [
    ...(Array.isArray(raw.explanation_limitations)
      ? (raw.explanation_limitations as unknown[]).map(String)
      : []),
    ...(typeof raw.is_not_a_control_failure === "string"
      ? [raw.is_not_a_control_failure]
      : []),
  ];

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
          {finding.familyLabel} &middot;{" "}
          {finding.entity.available ? (
            <>
              {entityLabel(finding.entity)}
              {finding.period.available
                ? `, ${periodLabel(finding.period)}`
                : ", period not determined"}
            </>
          ) : (
            "Entity not identified"
          )}
        </>
      }
      footer={
        <button
          type="button"
          className="text-[13px] text-accent underline-offset-2 hover:underline"
          onClick={() => onOpenScope(finding.assessment_id)}
        >
          Open the scope this finding belongs to
        </button>
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
          {typeof raw.rule_name === "string" ? (
            <DataRow label="Rule" value={raw.rule_name} />
          ) : null}
          {typeof raw.capability === "string" ? (
            <DataRow label="Capability" value={raw.capability} />
          ) : null}
        </Frame>

        <div>
          <p className="section-label">Why the pipeline reported this</p>
          <div className="mt-1.5">
            <BackendProse>
              {typeof raw.reason === "string" ? raw.reason : finding.reason}
            </BackendProse>
          </div>
        </div>

        {finding.evidenceConcepts.length > 0 ? (
          <div>
            <p className="section-label">Evidence concepts</p>
            <div className="mt-1.5">
              <ConceptList concepts={finding.evidenceConcepts} />
            </div>
          </div>
        ) : null}

        {limitations.length > 0 ? (
          <div className="min-w-0 space-y-1.5">
            <p className="section-label">Stated limitations</p>
            {limitations.map((limitation) => (
              <LimitationNote key={limitation}>{limitation}</LimitationNote>
            ))}
          </div>
        ) : null}
      </div>
    </DetailDrawer>
  );
}
