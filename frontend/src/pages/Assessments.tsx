import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAnalysis } from "../app/AnalysisContext";
import {
  capabilityTallyForScope,
  countByFamily,
  findingsForScope,
  scopeRows,
  unifiedFindings,
} from "../app/selectors";
import { Caveat, PageHeader } from "../components/layout/PageHeader";
import { Card } from "../components/ui/Card";
import { DataTable, HeadCell, TableBody, TableCell, TableHead, TableRow, UnresolvedCell } from "../components/ui/DataTable";
import { EmptyState } from "../components/ui/Metric";
import { SelectFilter, TextFilter } from "../components/ui/Filters";
import { StatusBadge } from "../components/ui/StatusBadge";
import {
  formatCount,
  entityLabel,
  entityResolved,
  periodLabel,
  periodResolved,
} from "../lib/formatters";
import {
  SIGNAL_FAMILIES,
  anomalyVerdict,
  capabilityStatus,
} from "../lib/status";
import type { AnomalyScopeResult } from "../types/pipeline";

/**
 * Every assessment scope, with the filters an examiner actually needs to
 * narrow a large evidence file: which entity, which period, and what the
 * pipeline's own evidence posture for that scope was.
 *
 * The anomaly column shows the verdict the model returned for the scope, and
 * says so when the scope was not evaluable. It does not infer a verdict from
 * the presence of other findings.
 */
