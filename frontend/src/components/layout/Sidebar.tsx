import {
  Activity,
  ClipboardList,
  FileText,
  LayoutGrid,
  ScrollText,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { cn } from "../../lib/cn";
import { useAnalysis } from "../../app/AnalysisContext";

/**
 * The primary navigation.
 *
 * Five destinations, named for what the examiner is doing rather than for the
 * layers that produced the data. No layer names, no model names, no internal
 * terminology: the intelligence that runs underneath is the backend's concern.
 */

const NAV = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  { to: "/assessments", label: "Assessments", icon: ClipboardList, end: false },
  { to: "/findings", label: "Findings", icon: Activity, end: false },
  { to: "/evidence", label: "Evidence", icon: ScrollText, end: false },
  { to: "/reports", label: "Reports", icon: FileText, end: false },
] as const;

export function Sidebar() {
  const { result } = useAnalysis();

  return (
    <aside
      className="flex w-[196px] shrink-0 flex-col border-r border-border bg-surface"
      data-print-hide
    >
      <div className="flex h-[52px] items-center border-b border-border px-4">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold tracking-tight text-primary">
            SAT-SA
          </div>
          <div className="micro leading-tight text-text-tertiary">
            Supervisory Analytics
          </div>
        </div>
      </div>

      <nav className="flex-1 px-2 py-3" aria-label="Primary">
        <ul className="flex flex-col gap-0.5">
          {NAV.map((item) => {
            const Icon = item.icon;

            return (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 rounded-[8px] px-2.5 py-1.5",
                      "text-[13px] font-medium transition-colors duration-100",
                      isActive
                        ? "bg-accent-subtle text-accent"
                        : "text-text-secondary hover:bg-subtle hover:text-text",
                    )
                  }
                >
                  <Icon className="size-3.5 shrink-0" aria-hidden="true" />
                  {item.label}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      {/*
        The subject of the current assessment, always visible. An examiner
        should be able to confirm which evidence is on screen from any page.
      */}
      <div className="border-t border-border px-4 py-3" data-print-hide>
        <div className="section-label">Subject</div>
        {result ? (
          <p
            className="mt-1 truncate micro text-text-secondary"
            title={result.dataset}
          >
            {result.dataset.split("/").pop()}
          </p>
        ) : (
          <p className="mt-1 micro text-text-tertiary italic">No analysis</p>
        )}
      </div>
    </aside>
  );
}
