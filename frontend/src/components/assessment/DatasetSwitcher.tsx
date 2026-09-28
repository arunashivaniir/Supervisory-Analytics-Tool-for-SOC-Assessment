import * as DialogPrimitive from "@radix-ui/react-dialog";
import { FileSearch, X } from "lucide-react";
import { useMemo, useState } from "react";

import { useAnalysis } from "../../app/AnalysisContext";
import { cn } from "../../lib/cn";
import { datasetName, formatBytes } from "../../lib/formatters";
import { Button } from "../ui/Button";
import { EmptyState, LoadingRows } from "../ui/Metric";
import { TextFilter } from "../ui/Filters";
import { StatusBadge } from "../ui/StatusBadge";

/**
 * Choosing which dataset is on screen.
 *
 * This is a dialog rather than a page, because the five screens are all about a
 * dataset that is already loaded. Replacing it should not mean leaving the
 * assessment, and above all should not mean discarding it: a pending run is
 * kept separate from the loaded one by the shared analysis state, so this dialog
 * can be closed at any point and the screens behind it are exactly as they were.
 *
 * Nothing here is preferred, ranked or recommended. The list is the adapter's
 * own directory listing in path order, and the loaded dataset is marked only so
 * the examiner can see which file is currently loaded. No dataset carries a
 * default.
 */