export function AssessmentsPage() {
  const { result, running, analysisError } = useAnalysis();
  const navigate = useNavigate();

  const [entity, setEntity] = useState("all");
  const [period, setPeriod] = useState("all");
  const [search, setSearch] = useState("");

  const rows = useMemo(() => scopeRows(result), [result]);
  const findings = useMemo(() => unifiedFindings(result), [result]);

  // Each row carries its own filter keys, so filtering never has to recover a
  // row's position in order to compare it with the current selection.
  const keyedRows = useMemo(
    () =>
      rows.map((row, index) => ({
        row,
        entityKey: `entity-${index}`,
        periodKey: `period-${index}`,
      })),
    [rows],
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();

    return keyedRows.filter(({ row, entityKey: rowEntity, periodKey: rowPeriod }) => {
      if (entity !== "all" && rowEntity !== entity) {
        return false;
      }

      if (period !== "all" && rowPeriod !== period) {
        return false;
      }

      if (!needle) {
        return true;
      }

      const entityText = entityResolved(row.entity) ? entityLabel(row.entity) : "";
      const periodText = periodResolved(row.period) ? periodLabel(row.period) : "";

      return (
        entityText.toLowerCase().includes(needle) ||
        periodText.toLowerCase().includes(needle) ||
        row.assessment_id.toLowerCase().includes(needle)
      );
    });
  }, [keyedRows, entity, period, search]);

  if (!result) {
    return (
      <div className="py-10">
        <PageHeader title="Assessments" />
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
        title="Assessments"
        subject={result.dataset.split("/").pop()}
        meta={`${formatCount(result.assessment.scope_count)} assessment ${
          result.assessment.scope_count === 1 ? "scope" : "scopes"
        } from ${formatCount(result.assessment.record_count)} records`}
      />

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <SelectFilter
          label="Entity"
          value={entity}
          onChange={setEntity}
          className="w-[200px]"
          options={[
            { value: "all", label: "All entities" },
            ...keyedRows.map(({ row, entityKey: key }) => ({
              value: key,
              label: entityResolved(row.entity)
                ? entityLabel(row.entity)
                : "Entity not identified",
            })),
          ]}
        />
        <SelectFilter
          label="Period"
          value={period}
          onChange={setPeriod}
          className="w-[200px]"
          options={[
            { value: "all", label: "All periods" },
            ...keyedRows.map(({ row, periodKey: key }) => ({
              value: key,
              label: periodResolved(row.period)
                ? periodLabel(row.period)
                : "Period not determined",
            })),
          ]}
        />
        <TextFilter
          label="Search"
          value={search}
          onChange={setSearch}
          placeholder="Entity, period or scope id"
          className="w-[260px]"
        />

        <div className="ml-auto text-xs text-text-tertiary">
          {visible.length} of {keyedRows.length} shown
        </div>
      </div>

      <Card>
        {visible.length === 0 ? (
          <EmptyState
            title="No scopes match these filters"
            description="Adjust or clear the filters to see the remaining assessment scopes."
          />
        ) : (
          <DataTable>
            <TableHead>
              <HeadCell>Entity</HeadCell>
              <HeadCell>Period</HeadCell>
              <HeadCell align="right">Records</HeadCell>
              <HeadCell>Evidence posture</HeadCell>
              <HeadCell align="right">Signals</HeadCell>
              <HeadCell>Primary signal</HeadCell>
              <HeadCell>Anomaly</HeadCell>
              <HeadCell align="right">Review</HeadCell>
          </TableHead>
            <TableBody>
              {visible.map(({ row }) => {
                const scopeFindings = findingsForScope(
                  findings,
                  row.assessment_id,
                );
                const total = scopeFindings.length;
                const perFamily = countByFamily(scopeFindings);
                const tally = capabilityTallyForScope(result, row.assessment_id);
                const anomaly = anomalyFor(result, row.assessment_id);

                return (
                  <TableRow
                    key={row.assessment_id}
                    onClick={() =>
                      navigate(`/assessments/${encodeURIComponent(row.assessment_id)}`)
                    }
                  >
                    <TableCell>
                      {entityResolved(row.entity) ? (
                        entityLabel(row.entity)
                      ) : (
                        <UnresolvedCell reason={row.entity.unavailable_reason}>
                          Entity not identified
                        </UnresolvedCell>
                      )}
                    </TableCell>
                    <TableCell>
                      {periodResolved(row.period) ? (
                        periodLabel(row.period)
                      ) : (
                        <UnresolvedCell reason={row.period.unavailable_reason}>
                          Period not determined
                        </UnresolvedCell>
                      )}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {formatCount(row.record_count)}
                    </TableCell>
                    <TableCell>
                      {tally.length === 0 ? (
                        <span className="text-text-tertiary italic">
                          Not reported
                        </span>
                      ) : (
                        <PostureTally tally={tally} />
                      )}
                    </TableCell>
                    <TableCell align="right" className="tabular">
                      {total === 0 ? (
                        <span className="text-text-tertiary">0</span>
                      ) : (
                        <span className="font-medium">{total}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <PrimaryFamily perFamily={perFamily} />
                    </TableCell>
                    <TableCell>
                      {anomaly ? (
                        <StatusBadge
                          tone={anomalyVerdict(anomaly.verdict).tone}
                          label={anomalyVerdict(anomaly.verdict).label}
                          raw={anomaly.verdict}
                        />
                      ) : (
                        <span className="text-text-tertiary italic">
                          Not reported
                        </span>
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <span className="text-xs font-medium text-accent">
                        Review
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </DataTable>
        )}
      </Card>

      {visible.length > 0 ? (
        <Caveat className="mt-2.5">
          Signal totals are the sum of the four families the pipeline reports.
          The families are deliberately not combined into a single severity, and
          a scope with no signals has not thereby been shown to be effective.
        </Caveat>
      ) : null}
    </>
  );
}

/**
 * The family with the most findings for a scope, ties broken by the
 * pipeline's own family order. Zero findings is stated as no signal, never
 * as a judgement about the entity.
 */
function PrimaryFamily({ perFamily }: { perFamily: Record<string, number> }) {
  let best: (typeof SIGNAL_FAMILIES)[number] | null = null;
  let bestCount = 0;

  for (const family of SIGNAL_FAMILIES) {
    const count = perFamily[family.id] ?? 0;

    if (count > bestCount) {
      best = family;
      bestCount = count;
    }
  }

  if (!best) {
    return (
      <span className="text-xs text-text-tertiary italic">No signal</span>
    );
  }

  return (
    <span className="whitespace-nowrap text-xs text-text">
      {best.singular}{" "}
      <span className="tabular text-text-tertiary">· {bestCount}</span>
    </span>
  );
}

function anomalyFor(
  result: NonNullable<ReturnType<typeof useAnalysis>["result"]>,
  assessmentId: string,
): AnomalyScopeResult | null {
  return (
    result.anomaly_findings.scope_results.find(
      (item) => item.assessment_id === assessmentId,
    ) ?? null
  );
}

/**
 * The evidence posture for a scope, as a compact set of counts.
 *
 * Each count is coloured by the backend's own capability state, and a zero is
 * shown plainly rather than being dropped, so the reader can tell "none of
 * these scopes had insufficient evidence" from "this scope was not assessed".
 */
function PostureTally({
  tally,
}: {
  tally: { status: string; count: number }[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 micro">
      {tally.map((entry) => {
        const presentation = capabilityStatus(entry.status);

        return (
          <span key={entry.status} className="inline-flex items-center gap-1">
            <span
              className="size-1.5 rounded-full"
              style={{
                backgroundColor:
                  entry.count === 0
                    ? "var(--color-border-strong)"
                    : `var(--color-${presentation.tone === "positive" ? "positive" : presentation.tone === "caution" ? "caution" : "neutral-tone"})`,
              }}
            />
            <span className="tabular text-text-secondary">{entry.count}</span>
            <span className="text-text-tertiary">{presentation.label}</span>
          </span>
        );
      })}
    </div>
  );
}

