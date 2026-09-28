import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  AdapterError,
  completedResult,
  fetchAnalysis,
  fetchAnalysisList,
  fetchDatasets,
  fetchHealth,
  startAnalysis,
} from "../services/api";
import type {
  AnalysisState,
  DatasetEntry,
  HealthState,
  PipelineResult,
} from "../types/pipeline";

/**
 * Analysis state, shared by every screen.
 *
 * A single analysis is current at a time. Holding it in one place is what lets
 * the Overview, Assessments, Findings, Evidence and Reports screens agree
 * without each of them re-fetching or re-deriving anything.
 *
 * The result is stored exactly as the adapter returned it. No screen is given
 * a pre-summarised or pre-counted version of it.
 *
 * Choosing a different dataset is a *change to what is on screen*, so it is
 * modelled as a replacement in two steps rather than as a fresh start. A run
 * that has been asked for but has not finished is a **pending** run, held
 * separately from the current one:
 *
 *   current analysis  →  everything on screen, including its result
 *   pending run       →  a dataset chosen to replace it, not yet produced
 *
 * The pending run is promoted into the current one only once it has actually
 * completed. Until then the screens keep showing the assessment that is already
 * loaded, and if the run fails or is cancelled the loaded assessment is still
 * there. An examiner who starts the wrong file, or who cancels, never loses a
 * finished assessment to get it back.
 */

interface PendingRun {
  /** The dataset that was asked for. */
  dataset: string;
  /** The adapter's identifier for the run. */
  jobId: string;
}

export interface AnalysisContextValue {
  /** Datasets the adapter can open. A listing, not a recommendation. */
  datasets: DatasetEntry[];
  datasetsError: string | null;
  datasetsLoading: boolean;

  health: HealthState | null;

  /** The current run's lifecycle, or null when nothing has been started. */
  analysis: AnalysisState | null;
  /** The completed pipeline result, or null when there is not one. */
  result: PipelineResult | null;
  /** True while the current run is in flight. */
  running: boolean;
  /** Set when the current run or fetch failed. */
  analysisError: string | null;

  /**
   * A run that has been asked for but has not been promoted.
   *
   * Null unless a dataset switch is in flight, so its presence is the
   * interface's single answer to "is another assessment being produced?".
   */
  pending: PendingRun | null;
  /**
   * True when a switch is under way while a loaded assessment stays on screen.
   *
   * This is the state a failure or a cancellation has to return to.
   */
  switching: boolean;

  /** Start a run. A pending run is promoted only once it completes. */
  run: (dataset: string) => Promise<void>;
  /** Stop waiting for a pending run. The loaded assessment is untouched. */
  cancelPending: () => void;
  /** Re-read the current run. */
  refresh: () => Promise<void>;
  /** Dismiss a reported error without changing what is loaded. */
  dismissError: () => void;
  /** Re-read the dataset listing. */
  reloadDatasets: () => Promise<void>;
}

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

/** How often a running job is polled, in milliseconds. */
const POLL_INTERVAL = 2000;

