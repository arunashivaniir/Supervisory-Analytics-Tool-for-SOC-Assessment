import { ChevronRight, ShieldCheck } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import {
  AdapterError,
  fetchEvidenceIntegrity,
  verifyEvidenceIntegrity,
} from "../../services/api";
import { cn } from "../../lib/cn";
import { formatBytes, NOT_AVAILABLE } from "../../lib/formatters";
import { humanise, integrityStatus } from "../../lib/status";
import type {
  EvidenceIntegrity,
  IntegrityComparison,
} from "../../types/evidence";
import { Caveat } from "../layout/PageHeader";
import { Button } from "../ui/Button";
import { Card, CardBody, CardHeader } from "../ui/Card";
import {
  DataTable,
  HeadCell,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "../ui/DataTable";
import { EmptyState, LoadingRows } from "../ui/Metric";
import { NotAvailable, StatusBadge } from "../ui/StatusBadge";

/**
 * Evidence integrity, as reported by the local evidence trust layer.
 *
 * This is a read of registered evidence, not an assessment of it. The digests
 * shown were computed in the local service by the same code that gates analysis;
 * the interface displays that comparison and does not recalculate, second-guess
 * or soften it. ``Verify Integrity`` re-runs that comparison, which is why it is
 * a button on each row and not a filter.
 *
 * The expanded row is the audit detail: both subjects with their paths, the
 * registered digest beside the digest observed for each copy, and the provenance
 * that was recorded together with the fields that were not stated at
 * submission. Provenance gaps are listed rather than filled, because a blank
 * that reads as a value is worse than an explicit absence.
 */
function readMessage(failure: unknown, fallback: string): string {
  return failure instanceof AdapterError ? failure.message : fallback;
}

export function EvidenceIntegrityPanel() {
  const [items, setItems] = useState<EvidenceIntegrity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [verifying, setVerifying] = useState<string | null>(null);

  const read = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      setItems(await fetchEvidenceIntegrity());
    } catch (failure) {
      setError(readMessage(failure, "The evidence register could not be read."));
    } finally {
      setLoading(false);
    }
  }, []);

  // The first read happens on mount rather than through `read`, so the states
  // are already at their starting values and only the response sets anything.
  useEffect(() => {
    let cancelled = false;

    fetchEvidenceIntegrity()
      .then((registered) => {
        if (!cancelled) {
          setItems(registered);
        }
      })
      .catch((failure: unknown) => {
        if (!cancelled) {
          setError(readMessage(failure, "The evidence register could not be read."));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const verify = useCallback(async (evidenceId: string) => {
    setVerifying(evidenceId);
    setError(null);

    try {
      const verified = await verifyEvidenceIntegrity(evidenceId);

      // Replace only the row that was verified, so the rest of the register
      // keeps whatever it last reported and nothing is re-summarised locally.
      setItems((current) =>
        current
          ? current.map((item) =>
              item.evidence_id === verified.evidence_id ? verified : item,
            )
          : [verified],
      );
    } catch (failure) {
      setError(readMessage(failure, "Verification could not be completed."));
    } finally {
      setVerifying(null);
    }
  }, []);

  const summary = useMemo(() => {
    if (!items) {
      return null;
    }

    return {
      total: items.length,
      verified: items.filter((item) => item.overall_status === "VERIFIED").length,
      failed: items.filter((item) => item.overall_status === "INTEGRITY_FAILED")
        .length,
      blocked: items.filter((item) => !item.analysis.permitted).length,
    };
  }, [items]);

  return (
    <Card className="mb-6">
      <CardHeader
        title="Evidence integrity"
        description={
          summary
            ? `${summary.total} registered submission${
                summary.total === 1 ? "" : "s"
              } · ${summary.verified} verified · ${summary.failed} with a digest mismatch · ${
                summary.blocked
              } blocked from analysis`
            : "Reading the local evidence register…"
        }
        action={
          <Button size="sm" variant="outline" onClick={() => void read()} disabled={loading}>
            Re-read register
          </Button>
        }
      />

      {error ? (
        <div className="px-4 py-3">
          <Caveat tone="caution">{error}</Caveat>
        </div>
      ) : null}

      {loading && !items ? (
        <LoadingRows rows={3} />
      ) : items && items.length === 0 ? (
        <CardBody>
          <EmptyState
            title="No evidence registered"
            description="No submission has been registered with the local evidence store."
          />
        </CardBody>
      ) : items ? (
        <>
          <DataTable>
            <TableHead>
              <HeadCell>Evidence</HeadCell>
              <HeadCell>Registered digest</HeadCell>
              <HeadCell>Original</HeadCell>
              <HeadCell>Working copy</HeadCell>
              <HeadCell>Overall</HeadCell>
              <HeadCell>Analysis</HeadCell>
              <HeadCell align="right">Action</HeadCell>
            </TableHead>
            <TableBody>
              {items.map((item) => {
                const original = integrityStatus(item.original.status);
                const working = integrityStatus(item.working.status);
                const overall = integrityStatus(item.overall_status);
                const open = expanded === item.evidence_id;

                return (
                  <Fragment key={item.evidence_id}>
                    <TableRow
                      onClick={() => setExpanded(open ? null : item.evidence_id)}
                      selected={open}
                    >
                      <TableCell>
                        <span className="flex items-center gap-1.5">
                          <ChevronRight
                            className={cn(
                              "size-3 shrink-0 text-text-tertiary transition-transform duration-100",
                              open && "rotate-90",
                            )}
                            aria-hidden="true"
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-[13px] text-text">
                              {item.source.filename ?? NOT_AVAILABLE}
                            </span>
                            <span className="block truncate micro tabular text-text-tertiary">
                              {item.evidence_id}
                            </span>
                          </span>
                        </span>
                      </TableCell>
                      <TableCell>
                        <Digest value={item.registered_sha256} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge
                          tone={original.tone}
                          label={original.label}
                          raw={item.original.status}
                          showDot={false}
                        />
                      </TableCell>
                      <TableCell>
                        <StatusBadge
                          tone={working.tone}
                          label={working.label}
                          raw={item.working.status}
                          showDot={false}
                        />
                      </TableCell>
                      <TableCell>
                        <StatusBadge
                          tone={overall.tone}
                          label={overall.label}
                          raw={item.overall_status}
                        />
                      </TableCell>
                      <TableCell>
                        {item.analysis.permitted ? (
                          <StatusBadge
                            tone="positive"
                            label="Permitted"
                            showDot={false}
                          />
                        ) : (
                          <StatusBadge
                            tone="critical"
                            label="Blocked"
                            showDot={false}
                            title={item.analysis.blocked_reason ?? undefined}
                          />
                        )}
                      </TableCell>
                      <TableCell align="right">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(event) => {
                            event.stopPropagation();
                            void verify(item.evidence_id);
                          }}
                          disabled={verifying !== null}
                        >
                          <ShieldCheck className="size-3" aria-hidden="true" />
                          {verifying === item.evidence_id
                            ? "Verifying…"
                            : "Verify integrity"}
                        </Button>
                      </TableCell>
                    </TableRow>

                    {open ? <EvidenceDetailRow item={item} /> : null}
                  </Fragment>
                );
              })}
            </TableBody>
          </DataTable>

          <div className="border-t border-border px-4 py-2.5">
            <p className="text-micro leading-relaxed text-text-tertiary">
              Digests are computed and compared by the local evidence trust
              layer. A working copy is verified against the digest recorded for
              the preserved original at registration, and analysis is gated on
              both copies verifying.
            </p>
          </div>
        </>
      ) : null}
    </Card>
  );
}

function EvidenceDetailRow({ item }: { item: EvidenceIntegrity }) {
  return (
    <tr>
      <td colSpan={7} className="border-b border-border bg-subtle px-4 py-3">
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <h3 className="section-label">Integrity comparison</h3>
            <ComparisonBlock
              label="Preserved original"
              comparison={item.original}
              registered={item.registered_sha256}
            />
            <ComparisonBlock
              label="Controlled working copy"
              comparison={item.working}
              registered={item.registered_sha256}
            />
            {item.analysis.blocked_reason ? (
              <p className="mt-2 text-xs leading-relaxed text-critical">
                {item.analysis.blocked_reason}
              </p>
            ) : null}
            {item.analysis.target_path ? (
              <p className="mt-1 break-all text-micro text-text-tertiary">
                Analysis target: {item.analysis.target_path}
              </p>
            ) : null}
          </div>

          <div>
            <h3 className="section-label">Provenance</h3>
            <ProvenanceBlock item={item} />
          </div>
        </div>
      </td>
    </tr>
  );
}

function ComparisonBlock({
  label,
  comparison,
  registered,
}: {
  label: string;
  comparison: IntegrityComparison;
  registered: string | null;
}) {
  const status = integrityStatus(comparison.status);

  return (
    <div className="mt-2 rounded-[8px] border border-border bg-surface px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-medium text-text">{label}</span>
        <StatusBadge
          tone={status.tone}
          label={status.label}
          raw={comparison.status}
          showDot={false}
        />
      </div>

      {comparison.path ? (
        <p className="mt-1 break-all text-micro text-text-tertiary">
          {comparison.path}
        </p>
      ) : null}

      <dl className="mt-2 space-y-1">
        <div className="flex gap-2">
          <dt className="w-[92px] shrink-0 text-micro uppercase tracking-[0.06em] text-text-tertiary">
            Expected
          </dt>
          <dd className="min-w-0 break-all font-mono text-micro text-text">
            {comparison.expected_sha256 ?? registered ?? NOT_AVAILABLE}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-[92px] shrink-0 text-micro uppercase tracking-[0.06em] text-text-tertiary">
            Observed
          </dt>
          <dd className="min-w-0 break-all font-mono text-micro text-text">
            {comparison.observed_sha256 ?? (
              <NotAvailable>Not observed</NotAvailable>
            )}
          </dd>
        </div>
      </dl>

      {comparison.detail ? (
        <p className="mt-1.5 text-micro leading-relaxed text-text-secondary">
          {comparison.detail}
        </p>
      ) : null}
    </div>
  );
}

function ProvenanceBlock({ item }: { item: EvidenceIntegrity }) {
  const provenance = item.provenance;

  if (!provenance) {
    return (
      <p className="mt-2 text-xs text-text-tertiary italic">
        <NotAvailable>No provenance record was written for this submission</NotAvailable>
      </p>
    );
  }

  const stated: Array<[string, string | null | number]> = [
    ["Received at", provenance.received_at ?? null],
    ["Status", provenance.status ?? null],
    ["Original filename", provenance.original_filename ?? null],
    ["File size", provenance.file_size === null || provenance.file_size === undefined ? null : formatBytes(provenance.file_size)],
    ["SHA-256 at intake", provenance.sha256 ?? null],
    ["Package type", provenance.package_type ?? null],
    ["Source identifier", provenance.source_identifier ?? null],
    ["Assessment period", provenance.assessment_period ?? null],
    ["Submitted by", provenance.submitted_by ?? null],
    ["Received channel", provenance.received_channel ?? null],
  ];

  return (
    <div className="mt-2 space-y-2">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
        {stated.map(([label, value]) => (
          <div key={label} className="flex min-w-0 flex-col">
            <dt className="text-micro uppercase tracking-[0.06em] text-text-tertiary">
              {label}
            </dt>
            <dd className="truncate text-[13px] text-text" title={value === null ? undefined : String(value)}>
              {value === null || value === "" ? (
                <NotAvailable>Not stated at submission</NotAvailable>
              ) : (
                value
              )}
            </dd>
          </div>
        ))}
      </dl>

      {provenance.unavailable_fields.length > 0 ? (
        <p className="text-micro leading-relaxed text-text-secondary">
          Not stated at submission:{" "}
          {provenance.unavailable_fields.map(humanise).join(", ")}.
        </p>
      ) : null}

      {provenance.custody_events.length > 0 ? (
        <div>
          <h4 className="text-micro uppercase tracking-[0.06em] text-text-tertiary">
            Custody events
          </h4>
          <ul className="mt-1 space-y-1">
            {provenance.custody_events.map((event, index) => (
              <li key={`${event.occurred_at}-${index}`} className="text-micro leading-relaxed">
                <span className="text-text">
                  {humanise(event.action)}
                </span>
                {event.occurred_at ? (
                  <span className="text-text-tertiary"> · {event.occurred_at}</span>
                ) : null}
                {event.actor ? (
                  <span className="text-text-secondary"> · {event.actor}</span>
                ) : null}
                {event.detail ? (
                  <span className="block text-text-secondary">{event.detail}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {item.files.length > 1 ? (
        <div>
          <h4 className="text-micro uppercase tracking-[0.06em] text-text-tertiary">
            Registered files
          </h4>
          <ul className="mt-1 space-y-0.5">
            {item.files.map((file) => (
              <li
                key={`${file.role}-${file.relative_path}`}
                className="break-all text-micro text-text-secondary"
              >
                {file.role} · {file.relative_path} · {formatBytes(file.size)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {Object.keys(provenance.metadata).length > 0 ? (
        <div>
          <h4 className="text-micro uppercase tracking-[0.06em] text-text-tertiary">
            Submission metadata
          </h4>
          <dl className="mt-1 space-y-0.5">
            {Object.entries(provenance.metadata).map(([key, value]) => (
              <div key={key} className="flex gap-2">
                <dt className="shrink-0 text-micro text-text-tertiary">
                  {humanise(key)}
                </dt>
                <dd className="min-w-0 break-words text-micro text-text">
                  {describeValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </div>
  );
}

/**
 * A recorded metadata value as text.
 *
 * A recorded value may be a string, a number, a boolean or a nested structure,
 * and a structure is rendered as JSON rather than handed to React as an object,
 * because a value that cannot be shown honestly is better shown literally than
 * not shown at all.
 */
function describeValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (value === null || value === undefined) {
    return "Not stated at submission";
  }

  try {
    return JSON.stringify(value);
  } catch {
    return "Recorded as a structured value";
  }
}
/**
 * A digest, shown the way a person reads one: identifiable, never truncated
 * beyond usefulness. The full value is always in the title and in the expanded
 * comparison, so nothing is hidden by the shortening.
 */
function Digest({ value }: { value: string | null }) {
  if (!value) {
    return <NotAvailable>Not recorded</NotAvailable>;
  }

  return (
    <span
      className="font-mono text-micro tabular text-text"
      title={value}
    >
      {value.slice(0, 12)}…
    </span>
  );
}
