import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * Buttons.
 *
 * Hand-rolled rather than composed from a variant library, because there are
 * three variants and one size and a dependency to express that is not worth
 * carrying. Every button declares `type` explicitly: a button inside a form
 * that submits by accident is a real defect in a tool with destructive actions.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    "border-transparent bg-primary text-white hover:bg-primary-hover disabled:hover:bg-primary",
  secondary:
    "border-border-strong bg-surface text-text hover:bg-subtle disabled:hover:bg-surface",
  ghost:
    "border-transparent bg-transparent text-text-secondary hover:bg-subtle hover:text-text disabled:hover:bg-transparent",
  danger:
    "border-transparent bg-critical text-white hover:opacity-90 disabled:hover:opacity-100",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-8 px-3 text-[13px]",
};

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  variant = "secondary",
  size = "md",
  type = "button",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-[8px] border font-medium transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-45 ${VARIANT_CLASS[variant]} ${SIZE_CLASS[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/**
 * A text action inside a table cell.
 *
 * A real button, so it is reachable by keyboard and announced as an action,
 * rather than a styled link or a click handler on a `<td>`.
 */
export function CellAction({
  children,
  onClick,
  className = "",
}: {
  children: ReactNode;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`whitespace-nowrap rounded-[6px] px-1.5 py-1 text-xs font-medium text-accent underline-offset-2 hover:bg-accent-subtle hover:underline focus-visible:outline-2 focus-visible:outline-accent ${className}`}
    >
      {children}
    </button>
  );
}
