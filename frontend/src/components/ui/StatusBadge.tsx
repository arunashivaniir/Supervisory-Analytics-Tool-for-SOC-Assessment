import type { ReactNode } from "react";

import { cn } from "../../lib/cn";
import type { Tone } from "../../lib/status";

/**
 * A backend status, rendered as a small pill.
 *
 * The component takes a tone rather than deciding one, so the colour always
 * originates in `lib/status.ts` from a string the backend produced. Nothing
 * here can turn a value into a severity.
 */

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-neutral-subtle text-neutral-tone border-border",
  info: "bg-info-subtle text-info border-border",
  positive: "bg-positive-subtle text-positive border-positive/20",
  caution: "bg-caution-subtle text-caution border-caution/20",
  critical: "bg-critical-subtle text-critical border-critical/20",
};

const DOT_CLASS: Record<Tone, string> = {
  neutral: "bg-text-tertiary",
  info: "bg-info",
  positive: "bg-positive",
  caution: "bg-caution",
  critical: "bg-critical",
};

export interface StatusBadgeProps {
  tone: Tone;
  label: string;
  /** Renders the backend's raw token beside the label, for traceability. */
  raw?: string;
  showDot?: boolean;
  className?: string;
  title?: string;
}

export function StatusBadge({
  tone,
  label,
  raw,
  showDot = true,
  className,
  title,
}: StatusBadgeProps) {
  return (
    <span
      title={title ?? (raw && raw !== label ? raw : undefined)}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-[6px] border px-1.5 py-0.5",
        "micro font-medium leading-4",
        TONE_CLASS[tone],
        className,
      )}
    >
      {showDot ? (
        <span className={cn("size-1.5 rounded-full", DOT_CLASS[tone])} />
      ) : null}
      {label}
    </span>
  );
}

/**
 * A value the backend did not determine.
 *
 * Rendered as muted text rather than a dash, because a dash in a table reads
 * as zero to an examiner scanning a column.
 */
export function NotAvailable({
  children = "Not available",
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("text-text-tertiary italic", className)}>{children}</span>
  );
}
