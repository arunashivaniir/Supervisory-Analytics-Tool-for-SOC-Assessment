import { formatCount, formatPercent, formatPercentile } from "../../lib/formatters";
import { baselineStatus, deviationBand } from "../../lib/status";
import type { PeerComparisonView, PeerMetricView } from "../../app/viewModel";
import { Note } from "../ui/Surface";
import { DetailSection } from "../ui/DetailDrawer";
import { LimitationNote, NotAvailable, StatusBadge } from "../ui/State";

/**
 * A metric's observed value, formatted.
 *
 * Whether a metric reads as a proportion is declared by the backend's metric
 * catalogue, so the interface formats what it was given instead of guessing from
 * the magnitude.
 */
function MetricValue({
  metric,
  className = "",
}: {
  metric: PeerMetricView;
  className?: string;
}) {
  if (metric.observed === null) {
    return <NotAvailable>{metric.notEvaluableReason ?? "Not available"}</NotAvailable>;
  }

  return (
    <span className={`tabular ${className}`}>
      {metric.observedIsRate
        ? formatPercent(metric.observed)
        : formatCount(metric.observed)}
    </span>
  );
}

/** A metric's value, formatted, or an explicit not-available. */
function Value({ metric, value }: { metric: PeerMetricView; value: number | null }) {
  if (value === null) {
    return <NotAvailable />;
  }

  return (
    <span className="tabular">
      {metric.observedIsRate ? formatPercent(value) : formatCount(value)}
    </span>
  );
}

/**
 * The backend's own reason for declining a statistic, as a sentence. The reason
 * strings begin lower case because they are read as a continuation elsewhere, so
 * the first letter is raised when one follows a full stop here.
 */
function sentence(reason: string | null): string | null {
  if (!reason) return null;
  return reason.charAt(0).toUpperCase() + reason.slice(1);
}

/**
 * The peer comparison for every metric the backend published for this scope.
 *
 * All of the backend's metrics are shown, in the order the view model derived
 * from the backend's own `statistical_status`, so a scope whose separating metric
 * is not first in the catalogue still leads with it.
 *
 * The zero-separation case is the important one. When the backend declines to
 * compute a standardised deviation it is because every comparable scope
 * reported the same value, and the backend says so in
 * `statistical_not_computable_reason`. A metric in that state reads "Tied — no
 * peer separation" instead of a percentile: the backend still publishes a
 * percentile of 0.5 for a cohort with no spread, and presenting that in the
 * headline position would report a ranking the cohort cannot support. The
 * percentile stays available in the statistical details, where the backend's
 * reason for declining it sits beside it.
 */
export function PeerComparisonPanel({
  peer,
  metrics,
  cohortLabel,
  cohortPeerCount,
  cohortRuleSteps,
  compact = false,
}: {
  peer: PeerComparisonView;
  metrics: PeerMetricView[];
  cohortLabel: string | null;
  cohortPeerCount: number;
  cohortRuleSteps: string[];
  compact?: boolean;
}) {
  if (!peer.available) {
    return (
      <Note tone="neutral">
        {peer.unavailableReason ??
          "The pipeline produced no peer benchmark for this assessment."}
      </Note>
    );
  }

  if (metrics.length === 0) {
    return (
      <Note tone="neutral">
        No benchmark metric was published for this scope.
      </Note>
    );
  }

  const separated = metrics.filter((metric) => metric.separated).length;

  return (
    <div className="min-w-0">
      <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="min-w-0 text-[13px] font-medium text-text">
          {metrics.length} peer {metrics.length === 1 ? "metric" : "metrics"}
          {separated < metrics.length ? (
            <span className="font-normal text-text-tertiary">
              {" "}
              · {separated} of {metrics.length} separated
            </span>
          ) : null}
        </p>

        <span className="tabular text-[11px] text-text-tertiary">
          {formatCount(cohortPeerCount)}
          {cohortLabel ? ` · ${cohortLabel}` : null}
        </span>
      </div>

      <ul className="mt-3 min-w-0 space-y-4">
        {metrics.map((metric, index) => (
          <li
            key={metric.metricId}
            className={
              index === 0
                ? "min-w-0"
                : "min-w-0 border-t border-border pt-4"
            }
          >
            <MetricBlock metric={metric} compact={compact} />
          </li>
        ))}
      </ul>

      {/*
        The cohort is a property of the scope, not of any one metric, so the rule
        that selected it is stated once rather than repeated under every metric.
      */}
      {!compact && cohortRuleSteps.length > 0 ? (
        <DetailSection title="Cohort selection rule">
          <ol className="min-w-0 list-decimal space-y-1 pl-4">
            {cohortRuleSteps.map((step, index) => (
              <li
                key={index}
                className="max-w-prose break-words text-xs leading-relaxed text-text-secondary"
              >
                {step}
              </li>
            ))}
          </ol>
        </DetailSection>
      ) : null}
    </div>
  );
}

/**
 * One metric's comparison: the metric, this scope's value, the peer median, and
 * how the scope sits in the cohort.
 */
