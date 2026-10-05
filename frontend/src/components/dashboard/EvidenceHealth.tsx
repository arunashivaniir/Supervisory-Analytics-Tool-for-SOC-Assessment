import { Link } from "react-router-dom";

import { formatCount } from "../../lib/formatters";
import type { EvidenceHealthView } from "../../app/viewModel";
import { EmptyState, NotAvailable } from "../ui/State";

/**
 * One integrity count as a row.
 *
 * A row rather than a stacked bar, and that is deliberate. `Verified`,
 * `Digest mismatch` and `Blocked` are three independent facts about a
 * submission: a submission whose digest no longer matches is *also* blocked
 * from analysis. A stacked bar would imply they are mutually exclusive and sum
 * to the total, which they are not, so the interface would be asserting a
 * partition the trust layer never claimed.
 */
function CountRow({
  label,
  count,
  total,
  tone,
  hint,
}: {
  label: string;
  count: number;
  total: number;
  tone: "positive" | "critical" | "neutral" | "caution";
  hint: string;
}) {
  const share = total > 0 ? Math.round((count / total) * 100) : 0;

  return (
    <li className="min-w-0" title={hint}>
      <div className="flex min-w-0 items-baseline justify-between gap-3">
        <span className="min-w-0 text-[13px] text-text">{label}</span>
        <span className="tabular shrink-0 text-[13px] font-medium text-text">
          {formatCount(count)}
        </span>
      </div>

      <div
        className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-neutral-subtle"
        role="img"
        aria-label={`${label}: ${formatCount(count)} of ${formatCount(total)} submissions, ${share}%`}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${count === 0 ? 0 : Math.max(share, 2)}%`,
            backgroundColor: `var(--color-${tone})`,
          }}
        />
      </div>
    </li>
  );
}

/**
 * Evidence health: can this assessment's evidence be trusted?
 *
 * A compact summary with a route into the full register, because the answer to
 * "can I trust it" is always per-submission and never a single number.
 */
export function EvidenceHealth({
  evidence,
  registerLoading,
  registerError,
}: {
  evidence: EvidenceHealthView | null;
  registerLoading: boolean;
  registerError: string | null;
}) {
  if (registerError) {
    return (
      <EmptyState
        title="Evidence register unavailable"
        description={registerError}
      />
    );
  }

  if (evidence === null) {
    return (
      <EmptyState
        title={
          registerLoading
            ? "Reading the evidence register"
            : "No evidence registered"
        }
        description={
          registerLoading
            ? undefined
            : "No submission is registered with the local evidence trust layer."
        }
      />
    );
  }

  if (evidence.total === 0) {
    return (
      <EmptyState
        title="No evidence registered"
        description="No submission is registered with the local evidence trust layer, so there is no integrity state to report."
      />
    );
  }

  return (
    <div className="min-w-0">
      <p className="text-[13px] text-text">
        {formatCount(evidence.total)}{" "}
        {evidence.total === 1 ? "registered submission" : "registered submissions"}
      </p>

      <ul className="mt-2.5 min-w-0 space-y-2">
        <CountRow
          label="Verified"
          count={evidence.verified}
          total={evidence.total}
          tone="positive"
          hint="Original and working copy both match the registered digest"
        />
        <CountRow
          label="Digest mismatch"
          count={evidence.mismatch}
          total={evidence.total}
          tone="critical"
          hint="The observed digest differs from the registered digest"
        />
        <CountRow
          label="Blocked for analysis"
          count={evidence.blocked}
          total={evidence.total}
          tone="caution"
          hint="The trust layer's analysis gate is closed for this submission"
        />
      </ul>

      <p className="mt-2.5 text-[11px] leading-relaxed text-text-tertiary">
        These counts overlap: a submission can be both a digest mismatch and
        blocked from analysis.
      </p>

      <p className="mt-2 text-[13px]">
        <Link
          to="/evidence"
          className="text-accent underline-offset-2 hover:underline"
        >
          Review the evidence register
        </Link>
      </p>
    </div>
  );
}

/** One scope's own capability coverage, for the entity page. */
export function ScopeEvidenceSummary({
  available,
  insufficient,
  notAssessed,
  nothingAssessable,
}: {
  available: number;
  insufficient: number;
  notAssessed: number;
  nothingAssessable: boolean;
}) {
  if (nothingAssessable) {
    return (
      <p className="text-[13px]">
        <NotAvailable>
          The backend published no capability state for this scope.
        </NotAvailable>
      </p>
    );
  }

  return (
    <dl className="grid min-w-0 grid-cols-3 gap-4">
      <div className="min-w-0">
        <dt className="section-label">Assessable</dt>
        <dd className="tabular mt-0.5 text-[17px] font-semibold text-positive">
          {formatCount(available)}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="section-label">Limited</dt>
        <dd className="tabular mt-0.5 text-[17px] font-semibold text-caution">
          {formatCount(insufficient)}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="section-label">Not assessed</dt>
        <dd className="tabular mt-0.5 text-[17px] font-semibold text-text-tertiary">
          {formatCount(notAssessed)}
        </dd>
      </div>
    </dl>
  );
}
