/**
 * The only place the frontend talks to the backend.
 *
 * Requests are relative, so they resolve against whichever origin served the
 * bundle. There is no configurable base URL, because a configurable host is
 * how a local analytical tool quietly acquires an outbound dependency.
 */

import type {
  AnalysisState,
  DatasetEntry,
  HealthState,
  PipelineResult,
} from "../types/pipeline";
import type { EvidenceIntegrity } from "../types/evidence";

const API_ROOT = "/api";

export class AdapterError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AdapterError";
    this.status = status;
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = (body as { detail?: unknown }).detail;

    if (typeof detail === "string") {
      return detail;
    }

    // A refusal may carry its reason as an object rather than a string, as the
    // evidence trust layer does when it declines to allow an analysis. The
    // reason is the whole point of the refusal, so it is not flattened away.
    if (detail && typeof detail === "object") {
      const reason = (detail as { reason?: unknown }).reason;

      if (typeof reason === "string") {
        return reason;
      }
    }
  } catch {
    // The body was not JSON. The status line is all we can honestly report.
  }

  return `Request failed with status ${response.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_ROOT}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new AdapterError(
      "The local analysis service is not responding. Start it with the SAT-SA launcher.",
      0,
    );
  }

  if (!response.ok) {
    throw new AdapterError(await readError(response), response.status);
  }

  return (await response.json()) as T;
}

export function fetchHealth(): Promise<HealthState> {
  return request<HealthState>("/health");
}

export async function fetchDatasets(): Promise<DatasetEntry[]> {
  const body = await request<{ datasets: DatasetEntry[] }>("/datasets");
  return body.datasets;
}

/**
 * Start an analysis. The adapter runs the pipeline on a worker thread, so this
 * resolves as soon as the run has been accepted, not when it has finished.
 */
export function startAnalysis(dataset: string): Promise<AnalysisState> {
  return request<AnalysisState>("/analyses", {
    method: "POST",
    body: JSON.stringify({ dataset }),
  });
}

export function fetchAnalysis(jobId: string): Promise<AnalysisState> {
  return request<AnalysisState>(`/analyses/${encodeURIComponent(jobId)}`);
}

/** Every retained run, oldest first, without their results. */
export function fetchAnalysisList(): Promise<AnalysisState[]> {
  return request<{ analyses: AnalysisState[] }>("/analyses").then(
    (body) => body.analyses,
  );
}

/**
 * Every registered evidence submission, with its integrity as the trust layer
 * reports it.
 *
 * The digests in the response were computed by the evidence trust layer in the
 * local service. Nothing is hashed in the browser, and no status here is decided
 * by the interface.
 */
export function fetchEvidenceIntegrity(): Promise<EvidenceIntegrity[]> {
  return request<{ evidence: EvidenceIntegrity[] }>("/evidence").then(
    (body) => body.evidence,
  );
}

/**
 * Re-verify one submission now.
 *
 * This is the action behind the interface's ``Verify Integrity`` control. The
 * comparison is performed by the trust layer; the returned statuses are the ones
 * it just produced.
 */
export function verifyEvidenceIntegrity(
  evidenceId: string,
): Promise<EvidenceIntegrity> {
  return request<EvidenceIntegrity>(
    `/evidence/${encodeURIComponent(evidenceId)}/verify`,
    { method: "POST" },
  );
}

/** The interface payload: the analysis exactly as the screens consumed it. */
export function exportUrl(jobId: string): string {
  return `${API_ROOT}/analyses/${encodeURIComponent(jobId)}/export.json`;
}

/** The complete pipeline result, including the per-record keys. */
export function fullExportUrl(jobId: string): string {
  return `${API_ROOT}/analyses/${encodeURIComponent(jobId)}/export-full.json`;
}

/**
 * A result is present only when a run has actually finished. Used to keep
 * "no analysis loaded" and "an analysis with no findings" visually distinct.
 */
export function completedResult(state: AnalysisState | null): PipelineResult | null {
  if (!state || state.status !== "complete") {
    return null;
  }

  return state.result ?? null;
}