function MetricBlock({
  metric,
  compact,
}: {
  metric: PeerMetricView;
  compact: boolean;
}) {
  const baseline = baselineStatus(metric.baselineStatus);
  const band = metric.separated ? deviationBand(metric.deviationBand) : null;
  const percentile =
    metric.percentile !== null && metric.percentileStatus === "COMPUTED"
      ? metric.percentile
      : null;

  return (
    <div className="min-w-0">
      <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="min-w-0 text-[13px] font-medium text-text">
          {metric.label}
        </p>

        <StatusBadge tone={baseline.tone} label={baseline.label} raw={metric.baselineStatus} />
      </div>

      <dl className="mt-2.5 grid min-w-0 grid-cols-2 gap-x-5 gap-y-2.5 sm:grid-cols-3">
        <div className="min-w-0">
          <dt className="section-label">This scope</dt>
          <dd className="mt-0.5 text-[15px] font-semibold text-text">
            <MetricValue metric={metric} />
          </dd>
        </div>

        <div className="min-w-0">
          <dt className="section-label">Peer median</dt>
          <dd className="mt-0.5 text-[15px] font-semibold text-text">
            <Value metric={metric} value={metric.median} />
          </dd>
        </div>

        <div className="min-w-0">
          {/*
            The comparison slot reports a percentile only when the backend
            computed a standardised deviation for this metric. Otherwise it
            states the tie, which is what the cohort actually supports.
          */}
          <dt className="section-label">Comparison</dt>
          <dd className="mt-0.5 text-[15px] font-semibold text-text">
            {metric.separated ? (
              percentile !== null ? (
                <span className="tabular">{formatPercentile(percentile)}</span>
              ) : (
                <NotAvailable>Not applicable</NotAvailable>
              )
            ) : (
              <span className="text-[13px] font-medium text-text-secondary">
                Tied — no peer separation
              </span>
            )}
          </dd>
        </div>
      </dl>

      {!metric.separated ? (
        <div className="mt-3">
          <Note tone="info">
            <span className="font-medium">Tied — no peer separation.</span>{" "}
            {sentence(metric.separationReason) ??
              "Every comparable scope reported the same value, so percentile differentiation is not meaningful."}
          </Note>
        </div>
      ) : null}

      {metric.interpretation ? (
        <p className="mt-3 max-w-prose break-words text-xs leading-relaxed text-text-secondary">
          {metric.interpretation}
        </p>
      ) : null}

      {!compact ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-accent hover:underline">
            View statistical details
          </summary>

          <div className="mt-2.5 min-w-0 space-y-3">
            <dl className="grid min-w-0 grid-cols-2 gap-x-5 gap-y-2 sm:grid-cols-4">
              <Detail
                label="Percentile"
                value={percentile}
                rate={false}
                unavailable="Not applicable"
                asPercentile
              />
              <Detail
                label="Rank"
                value={metric.rank}
                rate={false}
                unavailable="Not applicable"
              />
              <Detail
                label="Minimum"
                value={metric.distribution.minimum}
                rate={metric.observedIsRate}
              />
              <Detail label="Q1" value={metric.distribution.q1} rate={metric.observedIsRate} />
              <Detail
                label="Q3"
                value={metric.distribution.q3}
                rate={metric.observedIsRate}
              />
              <Detail
                label="Maximum"
                value={metric.distribution.maximum}
                rate={metric.observedIsRate}
              />
              <Detail label="IQR" value={metric.distribution.iqr} rate={false} />
              <Detail label="MAD" value={metric.distribution.mad} rate={false} />
              <Detail
                label="Modified Z"
                value={metric.modifiedZScore}
                rate={false}
                unavailable="Not computable"
              />
              <div className="min-w-0">
                <dt className="section-label">Deviation band</dt>
                <dd className="mt-0.5">
                  {band ? (
                    <StatusBadge tone={band.tone} label={band.label} raw={metric.deviationBand} />
                  ) : (
                    <NotAvailable>Not evaluable</NotAvailable>
                  )}
                </dd>
              </div>
            </dl>

            {metric.baselineReason ? (
              <p className="max-w-prose break-words text-xs leading-relaxed text-text-secondary">
                {metric.baselineReason}
              </p>
            ) : null}

            {metric.directionLabel ? (
              <p className="text-xs text-text-tertiary">{metric.directionLabel}</p>
            ) : null}

          </div>
        </details>
      ) : null}
    </div>
  );
}

function Detail({
  label,
  value,
  rate,
  unavailable = "Not available",
  asPercentile = false,
}: {
  label: string;
  value: number | null;
  rate: boolean;
  unavailable?: string;
  asPercentile?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="section-label">{label}</dt>
      <dd className="mt-0.5 text-[13px] text-text">
        {value === null ? (
          <NotAvailable>{unavailable}</NotAvailable>
        ) : (
          <span className="tabular">
            {asPercentile
              ? formatPercentile(value)
              : rate
                ? formatPercent(value)
                : formatCount(value)}
          </span>
        )}
      </dd>
    </div>
  );
}

/** The backend's own limits on peer comparison, shown once, collapsed. */
export function PeerLimitations({ peer }: { peer: PeerComparisonView }) {
  if (peer.limitations.length === 0) {
    return null;
  }

  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium text-accent hover:underline">
        What peer comparison cannot tell you
      </summary>

      <ul className="mt-2 min-w-0 space-y-1.5">
        {peer.limitations.map((limitation, index) => (
          <li key={index} className="min-w-0">
            <LimitationNote>{limitation}</LimitationNote>
          </li>
        ))}
      </ul>
    </details>
  );
}