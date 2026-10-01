/**
 * Submission-package state for the New Assessment wizard.
 *
 * This is the package the examiner is assembling, not the analysis that is
 * on screen: what is selected, which wizard step is active, the package
 * lifecycle state, and the per-dataset preview with its reviewer overrides.
 * The loaded analysis stays in `AnalysisContext`; this context never
 * duplicates it and never starts a run on its own.
 *
 * Steps (examiner progression):
 *
 *   Data -> Review -> Run
 *
 * State model:
 *
 *   DRAFT -> DATA_SELECTED -> PREVIEW_LOADING -> PREVIEW_READY
 *     -> ROLES_REVIEWED -> (Run explains the supported run boundary)
 *   REVIEW_REQUIRED where an unacknowledged UNKNOWN role (or another
 *   reviewable condition) holds the package; PREVIEW_STALE after any
 *   reviewer change until the preview is refreshed; BLOCKED on a
 *   validation error; ERROR when a preview itself fails.
 *
 * Every dataset previews independently: the backend has no multi-file
 * package object, and this context must not fake one. Cross-file joins
 * are never computed here.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { requestPreviews, type DatasetPreview } from "../services/api";
import type { ReviewerOverride } from "../lib/canonicalMapping";

export type BuilderStep = "select" | "roles" | "run";

export const BUILDER_STEPS: Array<{ id: BuilderStep; label: string }> = [
  { id: "select", label: "Data" },
  { id: "roles", label: "Review" },
  { id: "run", label: "Run" },
];

/** The strict role vocabulary. No free-text role exists anywhere. */
export const DATASET_ROLES = [
  "ALERTS",
  "CASES",
  "WORKFLOW_EVENTS",
  "ASSETS",
  "UNKNOWN",
] as const;

export type DatasetRole = (typeof DATASET_ROLES)[number];

export type PackageStatus =
  | "DRAFT"
  | "DATA_SELECTED"
  | "PREVIEW_LOADING"
  | "PREVIEW_READY"
  | "REVIEW_REQUIRED"
  | "PREVIEW_STALE"
  | "ROLES_REVIEWED"
  | "MAPPING_REVIEWED"
  | "VALIDATED"
  | "READY"
  | "RUNNING"
  | "COMPLETE"
  | "BLOCKED"
  | "ERROR"
  | "STALE";

export type PreviewEntryStatus = "loading" | "loaded" | "error" | "stale";

export interface PreviewEntry {
  status: PreviewEntryStatus;
  preview?: DatasetPreview;
  error?: string;
  /** Reviewer role; null means no reviewer choice recorded. */
  roleOverride?: string | null;
  /** True once the reviewer has explicitly chosen a role (any value). */
  roleReviewed?: boolean;
  /** Reviewer mapping choices: source field -> concept (null = UNMAPPED). */
  mappingOverrides: Record<string, string | null>;
  /** Full override audit records, mirroring the C.1 model. */
  mappingRecords: Record<string, ReviewerOverride>;
}

export interface RolesContinue {
  ok: boolean;
  reason: string | null;
}

export interface AssessmentBuilderValue {
  /** Repository-relative dataset paths in the package, in selection order. */
  datasets: string[];
  /** Active wizard step. */
  step: BuilderStep;
  /** Package lifecycle state. */
  status: PackageStatus;
  /** Per-dataset preview lifecycle, keyed by dataset path. */
  previews: Record<string, PreviewEntry>;
  toggleDataset: (path: string) => void;
  removeDataset: (path: string) => void;
  clearDatasets: () => void;
  /** Move forward; Select requires at least one dataset. */
  continueFrom: (step: BuilderStep) => void;
  /** Move back one step; never discards the selection. */
  back: () => void;
  goToStep: (step: BuilderStep) => void;
  /** Preview the package (missing entries) or one dataset again. */
  requestPackagePreviews: () => Promise<void>;
  refreshPreview: (dataset: string) => Promise<void>;
  setRoleOverride: (dataset: string, role: string | null) => void;
  setMappingOverride: (
    dataset: string,
    field: string,
    record: ReviewerOverride,
  ) => void;
  revertMappingOverride: (dataset: string, field: string) => void;
  /** Effective role: reviewer choice, else the detected one. */
  effectiveRole: (dataset: string) => string;
  /** Whether Roles may continue, and the honest reason when not. */
  rolesContinue: () => RolesContinue;
}

