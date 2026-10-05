import { useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { FolderOpen, RefreshCw } from "lucide-react";

import { useAnalysis } from "./AnalysisContext";
import { useDashboard } from "./DashboardContext";
import { Sidebar } from "../components/layout/Sidebar";
import { DatasetSwitcher } from "../components/assessment/DatasetSwitcher";
import { Button } from "../components/ui/Button";
import { StatusBadge } from "../components/ui/State";
import { runStatusLabel, runStatusTone, runTimestamp } from "./viewModel";
import { datasetName as datasetStem } from "../lib/formatters";
import { formatRunTime } from "../services/evidenceRegister";

/**
 * The application shell.
 *
 * A fixed sidebar, a compact header carrying the run's identity and state, and
 * one scrolling content column.
 *
 * The header is a `<header>` because it is the document's banner and because it
 * is the single place the run's state is stated. Every screen reads the same
 * value from the same component, so "Analysis complete" cannot mean two
 * different things on two pages.
 */
export function AppShell() {
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const { cancelPending, refresh } = useAnalysis();
  const { view } = useDashboard();
  const navigate = useNavigate();

  // From the lifecycle, not from the phase. The phase alone cannot tell a queued
  // run from a held-nothing, and inferring activity from it is what let the
  // shell report a busy pipeline with no dataset selected.
  const assessing = view.lifecycle === "ASSESSING";
  const timestamp = runTimestamp(view.run);

  return (
    <div className="flex h-screen min-h-screen bg-canvas">
      <Sidebar onNewAssessment={() => navigate("/assessments/new")} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex min-h-[52px] shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-surface px-4 py-2"
          data-print-hide
        >
          <div className="flex min-w-0 items-center gap-3">
            {/*
              The loaded dataset and the run state, as sibling elements.

              "Dataset" and its value are separate elements rather than a label
              and a paragraph inside one wrapper, because the header is read
              programmatically by the dataset-switching check: it finds the
              Dataset label and takes the element that follows it. Keeping the
              loaded dataset here and the pending one in the status badge is
              also what makes a switch honest — the assessment on screen has not
              changed while a replacement is produced behind it.
            */}
            <div className="min-w-0">
              <div className="section-label">Dataset</div>
              <div
                className="max-w-[42vw] truncate text-[13px] font-medium text-text md:max-w-[26vw]"
                title={view.run.datasetPath ?? view.run.datasetName ?? undefined}
              >
                {/*
                  The stem, as every screen names a dataset. The full path is on
                  the element's title, so the file is still identifiable without
                  making the running header wrap.
                */}
                {view.run.datasetName
                  ? datasetStem(view.run.datasetName)
                  : "No dataset selected"}
              </div>
            </div>

            <div className="min-w-0 border-l border-border pl-3">
              <div className="section-label">Last run</div>
              <div className="tabular whitespace-nowrap text-[13px] text-text-secondary">
                {formatRunTime(timestamp)}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <StatusBadge
              tone={runStatusTone(view.run)}
              label={runStatusLabel(view.run)}
              raw={view.run.statusToken}
              showDot
            />

            {view.run.switching && view.run.pendingDatasetName ? (
              <span className="min-w-0 max-w-[24vw] truncate text-[13px] text-info">
                {view.run.pendingDatasetName}
              </span>
            ) : null}

            {view.run.switching ? (
              <Button size="sm" variant="ghost" onClick={cancelPending}>
                Cancel switch
              </Button>
            ) : null}

            <Button
              size="sm"
              variant="ghost"
              onClick={() => void refresh()}
              disabled={!view.run.jobId || assessing || view.run.switching}
              aria-label="Re-read the current run"
            >
              <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
              Refresh
            </Button>

            <Button
              size="sm"
              variant="secondary"
              onClick={() => setSwitcherOpen(true)}
            >
              <FolderOpen aria-hidden="true" className="h-3.5 w-3.5" />
              Change dataset
            </Button>
          </div>
        </header>

        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden">
          <div className="mx-auto w-full min-w-0 max-w-[1400px] px-5 py-5">
            <Outlet />
          </div>
        </main>
      </div>

      <DatasetSwitcher open={switcherOpen} onOpenChange={setSwitcherOpen} />
    </div>
  );
}
