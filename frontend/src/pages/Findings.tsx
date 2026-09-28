import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import { unifiedFindings, type UnifiedFinding } from "../app/selectors";
import { Caveat, PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { SegmentedFilter, TextFilter } from "../components/ui/Filters";
import { ConceptList } from "../components/ui/DataDisplay";
import { FindingDetail } from "../components/findings/FindingDetail";
import { DetailDrawer } from "../components/ui/DetailDrawer";
import { EmptyState } from "../components/ui/Metric";
import { StatusBadge } from "../components/ui/StatusBadge";
import { DataTable, HeadCell, TableBody, TableCell, TableHead, TableRow } from "../components/ui/DataTable";
import {
  entityLabel,
  entityResolved,
  periodLabel,
  periodResolved,
} from "../lib/formatters";
import { SIGNAL_FAMILIES, signalStatus } from "../lib/status";

/**
 * The investigative screen.
 *
 * Every finding in the result, from all four signal families, in one dense
 * list. Selecting a row opens a drawer rather than navigating away, so the
 * examiner keeps their filters and their position while they read the detail
 * and move to the next finding.
 */
export function FindingsPage() {
  const { result, running, analysisError } = useAnalysis();
  const navigate = useNavigate();

  const [family, setFamily] = useState("all");
  const [search, setSearch] = useState("");
  const [entity, setEntity] = useState("all");
  const [period, setPeriod] = useState("all");
  const [selected, setSelected] = useState<UnifiedFinding | null>(null);

  const findings = useMemo(() => unifiedFindings(result), [result]);

  const counts = useMemo(() => {
    const tally: Record<string, number> = { all: findings.length };

    for (const family of SIGNAL_FAMILIES) {
      tally[family.id] =
        findings.filter((item) => item.family === family.id).length;
    }

    return tally;
  }, [findings]);

  const entityValues = useMemo(() => {
    const values = new Set<string>();

    for (const item of findings) {
      values.add(
        entityResolved(item.entity) ? entityLabel(item.entity) : "",
      );
    }

    return [...values].filter(Boolean).sort((a, b) => a.localeCompare(b));
  }, [findings]);

  const periodValues = useMemo(() => {
    const values = new Set<string>();

    for (const item of findings) {
      values.add(
        periodResolved(item.period) ? periodLabel(item.period) : "",
      );
    }

    return [...values].filter(Boolean).sort((a, b) => a.localeCompare(b));
  }, [findings]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();

    return findings.filter((item) => {
      if (family !== "all" && item.family !== family) {
        return false;
      }

      if (entity !== "all") {
        const label = entityResolved(item.entity) ? entityLabel(item.entity) : "";
        if (label !== entity) {
          return false;
        }
      }

      if (period !== "all") {
        const label = periodResolved(item.period) ? periodLabel(item.period) : "";
        if (label !== period) {
          return false;
        }
      }

      if (!needle) {
        return true;
      }

      return (
        item.indicator.toLowerCase().includes(needle) ||
        item.reason.toLowerCase().includes(needle) ||
        item.assessment_id.toLowerCase().includes(needle) ||
        item.evidenceConcepts.some((concept) =>
          concept.toLowerCase().includes(needle),
        )
      );
    });
  }, [findings, family, search, entity, period]);

  if (!result) {
    return (
      <div className="py-10">
        <PageHeader title="Findings" />
        {analysisError ? (
          <Caveat tone="caution">{analysisError}</Caveat>
        ) : running ? (
          <Caveat>The assessment is still being produced.</Caveat>
        ) : (
          <EmptyState
            title="No assessment loaded"
            description="Choose a dataset to produce an assessment."
          />
        )}
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title="Findings"
        subject={result.dataset.split("/").pop()}
        meta={`${findings.length} finding${findings.length === 1 ? "" : "s"} reported by the pipeline`}
      />

      {findings.length === 0 ? (
        <Card>
          <EmptyState
            title="No findings reported"
            description="The pipeline examined this evidence and returned no findings in any of the four signal families. This means no finding condition was met; it is not a statement that the assessed controls are effective."
          />
        </Card>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <SegmentedFilter
              label="Type"
              value={family}
              onChange={setFamily}
              options={[
                { value: "all", label: `All ${counts.all}` },
                ...SIGNAL_FAMILIES.map((item) => ({
                  value: item.id,
                  label: `${item.label} ${counts[item.id]}`,
                })),
              ]}
            />

            <TextFilter
              label="Search"
              value={search}
              onChange={setSearch}
              placeholder="Indicator, reason or concept"
              className="w-[240px]"
            />

            <NativeSelect
              label="Entity"
              value={entity}
              onChange={setEntity}
              options={entityValues}
              allLabel="All entities"
            />

            <NativeSelect
              label="Period"
              value={period}
              onChange={setPeriod}
              options={periodValues}
              allLabel="All periods"
            />

            <div className="ml-auto text-xs text-text-tertiary">
              {visible.length} of {findings.length} shown
            </div>
          </div>

          <Card>
            {visible.length === 0 ? (
              <EmptyState
                title="No findings match these filters"
                description="Adjust or clear the filters to see the remaining findings."
              />
            ) : (
              <DataTable>
                <TableHead>
                  <HeadCell>Type</HeadCell>
                  <HeadCell>Indicator</HeadCell>
                  <HeadCell>Entity</HeadCell>
                  <HeadCell>Period</HeadCell>
                  <HeadCell>Reason</HeadCell>
                  <HeadCell>Evidence</HeadCell>
                  <HeadCell>Status</HeadCell>
              </TableHead>
                <TableBody>
                  {visible.map((item) => {
                    const presentation = item.status
                      ? signalStatus(item.status)
                      : null;

                    return (
                      <TableRow
                        key={item.key}
                        selected={selected?.key === item.key}
                        onClick={() => setSelected(item)}
                      >
                        <TableCell className="whitespace-nowrap text-xs text-text-secondary">
                          {item.familyLabel}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-text">
                          {item.indicator}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {entityResolved(item.entity) ? (
                            entityLabel(item.entity)
                          ) : (
                            <span className="text-text-tertiary italic">
                              Not identified
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {periodResolved(item.period) ? (
                            periodLabel(item.period)
                          ) : (
                            <span className="text-text-tertiary italic">
                              Not determined
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="max-w-[420px]">
                          <span className="line-clamp-2 text-xs leading-relaxed text-text-secondary">
                            {item.reason}
                          </span>
                        </TableCell>
                        <TableCell>
                          <ConceptList
                            concepts={item.evidenceConcepts}
                            collapsed={2}
                          />
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {presentation ? (
                            <StatusBadge
                              tone={presentation.tone}
                              label={presentation.label}
                              raw={item.status ?? undefined}
                            />
                          ) : (
                            <span className="text-text-tertiary italic">
                              Not reported
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </DataTable>
            )}
          </Card>

          <Caveat className="mt-2.5">
            Each family is reported on its own terms. A finding in one family
            does not raise, lower or reclassify a finding in another, and the
            list above is not ordered by severity: the pipeline reports no
            severity or priority for these signals.
          </Caveat>
        </>
      )}

      <DetailDrawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSelected(null);
          }
        }}
        title={selected?.indicator ?? ""}
        subtitle={
          selected ? (
            <span className="flex flex-wrap items-center gap-2">
              <span>{selected.familyLabel}</span>
              {selected.status ? (
                <StatusBadge
                  tone={signalStatus(selected.status).tone}
                  label={signalStatus(selected.status).label}
                  raw={selected.status}
                />
              ) : null}
            </span>
          ) : null
        }
        footer={
          selected ? (
            <button
              type="button"
              onClick={() => {
                const id = selected.assessment_id;
                setSelected(null);
                navigate(`/assessments/${encodeURIComponent(id)}`);
              }}
              className="text-xs font-medium text-accent underline-offset-2 hover:underline"
            >
              Open the assessment scope this finding belongs to
            </button>
          ) : null
        }
      >
        {selected ? <FindingDrawerBody finding={selected} /> : null}
      </DetailDrawer>
    </>
  );
}

function FindingDrawerBody({ finding }: { finding: UnifiedFinding }) {
  return (
    <div className="flex flex-col">
      <FindingDetail finding={finding} />
    </div>
  );
}

function NativeSelect({
  label,
  value,
  options,
  onChange,
  allLabel,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  allLabel: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="section-label">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 w-[190px] cursor-pointer rounded-[8px] border border-border bg-surface px-2.5 text-[13px] text-text focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
      >
        <option value="all">{allLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

