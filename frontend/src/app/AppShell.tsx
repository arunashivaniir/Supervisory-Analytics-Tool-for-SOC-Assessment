import { useState } from "react";
import { Outlet } from "react-router-dom";

import { DatasetSwitcher } from "../components/assessment/DatasetSwitcher";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";
import { Button } from "../components/ui/Button";
import { useAnalysis } from "./AnalysisContext";

/**
 * The application frame.
 *
 * A fixed sidebar, a fixed top bar, and one scrolling content column. The
 * content column owns its own scroll so the chrome never moves, which keeps
 * the dataset and run status visible while the examiner works through a long
 * findings list.
 *
 * Dataset selection is the top bar's control and lives here, as one dialog for
 * the whole application, so every screen can reach it and there is never a
 * screen that cannot say which dataset is loaded. The error strip sits directly
 * beneath the bar for the same reason: a failure while replacing a dataset is
 * reported where the dataset is named, on every screen, rather than only inside
 * the empty state of whichever page happened to be open.
 */
export function AppShell() {
  const { analysisError, dismissError, result, pending } = useAnalysis();
  const [switcherOpen, setSwitcherOpen] = useState(false);

  return (
    <div className="flex h-screen min-h-screen bg-canvas">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onSelectDataset={() => setSwitcherOpen(true)} />

        {analysisError ? (
          <div
            role="status"
            className="flex items-start justify-between gap-4 border-b border-critical/25 bg-critical-subtle px-5 py-2"
          >
            <p className="min-w-0 text-xs leading-relaxed text-critical">
              {analysisError}
              {result && pending === null
                ? " The assessment on screen is unchanged."
                : null}
            </p>
            <Button
              size="sm"
              variant="ghost"
              className="shrink-0"
              onClick={dismissError}
            >
              Dismiss
            </Button>
          </div>
        ) : null}

        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>

      <DatasetSwitcher open={switcherOpen} onOpenChange={setSwitcherOpen} />
    </div>
  );
}
