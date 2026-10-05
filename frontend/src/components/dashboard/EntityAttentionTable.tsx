import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import {
  formatCount,
  entityLabel,
  formatPercentile,
  periodLabel,
} from "../../lib/formatters";
import { SIGNAL_FAMILIES } from "../../lib/status";
import type { EntityAttentionRow } from "../../app/viewModel";
import { CellAction } from "../ui/Button";
import { EmptyState } from "../ui/State";
import {
  HeadCell,
  HeadRow,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableScroller,
  Truncate,
  UnresolvedCell,
} from "../ui/Table";

/**
 * Evidence coverage for a scope, in one cell.
 *
 * The backend reports three capability states per scope. Reduced here to the one
 * that matters for triage — whether anything was assessable — with the full
 * triple available on the entity's own page. Presenting all three in a table
 * cell would triple the width of the column for information that only becomes
 * relevant once an examiner has chosen an entity.
 */
function EvidenceCell({ row }: { row: EntityAttentionRow }) {
  const { available, insufficient, notAssessed, nothingAssessable } = row.evidence;

  if (nothingAssessable) {
    return <span className="text-xs italic text-text-tertiary">Not reported</span>;
  }

  if (available === 0) {
    return (
      <span className="text-[13px] text-text-secondary">
        None assessable
        {insufficient + notAssessed > 0 ? (
          <span className="text-text-tertiary">
            {" "}
            ({insufficient + notAssessed} limited)
          </span>
        ) : null}
      </span>
    );
  }

  return (
    <span className="text-[13px] text-text">
      {formatCount(available)} assessable
      {insufficient + notAssessed > 0 ? (
        <span className="text-text-tertiary">
          {" "}
          ({insufficient + notAssessed} limited)
        </span>
      ) : null}
    </span>
  );
}

/**
 * How a scope sits against its peers, in one cell.
 *
 * Reads from the same benchmark the Overview and the scope's own page render, so
 * the roster does not assert a peer comparison the detail screen would contradict.
 * `row.benchmark.metrics` arrives in the order the view model derived from the
 * backend's `statistical_status`, so the first metric is the one the backend
 * could actually distinguish from its peers.
 *
 * A cohort with no spread reports "Tied" rather than the backend's 0.5
 * percentile: the percentile is a rank the cohort cannot support, and the full
 * per-metric comparison is on the scope's own page.
 */
function PeerCell({ row }: { row: EntityAttentionRow }) {
  const metrics = row.benchmark?.metrics ?? [];

  if (metrics.length === 0) {
    return <span className="text-xs italic text-text-tertiary">Not benchmarked</span>;
  }

  const lead = metrics[0];
  const separated = metrics.filter((metric) => metric.separated).length;
  const percentile =
    lead.percentile !== null && lead.percentileStatus === "COMPUTED"
      ? lead.percentile
      : null;

  return (
    <span className="min-w-0">
      <span className="block text-[13px] text-text">
        {separated > 0 ? "Separated" : "Tied"}
      </span>
      {/*
        The percentile leads this line so that a narrow cell wraps the metric
        name instead of cutting the number, which would read as a different value.
      */}
      <span className="block break-words text-[11px] leading-snug text-text-tertiary">
        {separated > 0
          ? `${percentile !== null ? `${formatPercentile(percentile)} · ` : ""}${lead.label}`
          : `no separation · ${formatCount(metrics.length)} metrics`}
      </span>
    </span>
  );
}

/**
 * The entity attention table.
 *
 * The primary action surface of the Overview, so it is built to answer one
 * question: which scope should I open next? Columns are chosen for that
 * decision and nothing else. Fields the backend published but that do not change
 * the decision — cohort tier, record positions, feature ids — are on the scope's
 * own page.
 *
 * `sort` chooses which question the row order answers:
 *
 *   - `priority` (default) sorts by signal count, then record count, then entity
 *     name. That is a triage order over backend counts; no risk, score or
 *     severity is used, because the backend does not publish one per scope for
 *     these datasets.
 *   - `backend` restores `assessment.scopes` order, which is what the Assessments
 *     screen shows. An examiner confirming that the run covered the scopes they
 *     expected is reading a roster, and a roster reordered by how many signals
 *     each produced would answer a question they did not ask.
 */
