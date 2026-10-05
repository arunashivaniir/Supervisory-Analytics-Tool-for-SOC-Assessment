/**
 * Display formatting.
 *
 * The single rule these helpers follow: they never invent a value. A field the
 * backend left empty renders as an explicit "not available" marker, never as a
 * zero, a dash that could be read as zero, or an empty cell that looks like
 * good news.
 */

import type {
  AnomalyVerdictCounts,
  CapabilityStatus,
  EntityRef,
  MaybeNumber,
  MaybeString,
  PeriodRef,
  Unrepresentable,
} from "../types/pipeline";

/** Shown wherever a value is genuinely absent, as distinct from zero. */
export const NOT_AVAILABLE = "Not available";

/** Shown where the backend declined to evaluate rather than finding nothing. */
export const NOT_EVALUATED = "Not evaluated";

/** Shown where evidence was submitted but insufficient. */
export const INSUFFICIENT = "Insufficient evidence";

export function isUnrepresentable(value: unknown): value is Unrepresentable {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Unrepresentable).__unrepresentable__ === true
  );
}

/**
 * A count. Zero is a real measurement and is shown as `0`. A missing count is
 * shown as not available, never as `0`.
 */
export function formatCount(value: MaybeNumber | undefined): string {
  if (value === null || value === undefined) {
    return NOT_AVAILABLE;
  }

  if (!Number.isFinite(value)) {
    return NOT_EVALUATED;
  }

  return new Intl.NumberFormat("en-GB").format(value);
}

/**
 * A proportion from 0 to 1 named as an ordinal percentile: 0.714 reads "71st".
 *
 * The suffix follows English usage rather than a plain "th", so 1st, 2nd, 3rd
 * and the teens (11th, 12th, 13th) are all correct.
 */
export function formatPercentile(value: number): string {
  const whole = Math.round(value * 100);
  const teens = whole % 100;
  const suffix =
    teens >= 10 && teens <= 20
      ? "th"
      : { 1: "st", 2: "nd", 3: "rd" }[whole % 10] ?? "th";

  return `${whole}${suffix}`;
}

/** A proportion from 0 to 1 shown as a percentage, keeping backend precision. */
export function formatPercent(
  value: MaybeNumber | undefined,
  digits = 1,
): string {
  if (value === null || value === undefined) {
    return NOT_AVAILABLE;
  }

  if (!Number.isFinite(value)) {
    return NOT_EVALUATED;
  }

  return `${(value * 100).toFixed(digits)}%`;
}

/** A raw number at a fixed precision, for scores and statistics. */
export function formatNumber(
  value: MaybeNumber | undefined,
  digits = 4,
): string {
  if (value === null || value === undefined) {
    return NOT_AVAILABLE;
  }

  if (!Number.isFinite(value)) {
    return NOT_EVALUATED;
  }

  return value.toFixed(digits);
}

/** A confidence value as reported by the backend, not rescaled or regraded. */
export function formatConfidence(value: MaybeNumber | undefined): string {
  if (value === null || value === undefined) {
    return NOT_AVAILABLE;
  }

  if (!Number.isFinite(value)) {
    return NOT_EVALUATED;
  }

  return value.toFixed(2);
}

/**
 * The entity an assessment scope belongs to.
 *
 * When the backend could not resolve an entity, the scope carries a
 * placeholder identifier and `available: false`. Showing the placeholder as
 * though it were a named entity would misrepresent the evidence, so the
 * unavailable state is stated instead.
 */
export function entityLabel(entity: EntityRef | null | undefined): string {
  if (!entity) {
    return NOT_AVAILABLE;
  }

  if (!entity.available) {
    return "Entity not identified";
  }

  if (entity.name) {
    return entity.name;
  }

  return entity.id ?? NOT_AVAILABLE;
}

export function periodLabel(period: PeriodRef | null | undefined): string {
  if (!period) {
    return NOT_AVAILABLE;
  }

  if (!period.available) {
    return "Period not determined";
  }

  if (period.start && period.end) {
    return `${period.start} – ${period.end}`;
  }

  return period.label ?? NOT_AVAILABLE;
}

/** Whether an identity field was resolved, for de-emphasising in tables. */
export function entityResolved(entity: EntityRef | null | undefined): boolean {
  return Boolean(entity?.available);
}

export function periodResolved(period: PeriodRef | null | undefined): boolean {
  return Boolean(period?.available);
}

/** Bytes as a human-readable size, for the dataset picker. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;

  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }

  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/** A filename without its extension, for headings. */
export function datasetName(path: string): string {
  const file = path.split("/").pop() ?? path;
  return file.replace(/\.[^.]+$/, "");
}

/** Totals for the anomaly verdict strip. Zero counts stay zero. */
export function verdictTotal(counts: AnomalyVerdictCounts | undefined): number {
  if (!counts) {
    return 0;
  }

  return Object.values(counts).reduce<number>((total, value) => {
    return total + (typeof value === "number" ? value : 0);
  }, 0);
}

/**
 * Capability status tally for one scope. Returns every state the backend can
 * report, so the interface never implies a state was absent from the
 * evaluation rather than absent from the evidence.
 */
export function capabilityTally(
  counts: Partial<Record<CapabilityStatus, number>> | undefined,
): { status: CapabilityStatus; count: number }[] {
  const states: CapabilityStatus[] = [
    "AVAILABLE",
    "INSUFFICIENT_EVIDENCE",
    "NOT_ASSESSED",
  ];

  return states.map((status) => ({
    status,
    count: counts?.[status] ?? 0,
  }));
}

/** Plain text for an optional backend string, with an explicit fallback. */
export function optionalText(
  value: MaybeString | undefined,
  fallback = NOT_AVAILABLE,
): string {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  return value;
}
