import { Search, X } from "lucide-react";
import { useId, type ChangeEvent, type ReactNode } from "react";

import { cn } from "../../lib/cn";

/**
 * A labelled filter control.
 *
 * Every filter states its label rather than relying on a placeholder, so a
 * filled field is still self-describing in a dense filter bar.
 */
export function FilterField({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1", className)}>
      <span className="section-label">{label}</span>
      {children}
    </label>
  );
}

const CONTROL =
  "h-8 w-full rounded-[8px] border border-border bg-surface px-2.5 text-[13px] text-text " +
  "placeholder:text-text-tertiary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

export function TextFilter({
  label,
  value,
  onChange,
  placeholder,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const id = useId();

  return (
    <FilterField label={label} className={className}>
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-tertiary"
          aria-hidden="true"
        />
        <input
          id={id}
          type="search"
          value={value}
          placeholder={placeholder}
          onChange={(event: ChangeEvent<HTMLInputElement>) =>
            onChange(event.target.value)
          }
          className={cn(CONTROL, "pl-7.5")}
        />
        {value ? (
          <button
            type="button"
            aria-label={`Clear ${label.toLowerCase()}`}
            onClick={() => onChange("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text"
          >
            <X className="size-3.5" aria-hidden="true" />
          </button>
        ) : null}
      </div>
    </FilterField>
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

/**
 * A select built on the native control.
 *
 * Native rather than a custom listbox: the options are short, the platform
 * already provides keyboard and screen-reader behaviour, and a custom widget
 * would add surface without adding capability.
 */
export function SelectFilter({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  className?: string;
}) {
  const id = useId();

  return (
    <FilterField label={label} className={className}>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={cn(CONTROL, "cursor-pointer pr-7")}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FilterField>
  );
}

/** A segmented control for a small, mutually exclusive set of options. */
export function SegmentedFilter({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="section-label">{label}</span>
      <div
        role="tablist"
        aria-label={label}
        className="inline-flex h-8 items-center gap-0.5 rounded-[8px] border border-border bg-subtle p-0.5"
      >
        {options.map((option) => {
          const active = option.value === value;

          return (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(option.value)}
              className={cn(
                "h-7 whitespace-nowrap rounded-[6px] px-2.5 text-xs font-medium transition-colors duration-100",
                active
                  ? "bg-surface text-text border border-border"
                  : "text-text-secondary hover:text-text",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
