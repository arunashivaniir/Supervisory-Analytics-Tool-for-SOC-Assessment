import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useDashboard } from "./DashboardContext";
import { useResult } from "./AnalysisContext";
import { unifiedFindings, findingsForScope } from "./selectors";
import type { UnifiedFinding } from "./selectors";

/**
 * The investigation thread: which entity, which finding, and how to get back.
 *
 * The product flow is Overview → Entity → Finding → Evidence, and the whole
 * point of that flow is that an examiner never loses track of *what they are
 * looking at*. Three facts have to survive every hop:
 *
 *   - the loaded assessment (owned by `AnalysisContext`, never duplicated here)
 *   - the entity being investigated
 *   - the finding being read
 *
 * The entity lives in the URL, because it must survive a reload and a shared
 * link. The finding does not: it is a drawer over a list, so its identity is
 * held here as a selection rather than as a route, which is what lets the list
 * behind the drawer keep its filters and its scroll position.
 *
 * A finding can also be addressed directly from a finding route when an examiner
 * wants a linkable target; `openFinding` accepts a key and resolves it against
 * the loaded result, so both entry points land on the same thing.
 */

export interface InvestigationContextValue {
  /** The scope currently being investigated, by the backend's own id. */
  assessmentId: string | null;
  /** Set the scope being investigated. */
  setAssessmentId: (assessmentId: string | null) => void;
  /** The finding currently open in a drawer. */
  activeFinding: UnifiedFinding | null;
  /** Open a finding by its stable key. */
  openFinding: (key: string) => void;
  /** Close the finding drawer. */
  closeFinding: () => void;
  /** All findings in the loaded result. */
  findings: UnifiedFinding[];
  /** Findings for one scope, in the loaded result. */
  findingsForScope: (assessmentId: string) => UnifiedFinding[];
}

const InvestigationContext = createContext<InvestigationContextValue | null>(null);

export function InvestigationProvider({ children }: { children: ReactNode }) {
  const { view } = useDashboard();
  const result = useResult();

  const [assessmentId, setAssessmentId] = useState<string | null>(null);
  const [findingKey, setFindingKey] = useState<string | null>(null);

  const findings = useMemo(() => unifiedFindings(result), [result]);

  // A dataset switch replaces the result underneath the investigation thread.
  // Holding a finding key from the previous run would resolve to nothing, or
  // worse to a same-keyed finding in the new run, so the selection is dropped
  // whenever the loaded assessment changes.
  const jobId = view.run.jobId;
  const [lastJobId, setLastJobId] = useState(jobId);

  if (jobId !== lastJobId) {
    setLastJobId(jobId);
    setFindingKey(null);
    setAssessmentId(null);
  }

  const openFinding = useCallback(
    (key: string) => {
      setFindingKey(key);
    },
    [],
  );

  const closeFinding = useCallback(() => setFindingKey(null), []);

  const scopeFindings = useCallback(
    (scopeId: string) => findingsForScope(findings, scopeId),
    [findings],
  );

  const activeFinding = useMemo(
    () => findings.find((finding) => finding.key === findingKey) ?? null,
    [findings, findingKey],
  );

  const value = useMemo<InvestigationContextValue>(
    () => ({
      assessmentId,
      setAssessmentId,
      activeFinding,
      openFinding,
      closeFinding,
      findings,
      findingsForScope: scopeFindings,
    }),
    [
      assessmentId,
      activeFinding,
      openFinding,
      closeFinding,
      findings,
      scopeFindings,
    ],
  );

  return (
    <InvestigationContext.Provider value={value}>
      {children}
    </InvestigationContext.Provider>
  );
}

export function useInvestigation(): InvestigationContextValue {
  const context = useContext(InvestigationContext);

  if (!context) {
    throw new Error(
      "useInvestigation must be used inside an InvestigationProvider",
    );
  }

  return context;
}
