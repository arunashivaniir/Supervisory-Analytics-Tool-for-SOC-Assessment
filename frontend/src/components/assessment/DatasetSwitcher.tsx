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
 *
 * The steps after selection are deliberately thin. Pre-run validation covers
 * what can be known before the pipeline reads the file; field mapping is
 * reported by the pipeline itself after the run, and the mapping step shows
 * the mapping observed on the loaded assessment so the examiner knows what
 * "mapped" means here before starting another run.
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
  const [step, setStep] = useState(0);

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
                New assessment
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
              <ol className="mt-2 flex flex-wrap gap-1.5" aria-label="Progress">
                {STEPS.map((label, index) => (
                  <li key={label}>
                    <button
                      type="button"
                      onClick={() => {
                        if (index === 0 || chosen) {
                          setStep(index);
                        }
                      }}
                      disabled={index !== 0 && !chosen}
                      aria-current={step === index ? "step" : undefined}
                      className={cn(
                        "rounded-[6px] border px-2 py-0.5 micro font-medium",
                        step === index
                          ? "border-accent bg-accent-subtle text-accent"
                          : "border-border bg-surface text-text-tertiary",
                        index !== 0 &&
                          !chosen &&
                          "cursor-not-allowed opacity-50",
                      )}
                    >
                      {index + 1}. {label}
                    </button>
                  </li>
                ))}
              </ol>
            </div>
            <DialogPrimitive.Close
              className="shrink-0 rounded-[6px] p-1 text-text-tertiary hover:bg-subtle hover:text-text"
              aria-label="Close"
            >
              <X className="size-4" aria-hidden="true" />
            </DialogPrimitive.Close>
          </header>

          {step === 0 ? (
          <>
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
          </>
          ) : null}

          {step === 1 ? <ValidateStep chosen={chosen} /> : null}

          {step === 2 ? <MappingStep /> : null}

          {step === 3 ? (
            <ConfirmStep
              chosenPath={chosen?.path ?? null}
              currentDataset={currentDataset}
            />
          ) : null}

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
              {step > 0 ? (
                <Button
                  variant="ghost"
                  onClick={() => setStep(step - 1)}
                  disabled={busy}
                >
                  Back
                </Button>
              ) : (
                <Button variant="ghost" onClick={onClose}>
                  {pending ? "Keep current" : "Cancel"}
                </Button>
              )}
              {step < 3 ? (
                <Button
                  variant="primary"
                  disabled={!chosen || busy}
                  onClick={() => setStep(step + 1)}
                >
                  Continue
                </Button>
              ) : (
                <Button
                  variant="primary"
                  disabled={!chosen || busy}
                  onClick={() => {
                    if (chosen) {
                      void run(chosen.path);
                      onClose();
                    }
                  }}
                >
                  {busy
                    ? "Assessing…"
                    : currentDataset
                      ? "Switch to this dataset"
                      : "Run assessment"}
                </Button>
              )}
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

const STEPS = ["Select", "Validate", "Mapping", "Confirm"] as const;

/**
 * What can be checked before the pipeline reads the file.
 *
 * File metadata only: the pipeline performs the real validation (structure,
 * required evidence, encoding) once the run starts, and a run that fails
 * validation reports its reason without touching the loaded assessment.
 */
function ValidateStep({
  chosen,
}: {
  chosen: {
    path: string;
    filename: string;
    size_bytes: number;
    modified: number;
  } | null;
}) {
  if (!chosen) {
    return (
      <div className="px-4 py-6">
        <EmptyState
          title="No dataset selected"
          description="Go back to Select and choose a file first."
        />
      </div>
    );
  }

  const modified = new Date(chosen.modified * 1000).toISOString().slice(0, 10);

  return (
    <div className="max-h-[46vh] overflow-y-auto px-4 py-3">
      <dl className="divide-y divide-border/70">
        <div className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] gap-3 py-1.5">
          <dt className="text-xs text-text-secondary">File</dt>
          <dd className="min-w-0 break-all text-[13px] text-text">
            {chosen.filename}
          </dd>
        </div>
        <div className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] gap-3 py-1.5">
          <dt className="text-xs text-text-secondary">Path</dt>
          <dd className="min-w-0 break-all font-mono micro text-text-secondary">
            {chosen.path}
          </dd>
        </div>
        <div className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] gap-3 py-1.5">
          <dt className="text-xs text-text-secondary">Size</dt>
          <dd className="text-[13px] text-text">
            {formatBytes(chosen.size_bytes)}
          </dd>
        </div>
        <div className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] gap-3 py-1.5">
          <dt className="text-xs text-text-secondary">Last modified</dt>
          <dd className="text-[13px] text-text">{modified}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-text-secondary">
        On run, the pipeline validates the submission: readable structure,
        recognisable timestamp, analyst and closure variants, and the evidence
        each capability needs. A file that fails validation is refused with a
        reason; the assessment on screen is unchanged.
      </p>
    </div>
  );
}

