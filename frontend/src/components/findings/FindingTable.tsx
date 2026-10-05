import { useNavigate } from "react-router-dom";

import type { UnifiedFinding } from "../../app/selectors";
import {
  entityLabel,
  formatCount,
  periodLabel,
} from "../../lib/formatters";
import { signalStatus } from "../../lib/status";
import {
  Clamp,
  HeadCell,
  HeadRow,
  TableBody,
  TableCell,
  TableEmptyRow,
  TableHead,
  TableRow,
  TableScroller,
  UnresolvedCell,
} from "../ui/Table";
import { StatusBadge } from "../ui/State";

/**
 * The findings table.
 *
 * One component, two screens. The Findings screen shows every finding in the
 * run; an entity page shows only that scope's. Sharing it is not tidiness — it
 * is the reason a finding opened from either screen shows the same indicator,
 * the same status and the same words, so an examiner reading a screenshot or a
 * shared link sees what their colleague saw.
 *
 * Selecting a row opens a drawer. It does not navigate: the list behind the
 * drawer keeps its filters and its scroll position, which is what makes
 * comparing findings practical. The row is the control, so the table stays
 * navigable by keyboard without nesting a button inside a cell.
 *
 * The family is the column that identifies a finding, so it comes first and is
 * coloured from the family palette. Colour carries no severity ordering, because
 * the families are kinds of detection rather than ranks.
 */
export function FindingTable({
  findings,
  onOpen,
  selectedKey = null,
  emptyTitle,
  emptyDescription,
  showEntity = true,
}: {
  findings: UnifiedFinding[];
  onOpen: (key: string) => void;
  selectedKey?: string | null;
  emptyTitle?: string;
  emptyDescription?: string;
  showEntity?: boolean;
}) {
  const navigate = useNavigate();

  const columnCount = showEntity ? 5 : 4;

  if (findings.length === 0) {
    return (
      <TableScroller>
        <TableHead>
          <HeadRow>
            <HeadCell>Indicator</HeadCell>
            {showEntity ? <HeadCell>Entity</HeadCell> : null}
            <HeadCell width="18%">Status</HeadCell>
            <HeadCell>Why the pipeline reported it</HeadCell>
            <HeadCell width="9%" align="right">
              Evidence
            </HeadCell>
          </HeadRow>
        </TableHead>

        <TableBody>
          <TableEmptyRow colSpan={columnCount}>
            <span className="block font-medium text-text">
              {emptyTitle ?? "No findings reported"}
            </span>
            <span className="mt-1 block text-text-tertiary">
              {emptyDescription ??
                "The pipeline did not report a finding for this selection."}
            </span>
          </TableEmptyRow>
        </TableBody>
      </TableScroller>
    );
  }

  return (
    <TableScroller>
      <TableHead>
        <HeadRow>
          <HeadCell width={showEntity ? "26%" : "32%"}>Indicator</HeadCell>
          {showEntity ? <HeadCell width="18%">Entity</HeadCell> : null}
          <HeadCell width="16%">Status</HeadCell>
          <HeadCell>Why the pipeline reported it</HeadCell>
          <HeadCell width="9%" align="right">
            Evidence
          </HeadCell>
        </HeadRow>
      </TableHead>

      <TableBody>
        {findings.map((item) => {
          const status = signalStatus(item.status);

          return (
            <TableRow
              key={item.key}
              onSelect={() => onOpen(item.key)}
              selected={item.key === selectedKey}
            >
              <TableCell>
                <span className="flex min-w-0 items-baseline gap-2">
                  <span
                    aria-hidden="true"
                    className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                    style={{
                      backgroundColor: `var(--color-family-${item.family})`,
                    }}
                  />
                  <span className="min-w-0">
                    <Clamp
                      lines={2}
                      title={item.indicator}
                      className="font-medium text-text"
                    >
                      {item.indicator}
                    </Clamp>
                    <span className="mt-0.5 block text-[11px] text-text-tertiary">
                      {item.familyLabel}
                    </span>
                  </span>
                </span>
              </TableCell>

              {showEntity ? (
                <TableCell>
                  {item.entity.available ? (
                    <span className="min-w-0">
                      <Clamp lines={2} title={entityLabel(item.entity)}>
                        {entityLabel(item.entity)}
                      </Clamp>
                      {item.period.available ? (
                        <span className="mt-0.5 block truncate text-[11px] text-text-tertiary">
                          {periodLabel(item.period)}
                        </span>
                      ) : (
                        <span className="mt-0.5 block text-[11px] italic text-text-tertiary">
                          period not determined
                        </span>
                      )}
                    </span>
                  ) : (
                    <UnresolvedCell
                      label="Entity not identified"
                      reason={item.entity.unavailable_reason}
                    />
                  )}
                </TableCell>
              ) : null}

              <TableCell>
                <StatusBadge
                  tone={status.tone}
                  label={status.label}
                  raw={item.status}
                />
              </TableCell>

              <TableCell>
                <Clamp lines={3} title={item.reason} className="text-text-secondary">
                  {item.reason}
                </Clamp>
              </TableCell>

              <TableCell align="right">
                <button
                  type="button"
                  className="tabular text-[13px] text-text-secondary underline-offset-2 hover:text-accent hover:underline"
                  onClick={(event) => {
                    event.stopPropagation();
                    navigate(`/evidence?assessment=${encodeURIComponent(item.assessment_id)}`);
                  }}
                  title="Open the evidence register for the scope this finding belongs to"
                >
                  {item.evidenceConcepts.length > 0
                    ? formatCount(item.evidenceConcepts.length)
                    : "—"}
                </button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </TableScroller>
  );
}
