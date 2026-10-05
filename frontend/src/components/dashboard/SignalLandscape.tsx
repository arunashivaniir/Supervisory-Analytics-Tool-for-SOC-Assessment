import { formatCount } from "../../lib/formatters";
import type { SignalFamilyCount, SignalLandscapeView } from "../../app/viewModel";
import { EmptyState } from "../ui/State";

/**
 * The four signal families, as a horizontal bar chart.
 *
 * Each bar's length is that family's share of the largest family. That is a
 * comparison between backend counts and nothing more: the axis carries no
 * numbers, because the numbers are already printed beside every bar and a
 * second set of them would be a second claim about the same data.
 *
 * Bars are coloured by family, from the fixed family palette in `index.css`.
 * Family is a *kind* of detection, not a severity, so the colours deliberately
 * carry no ordering: operational patterns are not "worse" than negative space,
 * and a palette that implied that would be the interface inventing a ranking.
 */
const FAMILY_COLOR: Record<string, string> = {
  execution_gap: "var(--color-family-execution-gap)",
  negative_space: "var(--color-family-negative-space)",
  operational_pattern: "var(--color-family-operational-pattern)",
  anomaly: "var(--color-family-anomaly)",
};

/** Bar geometry only. No value is derived here beyond the visual proportion. */
function widthPercent(count: number, largest: number, empty: boolean): number {
  if (empty || count === 0) {
    return 0;
  }

  // A 2% floor keeps a single signal visible next to a family with hundreds.
  return Math.max(Math.round((count / largest) * 100), 2);
}

function captionFor(
  known: Array<SignalFamilyCount & { count: number }>,
  landscape: SignalLandscapeView,
): string {
  if (landscape.empty) {
    return "Every signal family reported zero for this assessment.";
  }

  const largest = Math.max(...known.map((family) => family.count));
  const shared = known.filter((family) => family.count === largest);

  return shared.length > 1
    ? `${shared.length} families share the highest count, so no single family dominates.`
    : "Bar length is each family's share of the largest family.";
}

export function SignalLandscape({
  landscape,
  caption,
}: {
  landscape: SignalLandscapeView;
  caption?: string;
}) {
  const known = landscape.families.filter(
    (family): family is SignalFamilyCount & { count: number } =>
      family.count !== null,
  );

  if (known.length === 0) {
    return (
      <EmptyState
        title="No signal counts reported"
        description="The pipeline did not publish a count for any signal family in this result, so there is nothing to plot."
      />
    );
  }

  const largest = Math.max(...known.map((family) => family.count), 1);

  return (
    <figure className="min-w-0">
      <ul className="min-w-0 space-y-2.5">
        {known.map((family) => (
          <li key={family.id} className="min-w-0">
            <div className="flex min-w-0 items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-[13px] text-text">
                {family.label}
              </span>

              <span className="tabular shrink-0 text-[13px] font-medium text-text">
                {formatCount(family.count)}
              </span>
            </div>

            <div
              className="mt-1 h-2 w-full overflow-hidden rounded-full bg-neutral-subtle"
              role="img"
              aria-label={`${family.label}: ${formatCount(family.count)} signals`}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${widthPercent(family.count, largest, landscape.empty)}%`,
                  backgroundColor:
                    FAMILY_COLOR[family.id] ?? "var(--color-info)",
                }}
              />
            </div>
          </li>
        ))}
      </ul>

      <figcaption className="mt-2.5 text-[11px] leading-relaxed text-text-tertiary">
        {caption ?? captionFor(known, landscape)}
      </figcaption>
    </figure>
  );
}
