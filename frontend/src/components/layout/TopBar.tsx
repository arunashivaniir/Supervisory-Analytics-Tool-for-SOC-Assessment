import { RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useAnalysis } from "../../app/AnalysisContext";
import { useAssessmentBuilder } from "../../app/AssessmentBuilder";
import { cn } from "../../lib/cn";
import { datasetName } from "../../lib/formatters";
import {
  entryForDataset,
  formatRunTime,
  shortHash,
  useEvidenceRegister,
} from "../../services/evidenceRegister";
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
  const { datasets: packageDatasets } = useAssessmentBuilder();
  const { items: evidenceItems } = useEvidenceRegister();
  const navigate = useNavigate();

  const subject = result ? datasetName(result.dataset) : null;
  const evidenceEntry = result
    ? entryForDataset(evidenceItems, result.dataset)
    : null;
  const lastRun = analysis
    ? (analysis.finished_at ?? analysis.started_at)
    : null;

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
          <div className="section-label">
            {analysis || result
              ? "Dataset"
              : packageDatasets.length > 0
                ? "Assessment"
                : "Dataset"}
          </div>
          {subject ? (
            <div className="truncate text-[13px] font-medium text-text" title={result?.dataset}>
              {subject}
            </div>
          ) : analysis ? (
            <div className="truncate text-[13px] font-medium text-text-tertiary italic">
              {analysis.dataset.split("/").pop()}
            </div>
          ) : packageDatasets.length > 0 ? (
            <div
              className="truncate text-[13px] font-medium text-text"
              title={packageDatasets.join(", ")}
            >
              Assessment package ·{" "}
              {packageDatasets.length === 1
                ? "1 dataset"
                : `${packageDatasets.length} datasets`}
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

        {analysis ? (
          <div className="hidden min-w-0 border-l border-border pl-4 lg:block">
            <div className="section-label">Last run</div>
            <div className="truncate text-[13px] text-text-secondary">
              {lastRun ? formatRunTime(lastRun) : "Not recorded"}
              {evidenceItems !== null ? (
                <span
                  className="font-mono"
                  title={
                    evidenceEntry?.registered_sha256 ??
                    "This dataset matches no registered submission"
                  }
                >
                  {" "}
                  · {shortHash(evidenceEntry?.registered_sha256 ?? null)}
                </span>
              ) : null}
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
        {!analysis && packageDatasets.length > 0 ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigate("/assessments/new")}
            title="Return to the assessment package under review"
          >
            Review package
          </Button>
        ) : null}
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
