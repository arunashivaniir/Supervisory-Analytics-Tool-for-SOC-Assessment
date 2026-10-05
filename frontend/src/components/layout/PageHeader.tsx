import type { ReactNode } from "react";

/**
 * A page title.
 *
 * One `h1` per screen, and a short supporting line at most. The previous
 * interface put a paragraph of explanation under every title; the detail
 * belongs in the section it describes or in a disclosure, not above the fold.
 */
export function PageHeader({
  title,
  supporting,
  actions,
}: {
  title: string;
  supporting?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-5 flex min-w-0 flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-[19px] font-semibold leading-tight text-text">
          {title}
        </h1>

        {supporting ? (
          <p className="mt-1 max-w-3xl break-words text-[13px] text-text-secondary">
            {supporting}
          </p>
        ) : null}
      </div>

      {actions ? (
        <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      ) : null}
    </header>
  );
}
