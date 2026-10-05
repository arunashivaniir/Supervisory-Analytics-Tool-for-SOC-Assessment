import { Link, useNavigate } from "react-router-dom";

import { useDashboard } from "../app/DashboardContext";
import { useAnalysis } from "../app/AnalysisContext";
import { capabilityScopes } from "../app/selectors";
import { PageHeader } from "../components/layout/PageHeader";
import { EvidenceIntegrityPanel } from "../components/evidence/EvidenceIntegrityPanel";
import { MappingReviewSection } from "../components/assessment/CanonicalMappingReview";
import { EntityAttentionTable } from "../components/dashboard/EntityAttentionTable";
import {
  DataRow,
  Frame,
  Note,
  Section,
} from "../components/ui/Surface";
import {
  HeadCell,
  HeadRow,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableScroller,
} from "../components/ui/Table";
import {
  EmptyState,
  LoadingState,
  StatusBadge,
} from "../components/ui/State";
import { formatCount, optionalText } from "../lib/formatters";
import { capabilityStatus } from "../lib/status";
import { entryForDataset } from "../services/evidenceRegister";

/**
 * Evidence: what was submitted, and how far it can be trusted.
 *
 * Three things live here, in the order an examiner meets them.
 *
 *   1. The scope's own evidence coverage, per entity. Whether the backend could
 *      assess anything for a scope is the first constraint on every finding
 *      about it, so it is stated before the findings themselves.
 *   2. The register. What the trust layer holds, its integrity, custody and
 *      provenance. This is a property of the local store rather than of the run,
 *      and it is labelled as such.
 *   3. The canonical mapping review. Which incoming column became which concept,
 *      and which mappings a reviewer has overridden.
 *
 * The two are deliberately kept apart. The first describes the evidence the
 * pipeline could *use*; the second describes what was *submitted*. Conflating
 * them would let a digest mismatch look like an absence of findings.
 */
