import { NavLink } from "react-router-dom";
import { Plus } from "lucide-react";

import { useDashboard } from "../../app/DashboardContext";

/**
 * The five screens, and nothing else.
 *
 * The order is the assessment sequence rather than an arbitrary arrangement:
 * what changed, who it concerns, what was detected, whether the evidence holds,
 * and the formal record. An examiner walking the product story should be able to
 * read the navigation as that story.
 */
const PRIMARY = [
  { to: "/", label: "Overview", end: true },
  { to: "/assessments", label: "Assessments", end: false },
  { to: "/findings", label: "Findings", end: false },
  { to: "/evidence", label: "Evidence", end: false },
];

const SECONDARY = [{ to: "/reports", label: "Reports", end: false }];

function NavItem({
  to,
  label,
  end,
}: {
  to: string;
  label: string;
  end: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `block truncate rounded-[8px] px-2.5 py-1.5 text-[13px] transition-colors ${
          isActive
            ? "bg-accent-subtle font-medium text-accent"
            : "text-text-secondary hover:bg-subtle hover:text-text"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

export function Sidebar({ onNewAssessment }: { onNewAssessment: () => void }) {
  const { view } = useDashboard();
  const subject = view.run.datasetName;

  return (
    <aside
      className="hidden w-[184px] shrink-0 flex-col border-r border-border bg-surface md:flex"
      data-print-hide
    >
      <div className="flex h-[52px] shrink-0 items-center px-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-semibold text-primary">
            SAT-SA
          </p>
          <p className="truncate text-[11px] text-text-tertiary">
            Supervisory Analytics
          </p>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-2 py-3">
        <button
          type="button"
          onClick={onNewAssessment}
          className="flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-[8px] bg-primary px-2 text-[13px] font-medium text-white transition-colors hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-accent"
        >
          <Plus aria-hidden="true" className="h-3.5 w-3.5" />
          New assessment
        </button>

        <nav aria-label="Assessment screens" className="min-w-0 space-y-0.5">
          {PRIMARY.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>

        <nav aria-label="Records" className="min-w-0 space-y-0.5">
          <p className="section-label px-2.5 pb-1">Record</p>
          {SECONDARY.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>
      </div>

      <div className="shrink-0 border-t border-border px-3 py-2.5">
        <p className="section-label">Subject</p>
        <p
          className="mt-0.5 truncate text-xs text-text-secondary"
          title={subject ?? undefined}
        >
          {subject ?? "No assessment loaded"}
        </p>
      </div>
    </aside>
  );
}
