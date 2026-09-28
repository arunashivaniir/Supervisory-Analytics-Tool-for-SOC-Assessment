import { RefreshCw } from "lucide-react";

import { useAnalysis } from "../../app/AnalysisContext";
import { cn } from "../../lib/cn";
import { datasetName } from "../../lib/formatters";
import { Button } from "../ui/Button";
import { StatusBadge } from "../ui/StatusBadge";
import type { Tone } from "../../lib/status";

/**
 * The top bar: which evidence is on screen, and whether it has been analysed.
 *
 * Two facts and one action. No account menu, no notifications, no avatar:
 * this is an examination instrument, not an application with a signed-in user.
 *
 * The dataset named here is the one the screens are showing. While a different
 * dataset is being assessed that fact does not change: the pending run is named
 * separately, as something in progress, so a switch is never mistaken for a
 * completed result.
 */
export function TopBar({ onSelectDataset }: { onSelectDataset: () => void }) {
  const { analysis, result, running, pending, refresh } = useAnalysis();

  const subject = result ? datasetName(result.dataset) : null;

  const { label, tone } = describeStatus({
    hasRun: Boolean(analysis),
    running,
    switching: pending !== null,
    result,
  });

  return (
    <header
      className="flex h-[52px] shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-5"
      data-print-hide
    >
      <div className="flex min-w-0 items-center gap-4">
        <div className="min-w-0">
          <div className="section-label">Dataset</div>
          {subject ? (
            <div className="truncate text-[13px] font-medium text-text" title={result?.dataset}>
              {subject}
            </div>
          ) : analysis ? (
            <div className="truncate text-[13px] font-medium text-text-tertiary italic">
              {analysis.dataset.split("/").pop()}
            </div>
          ) : (
            <div className="text-[13px] font-medium text-text-tertiary italic">
              None selected
            </div>
          )}
        </div>

        {pending ? (
          <div className="min-w-0 border-l border-border pl-4">
            <div className="section-label">Assessing</div>
            <div
              className="truncate text-[13px] font-medium text-info"
              title={pending.dataset}
            >
              {datasetName(pending.dataset)}
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-2.5">
        <StatusBadge tone={tone} label={label} showDot={!running && !pending} />

        <div className="h-5 w-px bg-border" aria-hidden="true" />

        <Button
          size="sm"
          variant="outline"
          onClick={() => void refresh()}
          disabled={!analysis || running || pending !== null}
          title={
            analysis
              ? "Re-read the current analysis from the local service"
              : "No analysis to refresh"
          }
        >
          <RefreshCw
            className={cn("size-3", running && "animate-spin")}
            aria-hidden="true"
          />
          Refresh
        </Button>

        <Button size="sm" variant="ghost" onClick={onSelectDataset}>
          {analysis ? "Change dataset" : "Select dataset"}
        </Button>
      </div>
    </header>
  );
}

function describeStatus({
  hasRun,
  running,
  switching,
  result,
}: {
  hasRun: boolean;
  running: boolean;
  switching: boolean;
  result: unknown;
}): { label: string; tone: Tone } {
  if (switching) {
    // The loaded assessment is still on screen, so this is not "processing":
    // something is being produced, and what is loaded has not changed.
    return { label: "Switching", tone: "info" };
  }

  if (running) {
    return { label: "Processing", tone: "info" };
  }

  if (hasRun && result) {
    return { label: "Analysis complete", tone: "positive" };
  }

  if (hasRun) {
    return { label: "Error", tone: "critical" };
  }

  return { label: "No analysis", tone: "neutral" };
}