export function EvidencePage() {
  const { result, running, analysisError } = useAnalysis();
  const { view, register, registerLoading, registerError } = useDashboard();
  const navigate = useNavigate();

  if (!view.hasResult || !result) {
    return (
      <>
        <PageHeader title="Evidence" />

        {analysisError ? (
          <Note tone="caution">{analysisError}</Note>
        ) : running ? (
          <LoadingState
            title="Assessment in progress"
            detail="Evidence states appear once the pipeline completes."
          />
        ) : (
          <EmptyState
            title="No assessment loaded"
            description="Run an assessment before reading its evidence."
          />
        )}
      </>
    );
  }

  const scopes = capabilityScopes(result);
  const entry = entryForDataset(register, result.dataset ?? "");

  return (
    <>
      <PageHeader
        title="Evidence"
        supporting={
          <>
            What the pipeline could assess from the evidence supplied, and what the
            local trust layer holds.{" "}
            {view.run.datasetName
              ? `Currently assessing ${view.run.datasetName}`
              : ""}
            {view.status.records === null
              ? "."
              : `, over ${formatCount(view.status.records)} records.`}
          </>
        }
      />

      <Section
        title="Evidence coverage by entity"
        description="The three capability states the pipeline emits, per assessment scope. They describe whether evidence was available, never how well anything performed."
      >
        <EntityAttentionTable
          rows={view.entities}
          emptyTitle="No assessment scopes"
          emptyDescription="The pipeline reported no scopes for this result."
        />
      </Section>

      <Section
        title="Capability states in full"
        description="Every scope's coverage, as the pipeline counted it."
      >
        <Frame>
          <TableScroller>
            <TableHead>
              <HeadRow>
                <HeadCell width="26%">Scope</HeadCell>
                <HeadCell align="right">Available</HeadCell>
                <HeadCell align="right">Insufficient evidence</HeadCell>
                <HeadCell align="right">Not assessed</HeadCell>
                <HeadCell width="16%">State</HeadCell>
              </HeadRow>
            </TableHead>

            <TableBody>
              {scopes.map((scope) => {
                const row = view.entities.find(
                  (entity) => entity.assessmentId === scope.assessment_id,
                );
                const available = scope.status_counts.AVAILABLE ?? 0;
                const insufficient =
                  scope.status_counts.INSUFFICIENT_EVIDENCE ?? 0;
                const notAssessed = scope.status_counts.NOT_ASSESSED ?? 0;

                // The scope's overall state is the backend's own dominant
                // capability state, read from its counts. Ties resolve to the
                // weakest state on the assumption that an examiner would rather
                // be warned than reassured.
                const dominant = available >= insufficient && available >= notAssessed
                  ? "AVAILABLE"
                  : insufficient >= notAssessed
                    ? "INSUFFICIENT_EVIDENCE"
                    : "NOT_ASSESSED";
                const presentation = capabilityStatus(dominant);

                return (
                  <TableRow
                    key={scope.assessment_id}
                    onSelect={() =>
                      navigate(
                        `/assessments/${encodeURIComponent(scope.assessment_id)}`,
                      )
                    }
                  >
                    <TableCell>
                      <span className="block truncate text-[13px] text-text">
                        {row?.resolved
                          ? (row.entity.name ?? row.entity.id)
                          : "Entity not identified"}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-text-tertiary">
                        {row?.period.available
                          ? `${row.period.start ?? ""} ${row.period.label ?? ""}`.trim()
                          : "period not determined"}
                      </span>
                    </TableCell>

                    <TableCell align="right" className="tabular">
                      {formatCount(available)}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatCount(insufficient)}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatCount(notAssessed)}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        tone={presentation.tone}
                        label={presentation.label}
                        raw={dominant}
                      />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </TableScroller>
        </Frame>
      </Section>

      <Section
        title="Evidence integrity"
        description="What the local trust layer holds. This is a property of the evidence store on this machine, not of the assessment run."
      >
        <EvidenceIntegrityPanel
          entries={register}
          loading={registerLoading}
          error={registerError}
        />
      </Section>

      <Section
        title="This assessment's submission"
        description="The register entry matching the dataset on screen, when there is one."
      >
        {entry ? (
          <Frame>
            <div className="px-4 py-3">
              <DataRow
                label="Evidence id"
                value={<span className="font-mono text-[12px]">{entry.evidence_id}</span>}
              />
              <DataRow
                label="File"
                value={entry.source.filename ?? optionalText(null)}
              />
              <DataRow
                label="Registered digest"
                value={
                  <span className="font-mono text-[12px]">
                    {entry.registered_sha256 ?? "Not registered"}
                  </span>
                }
              />
              <DataRow
                label="Integrity"
                value={
                  <StatusBadge
                    tone={
                      entry.overall_status === "VERIFIED"
                        ? "positive"
                        : entry.overall_status === "INTEGRITY_FAILED"
                          ? "critical"
                          : "neutral"
                    }
                    label={
                      entry.overall_status === "VERIFIED"
                        ? "Verified"
                        : entry.overall_status === "INTEGRITY_FAILED"
                          ? "Digest mismatch"
                          : entry.overall_status === "MISSING"
                            ? "Missing"
                            : "Unavailable"
                    }
                    raw={entry.overall_status}
                  />
                }
              />
              <DataRow
                label="Analysis"
                value={
                  entry.analysis.permitted ? (
                    <StatusBadge tone="positive" label="Permitted" />
                  ) : (
                    <StatusBadge tone="critical" label="Blocked" />
                  )
                }
              />
            </div>
          </Frame>
        ) : (
          <Note tone="neutral">
            {registerLoading
              ? "The register is still being read."
              : "No registered submission matches the dataset on screen. The dataset may predate the register, or it may have been placed in the workspace directly. No digest is attributed to it."}
          </Note>
        )}
      </Section>

      <MappingReviewSection />

      <Section
        title="Reading these numbers"
        description="What the counts above do and do not establish."
      >
        <ul className="min-w-0 space-y-1.5">
          <li>
            <Note tone="neutral">
              A scope with nothing assessable is not a scope with nothing wrong.
              It is a scope the evidence did not permit the pipeline to assess.
            </Note>
          </li>
          <li>
            <Note tone="neutral">
              <Link
                to="/findings"
                className="text-accent underline-offset-2 hover:underline"
              >
                Findings
              </Link>{" "}
              report what was found in the evidence that existed. A low count
              alongside low coverage is a statement about the submission, not about
              the operations it describes.
            </Note>
          </li>
        </ul>
      </Section>
    </>
  );
}
