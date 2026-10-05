import { Link } from "react-router-dom";

import { formatCount } from "../lib/formatters";

import { useAnalysis } from "../app/AnalysisContext";
import { useDashboard } from "../app/DashboardContext";
import { PageHeader } from "../components/layout/PageHeader";
import { EntityAttentionTable } from "../components/dashboard/EntityAttentionTable";
import { Button } from "../components/ui/Button";
import { EmptyState, LoadingState } from "../components/ui/State";
import { Contain } from "../components/ui/Surface";

/**
 * Assessments: every scope the run produced.
 *
 * The same table the Overview uses to prioritise, with the period added, because
 * this is the screen where an examiner confirms that the scopes are the ones
 * they expected before investigating any of them. The Overview answers "where do
 * I start"; this one answers "is the set right".
 *
 * Both screens read one ordered set from the shared view model, so the order
 * cannot drift between them.
 */
export function AssessmentsPage() {
  const { running } = useAnalysis();
  const { view } = useDashboard();
  const { hasResult, entities, status } = view;

  const subject = view.run.datasetName;

  if (!hasResult) {
    return (
      <>
        <PageHeader title="Assessments" />

        {running ? (
          <LoadingState
            title="Assessment in progress"
            detail="Scopes appear here once the pipeline completes."
          />
        ) : (
          <EmptyState
            title="No assessment loaded"
            description="Run an assessment to see the scopes it produced."
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

  const scopeCount = status.scopes;

  return (
    <>
      <PageHeader
        title="Assessment scopes"
        supporting={
          scopeCount === null ? (
            "The pipeline did not report how many scopes it produced."
          ) : (
            <>
              {scopeCount === 1
                ? "1 assessment scope"
                : `${scopeCount} assessment scopes`}
              {subject ? ` in ${subject}` : ""}
              {status.records === null
                ? ", over a record count the pipeline did not report."
                : `, over ${formatCount(status.records)} records.`}
            </>
          )
        }
        actions={
          <Button variant="secondary" size="sm" onClick={() => window.print()}>
            Print
          </Button>
        }
      />

      <Contain>
        <EntityAttentionTable
          rows={entities}
          showPeriod
          sort="backend"
          caption="A scope is one entity over one period, as the pipeline grouped the records, in the order the pipeline reported them. Opening a scope keeps this assessment loaded, so returning here does not re-run anything."
        />
      </Contain>
    </>
  );
}