export function DatasetSwitcher({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-primary/20" />
        <DialogPrimitive.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[min(720px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2",
            "rounded-[10px] border border-border bg-surface focus:outline-none",
          )}
        >
          <SwitcherBody onClose={() => onOpenChange(false)} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/**
 * The dialog's contents, mounted only while it is open.
 *
 * The dialog content is unmounted when it closes, so the filter text and the
 * selection start fresh every time without anything having to be reset
 * afterwards. A dataset that is already loaded is preselected, so reopening
 * starts from the file that is actually on screen rather than an empty
 * selection that invites an accidental re-run of the same file.
 */
function SwitcherBody({ onClose }: { onClose: () => void }) {
  const {
    datasets,
    datasetsError,
    datasetsLoading,
    health,
    reloadDatasets,
    result,
    analysis,
    pending,
    run,
    cancelPending,
    analysisError,
  } = useAnalysis();

  const currentDataset = result?.dataset ?? analysis?.dataset ?? null;

  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(currentDataset);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();

    if (!needle) {
      return datasets;
    }

    return datasets.filter(
      (dataset) =>
        dataset.filename.toLowerCase().includes(needle) ||
        dataset.path.toLowerCase().includes(needle),
    );
  }, [datasets, query]);

  const grouped = useMemo(() => {
    const byDirectory = new Map<string, typeof filtered>();

    for (const dataset of filtered) {
      const group = byDirectory.get(dataset.directory) ?? [];
      group.push(dataset);
      byDirectory.set(dataset.directory, group);
    }

    return [...byDirectory.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  const chosen = datasets.find((item) => item.path === selected) ?? null;
  const busy = pending !== null || analysis?.status === "processing";

  return (
    <>
          <header className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-[13px] font-semibold text-text">
                Select evidence dataset
              </DialogPrimitive.Title>
              <DialogPrimitive.Description className="mt-0.5 text-xs text-text-secondary">
                {currentDataset ? (
                  <>
                    Loaded:{" "}
                    <span className="font-medium text-text">
                      {datasetName(currentDataset)}
                    </span>
                    . The loaded assessment stays on screen until the new one has
                    been produced.
                  </>
                ) : (
                  "Every dataset the local service can open, listed in path order. The assessment is produced by the analysis service."
                )}
              </DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close
              className="shrink-0 rounded-[6px] p-1 text-text-tertiary hover:bg-subtle hover:text-text"
              aria-label="Close"
            >
              <X className="size-4" aria-hidden="true" />
            </DialogPrimitive.Close>
          </header>

          <div className="flex items-end gap-3 border-b border-border px-4 py-3">
            <TextFilter
              label="Filter datasets"
              value={query}
              onChange={setQuery}
              placeholder="File name or path"
              className="w-[300px]"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => void reloadDatasets()}
              disabled={datasetsLoading || busy}
            >
              Rescan
            </Button>
          </div>

          <div className="max-h-[46vh] min-h-[220px] overflow-y-auto">
            {health && !health.pipeline_available ? (
              <p className="border-b border-border px-4 py-2 text-xs text-caution">
                The analysis pipeline could not be loaded:{" "}
                {health.pipeline_error}
              </p>
            ) : null}

            {datasetsError ? (
              <p className="border-b border-border px-4 py-2 text-xs text-critical">
                {datasetsError}
              </p>
            ) : null}

            {pending ? (
              <div className="flex items-center justify-between gap-3 border-b border-border bg-info-subtle px-4 py-2.5">
                <p className="min-w-0 text-xs text-info">
                  <span className="font-medium">Assessing </span>
                  <span className="truncate font-medium">
                    {datasetName(pending.dataset)}
                  </span>
                  . The loaded assessment stays on screen until this finishes.
                </p>
                <Button size="sm" variant="outline" onClick={cancelPending}>
                  Cancel switch
                </Button>
              </div>
            ) : null}

            {datasetsLoading ? (
              <LoadingRows rows={5} />
            ) : filtered.length === 0 ? (
              <EmptyState
                title={datasets.length === 0 ? "No datasets found" : "No match"}
                description={
                  datasets.length === 0
                    ? "No readable dataset files were found in the workspace."
                    : "No dataset in the workspace matches that filter."
                }
              />
            ) : (
              grouped.map(([directory, items]) => (
                <div key={directory}>
                  <div className="sticky top-0 z-10 border-b border-border bg-subtle px-4 py-1.5">
                    <span className="section-label">
                      {directory === "." ? "workspace root" : directory}
                    </span>
                  </div>
                  <ul className="divide-y divide-border">
                    {items.map((dataset) => {
                      const active = dataset.path === selected;
                      const loaded = dataset.path === currentDataset;

                      return (
                        <li key={dataset.path}>
                          <button
                            type="button"
                            onClick={() => setSelected(dataset.path)}
                            aria-pressed={active}
                            disabled={busy}
                            className={cn(
                              "flex w-full items-center justify-between gap-3 px-4 py-2 text-left",
                              "transition-colors duration-75 hover:bg-subtle",
                              "disabled:pointer-events-none disabled:opacity-60",
                              active && "bg-accent-subtle/60",
                            )}
                          >
                            <span className="flex min-w-0 items-center gap-2.5">
                              <FileSearch
                                className="size-3.5 shrink-0 text-text-tertiary"
                                aria-hidden="true"
                              />
                              <span className="min-w-0">
                                <span className="block truncate text-[13px] text-text">
                                  {dataset.filename}
                                </span>
                                <span className="block truncate micro tabular text-text-tertiary">
                                  {dataset.path}
                                </span>
                              </span>
                            </span>
                            <span className="flex shrink-0 items-center gap-2">
                              {loaded ? (
                                <StatusBadge
                                  tone="neutral"
                                  label="Loaded"
                                  showDot={false}
                                />
                              ) : null}
                              <span className="micro tabular text-text-tertiary">
                                {formatBytes(dataset.size_bytes)}
                              </span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </div>

          <footer className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
            <div className="min-w-0 text-xs text-text-secondary">
              {pending ? (
                <span className="text-info">
                  Waiting for {datasetName(pending.dataset)}
                </span>
              ) : chosen ? (
                <span className="truncate">
                  Selected{" "}
                  <span className="font-medium text-text">
                    {datasetName(chosen.path)}
                  </span>
                </span>
              ) : (
                <span className="text-text-tertiary italic">
                  No dataset selected
                </span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button variant="ghost" onClick={onClose}>
                {pending ? "Keep current" : "Cancel"}
              </Button>
              <Button
                variant="primary"
                disabled={!chosen || busy}
                onClick={() => {
                  if (chosen) {
                    void run(chosen.path);
                  }
                }}
              >
                {busy
                  ? "Assessing…"
                  : currentDataset
                    ? "Switch to this dataset"
                    : "Run assessment"}
              </Button>
            </div>
          </footer>

          {analysisError ? (
            <p className="border-t border-border bg-critical-subtle px-4 py-2.5 text-xs text-critical">
              {analysisError} The loaded assessment has not changed.
            </p>
          ) : null}
    </>
  );
}
