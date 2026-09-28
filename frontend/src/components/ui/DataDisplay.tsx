import { useState, type ReactNode } from "react";

import { cn } from "../../lib/cn";

/**
 * A label/value pair on a shared baseline grid.
 *
 * Every labelled value in the application uses this component, so labels align
 * down the page regardless of which screen they appear on.
 */
export function DataRow({
  label,
  value,
  className,
  valueClassName,
}: {
  label: string;
  value: ReactNode;
  className?: string;
  valueClassName?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[minmax(0,180px)_minmax(0,1fr)] items-baseline gap-3 py-1.5",
        className,
      )}
    >
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className={cn("min-w-0 text-[13px] text-text", valueClassName)}>
        {value}
      </dd>
    </div>
  );
}

/** A short monospace token, used for identifiers and fingerprints. */
export function Token({ children }: { children: ReactNode }) {
  return (
    <span className="font-mono micro text-text-secondary">{children}</span>
  );
}

/**
 * Prose that came from the backend, rendered verbatim.
 *
 * Explanations are the analyst's words. This component wraps them for
 * readability and does nothing else: no summarising, no shortening, no
 * rewriting into plainer language.
 */
export function BackendProse({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <p className={cn("text-[13px] leading-relaxed text-text", className)}>
      {children}
    </p>
  );
}

/** A term from the canonical concept vocabulary, shown as a tag. */
export function ConceptTag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-[5px] border border-border bg-subtle px-1.5 py-0.5 font-mono micro text-text-secondary">
      {children}
    </span>
  );
}

/**
 * A count of terms, collapsed when the list is long.
 *
 * Progressive disclosure: the first few terms are shown and the rest are
 * available on demand, so a wide vocabulary does not dominate the layout.
 */
export function ConceptList({
  concepts,
  collapsed = 6,
}: {
  concepts: string[];
  collapsed?: number;
}) {
  // The expanded state is keyed by the list itself, so a different set of
  // concepts starts collapsed without an effect that would reset it after a
  // render it should never have needed.
  const listKey = concepts.join("\u0000");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const expanded = expandedKey === listKey;

  if (concepts.length === 0) {
    return <span className="text-xs text-text-tertiary italic">None recorded</span>;
  }

  const visible = expanded ? concepts : concepts.slice(0, collapsed);
  const hidden = concepts.length - visible.length;

  return (
    <div className="flex flex-wrap items-center gap-1">
      {visible.map((concept) => (
        <ConceptTag key={concept}>{concept}</ConceptTag>
      ))}
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setExpandedKey(listKey)}
          className="micro text-accent underline-offset-2 hover:underline"
        >
          +{hidden} more
        </button>
      ) : null}
      {expanded && concepts.length > collapsed ? (
        <button
          type="button"
          onClick={() => setExpandedKey(null)}
          className="micro text-text-tertiary underline-offset-2 hover:underline"
        >
          Collapse
        </button>
      ) : null}
    </div>
  );
}
