/**
 * C.1 — Authoritative canonical mapping review.
 *
 * `MappingReviewCore` is the single implementation, driven entirely by
 * props so it works in two lifecycles:
 *
 *   - post-analysis (Evidence): overrides persist per assessment and a
 *     mapping change means the analysis must be rerun;
 *   - pre-run (New Assessment wizard): overrides live in the package
 *     builder state and a mapping change means the preview is stale
 *     until refreshed.
 *
 * The strict dropdown, candidate filtering, guard checks and UNMAPPED
 * semantics are identical in both: one logic, two banners.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { useAnalysis } from "../../app/AnalysisContext";
import {
  canonicalContract,
  canonicalDecisions,
  canonicalStates,
  profileCategoryByColumn,
} from "../../app/selectors";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/Metric";
import {
  DataTable,
  HeadCell,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "../ui/DataTable";
import { StatusBadge } from "../ui/StatusBadge";
import { Caveat, Section } from "../layout/PageHeader";
import {
  UNMAPPED,
  guardBlocks,
  needsAttention,
  rankedOptions,
  reviewerRecord,
  validateOverride,
  type ReviewerOverride,
} from "../../lib/canonicalMapping";
import type {
  CanonicalContractEntry,
  CanonicalMappingDecision,
  CanonicalMappingState,
} from "../../types/pipeline";

export type { ReviewerOverride };

function overridesKey(dataset: string): string {
  return `satsa.mapping-overrides::${dataset}`;
}

function readOverrides(dataset: string): Record<string, ReviewerOverride> {
  try {
    const raw = window.localStorage.getItem(overridesKey(dataset));

    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw) as Record<string, ReviewerOverride>;

    if (parsed && typeof parsed === "object") {
      return parsed;
    }
  } catch {
    // A corrupt entry must not break the review screen.
  }

  return {};
}

function stateTone(state: string): "positive" | "caution" | "critical" | "neutral" {
  switch (state) {
    case "MAPPED":
      return "positive";
    case "LOW_CONFIDENCE":
      return "caution";
    case "AMBIGUOUS":
      return "caution";
    case "INVALID":
      return "critical";
    default:
      return "neutral";
  }
}

function conceptFor(decision: CanonicalMappingDecision): string | null {
  return decision.canonical_concept ?? null;
}

export interface MappingReviewCoreProps {
  decisions: CanonicalMappingDecision[];
  states: Partial<Record<CanonicalMappingState, number>>;
  contract: Record<string, CanonicalContractEntry>;
  categories: Map<string, string>;
  overrides: Record<string, ReviewerOverride>;
  onOverride: (field: string, record: ReviewerOverride) => void;
  onRevert: (field: string) => void;
  /** Lifecycle notice (rerun vs refresh). Null when nothing changed. */
  banner: ReactNode;
  /** Where overrides live in this lifecycle, for the footnote. */
  persistenceNote: string;
}

