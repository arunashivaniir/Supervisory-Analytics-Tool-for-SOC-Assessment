import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

/**
 * A side panel for a detail view.
 *
 * The list behind it stays mounted. That is the whole reason this is a dialog
 * over the page rather than a navigation: an examiner comparing two findings
 * should not lose their filters, their scroll position, or their place in the
 * list by opening one.
 *
 * Radix handles the focus trap, the escape key, the scroll lock and the
 * `aria-modal` wiring. Writing that by hand is how dialogs end up trapping
 * focus on a container that is not there.
 */
export function DetailDrawer({
  open,
  onOpenChange,
  title,
  subtitle,
  children,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-primary/25" />

        <Dialog.Content
          className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[min(640px,100vw)] flex-col border-l border-border bg-surface shadow-lg focus:outline-none"
          data-print-hide
        >
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-[15px] font-semibold text-text">
                {title}
              </Dialog.Title>

              {subtitle ? (
                <Dialog.Description className="mt-0.5 break-words text-xs text-text-secondary">
                  {subtitle}
                </Dialog.Description>
              ) : null}
            </div>

            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close detail"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] text-text-secondary hover:bg-subtle hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </header>

          <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-5 py-4">
            {children}
          </div>

          {footer ? (
            <footer className="shrink-0 border-t border-border px-5 py-3">
              {footer}
            </footer>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A titled block inside a drawer or a detail page. */
export function DetailSection({
  title,
  description,
  children,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 border-t border-border pt-4 first:border-t-0 first:pt-0 ${className}`}>
      <h3 className="section-label">{title}</h3>

      {description ? (
        <p className="mt-1 max-w-prose text-xs leading-relaxed text-text-secondary">
          {description}
        </p>
      ) : null}

      <div className="mt-2.5 min-w-0">{children}</div>
    </section>
  );
}
