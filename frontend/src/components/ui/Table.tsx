import type { ReactNode } from "react";

/**
 * The table system.
 *
 * One decision drives everything here: a backend string can be arbitrarily
 * long, and it must never widen the page. So the table is `w-full` inside a
 * scroll container, and `index.css` sets `max-width: 0` on every cell, which
 * makes the column widths resolve against the container rather than against the
 * content. Cells that must stay on one line use `Truncate`; prose uses `Clamp`.
 *
 * The header is sticky because these tables are the primary working surface and
 * an examiner scrolling 40 findings should not have to scroll back to remember
 * what a column means.
 */

/** Scrolls horizontally inside its own bounds. Never the page. */
export function TableScroller({ children }: { children: ReactNode }) {
  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">{children}</table>
    </div>
  );
}

/**
 * The header row group.
 *
 * Takes the row itself, not the cells: the header is a `<thead>` around a
 * `<tr>`, and a component that supplied its own `<tr>` would nest one row inside
 * another whenever a caller passed a complete row. Sticky because these tables
 * are the primary working surface and an examiner scrolling 40 findings should
 * not have to scroll back to remember what a column means.
 */
export function TableHead({ children }: { children: ReactNode }) {
  return <thead className="sticky top-0 z-10 bg-subtle">{children}</thead>;
}

/** The header row: a `<tr>` with the bottom rule that separates it from the body. */
export function HeadRow({ children }: { children: ReactNode }) {
  return <tr className="border-b border-border">{children}</tr>;
}

export function HeadCell({
  children,
  align = "left",
  width,
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
  width?: string;
  className?: string;
}) {
  return (
    <th
      scope="col"
      style={width ? { width } : undefined}
      className={`px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.06em] text-text-tertiary ${
        align === "right" ? "text-right" : align === "center" ? "text-center" : ""
      } ${className}`}
    >
      {children}
    </th>
  );
}

export function TableBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-border">{children}</tbody>;
}

/**
 * A row. When `onSelect` is supplied the row becomes a real control: it takes
 * focus, responds to Enter and Space, and is announced as a button. That keeps
 * the table navigable by keyboard without putting a nested interactive element
 * inside a table cell, which breaks screen-reader table navigation.
 */
export function TableRow({
  children,
  onSelect,
  selected = false,
  className = "",
}: {
  children: ReactNode;
  onSelect?: () => void;
  selected?: boolean;
  className?: string;
}) {
  if (!onSelect) {
    return <tr className={className}>{children}</tr>;
  }

  return (
    <tr
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      tabIndex={0}
      role="button"
      aria-selected={selected}
      className={`cursor-pointer transition-colors hover:bg-subtle focus-visible:bg-subtle focus-visible:outline-2 focus-visible:outline-accent ${
        selected ? "bg-accent-subtle/60" : ""
      } ${className}`}
    >
      {children}
    </tr>
  );
}

export function TableCell({
  children,
  align = "left",
  colSpan,
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
  colSpan?: number;
  className?: string;
}) {
  return (
    <td
      colSpan={colSpan}
      className={`px-3 py-2 align-middle text-text ${
        align === "right" ? "text-right" : align === "center" ? "text-center" : ""
      } ${className}`}
    >
      {children}
    </td>
  );
}

/**
 * A value that must not wrap, with the full value on hover.
 *
 * Used for identifiers, dataset paths and digests: things an examiner needs to
 * read in full but whose full length would otherwise distort the table.
 */
export function Truncate({
  children,
  title,
  className = "",
}: {
  children: ReactNode;
  /** Defaults to the text itself. */
  title?: string;
  className?: string;
}) {
  const text = typeof children === "string" ? children : undefined;

  return (
    <span className={`truncate-cell ${className}`} title={title ?? text}>
      {children}
    </span>
  );
}

/**
 * Prose bounded to a few lines, with the full text on hover and always in full
 * in the detail view.
 */
export function Clamp({
  children,
  lines = 2,
  title,
  className = "",
}: {
  children: ReactNode;
  lines?: 2 | 3;
  title?: string;
  className?: string;
}) {
  return (
    <span
      className={`${lines === 2 ? "clamp-2" : "clamp-3"} ${className}`}
      title={title}
    >
      {children}
    </span>
  );
}

/**
 * An identity the backend could not resolve.
 *
 * The reason travels with the marker. "Entity not identified" on its own is an
 * accusation about the data; the reason is the backend's statement of what
 * prevented resolution.
 */
export function UnresolvedCell({
  label,
  reason,
}: {
  label: string;
  reason: string | null;
}) {
  return (
    <span className="min-w-0" title={reason ?? undefined}>
      <span className="text-xs italic text-text-tertiary">{label}</span>
    </span>
  );
}

/** The row a table shows when it has nothing to list. */
export function TableEmptyRow({
  colSpan,
  children,
}: {
  colSpan: number;
  children: ReactNode;
}) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-3 py-6 text-center text-[13px] text-text-secondary">
        {children}
      </td>
    </tr>
  );
}
