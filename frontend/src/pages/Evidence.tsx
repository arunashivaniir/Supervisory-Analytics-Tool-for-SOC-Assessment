import { useMemo, useState } from "react";

import { useAnalysis } from "../app/AnalysisContext";
import {
  capabilitiesForScope,
  capabilityTallyForScope,
  capabilityScopes,
  scopeRows,
} from "../app/selectors";
import { Caveat, PageHeader, Section } from "../components/layout/PageHeader";
import { EvidenceIntegrityPanel } from "../components/evidence/EvidenceIntegrityPanel";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/Metric";
import { SelectFilter } from "../components/ui/Filters";
import { StatusBadge } from "../components/ui/StatusBadge";
import {
  DataTable,
  HeadCell,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "../components/ui/DataTable";
import { ConceptList, DataRow, Token } from "../components/ui/DataDisplay";
import {
  entityLabel,
  entityResolved,
  formatCount,
  formatPercent,
  optionalText,
  periodLabel,
  periodResolved,
} from "../lib/formatters";
import { capabilityStatus } from "../lib/status";
import type { Capability } from "../types/pipeline";

/**
 * What the submitted data can and cannot establish.
 *
 * This screen is about evidence, not risk. It shows the capability states the
 * backend reported, and for each capability exactly which canonical concepts
 * were present, which were missing, and why a state was reached. No score is
 * shown here, because the pipeline does not produce one for evidence
 * availability and the interface will not manufacture a proxy for it.
 */
export function EvidencePage() {
  const { result, running, analysisError } = useAnalysis();

  const rows = useMemo(() => scopeRows(result), [result]);
  const scopes = useMemo(() => capabilityScopes(result), [result]);

  const [scopeId, setScopeId] = useState("all");

  const activeScopeId =
    scopeId === "all" ? (rows[0]?.assessment_id ?? null) : scopeId;

  const capabilities = useMemo(
    () => capabilitiesForScope(result, activeScopeId),
    [result, activeScopeId],
  );

  const posture = useMemo(
    () => capabilityTallyForScope(result, activeScopeId),
    [result, activeScopeId],
  );

  const [expanded, setExpanded] = useState<string | null>(null);

  const activeRow = rows.find((row) => row.assessment_id === activeScopeId) ?? null;

  if (!result) {
    return (
      <div className="py-10">
        <PageHeader title="Evidence" />
        {analysisError ? (
          <Caveat tone="caution">{analysisError}</Caveat>
        ) : running ? (
          <Caveat>The assessment is still being produced.</Caveat>
        ) : (
          <EmptyState
            title="No assessment loaded"
            description="Choose a dataset from the top bar to produce an assessment."
          />
        )}

        {/* The evidence register is a property of the local store rather than
            of the loaded assessment, so it is readable with nothing loaded. */}
        <div className="mt-6">
          <EvidenceIntegrityPanel />
        </div>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title="Evidence"
        subject={result.dataset.split("/").pop()}
        meta={`${formatCount(result.ingestion.record_count)} records · ${formatCount(
          result.ingestion.column_count,
        )} columns read · ${
          activeRow
            ? `${entityResolved(activeRow.entity) ? entityLabel(activeRow.entity) : "Entity not identified"}, ${
                periodResolved(activeRow.period) ? periodLabel(activeRow.period) : "period not determined"
              }`
            : "No scope selected"
        }`}
        description="Whether the submitted files are intact, and what the evidence each capability was assessed against, and where that evidence was absent. Evidence states describe the submitted data, not the strength of a control."
      />

      <EvidenceIntegrityPanel />

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <SelectFilter
          label="Assessment scope"
          value={scopeId}
          onChange={setScopeId}
          className="w-[280px]"
          options={[
            { value: "all", label: "All scopes (first shown)" },
            ...rows.map((row) => ({
              value: row.assessment_id,
              label: `${
                entityResolved(row.entity) ? entityLabel(row.entity) : "Entity not identified"
              } · ${
                periodResolved(row.period) ? periodLabel(row.period) : "period not determined"
              } · ${formatCount(row.record_count)} records`,
            })),
          ]}
        />

        {posture.length > 0 ? (
          <div className="flex items-end gap-2 pb-0.5">
            {posture.map((entry) => {
              const presentation = capabilityStatus(entry.status);

              return (
                <span
                  key={entry.status}
                  className="inline-flex items-center gap-1.5 rounded-[6px] border border-border bg-surface px-2 py-1"
                >
                  <StatusBadge
                    tone={entry.count === 0 ? "neutral" : presentation.tone}
                    label={presentation.label}
                    raw={entry.status}
                  />
                  <span className="tabular text-[13px] font-medium text-text">
                    {entry.count}
                  </span>
                </span>
              );
            })}
          </div>
        ) : null}
      </div>

      {capabilities.length === 0 ? (
        <Card>
          <EmptyState
            title="No capability evidence reported"
            description="The pipeline returned no capability evidence states for this scope."
          />
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-border">
            {capabilities.map(({ capability }) => (
              <CapabilityItem
                key={capability.capability_id}
                capability={capability}
                open={expanded === capability.capability_id}
                onToggle={() =>
                  setExpanded((current) =>
                    current === capability.capability_id
                      ? null
                      : capability.capability_id,
                  )
                }
              />
            ))}
          </ul>
        </Card>
      )}

      <Section
        title="Assessment scope"
        description="Scope-level counts, as the pipeline recorded them."
        className="mt-6"
      >
        <Card>
          {scopes.length === 0 ? (
            <EmptyState
              title="No scope evidence summary"
              description="The pipeline returned no capability scope records."
            />
          ) : (
            <DataTable>
              <TableHead>
                <HeadCell>Scope</HeadCell>
                <HeadCell align="right">Records</HeadCell>
                <HeadCell align="right">Available</HeadCell>
                <HeadCell align="right">Insufficient</HeadCell>
                <HeadCell align="right">Not assessed</HeadCell>
              </TableHead>
              <TableBody>
                {scopes.map((scope) => (
                  <TableRow key={scope.assessment_id}>
                    <TableCell>
                      <Token>{scope.assessment_id}</Token>
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatCount(scope.record_count)}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {scope.status_counts.AVAILABLE ?? 0}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {scope.status_counts.INSUFFICIENT_EVIDENCE ?? 0}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {scope.status_counts.NOT_ASSESSED ?? 0}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </DataTable>
          )}
        </Card>
      </Section>

      <Caveat className="mt-2.5">
        Insufficient evidence is not a control failure. Not assessed is not low
        risk. Both record that the submitted data did not permit a judgement,
        and neither should be read as a result.
      </Caveat>
    </>
  );
}

/**
 * One capability, expandable to the evidence behind its state.
 *
 * Collapsed, this is a state and a count. Expanded, it is the required
 * evidence, the submitted evidence, the canonical concepts, and the paths that
 * could not be satisfied.
 */
function CapabilityItem({
  capability,
  open,
  onToggle,
}: {
  capability: Capability;
  open: boolean;
  onToggle: () => void;
}) {
  const presentation = capabilityStatus(capability.status);

  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 px-4 py-2.5 text-left transition-colors duration-75 hover:bg-subtle"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <span className="text-[13px] font-medium text-text">
            {capability.name}
          </span>
          <StatusBadge
            tone={presentation.tone}
            label={presentation.label}
            raw={capability.status}
          />
        </div>
        <div className="shrink-0 micro text-text-tertiary">
          {open ? "Hide evidence" : "Show evidence"}
        </div>
      </button>

      {open ? (
        <div className="border-t border-border bg-subtle/50 px-4 py-3">
          <p className="text-[13px] leading-relaxed text-text">
            {capability.explanation}
          </p>

          <div className="mt-3 grid grid-cols-2 gap-x-8">
            <div>
              <DataRow
                label="Status"
                value={
                  <StatusBadge
                    tone={presentation.tone}
                    label={presentation.label}
                    raw={capability.status}
                  />
                }
              />
              <DataRow
                label="Assessable"
                value={capability.is_assessable ? "Yes" : "No"}
              />
              <DataRow
                label="Coverage"
                value={formatPercent(capability.coverage)}
              />
              <DataRow
                label="Confidence"
                value={
                  capability.confidence === null
                    ? optionalText(null)
                    : capability.confidence.toFixed(2)
                }
              />
            </div>
            <div>
              <DataRow
                label="Evidence present"
                value={
                  <ConceptList concepts={capability.evidence_available} />
                }
              />
              <DataRow
                label="Evidence missing"
                value={
                  capability.evidence_missing.length > 0 ? (
                    <ul className="list-inside list-disc text-xs text-text-secondary">
                      {capability.evidence_missing.map((item) => (
                        <li key={item} className="font-mono micro">
                          {item}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="text-text-tertiary italic">
                      Nothing recorded as missing
                    </span>
                  )
                }
              />
            </div>
          </div>

          {capability.evidence_detail.length > 0 ? (
            <div className="mt-3">
              <div className="section-label mb-1.5">Traceability</div>
              <DataTable className="rounded-[8px] border border-border text-xs">
                <TableHead>
                  <HeadCell>Canonical path</HeadCell>
                  <HeadCell>Concept</HeadCell>
                  <HeadCell>Tier</HeadCell>
                  <HeadCell>Satisfied</HeadCell>
                  <HeadCell>Source column</HeadCell>
                </TableHead>
                <TableBody>
                  {capability.evidence_detail.map((item) => (
                    <TableRow key={`${item.canonical_path}-${item.concept}`}>
                      <TableCell className="font-mono micro">
                        {item.canonical_path}
                      </TableCell>
                      <TableCell className="font-mono micro">
                        {item.concept}
                      </TableCell>
                      <TableCell>{item.tier}</TableCell>
                      <TableCell>
                        <span
                          className={
                            item.satisfied
                              ? "text-positive"
                              : "text-text-tertiary"
                          }
                        >
                          {item.satisfied ? "Yes" : "No"}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono micro">
                        {optionalText(item.source_column, "—")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </DataTable>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
