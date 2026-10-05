import type { HTMLAttributes, ReactNode } from "react";

/**
 * A surface with a heading.
 *
 * Deliberately the *only* container primitive in the application. Sections,
 * tables and status strips are separated by border and whitespace; a card
 * exists only where a group of fields genuinely needs its own boundary. Nesting
 * cards to build hierarchy is what produced the previous interface's density,
 * so it is not supported here.
 */
export function Section({
  title,
  description,
  actions,
  children,
  className = "",
  bodyClassName = "",
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={`min-w-0 border-t border-border pt-5 ${className}`}
    >
      <header className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-text">{title}</h2>

          {description ? (
            <p className="mt-0.5 max-w-3xl text-xs text-text-secondary">
              {description}
            </p>
          ) : null}
        </div>

        {actions ? (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        ) : null}
      </header>

      <div className={`min-w-0 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

/**
 * A neutral note. Used for backend-stated limits, never for reassurance.
 */
export function Note({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: "neutral" | "caution" | "info";
  className?: string;
}) {
  const toneClass =
    tone === "caution"
      ? "border-caution/30 bg-caution-subtle text-caution"
      : tone === "info"
        ? "border-info/30 bg-info-subtle text-info"
        : "border-border bg-subtle text-text-secondary";

  return (
    <div
      className={`min-w-0 rounded-[8px] border px-3 py-2 text-xs leading-relaxed ${toneClass} ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * A plain bordered block, for a table that needs a frame.
 *
 * Not a card in the decorative sense: it exists so a wide table has a visible
 * edge and a place to scroll inside, and it adds no padding of its own so the
 * table can sit flush against the border.
 */
export function Frame({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`min-w-0 overflow-hidden rounded-[10px] border border-border bg-surface ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * A definition row: a fixed-width term and a value that may be long.
 *
 * The value column is `minmax(0, 1fr)` so a long backend sentence wraps inside
 * the row instead of stretching it past the container.
 */
export function DataRow({
  label,
  value,
  mono = false,
  className = "",
}: {
  label: ReactNode;
  value: ReactNode;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`grid min-w-0 grid-cols-[minmax(0,150px)_minmax(0,1fr)] items-baseline gap-x-3 py-1.5 ${className}`}
    >
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd
        className={`min-w-0 break-words text-[13px] text-text ${mono ? "font-mono text-xs" : ""}`}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * Verbatim backend prose.
 *
 * The detector and the benchmark engine each write their own explanation. It is
 * shown as written: paraphrasing it would put a second, unofficial claim about
 * the same evidence on screen next to the official one.
 */
export function BackendProse({
  children,
  className = "",
}: {
  children: string;
  className?: string;
}) {
  return (
    <p
      className={`min-w-0 max-w-prose break-words text-[13px] leading-relaxed text-text-secondary ${className}`}
    >
      {children}
    </p>
  );
}

/** A canonical concept identifier, in the interface's monospace face. */
export function ConceptTag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-block max-w-full truncate rounded-[5px] border border-border bg-subtle px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
      {children}
    </span>
  );
}

/**
 * A list of concept tags that collapses past a readable number.
 *
 * The full list stays reachable: expanding is a disclosure, not a truncation,
 * so nothing the backend reported is hidden behind a hover.
 */
export function ConceptList({
  concepts,
  collapseAfter = 6,
}: {
  concepts: string[];
  collapseAfter?: number;
}) {
  if (concepts.length === 0) {
    return (
      <span className="text-xs italic text-text-tertiary">None recorded</span>
    );
  }

  return (
    <details className="min-w-0">
      <summary className="flex cursor-pointer list-none flex-wrap gap-1">
        {concepts.slice(0, collapseAfter).map((concept) => (
          <ConceptTag key={concept}>{concept}</ConceptTag>
        ))}

        {concepts.length > collapseAfter ? (
          <span className="self-center text-xs text-text-secondary">
            +{concepts.length - collapseAfter} more
          </span>
        ) : null}
      </summary>

      <div className="mt-1.5 flex flex-wrap gap-1">
        {concepts.map((concept) => (
          <ConceptTag key={concept}>{concept}</ConceptTag>
        ))}
      </div>
    </details>
  );
}

/** A container that guarantees its children cannot push the page wider. */
export function Contain({
  children,
  className = "",
  ...rest
}: { children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`min-w-0 ${className}`} {...rest}>
      {children}
    </div>
  );
}
