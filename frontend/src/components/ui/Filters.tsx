import { useId, type ReactNode } from "react";
import { Search, X } from "lucide-react";

/**
 * Filters.
 *
 * Native `<select>` and `<input type="search">` throughout. A custom listbox
 * would need its own keyboard handling, its own focus management and its own
 * screen-reader wiring to be no worse than the platform control, which already
 * has all three on every machine the examiner might use.
 */

const CONTROL =
  "h-8 w-full min-w-0 rounded-[8px] border border-border bg-surface px-2.5 text-[13px] text-text placeholder:text-text-tertiary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

export function FilterField({
  label,
  children,
  className = "",
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <label className="section-label mb-1 block">{label}</label>
      {children}
    </div>
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

export function SelectFilter({
  label,
  value,
  options,
  onChange,
  className = "",
  hideLabel = false,
}: {
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  className?: string;
  hideLabel?: boolean;
}) {
  const id = useId();

  return (
    <div className={`min-w-0 ${className}`}>
      <label
        htmlFor={id}
        className={hideLabel ? "sr-only" : "section-label mb-1 block"}
      >
        {label}
      </label>

      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={CONTROL}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function TextFilter({
  label,
  value,
  onChange,
  placeholder,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const id = useId();

  return (
    <div className={`min-w-0 ${className}`}>
      <label htmlFor={id} className="section-label mb-1 block">
        {label}
      </label>

      <div className="relative min-w-0">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-tertiary"
        />

        <input
          id={id}
          type="search"
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          className={`${CONTROL} pl-8`}
        />

        {value.length > 0 ? (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label={`Clear ${label.toLowerCase()}`}
            className="absolute right-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-text-tertiary hover:bg-subtle hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
          >
            <X aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * A small set of mutually exclusive choices.
 *
 * Rendered as radio inputs rather than a tablist: these filter a list, they do
 * not switch a panel, and a tablist would tell a screen-reader user they are
 * looking at different documents.
 */
export function SegmentedFilter({
  label,
  value,
  options,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  className?: string;
}) {
  const name = useId();

  return (
    <fieldset className={`min-w-0 ${className}`}>
      <legend className="section-label mb-1">{label}</legend>

      <div className="flex flex-wrap gap-1">
        {options.map((option) => {
          const checked = option.value === value;

          return (
            <label
              key={option.value}
              className={`cursor-pointer whitespace-nowrap rounded-[8px] border px-2.5 py-1 text-xs font-medium transition-colors ${
                checked
                  ? "border-primary bg-primary text-white"
                  : "border-border bg-surface text-text-secondary hover:bg-subtle"
              }`}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={checked}
                onChange={() => onChange(option.value)}
                className="sr-only"
              />
              {option.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