export function EntityAttentionTable({
  rows,
  emptyTitle,
  emptyDescription,
  showPeriod = false,
  sort = "priority",
  caption,
}: {
  rows: EntityAttentionRow[];
  emptyTitle?: string;
  emptyDescription?: string;
  showPeriod?: boolean;
  sort?: "priority" | "backend";
  caption?: string;
}) {
  const navigate = useNavigate();

  const ordered = useMemo(
    () =>
      sort === "backend"
        ? [...rows].sort((a, b) => a.order - b.order)
        : rows,
    [rows, sort],
  );

  // The Peers column only exists when the run published a benchmark, so a
  // dataset without one is not given an empty column.
  const anyBenchmarked = useMemo(
    () => ordered.some((row) => (row.benchmark?.metrics.length ?? 0) > 0),
    [ordered],
  );

  if (ordered.length === 0) {
    return (
      <EmptyState
        title={emptyTitle ?? "No assessment scopes"}
        description={
          emptyDescription ??
          "The pipeline reported no assessment scopes for this result, so there is nothing to investigate."
        }
      />
    );
  }

  return (
    <div className="min-w-0">
      <TableScroller>
        <TableHead>
          <HeadRow>
            <HeadCell width="20%">Entity</HeadCell>
            {showPeriod ? <HeadCell width="12%">Period</HeadCell> : null}
            <HeadCell width="7%" align="right">
              Signals
            </HeadCell>
            <HeadCell width="17%">Primary signal</HeadCell>
            <HeadCell width="16%">Attention</HeadCell>
            <HeadCell width="12%">Evidence</HeadCell>
            {anyBenchmarked ? <HeadCell width="14%">Peers</HeadCell> : null}
            <HeadCell width="8%" align="right">
              Action
            </HeadCell>
          </HeadRow>
        </TableHead>

        <TableBody>
          {ordered.map((row) => {
            const entityText = entityLabel(row.entity);
            const periodText = periodLabel(row.period);

            return (
              <TableRow
                key={row.assessmentId}
                onSelect={() =>
                  navigate(`/assessments/${encodeURIComponent(row.assessmentId)}`)
                }
              >
                <TableCell>
                  {row.resolved ? (
                    <Truncate className="font-medium">{entityText}</Truncate>
                  ) : (
                    <UnresolvedCell
                      label="Entity not identified"
                      reason={row.entity.unavailable_reason}
                    />
                  )}
                </TableCell>

                {showPeriod ? (
                  <TableCell>
                    {row.period.available ? (
                      <Truncate className="text-text-secondary">
                        {periodText}
                      </Truncate>
                    ) : (
                      <UnresolvedCell
                        label="Period not determined"
                        reason={row.period.unavailable_reason}
                      />
                    )}
                  </TableCell>
                ) : null}

                <TableCell align="right">
                  <span
                    className={
                      row.signals > 0
                        ? "tabular font-medium text-text"
                        : "tabular text-text-tertiary"
                    }
                  >
                    {formatCount(row.signals)}
                  </span>
                </TableCell>

                <TableCell>
                  {row.primaryFamily ? (
                    <Truncate className="text-text-secondary">
                      {primaryLabelOf(row)}
                    </Truncate>
                  ) : row.signals === 0 ? (
                    <span className="text-xs italic text-text-tertiary">None</span>
                  ) : (
                    <span className="text-xs text-text-tertiary">Split across families</span>
                  )}
                </TableCell>

                <TableCell>
                  <span className="text-[13px] text-text">{row.attention.label}</span>
                  <span className="block truncate text-[11px] text-text-tertiary">
                    {row.attention.detail}
                  </span>
                </TableCell>

                <TableCell>
                  <EvidenceCell row={row} />
                </TableCell>

                {anyBenchmarked ? (
                  <TableCell>
                    <PeerCell row={row} />
                  </TableCell>
                ) : null}

                <TableCell align="right">
                  <CellAction
                    onClick={() =>
                      navigate(
                        `/assessments/${encodeURIComponent(row.assessmentId)}`,
                      )
                    }
                  >
                    Investigate
                  </CellAction>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </TableScroller>

      {caption ? (
        <p className="mt-2 text-[11px] leading-relaxed text-text-tertiary">
          {caption}
        </p>
      ) : null}
    </div>
  );
}

const FAMILY_SINGULAR: Record<string, string> = Object.fromEntries(
  SIGNAL_FAMILIES.map((family) => [family.id, family.singular]),
);

function primaryLabelOf(row: EntityAttentionRow): string {
  return row.primaryFamily ? (FAMILY_SINGULAR[row.primaryFamily] ?? "") : "";
}
