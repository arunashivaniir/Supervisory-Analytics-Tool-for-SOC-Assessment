import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  BUILDER_STEPS,
  DATASET_ROLES,
  useAssessmentBuilder,
  type BuilderStep,
} from "../app/AssessmentBuilder";
import { useAnalysis } from "../app/AnalysisContext";
import { cn } from "../lib/cn";
import { datasetName, formatBytes, formatCount } from "../lib/formatters";
import { Caveat, PageHeader, Section } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { EmptyState, LoadingRows } from "../components/ui/Metric";
import { TextFilter } from "../components/ui/Filters";
import {
  DataTable,
  HeadCell,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "../components/ui/DataTable";
import { StatusBadge } from "../components/ui/StatusBadge";
import { DataRow } from "../components/ui/DataDisplay";
import { MappingReviewCore } from "../components/assessment/CanonicalMappingReview";
import type { DatasetPreview } from "../services/api";

/**
 * New Assessment wizard: Data -> Review -> Run.
 *
 * Data assembles the assessment package (one or more available datasets,
 * each kept independent). Review previews each selected dataset
 * independently through `/api/previews` and reuses the canonical mapping
 * review. Run states the supported run boundary honestly: the backend
 * analyses a single dataset per run, so a multi-dataset package is never
 * presented as one merged analytical dataset.
 */
export function NewAssessmentPage() {
  const { step } = useAssessmentBuilder();

  return (
    <>
      <PageHeader
        title="New Assessment"
        subject="Create a new supervisory assessment from submitted SOC operational data."
        meta="Starts a new assessment package. To change the dataset shown on the current screens instead, use Change dataset in the top bar."
      />
      <StepIndicator current={step} />
      {step === "select" ? (
        <DataStep />
      ) : step === "roles" ? (
        <ReviewStep />
      ) : (
        <RunStep />
      )}
    </>
  );
}

function StepIndicator({ current }: { current: BuilderStep }) {
  const { goToStep, datasets } = useAssessmentBuilder();
  const order = BUILDER_STEPS.map((item) => item.id);
  const currentIndex = order.indexOf(current);

  return (
    <ol
      aria-label="New assessment progress"
      className="mb-5 flex flex-wrap items-center gap-1.5"
    >
      {BUILDER_STEPS.map((item, index) => {
        const done = index < currentIndex;
        const active = item.id === current;
        const reachable = index === 0 || datasets.length > 0;

        return (
          <li key={item.id} className="flex items-center gap-1.5">
            {index > 0 ? (
              <span aria-hidden="true" className="mx-0.5 text-text-tertiary">
                →
              </span>
            ) : null}
            <button
              type="button"
              disabled={!reachable}
              onClick={() => goToStep(item.id)}
              aria-current={active ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5 rounded-[6px] border px-2.5 py-1 text-xs font-medium",
                active
                  ? "border-accent bg-accent-subtle text-accent"
                  : done
                    ? "border-border bg-surface text-text"
                    : "border-border bg-surface text-text-tertiary",
                !reachable && "cursor-not-allowed opacity-50",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-4 items-center justify-center rounded-full border text-[10px]",
                  done
                    ? "border-positive bg-positive text-white"
                    : active
                      ? "border-accent text-accent"
                      : "border-border text-text-tertiary",
                )}
              >
                {done ? "✓" : index + 1}
              </span>
              {item.label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** File type derived from the filename extension. Labelling only. */
function fileTypeLabel(filename: string): string {
  const lower = filename.toLowerCase();

  if (lower.endsWith(".ndjson") || lower.endsWith(".jsonl")) {
    return "NDJSON";
  }

  if (lower.endsWith(".json")) {
    return "JSON";
  }

  if (lower.endsWith(".tsv") || lower.endsWith(".txt")) {
    return "TSV";
  }

  if (lower.endsWith(".db") || lower.endsWith(".sqlite") || lower.endsWith(".sqlite3")) {
    return "SQLite";
  }

  return "CSV";
}

/**
 * Step 1 — Data.
 *
 * The same available listing the workspace already uses (no second
 * discovery, no uploader). Multiple datasets form one package with
 * boundaries preserved; the same source cannot be selected twice.
 * This step starts a new assessment package; it does not change the
 * dataset currently shown on the screens.
 */
function DataStep() {
  const {
    datasets: selected,
    toggleDataset,
    removeDataset,
    clearDatasets,
    continueFrom,
  } = useAssessmentBuilder();
  const { datasets, datasetsLoading, datasetsError, reloadDatasets } =
    useAnalysis();
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();

    if (!needle) {
      return datasets;
    }

    return datasets.filter((dataset) =>
      dataset.filename.toLowerCase().includes(needle),
    );
  }, [datasets, query]);

  const sorted = useMemo(
    () => [...filtered].sort((a, b) => a.path.localeCompare(b.path)),
    [filtered],
  );

  return (
    <>
      <Section
        title="Selected for this assessment"
        description="Select the operational datasets submitted for this assessment. Each selected dataset is profiled independently before assessment."
        action={
          selected.length > 0 ? (
            <button
              type="button"
              onClick={clearDatasets}
              className="text-xs font-medium text-text-tertiary underline-offset-2 hover:underline"
            >
              Clear selection
            </button>
          ) : undefined
        }
      >
        <Card>
          {selected.length === 0 ? (
            <div className="px-4 py-3">
              <p className="text-[13px] font-medium text-text">
                No datasets selected yet
              </p>
              <p className="mt-0.5 text-xs text-text-tertiary">
                Choose assessment data from the available list below. At least
                one dataset is required to continue.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {selected.map((path, index) => (
                <li
                  key={path}
                  className="flex items-center justify-between gap-3 px-4 py-2"
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span
                      aria-hidden="true"
                      className="flex size-4 shrink-0 items-center justify-center rounded-full bg-positive text-[10px] text-white"
                    >
                      ✓
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-medium text-text">
                        {path.split("/").pop() ?? path}
                      </span>
                      <span className="block truncate micro tabular text-text-tertiary">
                        Selected · {index + 1} of {selected.length}
                      </span>
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={() => removeDataset(path)}
                      aria-label={`Remove ${datasetName(path)} from this assessment`}
                      className="rounded-[6px] border border-border px-2 py-0.5 text-xs text-text-secondary hover:bg-subtle"
                    >
                      Remove
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Caveat className="mt-2.5">
          Each dataset keeps its own schema and provenance. No cross-file
          linkage is computed at this stage.
        </Caveat>
      </Section>

      <Section
        title="Available assessment data"
        description="Every dataset available for assessment, in path order. Nothing here is ranked or recommended."
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <TextFilter
            label="Filter assessment data"
            value={query}
            onChange={setQuery}
            placeholder="File name"
            className="w-[300px]"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => void reloadDatasets()}
            disabled={datasetsLoading}
          >
            Rescan
          </Button>
          <div className="ml-auto text-xs text-text-tertiary">
            {selected.length} selected
          </div>
        </div>
        <Card>
          <div className="max-h-[46vh] min-h-[220px] overflow-y-auto">
            {datasetsError ? (
              <p className="border-b border-border px-4 py-2 text-xs text-critical">
                {datasetsError}
              </p>
            ) : null}
            {datasetsLoading ? (
              <LoadingRows rows={5} />
            ) : sorted.length === 0 ? (
              <EmptyState
                title={datasets.length === 0 ? "No assessment data found" : "No match"}
                description={
                  datasets.length === 0
                    ? "No readable dataset files were found."
                    : "No assessment data matches that filter."
                }
              />
            ) : (
              <ul className="divide-y divide-border">
                {sorted.map((dataset) => {
                  const active = selected.includes(dataset.path);

                  return (
                    <li key={dataset.path}>
                      <label
                        className={cn(
                          "flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-2 text-left",
                          "transition-colors duration-75 hover:bg-subtle",
                          active && "bg-accent-subtle/60",
                        )}
                      >
                        <span className="flex min-w-0 items-center gap-2.5">
                          <input
                            type="checkbox"
                            checked={active}
                            onChange={() => toggleDataset(dataset.path)}
                            aria-label={`Select ${dataset.path}`}
                            className="size-3.5 shrink-0 accent-[#0f766e]"
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-[13px] text-text">
                              {dataset.filename}
                            </span>
                            <span className="block truncate micro tabular text-text-tertiary">
                              {fileTypeLabel(dataset.filename)} ·{" "}
                              {formatBytes(dataset.size_bytes)}
                            </span>
                          </span>
                        </span>
                        <span className="micro shrink-0 tabular text-text-tertiary">
                          {fileTypeLabel(dataset.filename)}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Card>
      </Section>

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button
          variant="primary"
          disabled={selected.length === 0}
          onClick={() => continueFrom("select")}
        >
          Continue to Review →
        </Button>
      </div>
      {selected.length === 0 ? (
        <Caveat className="mt-2.5">
          Select at least one dataset to continue to review.
        </Caveat>
      ) : null}
    </>
  );
}

/**
 * Step 2 — Review.
 *
 * Every selected dataset previews independently through
 * `/api/previews`: record count, detected role, mapping
 * decisions, validation and relationship summaries. No analytics run,
 * and no cross-file join is computed or claimed. The canonical mapping
 * review is reused for per-dataset mapping review; a mapping or role
 * change marks that dataset stale until its preview is refreshed, and
 * the wizard cannot continue past a stale, blocked or unreviewed package.
 */
function ReviewStep() {
  const {
    datasets,
    previews,
    back,
    continueFrom,
    requestPackagePreviews,
    refreshPreview,
    setRoleOverride,
    setMappingOverride,
    revertMappingOverride,
    effectiveRole,
    rolesContinue,
  } = useAssessmentBuilder();
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    void requestPackagePreviews();
    // Once on entry: continuation reuses stored previews.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const gate = rolesContinue();

  return (
    <>
      <Section
        title="Review Assessment Data"
        description="Review detected roles, mapping coverage and validation status before continuing."
      >
        {datasets.length > 1 ? (
          <Caveat className="mb-2.5">
            {datasets.length} datasets selected. Each is profiled
            independently in this stage — no merged dataset is created and no
            cross-file linkage is computed.
          </Caveat>
        ) : null}
        <Card>
          <ul className="divide-y divide-border">
            {datasets.map((path) => {
              const entry = previews[path];
              const preview = entry?.preview;
              const open = expanded === path;
              const filename = path.split("/").pop() ?? path;
              const states = preview?.mapping_states ?? {};
              const mapped =
                (states.MAPPED ?? 0) + (states.LOW_CONFIDENCE ?? 0);
              const attention =
                (states.LOW_CONFIDENCE ?? 0) +
                (states.AMBIGUOUS ?? 0) +
                (states.INVALID ?? 0) +
                (states.UNMAPPED ?? 0);

              return (
                <li key={path}>
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((current) => (current === path ? null : path))
                    }
                    aria-expanded={open}
                    aria-label={`Review ${path}`}
                    className="flex w-full items-center justify-between gap-4 px-4 py-2.5 text-left transition-colors duration-75 hover:bg-subtle"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-text">
                        {filename}
                      </span>
                      <span className="mt-0.5 block truncate micro tabular text-text-tertiary">
                        {preview
                          ? `${formatCount(preview.record_count)} records · ${roleSummary(path, preview, entry?.roleOverride ?? null)} · ${mapped} of ${preview.mapping_decisions.length} mapped · ${attention} attention · E${preview.validation.error_count ?? 0} W${preview.validation.warning_count ?? 0}`
                          : (entry?.status === "error"
                            ? (entry.error ?? "Preview failed.")
                            : "Previewing…")}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <DatasetStatus entryStatus={entry?.status} preview={preview} roleReviewed={entry?.roleReviewed} />
                      <span className="micro text-text-tertiary">
                        {open ? "Hide" : "Review"}
                      </span>
                    </span>
                  </button>

                  {open ? (
                    <div className="border-t border-border bg-subtle/50 px-4 py-3">
                      {!preview || entry?.status === "loading" ? (
                        <LoadingRows rows={3} />
                      ) : entry?.status === "error" ? (
                        <Caveat tone="caution">
                          {entry.error ?? "Preview failed."}{" "}
                          <button
                            type="button"
                            onClick={() => void refreshPreview(path)}
                            className="font-medium text-accent underline-offset-2 hover:underline"
                          >
                            Retry preview
                          </button>
                        </Caveat>
                      ) : (
                        <DatasetDetail
                          path={path}
                          preview={preview}
                          stale={entry?.status === "stale"}
                          roleOverride={entry?.roleOverride ?? null}
                          effective={effectiveRole(path)}
                          onRole={(role) => setRoleOverride(path, role)}
                          onRefresh={() => void refreshPreview(path)}
                          mappingRecords={entry?.mappingRecords ?? {}}
                          onMappingOverride={(field, record) =>
                            setMappingOverride(path, field, record)
                          }
                          onMappingRevert={(field) =>
                            revertMappingOverride(path, field)
                          }
                        />
                      )}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </Card>
        <Caveat className="mt-2.5">
          Each selected dataset is profiled independently before assessment.
          No cross-file linkage is computed at this stage.
        </Caveat>
      </Section>

      <div className="mt-4 flex items-center justify-between gap-2">
        <Button variant="ghost" onClick={back}>
          Back
        </Button>
        <div className="flex items-center gap-3">
          {!gate.ok ? (
            <span className="text-xs text-caution">{gate.reason}</span>
          ) : null}
          <Button
            variant="primary"
            disabled={!gate.ok}
            onClick={() => continueFrom("roles")}
          >
            Continue to Run →
          </Button>
        </div>
      </div>
    </>
  );
}

function roleSummary(
  _path: string,
  preview: DatasetPreview,
  roleOverride: string | null,
): string {
  const auto = preview.detected_role.role;

  if (roleOverride && roleOverride !== auto) {
    return `${roleOverride} (reviewer; auto ${auto})`;
  }

  return auto;
}

function DatasetStatus({
  entryStatus,
  preview,
  roleReviewed,
}: {
  entryStatus: string | undefined;
  preview: DatasetPreview | undefined;
  roleReviewed: boolean | undefined;
}) {
  if (!preview || entryStatus === "loading") {
    return <StatusBadge tone="neutral" label="Loading" showDot={false} />;
  }

  if (entryStatus === "error") {
    return <StatusBadge tone="critical" label="Error" showDot={false} />;
  }

  if (entryStatus === "stale") {
    return <StatusBadge tone="caution" label="Stale" showDot={false} />;
  }

  if ((preview.validation.error_count ?? 0) > 0) {
    return <StatusBadge tone="critical" label="Blocked" showDot={false} />;
  }

  if (preview.detected_role.role === "UNKNOWN" && !roleReviewed) {
    return (
      <StatusBadge tone="caution" label="Review required" showDot={false} />
    );
  }

  if ((preview.validation.warning_count ?? 0) > 0) {
    return (
      <StatusBadge tone="caution" label="Ready with warnings" showDot={false} />
    );
  }

  return <StatusBadge tone="positive" label="Ready" showDot={false} />;
}

function DatasetDetail({
  path,
  preview,
  stale,
  roleOverride,
  effective,
  onRole,
  onRefresh,
  mappingRecords,
  onMappingOverride,
  onMappingRevert,
}: {
  path: string;
  preview: DatasetPreview;
  stale: boolean;
  roleOverride: string | null;
  effective: string;
  onRole: (role: string | null) => void;
  onRefresh: () => void;
  mappingRecords: Record<string, import("../lib/canonicalMapping").ReviewerOverride>;
  onMappingOverride: (
    field: string,
    record: import("../lib/canonicalMapping").ReviewerOverride,
  ) => void;
  onMappingRevert: (field: string) => void;
}) {
  const auto = preview.detected_role;
  const categories = useMemo(() => {
    const byColumn = new Map<string, string>();

    for (const column of preview.schema.columns ?? []) {
      if (typeof column?.column_name === "string") {
        byColumn.set(
          column.column_name.toLowerCase(),
          typeof column.category === "string" ? column.category : "",
        );
      }
    }

    return byColumn;
  }, [preview]);

  const states = preview.mapping_states ?? {};
  const mapped = (states.MAPPED ?? 0) + (states.LOW_CONFIDENCE ?? 0);
  const total = preview.mapping_decisions.length;
  const attention =
    (states.LOW_CONFIDENCE ?? 0) +
    (states.AMBIGUOUS ?? 0) +
    (states.INVALID ?? 0) +
    (states.UNMAPPED ?? 0);

  return (
    <div className="space-y-4">
      <div>
        <div className="section-label mb-1.5">Pipeline role</div>
        <div className="grid grid-cols-1 gap-x-8 lg:grid-cols-2">
          <div>
            <DataRow label="Automatic role" value={auto.role} />
            <DataRow
              label="Confidence"
              value={
                typeof auto.confidence === "number"
                  ? auto.confidence.toFixed(2)
                  : "Not reported"
              }
            />
            {auto.reason ? (
              <DataRow label="Basis" value={auto.reason} />
            ) : null}
          </div>
          <div>
            <label
              htmlFor={`role-select-${path}`}
              className="mb-1 block text-xs font-medium text-text"
            >
              Reviewer role (strict list, optional)
            </label>
            <select
              id={`role-select-${path}`}
              value={roleOverride ?? ""}
              onChange={(event) =>
                onRole(event.target.value === "" ? null : event.target.value)
              }
              className="w-full max-w-[320px] rounded-[8px] border border-border bg-surface px-2.5 py-2 text-[13px] text-text focus:outline-2 focus:outline-accent"
            >
              <option value="">Keep automatic ({auto.role})</option>
              {DATASET_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
            {roleOverride ? (
              <p className="mt-1 micro text-text-tertiary">
                Automatic {auto.role} → reviewer {roleOverride}. Changing the
                role refreshes the preview.
              </p>
            ) : auto.role === "UNKNOWN" ? (
              <p className="mt-1 micro text-caution">
                UNKNOWN — review required. Confirm a role to continue.
              </p>
            ) : null}
          </div>
        </div>
        <dl className="mt-2 grid grid-cols-2 gap-x-8 sm:grid-cols-4">
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Records</dt>
            <dd className="tabular text-xs text-text">
              {formatCount(preview.record_count)}
            </dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Mapped</dt>
            <dd className="tabular text-xs text-text">
              {mapped} of {total}
            </dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Attention</dt>
            <dd className="tabular text-xs text-text">{attention} fields</dd>
          </div>
          <div className="flex gap-2 py-0.5">
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">Mode</dt>
            <dd className="text-xs text-text">
              {preview.execution_mode === "large_scan"
                ? "Large-data scan"
                : "Standard"}
            </dd>
          </div>
        </dl>
      </div>

      <div>
        <div className="section-label mb-1.5">
          Canonical mapping · {effective}
        </div>
        {stale ? (
          <Caveat tone="caution" className="mb-2.5">
            Mapping changed — preview must be refreshed. Validation and
            readiness below are from the previous mapping.
            <span className="mt-2 block">
              <button
                type="button"
                onClick={onRefresh}
                className="rounded-[8px] bg-primary px-3 py-1.5 text-xs font-semibold text-white transition-opacity duration-100 hover:opacity-90"
              >
                Refresh preview
              </button>
            </span>
          </Caveat>
        ) : null}
        <MappingReviewCore
          decisions={preview.mapping_decisions}
          states={preview.mapping_states ?? {}}
          contract={preview.canonical_contract ?? {}}
          categories={categories}
          overrides={mappingRecords}
          onOverride={onMappingOverride}
          onRevert={onMappingRevert}
          banner={null}
          persistenceNote="Overrides are kept in this assessment package until its preview is refreshed;"
        />
      </div>

      <div>
        <div className="section-label mb-1.5">Validation</div>
        <ValidationSummary preview={preview} stale={stale} />
      </div>

      <div>
        <div className="section-label mb-1.5">Relationships (within this file)</div>
        <RelationshipSummary preview={preview} stale={stale} />
      </div>

      <div>
        <div className="section-label mb-1.5">Schema</div>
        <DataTable>
          <TableHead>
            <HeadCell>Column</HeadCell>
            <HeadCell>Category</HeadCell>
            <HeadCell>Sample values</HeadCell>
          </TableHead>
          <TableBody>
            {preview.schema.columns.map((column) => (
              <TableRow key={column.column_name ?? ""}>
                <TableCell className="font-mono micro">
                  {column.column_name}
                </TableCell>
                <TableCell className="text-xs text-text-secondary">
                  {column.category ?? "—"}
                </TableCell>
                <TableCell className="max-w-[360px] truncate font-mono micro text-text-secondary">
                  {(column.sample_values ?? []).slice(0, 3).map(String).join(" · ") || (
                    <span className="text-text-tertiary italic">No sample</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      </div>
    </div>
  );
}

function ValidationSummary({
  preview,
  stale,
}: {
  preview: DatasetPreview;
  stale: boolean;
}) {
  const [open, setOpen] = useState<"error" | "warning" | "info" | null>(null);
  const validation = preview.validation;
  const issues = validation.issues ?? [];
  const groups = [
    { id: "error" as const, label: "Errors", count: validation.error_count ?? 0 },
    { id: "warning" as const, label: "Warnings", count: validation.warning_count ?? 0 },
    {
      id: "info" as const,
      label: "Information",
      count: issues.filter((item) => item.severity === "info").length,
    },
  ];

  return (
    <div>
      <p className="text-xs text-text-secondary">
        Errors: {validation.error_count ?? 0} · Warnings:{" "}
        {validation.warning_count ?? 0} · Info:{" "}
        {issues.filter((item) => item.severity === "info").length}
        {(validation.error_count ?? 0) > 0
          ? " — a blocking error must be resolved before this dataset can continue."
          : (validation.warning_count ?? 0) > 0
            ? " — the assessment can run with warnings."
            : ""}
        {stale ? " (from the previous mapping)" : ""}
      </p>
      <div className="mt-2 space-y-1.5">
        {groups.map((group) => {
          const items = issues.filter((item) => item.severity === group.id);

          if (items.length === 0) {
            return null;
          }

          const isOpen = open === group.id;

          return (
            <div
              key={group.id}
              className="rounded-[8px] border border-border bg-surface"
            >
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : group.id)}
                aria-expanded={isOpen}
                className="flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left"
              >
                <span className="text-xs font-medium text-text">
                  {group.label}{" "}
                  <span className="tabular text-text-tertiary">
                    · {group.id === "info" ? items.length : group.count}
                  </span>
                </span>
                <span className="micro text-text-tertiary">
                  {isOpen ? "Hide" : "Show"}
                </span>
              </button>
              {isOpen ? (
                <ul className="divide-y divide-border/70 border-t border-border">
                  {items.slice(0, 25).map((item, index) => (
                    <li key={`${item.code}-${index}`} className="px-3 py-1.5">
                      <span className="font-mono micro text-text">
                        {item.code}
                      </span>
                      {item.field ? (
                        <span className="ml-2 font-mono micro text-text-secondary">
                          {item.field}
                        </span>
                      ) : null}
                      <p className="mt-0.5 text-xs leading-relaxed text-text-secondary">
                        {item.message}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : null}
              {isOpen && items.length > 25 ? (
                <p className="border-t border-border px-3 py-1.5 micro text-text-tertiary">
                  +{items.length - 25} further {group.label.toLowerCase()} not shown
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RelationshipSummary({
  preview,
  stale,
}: {
  preview: DatasetPreview;
  stale: boolean;
}) {
  const rel = preview.relationships as Record<string, unknown>;

  const countOf = (value: unknown): number | null => {
    if (typeof value === "number") {
      return value;
    }

    if (value && typeof value === "object" && "count" in value) {
      const count = (value as { count: unknown }).count;
      return typeof count === "number" ? count : null;
    }

    return null;
  };

  const rows: Array<[string, unknown]> = [
    ["Alerts", rel.alerts],
    ["Cases", rel.cases],
    ["Workflow events", rel.workflow_events],
    ["Assets", rel.assets],
    ["Linked cases", rel.linked_cases],
    ["Alerts without case", rel.alerts_without_case],
    ["Orphan cases", rel.orphan_cases],
    ["Workflow events without case", rel.orphan_workflow_cases],
  ];

  const assessable =
    rel.alert_case_assessable === true || rel.workflow_assessable === true;

  return (
    <div>
      {!assessable ? (
        <p className="text-xs text-text-tertiary italic">
          Relationship joins not assessable for this file — join keys did not
          map. This is a boundary of what was checkable, not a finding.
        </p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-8 sm:grid-cols-4">
          {rows.map(([label, value]) => {
            const count = countOf(value);

            return (
              <div key={label} className="flex gap-2 py-0.5">
                <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">
                  {label}
                </dt>
                <dd className="tabular text-xs text-text">
                  {count === null ? "—" : formatCount(count)}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      <p className="mt-1 micro text-text-tertiary">
        Within this file only; cross-file linkage is not computed before
        analysis.{stale ? " Values below are from the previous mapping." : ""}
      </p>
    </div>
  );
}

/**
 * Step 3 — Run.
 *
 * Each selected dataset is assessed independently through the existing
 * single-dataset analysis: one Run per dataset, one result per run. A
 * multi-dataset package is never merged into one analytical dataset, so
 * this step starts no combined run and claims none. Starting a run
 * navigates to Overview, which shows the run progressing and then its
 * results; the package itself is kept, so the examiner can return here
 * and run the next dataset.
 */
function RunStep() {
  const { datasets, previews, back, rolesContinue } = useAssessmentBuilder();
  const { run, analysis, pending } = useAnalysis();
  const navigate = useNavigate();
  const gate = rolesContinue();
  const busy =
    analysis?.status === "processing" || pending !== null;

  const readiness = (path: string): { ready: boolean; reason: string | null } => {
    const entry = previews[path];
    const preview = entry?.preview;

    if (!preview || entry?.status !== "loaded") {
      return { ready: false, reason: "Preview this dataset before running it." };
    }

    if ((preview.validation.error_count ?? 0) > 0) {
      return { ready: false, reason: "Resolve the blocking validation error first." };
    }

    const role = entry.roleOverride ?? preview.detected_role.role;

    if (role === "UNKNOWN" && !entry.roleReviewed) {
      return { ready: false, reason: "Confirm the dataset role first." };
    }

    return { ready: true, reason: null };
  };

  const startRun = async (path: string) => {
    await run(path);
    navigate("/");
  };

  return (
    <>
      <Section
        title="Run Assessment"
        description="Run each dataset as its own assessment. The backend analyses one dataset per run — Overview shows each run progressing, then its results."
      >
        <Card>
          <ul className="divide-y divide-border">
            {datasets.map((path) => {
              const entry = previews[path];
              const preview = entry?.preview;
              const blocked = (preview?.validation.error_count ?? 0) > 0;
              const state = readiness(path);
              const filename = path.split("/").pop() ?? path;

              return (
                <li
                  key={path}
                  className="flex items-center justify-between gap-3 px-4 py-2.5"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-text">
                      {filename}
                    </span>
                    <span className="mt-0.5 block truncate micro tabular text-text-tertiary">
                      {preview
                        ? `${formatCount(preview.record_count)} records · ${entry?.roleOverride ?? preview.detected_role.role}`
                        : "Not previewed — return to Review."}
                      {!state.ready && state.reason ? ` · ${state.reason}` : ""}
                      {busy ? " · a run is already in flight" : ""}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    {!preview ? (
                      <StatusBadge tone="neutral" label="Unreviewed" showDot={false} />
                    ) : entry?.status === "stale" ? (
                      <StatusBadge tone="caution" label="Stale" showDot={false} />
                    ) : blocked ? (
                      <StatusBadge tone="critical" label="Blocked" showDot={false} />
                    ) : (
                      <StatusBadge tone="positive" label="Ready" showDot={false} />
                    )}
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={!state.ready || busy}
                      onClick={() => void startRun(path)}
                    >
                      Run
                    </Button>
                  </span>
                </li>
              );
            })}
          </ul>
        </Card>
        <Caveat className="mt-2.5">
          {busy
            ? "A run is already in flight. Overview shows its progress; further runs wait until it finishes."
            : gate.ok
              ? "Each Run starts an independent single-dataset assessment. Overview shows the latest run — earlier runs stay in the service and are not merged."
              : (gate.reason ?? "Refresh every dataset preview before running.")}
        </Caveat>
        <Caveat className="mt-2.5">
          No cross-file linkage is computed. A merged multi-dataset analysis
          is not supported: running this package does not create one combined
          analytical dataset.
        </Caveat>
      </Section>

      <div className="mt-4 flex items-center justify-between gap-2">
        <Button variant="ghost" onClick={back}>
          Back
        </Button>
        <Button variant="outline" onClick={() => navigate("/")}>
          Open Overview
        </Button>
      </div>
    </>
  );
}
