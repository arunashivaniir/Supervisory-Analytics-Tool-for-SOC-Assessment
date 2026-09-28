import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "../../lib/cn";
import { anomalyVerdict, type Tone } from "../../lib/status";
import type { AnomalyVerdict, AnomalyVerdictCounts } from "../../types/pipeline";

/**
 * The anomaly verdict distribution.
 *
 * A single horizontal bar per verdict the backend actually reported a count
 * for. Verdicts absent from the result are not drawn as zero, because a
 * verdict the pipeline did not report is not the same as a scope judged to
 * have no anomaly.
 *
 * Drawn as a plain bar chart with a value label and no axis furniture: four
 * categories do not need a grid, a legend or tooltips to be read.
 */

const TONE_FILL: Record<Tone, string> = {
  neutral: "var(--color-neutral-tone)",
  info: "var(--color-info)",
  positive: "var(--color-positive)",
  caution: "var(--color-caution)",
  critical: "var(--color-critical)",
};

interface Datum {
  verdict: AnomalyVerdict;
  label: string;
  count: number;
  fill: string;
}

export function VerdictDistribution({
  counts,
  className,
}: {
  counts: AnomalyVerdictCounts;
  className?: string;
}) {
  const data: Datum[] = (Object.keys(counts) as AnomalyVerdict[])
    .filter((verdict) => (counts[verdict] ?? 0) > 0)
    .map((verdict) => {
      const presentation = anomalyVerdict(verdict);

      return {
        verdict,
        label: presentation.label,
        count: counts[verdict] ?? 0,
        fill: TONE_FILL[presentation.tone],
      };
    });

  if (data.length === 0) {
    return null;
  }

  return (
    <ul className={cn("flex flex-col gap-2.5", className)}>
      {data.map((item) => (
        <li key={item.verdict}>
          <div className="flex items-baseline justify-between gap-3">
            <span
              className="text-[13px] text-text"
              title={item.verdict}
            >
              {item.label}
            </span>
            <span className="tabular text-[13px] font-medium text-text">
              {item.count}
            </span>
          </div>
          <div
            className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-border/70"
            role="img"
            aria-label={`${item.label}: ${item.count} of ${data.reduce(
              (sum, entry) => sum + entry.count,
              0,
            )} scopes`}
          >
            <div
              className="h-full rounded-full"
              style={{
                width: `${percentage(item.count, data)}%`,
                backgroundColor: item.fill,
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function percentage(count: number, data: Datum[]): number {
  const total = data.reduce((sum, entry) => sum + entry.count, 0);

  if (total === 0) {
    return 0;
  }

  return (count / total) * 100;
}

/**
 * The same distribution as a chart, for the case where a real comparison
 * between many categories is needed. Kept separate from the list above so the
 * common case stays a list.
 */
export function VerdictBarChart({
  counts,
  className,
}: {
  counts: AnomalyVerdictCounts;
  className?: string;
}) {
  const data: Datum[] = (Object.keys(counts) as AnomalyVerdict[])
    .filter((verdict) => (counts[verdict] ?? 0) > 0)
    .map((verdict) => {
      const presentation = anomalyVerdict(verdict);

      return {
        verdict,
        label: presentation.label,
        count: counts[verdict] ?? 0,
        fill: TONE_FILL[presentation.tone],
      };
    });

  if (data.length <= 1) {
    return null;
  }

  return (
    <div className={cn("h-[150px] w-full", className)}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid vertical={false} stroke="var(--color-border)" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
            axisLine={{ stroke: "var(--color-border)" }}
            tickLine={false}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }}
            axisLine={false}
            tickLine={false}
          />
          <Bar dataKey="count" radius={[3, 3, 0, 0]} maxBarSize={44}>
            {data.map((item) => (
              <Cell key={item.verdict} fill={item.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
