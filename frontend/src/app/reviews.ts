import { useCallback, useEffect, useState } from "react";

/**
 * Lightweight examiner review state.
 *
 * Three verdicts and a short note per finding. Stored in `localStorage`,
 * keyed by the analysis job and the finding key, so review metadata is
 * always separate from the submitted evidence: nothing here can modify,
 * overwrite or re-interpret the pipeline result. Clearing the browser
 * storage clears reviews; the evidence is untouched either way.
 *
 * No task management, no remediation tracking, no workflow engine. An
 * examiner records what they concluded about a finding and moves on.
 */

export type ReviewVerdict = "confirmed_gap" | "false_positive" | "needs_review";

export const REVIEW_VERDICTS: Array<{ id: ReviewVerdict; label: string }> = [
  { id: "confirmed_gap", label: "Confirmed gap" },
  { id: "false_positive", label: "False positive" },
  { id: "needs_review", label: "Needs deeper review" },
];

export interface FindingReview {
  verdict: ReviewVerdict;
  note: string;
  updated_at: string;
}

type ReviewMap = Record<string, FindingReview>;

const STORAGE_PREFIX = "satsa:reviews:";

function storageKey(jobId: string): string {
  return `${STORAGE_PREFIX}${jobId}`;
}

function readReviews(jobId: string | null): ReviewMap {
  if (!jobId) {
    return {};
  }

  try {
    const raw = window.localStorage.getItem(storageKey(jobId));

    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw) as unknown;

    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as ReviewMap;
    }
  } catch {
    // A foreign or corrupted value is treated as no reviews, never as an
    // error on screen: reviews are advisory metadata, not evidence.
  }

  return {};
}

function reviewLabel(verdict: ReviewVerdict): string {
  return REVIEW_VERDICTS.find((item) => item.id === verdict)?.label ?? verdict;
}

export { reviewLabel };

/**
 * Reviews for one analysis run.
 *
 * `jobId` scopes the map: switching datasets starts a fresh review set for
 * the new run, and returning to an earlier run restores its reviews.
 */
export function useFindingReviews(jobId: string | null) {
  const [reviews, setReviews] = useState<ReviewMap>(() => readReviews(jobId));

  useEffect(() => {
    setReviews(readReviews(jobId));
  }, [jobId]);

  const saveReview = useCallback(
    (findingKey: string, verdict: ReviewVerdict, note: string) => {
      if (!jobId) {
        return;
      }

      setReviews((current) => {
        const next: ReviewMap = {
          ...current,
          [findingKey]: {
            verdict,
            note: note.slice(0, 2000),
            updated_at: new Date().toISOString(),
          },
        };

        try {
          window.localStorage.setItem(storageKey(jobId), JSON.stringify(next));
        } catch {
          // Storage full or unavailable: the in-memory state still updates so
          // the examiner's work is visible for this session.
        }

        return next;
      });
    },
    [jobId],
  );

  const clearReview = useCallback(
    (findingKey: string) => {
      if (!jobId) {
        return;
      }

      setReviews((current) => {
        if (!(findingKey in current)) {
          return current;
        }

        const next: ReviewMap = { ...current };
        delete next[findingKey];

        try {
          window.localStorage.setItem(storageKey(jobId), JSON.stringify(next));
        } catch {
          // See saveReview: session state still updates.
        }

        return next;
      });
    },
    [jobId],
  );

  return { reviews, saveReview, clearReview };
}
