import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { fetchEvidenceIntegrity } from "../services/api";
import type { EvidenceIntegrity } from "../types/evidence";
import { useAnalysis } from "./AnalysisContext";
import {
  buildDashboardViewModel,
  type DashboardViewModel,
  type EvidenceHealthView,
} from "./viewModel";

/**
 * One view model for the whole application.
 *
 * `AnalysisContext` already holds a single run and its result, and polls it once
 * while it is in flight. This provider adds the two things the five screens all
 * need and none of them should fetch independently:
 *
 *   1. the evidence register, read once per run rather than once per card
 *   2. the projection of both into one `DashboardViewModel`
 *
 * The register is re-read whenever the loaded run changes, because it is a
 * property of the local store rather than of a run, and re-verifying evidence
 * must be visible on every screen at once rather than on whichever screen
 * happened to trigger it.
 */

export interface DashboardContextValue {
  view: DashboardViewModel;
  /** The register as the trust layer reports it, or null when unreadable. */
  register: EvidenceIntegrity[] | null;
  registerError: string | null;
  registerLoading: boolean;
  /** Re-read the register now. */
  reloadRegister: () => Promise<void>;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

/**
 * Counts the trust layer's own statuses.
 *
 * These are four separate facts about each submission, not one partition:
 * a submission can be `INTEGRITY_FAILED` *and* have its analysis gate closed,
 * which is a real and important combination. So the dashboard reports each count
 * independently and says so, rather than drawing a stacked bar that would imply
 * the categories are mutually exclusive and sum to the total.
 */
function summariseRegister(
  items: EvidenceIntegrity[] | null,
): EvidenceHealthView | null {
  if (!items) {
    return null;
  }

  return {
    total: items.length,
    verified: items.filter((item) => item.overall_status === "VERIFIED").length,
    mismatch: items.filter(
      (item) => item.overall_status === "INTEGRITY_FAILED",
    ).length,
    missing: items.filter((item) => item.overall_status === "MISSING").length,
    blocked: items.filter((item) => !item.analysis.permitted).length,
    categoriesOverlap: true,
  };
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const { analysis, result, switching, pending } = useAnalysis();
  const jobId = analysis?.job_id ?? null;

  const [register, setRegister] = useState<EvidenceIntegrity[] | null>(null);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registerLoading, setRegisterLoading] = useState(true);

  const readRegister = useMemo(
    () => async () => {
      setRegisterLoading(true);
      setRegisterError(null);

      try {
        setRegister(await fetchEvidenceIntegrity());
      } catch (error) {
        // The register is adjacent to the assessment, not part of it. A failure
        // to read it must not blank the screens, so it becomes an honest
        // unavailable state on the evidence section alone.
        setRegister(null);
        setRegisterError(
          error instanceof Error
            ? error.message
            : "The evidence register could not be read.",
        );
      } finally {
        setRegisterLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void readRegister();
  }, [readRegister, jobId]);

  const view = useMemo(
    () =>
      buildDashboardViewModel(
        analysis,
        result,
        summariseRegister(register),
        switching,
        pending === null ? null : { jobId: pending.jobId, dataset: pending.dataset },
      ),
    [analysis, result, register, switching, pending],
  );

  const value = useMemo<DashboardContextValue>(
    () => ({
      view,
      register,
      registerError,
      registerLoading,
      reloadRegister: readRegister,
    }),
    [view, register, registerError, registerLoading, readRegister],
  );

  return (
    <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>
  );
}

export function useDashboard(): DashboardContextValue {
  const context = useContext(DashboardContext);

  if (!context) {
    throw new Error("useDashboard must be used inside a DashboardProvider");
  }

  return context;
}