const AssessmentBuilderContext =
  createContext<AssessmentBuilderValue | null>(null);

const STEP_ORDER: BuilderStep[] = ["select", "roles", "run"];

function emptyEntry(): PreviewEntry {
  return { status: "loading", mappingOverrides: {}, mappingRecords: {} };
}

export function AssessmentBuilderProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [datasets, setDatasets] = useState<string[]>([]);
  const [step, setStep] = useState<BuilderStep>("select");
  const [status, setStatus] = useState<PackageStatus>("DRAFT");
  const [previews, setPreviews] = useState<Record<string, PreviewEntry>>({});
  const previewsRef = useRef(previews);

  previewsRef.current = previews;

  const recomputeStatus = useCallback(
    (entries: Record<string, PreviewEntry>, selected: string[]) => {
      if (selected.length === 0) {
        setStatus("DRAFT");
        return;
      }

      const relevant = selected.map((path) => entries[path]);

      if (relevant.some((entry) => !entry || entry.status === "loading")) {
        setStatus("PREVIEW_LOADING");
        return;
      }

      if (relevant.some((entry) => entry.status === "error")) {
        setStatus("ERROR");
        return;
      }

      if (relevant.some((entry) => entry.status === "stale")) {
        setStatus("PREVIEW_STALE");
        return;
      }

      const blocked = relevant.some(
        (entry) => (entry.preview?.validation.error_count ?? 0) > 0,
      );

      if (blocked) {
        setStatus("BLOCKED");
        return;
      }

      const reviewRequired = relevant.some((entry) => {
        const role =
          entry.roleOverride ?? entry.preview?.detected_role.role ?? "UNKNOWN";
        return role === "UNKNOWN" && !entry.roleReviewed;
      });

      if (relevant.some((entry) => !entry.preview)) {
        setStatus("DATA_SELECTED");
        return;
      }

      setStatus(reviewRequired ? "REVIEW_REQUIRED" : "PREVIEW_READY");
    },
    [],
  );

  const storePreviews = useCallback(
    (incoming: DatasetPreview[]) => {
      setPreviews((current) => {
        const next = { ...current };

        for (const preview of incoming) {
          const previous = next[preview.dataset] ?? emptyEntry();

          if (preview.error) {
            next[preview.dataset] = {
              ...previous,
              status: "error",
              error: preview.error,
              preview: undefined,
            };
          } else {
            next[preview.dataset] = {
              ...previous,
              status: "loaded",
              preview,
              error: undefined,
            };
          }
        }

        return next;
      });
    },
    [],
  );

  const fetchPreviews = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) {
        return;
      }

      const snapshot = previewsRef.current;
      const explicitRoles: Record<string, string> = {};
      const mappingOverrides: Record<string, Record<string, string | null>> = {};

      for (const path of paths) {
        const entry = snapshot[path];

        if (entry?.roleOverride) {
          explicitRoles[path] = entry.roleOverride;
        }

        if (entry && Object.keys(entry.mappingOverrides).length > 0) {
          mappingOverrides[path] = entry.mappingOverrides;
        }
      }

      const body = await requestPreviews(paths, explicitRoles, mappingOverrides);
      storePreviews(body.previews ?? []);
    },
    [storePreviews],
  );

  const requestPackagePreviews = useCallback(async () => {
    const missing = datasets.filter(
      (path) =>
        !previewsRef.current[path] ||
        previewsRef.current[path].status === "error",
    );

    if (missing.length === 0) {
      recomputeStatus(previewsRef.current, datasets);
      return;
    }

    setPreviews((current) => {
      const next = { ...current };

      for (const path of missing) {
        next[path] = { ...(next[path] ?? emptyEntry()), status: "loading" };
      }

      return next;
    });
    setStatus("PREVIEW_LOADING");

    try {
      await fetchPreviews(missing);
    } catch (error) {
      setPreviews((current) => {
        const next = { ...current };

        for (const path of missing) {
          next[path] = {
            ...(next[path] ?? emptyEntry()),
            status: "error",
            error:
              error instanceof Error ? error.message : "Preview request failed.",
          };
        }

        return next;
      });
    }

    // Read the stored entries after the state commits above.
    window.setTimeout(() => {
      const latest = previewsRef.current;

      // Entries that finished without a preview and without an error are
      // still in flight; leave the status alone rather than guessing.
      recomputeStatus(latest, datasets);
    }, 0);
  }, [datasets, fetchPreviews, recomputeStatus]);

  const refreshPreview = useCallback(
    async (dataset: string) => {
      setPreviews((current) => ({
        ...current,
        [dataset]: {
          ...(current[dataset] ?? emptyEntry()),
          status: "loading",
          error: undefined,
        },
      }));
      setStatus("PREVIEW_LOADING");

      try {
        await fetchPreviews([dataset]);
      } catch (error) {
        setPreviews((current) => ({
          ...current,
          [dataset]: {
            ...(current[dataset] ?? emptyEntry()),
            status: "error",
            error:
              error instanceof Error ? error.message : "Preview request failed.",
          },
        }));
      }

      window.setTimeout(() => {
        recomputeStatus(previewsRef.current, datasets);
      }, 0);
    },
    [datasets, fetchPreviews, recomputeStatus],
  );

  const markStale = useCallback(
    (dataset: string, mutate: (entry: PreviewEntry) => PreviewEntry) => {
      setPreviews((current) => {
        const next = {
          ...current,
          [dataset]: mutate(current[dataset] ?? emptyEntry()),
        };
        window.setTimeout(() => recomputeStatus(next, datasets), 0);
        return next;
      });
      setStatus("PREVIEW_STALE");
    },
    [datasets, recomputeStatus],
  );

  const setRoleOverride = useCallback(
    (dataset: string, role: string | null) => {
      markStale(dataset, (entry) => ({
        ...entry,
        roleOverride: role,
        roleReviewed: role !== null,
        status: entry.preview ? "stale" : entry.status,
      }));
    },
    [markStale],
  );

  const setMappingOverride = useCallback(
    (dataset: string, field: string, record: ReviewerOverride) => {
      markStale(dataset, (entry) => ({
        ...entry,
        mappingOverrides: { ...entry.mappingOverrides, [field]: record.concept },
        mappingRecords: { ...entry.mappingRecords, [field]: record },
        status: entry.preview ? "stale" : entry.status,
      }));
    },
    [markStale],
  );

  const revertMappingOverride = useCallback(
    (dataset: string, field: string) => {
      markStale(dataset, (entry) => {
        const overrides = { ...entry.mappingOverrides };
        const records = { ...entry.mappingRecords };
        delete overrides[field];
        delete records[field];

        return {
          ...entry,
          mappingOverrides: overrides,
          mappingRecords: records,
          status: entry.preview ? "stale" : entry.status,
        };
      });
    },
    [markStale],
  );

  const toggleDataset = useCallback(
    (path: string) => {
      setDatasets((current) => {
        const next = current.includes(path)
          ? current.filter((item) => item !== path)
          : [...current, path];

        setPreviews((entries) => {
          if (next.includes(path)) {
            return entries;
          }

          const pruned = { ...entries };
          delete pruned[path];
          window.setTimeout(() => recomputeStatus(pruned, next), 0);
          return pruned;
        });

        if (!next.includes(path) && next.length > 0) {
          window.setTimeout(
            () => recomputeStatus(previewsRef.current, next),
            0,
          );
        } else if (next.length === 0) {
          setStatus("DRAFT");
        }

        return next;
      });
    },
    [recomputeStatus],
  );

  const removeDataset = useCallback(
    (path: string) => {
      setDatasets((current) => {
        const next = current.filter((item) => item !== path);

        setPreviews((entries) => {
          const pruned = { ...entries };
          delete pruned[path];
          window.setTimeout(() => recomputeStatus(pruned, next), 0);
          return pruned;
        });

        if (next.length === 0) {
          setStatus("DRAFT");
        }

        return next;
      });
    },
    [recomputeStatus],
  );

  const clearDatasets = useCallback(() => {
    setDatasets([]);
    setPreviews({});
    setStatus("DRAFT");
    setStep("select");
  }, []);

  const effectiveRole = useCallback(
    (dataset: string) => {
      const entry = previewsRef.current[dataset];
      return (
        entry?.roleOverride ?? entry?.preview?.detected_role.role ?? "UNKNOWN"
      );
    },
    [],
  );

  const rolesContinue = useCallback((): RolesContinue => {
    if (datasets.length === 0) {
      return { ok: false, reason: "Select at least one dataset first." };
    }

    for (const path of datasets) {
      const entry = previews[path];

      if (!entry || !entry.preview || entry.status !== "loaded") {
        return {
          ok: false,
          reason: "Refresh every dataset preview before continuing.",
        };
      }

      if ((entry.preview.validation.error_count ?? 0) > 0) {
        return {
          ok: false,
          reason: `Resolve the blocking validation error in ${path}.`,
        };
      }

      const role = entry.roleOverride ?? entry.preview.detected_role.role;

      if (role === "UNKNOWN" && !entry.roleReviewed) {
        return {
          ok: false,
          reason: `Confirm the dataset role for ${path}.`,
        };
      }
    }

    return { ok: true, reason: null };
  }, [datasets, previews]);

  const continueFrom = useCallback(
    (from: BuilderStep) => {
      if (from === "select" && datasets.length === 0) {
        return;
      }

      if (from === "roles" && !rolesContinue().ok) {
        return;
      }

      const index = STEP_ORDER.indexOf(from);

      if (index >= 0 && index < STEP_ORDER.length - 1) {
        const next = STEP_ORDER[index + 1];
        setStep(next);

        if (from === "select") {
          setStatus(datasets.length > 0 ? "DATA_SELECTED" : "DRAFT");

          if (next === "roles") {
            void requestPackagePreviews();
          }
        }

        if (from === "roles") {
          setStatus("ROLES_REVIEWED");
        }
      }
    },
    [datasets.length, requestPackagePreviews, rolesContinue],
  );

  const back = useCallback(() => {
    setStep((current) => {
      const index = STEP_ORDER.indexOf(current);
      return index > 0 ? STEP_ORDER[index - 1] : current;
    });
  }, []);

  const goToStep = useCallback(
    (target: BuilderStep) => {
      const targetIndex = STEP_ORDER.indexOf(target);
      const currentIndex = STEP_ORDER.indexOf(step);

      // Forward navigation past Select needs a non-empty package; backward
      // navigation is always safe and never discards state.
      if (targetIndex > 0 && datasets.length === 0) {
        return;
      }

      if (targetIndex <= currentIndex || datasets.length > 0) {
        // Never jump ahead of a stale or unfinished preview: downstream
        // steps must not see yesterday's values.
        if (targetIndex > 1) {
          const gate = rolesContinue();

          if (!gate.ok && targetIndex > currentIndex) {
            return;
          }

          if (status === "PREVIEW_STALE" && targetIndex > currentIndex) {
            return;
          }
        }

        setStep(target);
      }
    },
    [datasets.length, step, rolesContinue, status],
  );

  const value = useMemo(
    () => ({
      datasets,
      step,
      status,
      previews,
      toggleDataset,
      removeDataset,
      clearDatasets,
      continueFrom,
      back,
      goToStep,
      requestPackagePreviews,
      refreshPreview,
      setRoleOverride,
      setMappingOverride,
      revertMappingOverride,
      effectiveRole,
      rolesContinue,
    }),
    [
      datasets,
      step,
      status,
      previews,
      toggleDataset,
      removeDataset,
      clearDatasets,
      continueFrom,
      back,
      goToStep,
      requestPackagePreviews,
      refreshPreview,
      setRoleOverride,
      setMappingOverride,
      revertMappingOverride,
      effectiveRole,
      rolesContinue,
    ],
  );

  return (
    <AssessmentBuilderContext.Provider value={value}>
      {children}
    </AssessmentBuilderContext.Provider>
  );
}

export function useAssessmentBuilder(): AssessmentBuilderValue {
  const context = useContext(AssessmentBuilderContext);

  if (!context) {
    throw new Error(
      "useAssessmentBuilder must be used inside an AssessmentBuilderProvider",
    );
  }

  return context;
}