export function MappingReviewCore({
  decisions,
  states,
  contract,
  categories,
  overrides,
  onOverride,
  onRevert,
  banner,
  persistenceNote,
}: MappingReviewCoreProps) {
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<string>(UNMAPPED);
  const [blockMessage, setBlockMessage] = useState<string | null>(null);

  const overrideConcepts = useMemo(() => {
    const out: Record<string, string | null> = {};

    for (const [field, record] of Object.entries(overrides)) {
      out[field] = record.concept;
    }

    return out;
  }, [overrides]);

  const visible = useMemo(() => {
    if (!attentionOnly) {
      return decisions;
    }

    return decisions.filter(
      (decision) =>
        needsAttention(decision.mapping_state) || overrides[decision.source_field],
    );
  }, [decisions, attentionOnly, overrides]);

  const attentionCount = useMemo(
    () => decisions.filter((decision) => needsAttention(decision.mapping_state)).length,
    [decisions],
  );

  const overrideCount = Object.keys(overrides).length;

  if (decisions.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No canonical decisions reported"
          description="No authoritative mapping decisions were provided for this review."
        />
      </Card>
    );
  }

  const beginEdit = (decision: CanonicalMappingDecision) => {
    const current = overrides[decision.source_field]?.concept
      ?? conceptFor(decision) ?? UNMAPPED;
    setEditing(decision.source_field);
    setDraft(current ?? UNMAPPED);
    setBlockMessage(null);
  };

  const applyOverride = (decision: CanonicalMappingDecision) => {
    const next: string | null = draft === UNMAPPED ? null : draft;
    const category =
      categories.get(decision.source_column) ??
      categories.get(decision.source_field.toLowerCase()) ??
      "";
    const offered = new Set(
      rankedOptions(decision, category, contract).map((item) => item.concept),
    );

    if (next !== null && !offered.has(next)) {
      setBlockMessage(
        `'${next}' is not offered for '${decision.source_field}'. ` +
          `Choose from the strict list or leave the field unmapped.`,
      );
      return;
    }

    const check = validateOverride(
      decision.source_field,
      next,
      decisions,
      overrideConcepts,
      contract,
    );

    if (!check.ok) {
      setBlockMessage(check.reason);
      return;
    }

    onOverride(decision.source_field, reviewerRecord(decision, next));
    setEditing(null);
    setBlockMessage(null);
  };

  const revertOverride = (field: string) => {
    onRevert(field);

    if (editing === field) {
      setEditing(null);
      setBlockMessage(null);
    }
  };

  return (
    <div>
      <dl className="mb-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
        {(
          [
            ["MAPPED", "Mapped"],
            ["LOW_CONFIDENCE", "Low confidence"],
            ["AMBIGUOUS", "Ambiguous"],
            ["UNMAPPED", "Unmapped"],
            ["INVALID", "Invalid"],
          ] as Array<[CanonicalMappingState, string]>
        ).map(([state, label]) => (
          <div
            key={state}
            className="rounded-[8px] border border-border bg-surface px-2.5 py-2"
          >
            <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">
              {label}
            </dt>
            <dd className="tabular text-lg font-semibold text-text">
              {states[state] ?? 0}
            </dd>
          </div>
        ))}
        <div className="rounded-[8px] border border-border bg-surface px-2.5 py-2">
          <dt className="micro uppercase tracking-[0.06em] text-text-tertiary">
            Reviewer overrides
          </dt>
          <dd className="tabular text-lg font-semibold text-text">
            {overrideCount}
          </dd>
        </div>
      </dl>

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="flex cursor-pointer items-center gap-2 text-[13px] text-text-secondary">
          <input
            type="checkbox"
            checked={attentionOnly}
            onChange={(event) => setAttentionOnly(event.target.checked)}
            className="size-3.5 accent-[#0f766e]"
          />
          Review attention-required mappings
          <span className="micro tabular text-text-tertiary">
            ({attentionCount} of {decisions.length})
          </span>
        </label>
        <span className="micro text-text-tertiary">
          Confident automatic mappings stay automatic; only uncertain or unsafe
          fields need review.
        </span>
      </div>

      {banner}

      <Card>
        <DataTable>
          <TableHead>
            <HeadCell>Source field</HeadCell>
            <HeadCell>Canonical concept</HeadCell>
            <HeadCell align="right">Confidence</HeadCell>
            <HeadCell>State</HeadCell>
            <HeadCell>Reason</HeadCell>
            <HeadCell align="right">Action</HeadCell>
          </TableHead>
          <TableBody>
            {visible.map((decision) => {
              const override = overrides[decision.source_field];
              const effectiveConcept = override
                ? override.concept
                : conceptFor(decision);
              const effectiveState = override
                ? override.newState
                : decision.mapping_state;
              const isEditing = editing === decision.source_field;
              const guardNote = guardBlocks(decision.source_field, decision.canonical_concept ?? "");

              return (
                <TableRow key={decision.source_field}>
                  <TableCell className="font-mono micro">
                    {decision.source_field}
                  </TableCell>
                  <TableCell className="font-mono micro">
                    {effectiveConcept ?? (
                      <span className="text-text-tertiary italic">—</span>
                    )}
                    {override ? (
                      <span className="ml-2 inline-flex items-center rounded-[6px] border border-caution/40 bg-caution/10 px-1.5 py-0.5 micro font-medium text-caution">
                        reviewer
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell align="right" className="tabular">
                    {decision.mapping_state === "MAPPED" ||
                    decision.mapping_state === "LOW_CONFIDENCE" ? (
                      decision.confidence.toFixed(2)
                    ) : (
                      <span className="text-text-tertiary">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      tone={override ? "caution" : stateTone(decision.mapping_state)}
                      label={
                        override
                          ? `${effectiveState} · override`
                          : decision.mapping_state.replace("_", " ")
                      }
                      raw={decision.mapping_state}
                      showDot={false}
                    />
                  </TableCell>
                  <TableCell className="max-w-[320px]">
                    <span className="line-clamp-3 text-xs leading-relaxed text-text-secondary">
                      {decision.reason}
                      {guardNote ? ` ${guardNote}` : ""}
                    </span>
                    {override ? (
                      <span className="mt-1 block micro text-text-tertiary">
                        Automatic {override.previousState}
                        {override.previousConcept ? ` (${override.previousConcept})` : ""} →{" "}
                        reviewer {override.concept ?? UNMAPPED} ·{" "}
                        {override.updatedAt.slice(0, 19).replace("T", " ")}Z
                      </span>
                    ) : null}
                    {decision.candidate_mappings.length > 1 &&
                    decision.mapping_state === "AMBIGUOUS" &&
                    !isEditing ? (
                      <span className="mt-1 block micro text-text-tertiary">
                        Candidates:{" "}
                        {decision.candidate_mappings
                          .slice(0, 3)
                          .map((item) => `${item.concept} (${item.confidence.toFixed(2)})`)
                          .join(" · ")}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell align="right">
                    {isEditing ? (
                      <span className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => applyOverride(decision)}
                          className="rounded-[6px] bg-primary px-2 py-1 text-xs font-semibold text-white hover:opacity-90"
                        >
                          Apply
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setEditing(null);
                            setBlockMessage(null);
                          }}
                          className="rounded-[6px] border border-border px-2 py-1 text-xs text-text-secondary hover:bg-subtle"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <span className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => beginEdit(decision)}
                          aria-label={`Edit mapping for ${decision.source_field}`}
                          className="rounded-[6px] border border-border px-2 py-1 text-xs font-medium text-accent hover:bg-subtle"
                        >
                          Edit
                        </button>
                        {override ? (
                          <button
                            type="button"
                            onClick={() => revertOverride(decision.source_field)}
                            aria-label={`Clear override for ${decision.source_field}`}
                            className="rounded-[6px] border border-border px-2 py-1 text-xs text-text-secondary hover:bg-subtle"
                          >
                            Revert
                          </button>
                        ) : null}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </DataTable>
      </Card>

      {editing ? (
        <EditPanel
          decision={decisions.find((item) => item.source_field === editing) ?? null}
          category={
            (() => {
              const found = decisions.find((item) => item.source_field === editing);
              return found
                ? (categories.get(found.source_column) ??
                  categories.get(found.source_field.toLowerCase()) ??
                  "")
                : "";
            })()
          }
          contract={contract}
          draft={draft}
          blockMessage={blockMessage}
          onDraft={setDraft}
        />
      ) : null}

      <p className="mt-2 micro leading-relaxed text-text-tertiary">
        Authoritative source: Phase 1 canonical decisions. The legacy
        semantic list is not shown as truth. {persistenceNote} The original
        source field and automatic decision are always preserved.
      </p>
    </div>
  );
}

/**
 * Post-analysis wiring: overrides persist per assessment in local session
 * storage, and any override means the loaded analysis must be rerun.
 */
export function CanonicalMappingReview() {
  const { result, analysis, run } = useAnalysis();
  const dataset = result?.dataset ?? analysis?.dataset ?? "";

  const decisions = useMemo(() => canonicalDecisions(result), [result]);
  const contract = useMemo(() => canonicalContract(result), [result]);
  const states = useMemo(() => canonicalStates(result), [result]);
  const categories = useMemo(
    () => profileCategoryByColumn(result),
    [result],
  );

  const [overrides, setOverrides] = useState<Record<string, ReviewerOverride>>({});

  useEffect(() => {
    if (dataset) {
      setOverrides(readOverrides(dataset));
    } else {
      setOverrides({});
    }
  }, [dataset]);

  if (!result) {
    return null;
  }

  const persist = (next: Record<string, ReviewerOverride>) => {
    setOverrides(next);

    if (dataset) {
      try {
        window.localStorage.setItem(overridesKey(dataset), JSON.stringify(next));
      } catch {
        // Storage pressure must not lose the on-screen review state.
      }
    }
  };

  const banner =
    Object.keys(overrides).length > 0 ? (
      <Caveat tone="caution" className="mb-3">
        Mapping changed — analysis must be rerun. The figures on screen were
        produced from the previous mapping.
        <span className="mt-2 block">
          <button
            type="button"
            onClick={() => {
              if (dataset) {
                void run(dataset);
              }
            }}
            className="rounded-[8px] bg-primary px-3 py-1.5 text-xs font-semibold text-white transition-opacity duration-100 hover:opacity-90"
          >
            Run analysis
          </button>
        </span>
      </Caveat>
    ) : null;

  return (
    <MappingReviewCore
      decisions={decisions}
      states={states}
      contract={contract}
      categories={categories}
      overrides={overrides}
      onOverride={(field, record) =>
        persist({ ...overrides, [field]: record })
      }
      onRevert={(field) => {
        const next = { ...overrides };
        delete next[field];
        persist(next);
      }}
      banner={banner}
      persistenceNote="Overrides are kept for this assessment only (local session storage);"
    />
  );
}

function EditPanel({
  decision,
  category,
  contract,
  draft,
  blockMessage,
  onDraft,
}: {
  decision: CanonicalMappingDecision | null;
  category: string;
  contract: Record<string, { datatype?: string | null; category?: string | null }>;
  draft: string;
  blockMessage: string | null;
  onDraft: (value: string) => void;
}) {
  if (!decision) {
    return null;
  }

  const fullContract = contract as Parameters<typeof rankedOptions>[2];
  const options = rankedOptions(decision, category, fullContract);
  const recommended = options.filter((item) => item.group === "recommended");
  const compatible = options.filter((item) => item.group === "compatible");
  const allowed = new Set(options.map((item) => item.concept));

  return (
    <div className="mt-3 rounded-[10px] border border-border bg-surface px-4 py-3">
      <div className="section-label">
        Edit mapping · <span className="font-mono">{decision.source_field}</span>
      </div>
      <p className="mt-1 micro text-text-tertiary">
        Detected type: {category || "unknown"}
        {decision.candidate_mappings.length > 0
          ? ` · automatic candidates: ${decision.candidate_mappings
              .slice(0, 3)
              .map((item) => `${item.concept} (${item.confidence.toFixed(2)})`)
              .join(", ")}`
          : " · no automatic candidate"}
      </p>
      <div className="mt-2 max-w-[520px]">
        <label
          htmlFor={`canonical-select-${decision.source_field}`}
          className="mb-1 block text-xs font-medium text-text"
        >
          Canonical concept (strict list, no free text)
        </label>
        <select
          id={`canonical-select-${decision.source_field}`}
          value={allowed.has(draft) || draft === UNMAPPED ? draft : UNMAPPED}
          onChange={(event) => onDraft(event.target.value)}
          className="w-full rounded-[8px] border border-border bg-surface px-2.5 py-2 text-[13px] text-text focus:outline-2 focus:outline-accent"
        >
          <optgroup label="Recommended">
            {recommended.length === 0 ? (
              <option value={UNMAPPED} disabled>
                No recommended candidate — leave unmapped or pick compatible
              </option>
            ) : (
              recommended.map((item) => (
                <option key={item.concept} value={item.concept}>
                  {item.concept}
                  {item.confidence !== null ? ` (${item.confidence.toFixed(2)})` : ""} —{" "}
                  {item.explanations.slice(0, 2).join("; ")}
                </option>
              ))
            )}
          </optgroup>
          <optgroup label="Other compatible">
            {compatible.map((item) => (
              <option key={item.concept} value={item.concept}>
                {item.concept}
                {item.confidence !== null ? ` (${item.confidence.toFixed(2)})` : ""} —{" "}
                {item.explanations.slice(0, 2).join("; ")}
              </option>
            ))}
          </optgroup>
          <optgroup label="Unmapped">
            <option value={UNMAPPED}>{UNMAPPED} — leave intentionally unmapped</option>
          </optgroup>
        </select>
        <p className="mt-1 micro text-text-tertiary">
          Only registry concepts appear. An incompatible choice is blocked with
          a reason; a wrong mapping is worse than unmapped.
        </p>
        {blockMessage ? (
          <p role="alert" className="mt-2 text-xs font-medium text-critical">
            {blockMessage}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function MappingReviewSection() {
  return (
    <Section
      title="Canonical mapping review"
      description="Authoritative Phase 1 decisions. Confident mappings are already applied; review the fields that need attention and rerun the analysis after any change."
    >
      <CanonicalMappingReview />
    </Section>
  );
}
