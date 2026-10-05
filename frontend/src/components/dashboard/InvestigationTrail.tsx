import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";

import { entityLabel, periodLabel } from "../../lib/formatters";
import { useDashboard } from "../../app/DashboardContext";
import { useInvestigation } from "../../app/InvestigationContext";
import { Truncate } from "../ui/Table";

/**
 * Where the examiner is, and how to get back.
 *
 * The failure this prevents: an examiner opens an entity, opens a finding, and
 * the screen they return to is no longer the screen they left. Three things are
 * always visible — the assessment, the entity, and the finding — and each is a
 * link to the level above it.
 *
 * The assessment is the dataset name the backend reported, not the job id: the
 * job id is shown alongside it on the Reports screen where it matters, and
 * putting a hex string at the top of every page would cost more than it gives.
 */
export function InvestigationTrail({
  entityAssessmentId,
  findingIndicator,
}: {
  /** The scope being investigated, if any. */
  entityAssessmentId?: string | null;
  /** The finding being read, if any. */
  findingIndicator?: string | null;
}) {
  const { view } = useDashboard();
  const { assessmentId } = useInvestigation();

  const scopeId = entityAssessmentId ?? assessmentId ?? null;
  const row = scopeId
    ? view.entities.find((entity) => entity.assessmentId === scopeId)
    : null;

  const entityText = row ? entityLabel(row.entity) : null;
  const periodText = row ? periodLabel(row.period) : null;

  return (
    <div aria-label="Investigation trail" className="mb-4 min-w-0">
      <ol className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
        <li className="min-w-0">
          <Link
            to="/"
            className="rounded-[4px] text-text-secondary hover:text-text hover:underline"
          >
            Assessment
          </Link>
        </li>

        {view.run.datasetName ? (
          <>
            <Chevron aria-hidden="true" />
            <li className="min-w-0 max-w-[46vw]">
              <span
                className="block truncate text-text-tertiary"
                title={view.run.datasetName}
              >
                {view.run.datasetName}
              </span>
            </li>
          </>
        ) : null}

        {row && entityText ? (
          <>
            <Chevron aria-hidden="true" />
            <li className="min-w-0 max-w-[46vw]">
              <Link
                to={`/assessments/${encodeURIComponent(row.assessmentId)}`}
                className="block truncate font-medium text-text hover:underline"
                title={entityText}
              >
                {entityText}
              </Link>
            </li>

            {periodText ? (
              <>
                <Chevron aria-hidden="true" />
                <li className="min-w-0 max-w-[36vw]">
                  <Truncate
                    className="text-text-tertiary"
                    title={`Period ${periodText}`}
                  >
                    {periodText}
                  </Truncate>
                </li>
              </>
            ) : null}
          </>
        ) : null}

        {findingIndicator ? (
          <>
            <Chevron aria-hidden="true" />
            <li className="min-w-0 max-w-[40vw]">
              <Truncate
                className="font-medium text-text"
                title={findingIndicator}
              >
                {findingIndicator}
              </Truncate>
            </li>
          </>
        ) : null}
      </ol>
    </div>
  );
}

function Chevron({ className = "" }: { className?: string }) {
  return (
    <li aria-hidden="true" className="shrink-0">
      <ChevronRight className={`h-3 w-3 text-text-tertiary ${className}`} />
    </li>
  );
}
