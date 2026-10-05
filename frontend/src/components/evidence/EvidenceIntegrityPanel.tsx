import { useState } from "react";

import type { EvidenceIntegrity } from "../../types/evidence";
import { formatBytes } from "../../lib/formatters";
import { integrityStatus } from "../../lib/status";
import { Frame, Note } from "../ui/Surface";
import {
  HeadCell,
  HeadRow,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableScroller,
} from "../ui/Table";
import { EmptyState, StatusBadge } from "../ui/State";

/**
 * Evidence integrity, one row per registered submission.
 *
 * What this panel is for
 * ---------------------
 * An examiner has to be able to say, before reading anything else on the screen,
 * "can this evidence be trusted?". That question is answered per submission, so
 * it is answered in rows: one row per thing that was registered, each carrying
 * its own verdict and expandable to the comparison behind it.
 *
 * Why the counts are not a total
 * ------------------------------
 * `Verified`, `Digest mismatch` and `Blocked` are three independent facts about
 * one submission. A submission whose digest no longer matches is *also* refused
 * by the analysis gate. Presenting them as three slices that sum to the total
 * would assert a partition the trust layer never made, and would make the
 * counts impossible to add up. They are stated side by side as what they are,
 * and the panel says so in as many words.
 *
 * Row expansion is the point rather than a convenience: the verdict token is a
 * summary of a comparison, and a reader who cannot see the comparison cannot
 * check the summary.
 */
export function EvidenceIntegrityPanel({
  entries,
  loading,
  error,
}: {
  entries: EvidenceIntegrity[] | null;
  loading: boolean;
  error: string | null;
}) {
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);

  if (error) {
    return <Note tone="caution">The evidence register could not be read: {error}</Note>;
  }

  if (loading || entries === null) {
    return (
      <EmptyState
        title="Reading the evidence register"
        description="The trust layer is being asked what it holds."
      />
    );
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        title="No evidence registered"
        description="No submission is registered with the local evidence trust layer, so there is no integrity state to report."
      />
    );
  }

  const mismatched = entries.filter(
    (entry) => entry.overall_status === "INTEGRITY_FAILED",
  ).length;
  const blocked = entries.filter((entry) => !entry.analysis.permitted).length;
  const verified = entries.filter(
    (entry) => entry.overall_status === "VERIFIED",
  ).length;

  return (
    <div className="min-w-0" data-testid="evidence-integrity-panel">
      <p className="mb-2 text-[13px] text-text">
        {entries.length === 1
          ? "1 registered submission"
          : `${entries.length} registered submissions`}
        <span className="text-text-tertiary">
          {" "}
          — {verified} verified, {mismatched} with a digest mismatch, {blocked}{" "}
          blocked from analysis.
        </span>
      </p>

      <p className="mb-3 text-[11px] leading-relaxed text-text-tertiary">
        These counts overlap. A submission whose digest no longer matches is
        also blocked from analysis, so they are three separate facts about each
        submission rather than three slices of one total.
      </p>

      <Frame>
        <TableScroller>
          <TableHead>
            <HeadRow>
              <HeadCell width="26%">Submission</HeadCell>
              <HeadCell width="24%">Registered digest</HeadCell>
              <HeadCell width="15%">Integrity</HeadCell>
              <HeadCell width="15%">Analysis gate</HeadCell>
              <HeadCell width="12%" align="right">
                Files
              </HeadCell>
              <HeadCell width="8%" align="right">
                Detail
              </HeadCell>
            </HeadRow>
          </TableHead>

          <TableBody>
            {entries.map((entry) => {
              const integrity = integrityStatus(entry.overall_status);
              const isOpen = openEvidence === entry.evidence_id;

              return (
                <IntegrityRow
                  key={entry.evidence_id}
                  entry={entry}
                  integrityTone={integrity.tone}
                  integrityLabel={integrity.label}
                  isOpen={isOpen}
                  onToggle={() =>
                    setOpenEvidence(isOpen ? null : entry.evidence_id)
                  }
                />
              );
            })}
          </TableBody>
        </TableScroller>
      </Frame>
    </div>
  );
}

/**
 * One submission, and its detail.
 *
 * The detail row is rendered inside the same table rather than beside it so the
 * expanded comparison stays attached to the verdict it explains; a detail panel
 * that pushed the table down would lose that association.
 */