/**
 * How incoming fields become canonical concepts.
 *
 * The mapping itself is the pipeline's work, reported after the run. This
 * step shows the authoritative Phase 1 decision counts observed on the
 * loaded assessment (not the legacy confidence bands), so the examiner
 * sees what "mapped" means here — including which columns stayed
 * low-confidence, ambiguous, invalid or unmapped — before starting
 * another run. Full review lives on the Evidence screen.
 */
function MappingStep() {
  const { result } = useAnalysis();
  const report = result?.mapping_report ?? null;
  const canonical = result?.canonical_package ?? null;
  const states = canonical?.mapping_states ?? null;

  if (!report) {
    return (
      <div className="px-4 py-6">
        <EmptyState
          title="No mapping observed yet"
          description="No assessment is loaded, so there is no mapping to show. The pipeline reports its canonical mapping after the run, on the Evidence screen."
        />
      </div>
    );
  }

  const bands: Array<{
    label: string;
    entries: typeof report.high_confidence;
  }> = [
    { label: "High confidence", entries: report.high_confidence },
    { label: "Medium confidence", entries: report.medium_confidence },
    { label: "Low confidence", entries: report.low_confidence },
  ];

  return (
    <div className="max-h-[46vh] overflow-y-auto px-4 py-3">
      <p className="text-xs leading-relaxed text-text-secondary">
        Mapping observed on{" "}
        <span className="font-medium text-text">
          {datasetName(result?.dataset ?? "")}
        </span>
        {states ? (
          <>
            : {states.MAPPED ?? 0} mapped · {states.LOW_CONFIDENCE ?? 0} low
            confidence · {states.AMBIGUOUS ?? 0} ambiguous ·{" "}
            {states.UNMAPPED ?? 0} unmapped · {states.INVALID ?? 0} invalid
          </>
        ) : (
          <>
            : {report.mapped_columns} of {report.dataset_columns} columns mapped
            {report.unmapped_columns.length > 0
              ? `, ${report.unmapped_columns.length} unmapped`
              : ", none unmapped"}
          </>
        )}
        . Ambiguous fields are left unmapped rather than guessed.
      </p>
      <p className="mt-1 micro text-text-tertiary">
        Authoritative counts come from Phase 1 decisions. Review and correct
        them on the Evidence screen; analysis must be rerun after any change.
      </p>
      <div className="mt-3 space-y-3">
        {bands.map((band) =>
          band.entries.length === 0 ? null : (
            <div key={band.label}>
              <div className="section-label mb-1">
                {band.label} ({band.entries.length})
              </div>
              <ul className="divide-y divide-border/70 rounded-[8px] border border-border">
                {band.entries.slice(0, 8).map((entry) => (
                  <li
                    key={entry.source_column}
                    className="flex items-baseline justify-between gap-3 px-2.5 py-1.5"
                  >
                    <span className="min-w-0 truncate font-mono micro text-text">
                      {entry.source_column}
                    </span>
                    <span className="shrink-0 text-right micro text-text-secondary">
                      → {entry.canonical_concept} ·{" "}
                      {entry.confidence.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
              {band.entries.length > 8 ? (
                <p className="mt-1 micro text-text-tertiary">
                  +{band.entries.length - 8} more on the Evidence screen
                </p>
              ) : null}
            </div>
          ),
        )}
      </div>
    </div>
  );
}

function ConfirmStep({
  chosenPath,
  currentDataset,
}: {
  chosenPath: string | null;
  currentDataset: string | null;
}) {
  return (
    <div className="px-4 py-3">
      {chosenPath ? (
        <dl className="divide-y divide-border/70">
          <div className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] gap-3 py-1.5">
            <dt className="text-xs text-text-secondary">Dataset</dt>
            <dd className="min-w-0 break-all text-[13px] font-medium text-text">
              {datasetName(chosenPath)}
            </dd>
          </div>
          <div className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)] gap-3 py-1.5">
            <dt className="text-xs text-text-secondary">Effect</dt>
            <dd className="text-[13px] text-text-secondary">
              {currentDataset
                ? "The loaded assessment stays on screen until the new run completes."
                : "This becomes the loaded assessment once the run completes."}
            </dd>
          </div>
        </dl>
      ) : (
        <EmptyState
          title="No dataset selected"
          description="Go back to Select and choose a file first."
        />
      )}
      <p className="mt-3 text-xs leading-relaxed text-text-secondary">
        Running starts the supervisory analytics: validation, canonical
        mapping, execution-gap, negative-space, operational-pattern and anomaly
        layers. Nothing is modified in the submission; the pipeline reads a
        controlled copy.
      </p>
    </div>
  );
}
