import type { UnifiedFinding } from "../../app/selectors";

/**
 * The alert → case → workflow chain behind one finding, as the
 * finding's own record reference states it. Missing links are said
 * to be missing: an unmatched alert is itself meaningful, never
 * papered over with a placeholder link.
 *
 * Shared by the entity workspace and the finding detail so both read
 * the same fields the same way.
 */
export function AlertCaseChain({ finding }: { finding: UnifiedFinding }) {
  const reference = finding.finding.record_reference;
  const get = (key: string): string | null => {
    const value =
      reference && typeof reference === "object"
        ? (reference as Record<string, unknown>)[key]
        : null;

    return value === null || value === undefined || value === ""
      ? null
      : String(value);
  };

  const alertId = get("alert_id");
  const caseId = get("case_id");
  const severity = get("severity");
  const triggered = get("triggered_at") ?? get("timestamp") ?? get("opened_at");
  const acknowledged = get("acknowledged_at");
  const closed = get("closed_at");

  if (!alertId && !caseId) {
    return (
      <p className="text-xs text-text-tertiary italic">
        No linked case found in submitted data.
      </p>
    );
  }

  return (
    <div className="rounded-[8px] border border-border bg-subtle/50 px-3 py-2">
      <div className="section-label">Alert → Case</div>
      <div className="mt-1.5 flex flex-col gap-1.5">
        {alertId ? (
          <div className="text-xs text-text">
            <span className="font-medium">Alert </span>
            <span className="font-mono">{alertId}</span>
            {severity ? <span className="text-text-secondary"> · {severity}</span> : null}
            {triggered ? <span className="text-text-secondary"> · triggered {triggered}</span> : null}
          </div>
        ) : null}
        {alertId && caseId ? (
          <div className="micro text-text-tertiary" aria-hidden="true">↓</div>
        ) : null}
        {caseId ? (
          <div className="text-xs text-text">
            <span className="font-medium">Case </span>
            <span className="font-mono">{caseId}</span>
            {acknowledged ? <span className="text-text-secondary"> · acknowledged {acknowledged}</span> : null}
            {closed ? <span className="text-text-secondary"> · closed {closed}</span> : null}
          </div>
        ) : (
          <p className="text-xs text-text-tertiary italic">
            No linked case found in submitted data.
          </p>
        )}
      </div>
    </div>
  );
}
