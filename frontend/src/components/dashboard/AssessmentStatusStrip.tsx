import { formatCount } from "../../lib/formatters";
import {
  runStatusLabel,
  runStatusTone,
  type RunView,
  type StatusStripView,
} from "../../app/viewModel";
import { StatusBadge } from "../ui/State";

/**
 * One statistic in the strip.
 *
 * A value, its label, and at most one line of provenance. No icon: an icon here
 * would repeat the label in a different visual language and add nothing an
 * examiner could act on.
 */
function Stat({
  label,
  value,
  unavailable,
  detail,
}: {
  label: string;
  value: number | null;
  unavailable: string;
  detail?: string | null;
}) {
  return (
    <div className="min-w-0 flex-1 px-4 py-2.5 first:pl-0">
      <p className="section-label">{label}</p>

      {value === null ? (
        <p className="mt-0.5 text-[15px] font-medium leading-tight italic text-text-tertiary">
          {unavailable}
        </p>
      ) : (
        <p className="tabular mt-0.5 text-[19px] font-semibold leading-tight text-text">
          {formatCount(value)}
        </p>
      )}

      {detail ? (
        <p
          className="mt-0.5 truncate text-[11px] text-text-tertiary"
          title={detail}
        >
          {detail}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The assessment status strip.
 *
 * Horizontal statistics, divided rather than boxed. The previous interface gave
 * each number its own card, which made four numbers look like four separate
 * claims; here they read as one row of measurements of the same run.
 *
 * Nothing here defaults to zero. A run that has not finished reports nothing,
 * which is what keeps "0 findings" from appearing while data is still loading.
 */
export function AssessmentStatusStrip({
  status,
  run,
}: {
  status: StatusStripView;
  run: RunView;
}) {
  const scopeDetail =
    status.entities !== null
      ? `${formatCount(status.entities)} distinct ${
          status.entities === 1 ? "entity" : "entities"
        }`
      : status.unresolvedScopes !== null && status.unresolvedScopes > 0
        ? "Entity identity unresolved"
        : null;

  const modelDetail = status.modelStatus
    ? `Anomaly model: ${status.modelStatus}`
    : null;

  return (
    <div className="min-w-0 overflow-hidden rounded-[10px] border border-border bg-surface">
      <div className="flex min-w-0 flex-wrap divide-x divide-y divide-border sm:flex-nowrap sm:divide-y-0">
        <Stat label="Records" value={status.records} unavailable="Not reported" />

        <Stat
          label="Assessment scopes"
          value={status.scopes}
          unavailable="Not reported"
          detail={scopeDetail}
        />

        <Stat
          label="Supervisory signals"
          value={status.signals}
          unavailable="Not reported"
          detail="Across four signal families"
        />

        <div className="min-w-0 flex-1 px-4 py-2.5">
          <p className="section-label">Run status</p>

          <div className="mt-1">
            <StatusBadge
              tone={runStatusTone(run)}
              label={runStatusLabel(run)}
              raw={run.statusToken}
              showDot
            />
          </div>

          {run.switching && run.pendingDatasetName ? (
            <p
              className="mt-1 truncate text-[11px] text-text-tertiary"
              title={`Assessing ${run.pendingDatasetName}`}
            >
              Assessing {run.pendingDatasetName}
            </p>
          ) : modelDetail ? (
            <p className="mt-1 truncate text-[11px] text-text-tertiary" title={modelDetail}>
              {modelDetail}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
