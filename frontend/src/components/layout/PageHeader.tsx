import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

/**
 * A page heading.
 *
 * The subject of the assessment, the size of the evidence, and what was
 * produced. One hierarchy per page: heading, then metric row, then content.
 */
export function PageHeader({
  title,
  subject,
  meta,
  actions,
  description,
}: {
  title: string;
  subject?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  description?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-start justify-between gap-6">
      <div className="min-w-0">
        <h1 className="text-[19px] font-semibold tracking-[-0.01em] text-text">
          {title}
        </h1>
        {subject ? (
          <p className="mt-1 truncate text-[13px] text-text-secondary">
            {subject}
          </p>
        ) : null}
        {meta ? (
          <p className="mt-0.5 text-xs text-text-tertiary">{meta}</p>
        ) : null}
        {description ? (
          <p className="mt-2 max-w-3xl text-xs leading-relaxed text-text-secondary">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}

/** A titled content band. The label is uppercase and deliberately quiet. */
export function Section({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("mt-7 first:mt-0", className)}>
      <div className="mb-2.5 flex items-end justify-between gap-4">
        <div className="min-w-0">
          <h2 className="section-label">{title}</h2>
          {description ? (
            <p className="mt-1 text-xs text-text-secondary">{description}</p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

/**
 * A persistent interpretive note.
 *
 * Used where the absence of a finding would otherwise read as a clean result.
 * The wording comes from the backend wherever the backend supplies it.
 */
export function Caveat({
  children,
  className,
  tone = "neutral",
}: {
  children: ReactNode;
  className?: string;
  tone?: "neutral" | "caution";
}) {
  return (
    <p
      className={cn(
        "rounded-[8px] border px-3 py-2 text-xs leading-relaxed",
        tone === "caution"
          ? "border-caution/25 bg-caution-subtle text-caution"
          : "border-border bg-subtle text-text-secondary",
        className,
      )}
    >
      {children}
    </p>
  );
}