function IntegrityRow({
  entry,
  integrityTone,
  integrityLabel,
  isOpen,
  onToggle,
}: {
  entry: EvidenceIntegrity;
  integrityTone: "positive" | "critical" | "caution" | "neutral" | "info";
  integrityLabel: string;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const filename = entry.source.filename ?? entry.source.stored_name ?? "Unnamed submission";

  return (
    <>
      <TableRow onSelect={onToggle} selected={isOpen}>
        <TableCell>
          <span className="block truncate font-medium text-text" title={filename}>
            {filename}
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-text-tertiary">
            {entry.evidence_id}
            {entry.source.modified_at
              ? ` · ${entry.source.modified_at.slice(0, 10)}`
              : ""}
          </span>
        </TableCell>

        <TableCell>
          <span className="font-mono text-[11px] text-text-secondary">
            {entry.registered_sha256
              ? entry.registered_sha256.slice(0, 12)
              : "Not registered"}
          </span>
        </TableCell>

        <TableCell>
          <StatusBadge
            tone={integrityTone}
            label={integrityLabel}
            raw={entry.overall_status}
          />
        </TableCell>

        <TableCell>
          <StatusBadge
            tone={entry.analysis.permitted ? "positive" : "critical"}
            label={entry.analysis.permitted ? "Permitted" : "Blocked"}
          />
        </TableCell>

        <TableCell align="right" className="tabular text-text-secondary">
          {entry.file_count ?? entry.files.length}
        </TableCell>

        <TableCell align="right">
          <button
            type="button"
            aria-expanded={isOpen}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
            className="rounded-[6px] px-1.5 py-0.5 text-[12px] font-medium text-accent underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
          >
            {isOpen ? "Close" : "Open"}
          </button>
        </TableCell>
      </TableRow>

      {isOpen ? (
        <tr>
          <td colSpan={6} className="bg-subtle px-4 py-3">
            <IntegrityDetail entry={entry} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

/**
 * The detail behind one verdict.
 *
 * Three things a reader needs in order to check the verdict rather than accept
 * it: the comparison that produced it, the custody record of the submission, and
 * the provenance captured at intake. A value the backend returned as a structure
 * is rendered as a structure — collapsing one to a string is how an interface
 * ends up displaying `[object Object]` where a manifest should be.
 */
function IntegrityDetail({ entry }: { entry: EvidenceIntegrity }) {
  const manifest = entry.files ?? [];
  const custody = entry.provenance?.custody_events ?? [];
  const provenance = entry.provenance;

  return (
    <div className="min-w-0 space-y-4">
      <div>
        <h3 className="section-label">Integrity comparison</h3>
        <div className="mt-1.5 grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2">
          <ComparisonCard
            subject="Preserved original"
            comparison={entry.original}
          />
          <ComparisonCard subject="Working copy" comparison={entry.working} />
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-text-tertiary">
          Algorithm {entry.hash_algorithm ?? "not stated"} · manifest schema{" "}
          {entry.manifest_schema_version ?? "not stated"} ·{" "}
          {entry.originals_read_only === null ? "read-only status not stated" : entry.originals_read_only ? "originals stored read-only" : "originals are not stored read-only"}.
        </p>
      </div>

      {!entry.analysis.permitted ? (
        <Note tone="caution">
          Blocked from analysis. {entry.analysis.blocked_reason ?? "The trust layer gave no reason."}
        </Note>
      ) : null}

      <div>
        <h3 className="section-label">Custody events</h3>
        {custody.length === 0 ? (
          <p className="mt-1 text-[13px] italic text-text-tertiary">
            No custody events were recorded at intake.
          </p>
        ) : (
          <ol className="mt-1.5 space-y-1">
            {custody.map((event, index) => (
              <li
                key={`${event.action}-${index}`}
                className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px]"
              >
                <span className="font-medium text-text">{event.action}</span>
                <span className="text-text-tertiary">
                  {event.actor ?? "actor not stated"}
                </span>
                <span className="tabular text-[11px] text-text-tertiary">
                  {event.occurred_at ?? "time not stated"}
                </span>
                {event.detail ? (
                  <span className="min-w-0 basis-full text-[12px] text-text-secondary">
                    {event.detail}
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>

      <div>
        <h3 className="section-label">Provenance</h3>
        {!provenance ? (
          <p className="mt-1 text-[13px] italic text-text-tertiary">
            The trust layer holds no provenance record for this submission.
          </p>
        ) : (
          <>
            <dl className="mt-1.5 grid grid-cols-1 gap-x-6 sm:grid-cols-2">
              <ProvenanceField label="Original file name" value={provenance.original_filename} />
              <ProvenanceField label="Package type" value={provenance.package_type} />
              <ProvenanceField label="Source identifier" value={provenance.source_identifier} />
              <ProvenanceField label="Assessment period" value={provenance.assessment_period} />
              <ProvenanceField label="Submitted by" value={provenance.submitted_by} />
              <ProvenanceField label="Received channel" value={provenance.received_channel} />
              <ProvenanceField label="Received at" value={provenance.received_at} />
              <ProvenanceField label="Status" value={provenance.status} />
            </dl>

            {provenance.unavailable_fields.length > 0 ? (
              <p className="mt-2 text-[11px] leading-relaxed text-text-tertiary">
                Not stated at submission:{" "}
                {provenance.unavailable_fields.join(", ")}. These fields are absent
                rather than empty, so they must not be read as a value of zero.
              </p>
            ) : null}
          </>
        )}
      </div>

      {manifest.length > 0 ? (
        <div>
          <h3 className="section-label">Manifest</h3>
          <Frame className="mt-1.5">
            <TableScroller>
              <TableHead>
                <HeadRow>
                  <HeadCell>File</HeadCell>
                  <HeadCell>Role</HeadCell>
                  <HeadCell align="right">Size</HeadCell>
                  <HeadCell>Digest</HeadCell>
                </HeadRow>
              </TableHead>

              <TableBody>
                {manifest.map((file) => (
                  <TableRow key={file.stored_name}>
                    <TableCell className="truncate font-mono text-[11px]">
                      {file.name}
                    </TableCell>
                    <TableCell className="text-[13px] text-text-secondary">
                      {file.role}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatBytes(file.size)}
                    </TableCell>
                    <TableCell className="truncate font-mono text-[11px] text-text-secondary">
                      {file.sha256 ? file.sha256.slice(0, 12) : "Not recorded"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </TableScroller>
          </Frame>
        </div>
      ) : null}
    </div>
  );
}

function ComparisonCard({
  subject,
  comparison,
}: {
  subject: string;
  comparison: EvidenceIntegrity["original"];
}) {
  const presentation = integrityStatus(comparison.status);

  return (
    <div className="min-w-0 rounded-[8px] border border-border bg-surface px-3 py-2">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-text">{subject}</span>
        <StatusBadge
          tone={presentation.tone}
          label={presentation.label}
          raw={comparison.status}
        />
      </div>

      <p className="mt-1 text-[12px] leading-relaxed text-text-secondary">
        {comparison.detail}
      </p>

      <dl className="mt-1.5 space-y-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <dt className="shrink-0 text-[11px] text-text-tertiary">Path</dt>
          <dd className="min-w-0 truncate font-mono text-[11px] text-text-secondary">
            {comparison.path ?? "Not examined"}
          </dd>
        </div>
        <div className="flex min-w-0 items-baseline gap-2">
          <dt className="shrink-0 text-[11px] text-text-tertiary">Expected</dt>
          <dd className="min-w-0 truncate font-mono text-[11px] text-text-secondary">
            {comparison.expected_sha256
              ? comparison.expected_sha256.slice(0, 12)
              : "Not recorded"}
          </dd>
        </div>
        <div className="flex min-w-0 items-baseline gap-2">
          <dt className="shrink-0 text-[11px] text-text-tertiary">Observed</dt>
          <dd className="min-w-0 truncate font-mono text-[11px] text-text-secondary">
            {comparison.observed_sha256
              ? comparison.observed_sha256.slice(0, 12)
              : "Not recorded"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function ProvenanceField({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div className="flex min-w-0 items-baseline justify-between gap-3 border-b border-border/60 py-1">
      <dt className="shrink-0 text-[12px] text-text-secondary">{label}</dt>
      <dd className="min-w-0 truncate text-[12px] text-text">
        {value && value.trim() ? value : (
          <span className="italic text-text-tertiary">Not stated</span>
        )}
      </dd>
    </div>
  );
}
