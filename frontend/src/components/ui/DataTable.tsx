import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

/**
 * A dense analytical table.
 *
 * Deliberately not card-like: no row hover fill beyond a faint tint, no zebra
 * striping, no rounded row corners. Row separation is a 1px border, which is
 * what lets a hundred rows stay readable without decoration.
 */
export function DataTable({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <table className="w-full border-collapse text-[13px]">{children}</table>
    </div>
  );
}

export function TableHead({
  children,
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <thead className={cn("bg-subtle", className)}>
      <tr className="border-b border-border">{children}</tr>
    </thead>
  );
}

/** A column header. Uppercase, quiet, and never a visual anchor. */
export function HeadCell({
  children,
  className,
  align = "left",
}: {
  children?: ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      scope="col"
      className={cn(
        "px-3 py-2 micro font-semibold uppercase tracking-[0.06em] text-text-tertiary",
        align === "right" && "text-right",
        align === "center" && "text-center",
        align === "left" && "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TableBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-border">{children}</tbody>;
}

export function TableRow({
  children,
  className,
  onClick,
  selected,
}: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  selected?: boolean;
}) {
  const interactive = Boolean(onClick);

  return (
    <tr
      onClick={onClick}
      tabIndex={interactive ? 0 : undefined}
      role={interactive ? "button" : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      className={cn(
        "transition-colors duration-75",
        interactive &&
          "cursor-pointer hover:bg-subtle focus-visible:bg-subtle focus-visible:outline-none",
        selected && "bg-accent-subtle/60",
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TableCell({
  children,
  className,
  align = "left",
}: {
  children?: ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}) {
  return (
    <td
      className={cn(
        "px-3 py-2 align-top text-text",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </td>
  );
}

/** A cell holding an identity the backend could not resolve. */
export function UnresolvedCell({
  children,
  reason,
}: {
  children: ReactNode;
  reason?: string | null;
}) {
  return (
    <span className="text-text-tertiary italic" title={reason ?? undefined}>
      {children}
    </span>
  );
}
