import { Link } from "react-router-dom";

import { formatCount } from "../../lib/formatters";
import type { FindingSummaryView } from "../../app/viewModel";
import { EmptyState } from "../ui/State";

/**
 * A compact finding summary for the Overview.
 *
 * The total, then the family split, then a route to the full list. It
 * deliberately does not reproduce the Findings page: an examiner reading the
 * Overview wants to know how much there is and where to go, not to read it
 * twice.
 */
export function FindingSummary({
  findings,
  entityFilterHref,
}: {
  findings: FindingSummaryView;
  /** Set when the summary is scoped to one entity, so the link stays scoped. */
  entityFilterHref?: string;
}) {
  const href = entityFilterHref ?? "/findings";

  if (findings.families.length === 0) {
    return (
      <EmptyState
        title="No finding counts reported"
        description="The pipeline did not publish a count for any signal family."
      />
    );
  }

  if (findings.empty) {
    return (
      <div className="min-w-0">
        <p className="text-[13px] text-text">
          No findings reported by the pipeline for this assessment.
        </p>
        <p className="mt-1 text-[13px]">
          <Link
            to={href}
            className="text-accent underline-offset-2 hover:underline"
          >
            View the findings screen
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className="min-w-0">
      <p className="text-[13px] text-text">
        <span className="tabular text-[17px] font-semibold">
          {formatCount(findings.total)}
        </span>{" "}
        {findings.total === 1 ? "finding" : "findings"} reported by the pipeline
      </p>

      <ul className="mt-2 min-w-0 space-y-1">
        {findings.families.map((family) => (
          <li
            key={family.id}
            className="flex min-w-0 items-baseline justify-between gap-3 text-[13px]"
          >
            <span className="min-w-0 truncate text-text-secondary">
              {family.label}
            </span>

            <span className="tabular shrink-0 font-medium text-text">
              {family.count === null ? "Not reported" : formatCount(family.count)}
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[13px]">
        <Link
          to={href}
          className="text-accent underline-offset-2 hover:underline"
        >
          View all findings
        </Link>
      </p>
    </div>
  );
}