function messageFor(error: unknown, fallback: string): string {
  return error instanceof AdapterError ? error.message : fallback;
}

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [datasets, setDatasets] = useState<DatasetEntry[]>([]);
  const [datasetsError, setDatasetsError] = useState<string | null>(null);
  const [datasetsLoading, setDatasetsLoading] = useState(true);

  const [health, setHealth] = useState<HealthState | null>(null);

  const [analysis, setAnalysis] = useState<AnalysisState | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingRun | null>(null);

  // Read inside callbacks that must see the latest state without being
  // re-created on every render, which would restart polling mid-run. Written
  // after commit rather than during render, so the ref is never read while the
  // component is rendering.
  const latest = useRef<{
    analysis: AnalysisState | null;
    pending: PendingRun | null;
  }>({ analysis: null, pending: null });

  useEffect(() => {
    latest.current = { analysis, pending };
  }, [analysis, pending]);

  const readDatasets = useCallback(async () => {
    try {
      setDatasets(await fetchDatasets());
    } catch (error) {
      setDatasetsError(
        messageFor(error, "Dataset listing could not be read."),
      );
    } finally {
      setDatasetsLoading(false);
    }
  }, []);

  const reloadDatasets = useCallback(async () => {
    setDatasetsLoading(true);
    setDatasetsError(null);
    await readDatasets();
  }, [readDatasets]);

  /**
   * Adopt the most recent finished run when the application mounts.
   *
   * A reload is not a new examination. Without this, reloading on /findings
   * would empty every screen and the examiner would have to run the same
   * evidence again to get the same answer, which for a large file means
   * waiting minutes for a result the local service already has. The adopted run
   * is named in the top bar, so nothing is loaded that is not identified, and
   * "Change dataset" replaces it.
   *
   * A run still in flight is adopted too, and the poll below picks it up.
   */
  const restoreLatestRun = useCallback(async () => {
    try {
      const runs = await fetchAnalysisList();

      if (runs.length === 0) {
        return;
      }

      // The listing is oldest first, so the last entry is the most recent run.
      setAnalysis(await fetchAnalysis(runs[runs.length - 1].job_id));
    } catch {
      // A service that cannot be reached leaves nothing loaded, which is the
      // same state as a first visit, so it needs no error.
    }
  }, []);

  useEffect(() => {
    // The initial state is already "loading", so mounting only has to read.
    void readDatasets();
    fetchHealth().then(setHealth).catch(() => setHealth(null));
    void restoreLatestRun();
  }, [readDatasets, restoreLatestRun]);

  /**
   * Ask the adapter to assess a dataset.
   *
   * With nothing loaded there is nothing to lose, so the run becomes the
   * current one immediately and the screens show it progressing. With an
   * assessment already on screen the run is held as pending: the current
   * assessment stays visible, and the screens change only when the new run has
   * actually produced a result.
   */
  const run = useCallback(async (dataset: string) => {
    if (
      latest.current.analysis?.status === "processing" ||
      latest.current.pending
    ) {
      // One run at a time. The interface never leaves two runs in flight,
      // because it could not say which one the screen belonged to.
      return;
    }

    setAnalysisError(null);

    const replacing = completedResult(latest.current.analysis) !== null;

    try {
      const started = await startAnalysis(dataset);

      if (replacing) {
        setPending({ dataset: started.dataset, jobId: started.job_id });
        return;
      }

      setAnalysis(started);
    } catch (error) {
      // A run that could not be started changes nothing that is on screen. The
      // current assessment, if there is one, is deliberately left loaded.
      setAnalysisError(
        messageFor(error, "The analysis could not be started."),
      );
    }
  }, []);

  /**
   * Stop waiting for a pending run.
   *
   * The pipeline run itself is left alone: it is a worker in the local service
   * and this interface does not pretend to stop work it cannot stop. What is
   * cancelled is the *switch*, so the loaded assessment stays loaded and no
   * later poll can replace it.
   */
  const cancelPending = useCallback(() => {
    setPending(null);
    setAnalysisError(null);
  }, []);

  const refresh = useCallback(async () => {
    const current = latest.current.analysis;

    if (!current) {
      return;
    }

    try {
      setAnalysis(await fetchAnalysis(current.job_id));
    } catch (error) {
      setAnalysisError(
        messageFor(error, "The analysis could not be re-read."),
      );
    }
  }, []);

  const dismissError = useCallback(() => setAnalysisError(null), []);

  // Poll whichever run is in flight, and only while it genuinely is. A pending
  // run is polled instead of the current one, so a switch does not stop while
  // the assessment on screen is finished and idle.
  const pendingJobId = pending?.jobId ?? null;
  const currentJobId =
    analysis?.status === "processing" ? analysis.job_id : null;
  const jobId = pendingJobId ?? currentJobId;

  useEffect(() => {
    if (!jobId) {
      return;
    }

    let cancelled = false;

    const tick = async () => {
      let next: AnalysisState;

      try {
        next = await fetchAnalysis(jobId);
      } catch (error) {
        if (!cancelled) {
          setAnalysisError(
            messageFor(error, "The analysis could not be re-read."),
          );
        }

        return;
      }

      if (cancelled) {
        return;
      }

      if (next.status === "processing") {
        window.setTimeout(tick, POLL_INTERVAL);
        return;
      }

      if (latest.current.pending?.jobId === jobId) {
        // The switch finished. Promote the run only now, so the screens never
        // show a result that does not exist yet.
        if (next.status === "complete") {
          setPending(null);
          setAnalysisError(null);
          setAnalysis(next);
          return;
        }

        // The switch failed. The loaded assessment stays loaded and the reason
        // is reported, which is a recoverable state rather than a blank one.
        setPending(null);
        setAnalysisError(
          next.error ?? "The analysis did not complete.",
        );
        return;
      }

      setAnalysis(next);

      if (next.status === "error") {
        setAnalysisError(next.error ?? "The analysis did not complete.");
      }
    };

    const timer = window.setTimeout(tick, POLL_INTERVAL);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  const value = useMemo<AnalysisContextValue>(() => {
    const result = completedResult(analysis);

    return {
      datasets,
      datasetsError,
      datasetsLoading,
      health,
      analysis,
      result,
      running: analysis?.status === "processing",
      analysisError,
      pending,
      switching: pending !== null && result !== null,
      run,
      cancelPending,
      refresh,
      dismissError,
      reloadDatasets,
    };
  }, [
    datasets,
    datasetsError,
    datasetsLoading,
    health,
    analysis,
    analysisError,
    pending,
    run,
    cancelPending,
    refresh,
    dismissError,
    reloadDatasets,
  ]);

  return (
    <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>
  );
}

export function useAnalysis(): AnalysisContextValue {
  const context = useContext(AnalysisContext);

  if (!context) {
    throw new Error("useAnalysis must be used inside an AnalysisProvider");
  }

  return context;
}

/**
 * The completed result, or null.
 *
 * Screens that need a result call this and render an explicit empty state when
 * it is null. They never substitute a default result, because a fabricated
 * empty analysis and a real one with nothing to report look identical on
 * screen and mean opposite things to an examiner.
 */
export function useResult(): PipelineResult | null {
  return useAnalysis().result;
}
