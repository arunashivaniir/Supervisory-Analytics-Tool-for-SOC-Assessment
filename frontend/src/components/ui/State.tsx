import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, Loader2, TriangleAlert } from "lucide-react";

import type { Tone } from "../../lib/status";

/**
 * Status vocabulary and the states a screen can be in.
 *
 * Colour comes from a backend token via `lib/status.ts`. A component in this
 * file never decides that something is green or red on its own; it is handed a
 * tone. That is what keeps a state identical on every screen.
 */

const TONE_CLASS: Record<Tone, string> = {
  neutral: "border-border-strong bg-neutral-subtle text-neutral-tone",
  info: "border-info/30 bg-info-subtle text-info",
  positive: "border-positive/30 bg-positive-subtle text-positive",
  caution: "border-caution/30 bg-caution-subtle text-caution",
  critical: "border-critical/30 bg-critical-subtle text-critical",
};

const DOT_CLASS: Record<Tone, string> = {
  neutral: "bg-neutral-tone",
  info: "bg-info",
  positive: "bg-positive",
  caution: "bg-caution",
  critical: "bg-critical",
};

/**
 * The badge. Colour is semantic, the raw token is always available as a title
 * so a value the interface has not seen before is still readable.
 */
export function StatusBadge({
  tone,
  label,
  raw,
  showDot = false,
  className = "",
}: {
  tone: Tone;
  label: string;
  raw?: string | null;
  showDot?: boolean;
  className?: string;
}) {
  const title =
    raw && raw !== label ? `${label} — backend reported "${raw}"` : undefined;

  return (
    <span
      title={title}
      className={`inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONE_CLASS[tone]} ${className}`}
    >
      {showDot ? (
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_CLASS[tone]}`}
        />
      ) : null}
      <span className="truncate">{label}</span>
    </span>
  );
}

/**
 * A value the backend did not produce.
 *
 * Rendered in words, in italics, never as a dash or a zero. "Not available" and
 * "0" mean opposite things to an examiner and only one of them is true.
 */
export function NotAvailable({
  children = "Not available",
  className = "",
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <span className={`text-[13px] italic text-text-tertiary ${className}`}>
      {children}
    </span>
  );
}

/** Inert skeleton. Widths are deterministic so the layout does not jump. */
export function LoadingRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="min-w-0 space-y-2" role="status" aria-live="polite">
      <span className="sr-only">Loading</span>

      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          className="h-4 animate-pulse rounded-[4px] bg-neutral-subtle"
          style={{ width: `${45 + ((index * 17) % 40)}%` }}
        />
      ))}
    </div>
  );
}

/** A spinner with a stated subject, for a run that is genuinely in flight. */
export function LoadingState({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-w-0 items-start gap-3 rounded-[10px] border border-border bg-surface px-4 py-5"
    >
      <Loader2
        aria-hidden="true"
        className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-text-secondary"
      />

      <div className="min-w-0">
        <p className="text-[13px] font-medium text-text">{title}</p>

        {detail ? (
          <p className="mt-0.5 text-xs text-text-secondary">{detail}</p>
        ) : null}
      </div>
    </div>
  );
}

/**
 * A completed run that produced nothing.
 *
 * The wording is the important part. "No findings" is a claim about the
 * assessment; this states what was run and what it returned, and does not
 * extend that into a claim that the controls in scope are effective, which
 * would be a conclusion the pipeline did not reach.
 */
export function EmptyState({
  title,
  description,
  action,
  icon: Icon = Info,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: typeof Info;
}) {
  return (
    <div className="flex min-w-0 flex-col items-start gap-2 rounded-[10px] border border-dashed border-border-strong bg-surface px-4 py-6">
      <Icon aria-hidden="true" className="h-4 w-4 shrink-0 text-text-tertiary" />

      <div className="min-w-0">
        <p className="text-[13px] font-medium text-text">{title}</p>

        {description ? (
          <p className="mt-1 max-w-prose text-xs leading-relaxed text-text-secondary">
            {description}
          </p>
        ) : null}
      </div>

      {action}
    </div>
  );
}

/** A failure, with what the backend said. */
export function ErrorState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string | null;
  action?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="flex min-w-0 items-start gap-3 rounded-[10px] border border-critical/30 bg-critical-subtle px-4 py-4"
    >
      <AlertCircle
        aria-hidden="true"
        className="mt-0.5 h-4 w-4 shrink-0 text-critical"
      />

      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-critical">{title}</p>

        {detail ? (
          <p className="mt-1 break-words text-xs leading-relaxed text-critical">
            {detail}
          </p>
        ) : null}

        {action ? <div className="mt-2">{action}</div> : null}
      </div>
    </div>
  );
}

/**
 * A constraint the backend stated about its own output.
 *
 * Distinct from `ErrorState`: nothing failed, the pipeline is telling the
 * examiner where its own output should not be over-read.
 */
export function LimitationNote({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-start gap-2.5 rounded-[8px] border border-caution/25 bg-caution-subtle/60 px-3 py-2">
      <TriangleAlert
        aria-hidden="true"
        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-caution"
      />

      <p className="min-w-0 break-words text-xs leading-relaxed text-caution">
        {children}
      </p>
    </div>
  );
}

/** Confirmation that a specific requirement was met. */
export function MetNote({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-start gap-2.5 rounded-[8px] border border-positive/25 bg-positive-subtle px-3 py-2">
      <CheckCircle2
        aria-hidden="true"
        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive"
      />

      <p className="min-w-0 break-words text-xs leading-relaxed text-positive">
        {children}
      </p>
    </div>
  );
}
