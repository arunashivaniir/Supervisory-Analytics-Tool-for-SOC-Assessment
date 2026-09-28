import type { ReactNode } from "react";

import { cn } from "../../lib/cn";
import { NOT_AVAILABLE } from "../../lib/formatters";

/**
 * A single headline figure.
 *
 * The value and its context travel together. A metric without a source label
 * is an assertion the examiner cannot check, so the block always states what
 * the number is and where it came from.
 *
 * `state` distinguishes the three absences that matter to an examiner and must
 * never be collapsed: a real zero, a value the backend did not produce, and a
 * layer that declined to evaluate.
 */
export type MetricState = "measured" | "zero" | "absent" | "not-evaluated";

export function MetricBlock({
  label,
  value,
  context,
  state = "measured",
  className,
}: {
  label: string;
  value: ReactNode;
  context?: ReactNode;
  state?: MetricState;
  className?: string;
}) {
  const absent = state === "absent" || state === "not-evaluated";

  return (
    <div
      className={cn(
        "flex min-w-0 flex-col justify-between rounded-[10px] border border-border bg-surface px-4 py-3",
        className,
      )}
    >
      <span className="section-label">{label}</span>
      <div className="mt-2">
        <div
          className={cn(
            "text-2xl font-semibold leading-none tracking-[-0.01em]",
            absent ? "text-text-tertiary" : "text-text",
          )}
        >
          {value}
        </div>
        {context ? (
          <p className="mt-1.5 micro leading-snug text-text-secondary">
            {context}
          </p>
        ) : null}
      </div>
    </div>
  );
}

/** The value a metric shows when the backend produced nothing to count. */
export function absentValue(label: string): string {
  return label === "zero" ? "0" : NOT_AVAILABLE;
}

/**
 * The empty state.
 *
 * States which of the three conditions applies, because "no findings" and "no
 * analysis yet" and "this layer did not evaluate" are different statements
 * about the same empty table.
 */
export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-12 text-center",
        className,
      )}
    >
      <p className="text-[13px] font-medium text-text">{title}</p>
      {description ? (
        <p className="max-w-md text-xs leading-relaxed text-text-secondary">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** A neutral placeholder while a run is in flight. */
export function LoadingRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="divide-y divide-border" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="px-3 py-2.5">
          <div
            className="h-3 rounded-[4px] bg-border/70"
            style={{ width: `${45 + ((index * 17) % 40)}%` }}
          />
        </div>
      ))}
    </div>
  );
}
