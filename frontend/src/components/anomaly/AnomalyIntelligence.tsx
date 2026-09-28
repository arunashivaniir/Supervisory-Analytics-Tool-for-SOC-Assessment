import { useState } from "react";

import { availableFeatureCount } from "../../app/selectors";
import { cn } from "../../lib/cn";
import {
  NOT_AVAILABLE,
  formatNumber,
  optionalText,
} from "../../lib/formatters";
import { anomalyVerdict, signalStatus } from "../../lib/status";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/Metric";
import { StatusBadge } from "../ui/StatusBadge";
import { ConceptList, DataRow, Token } from "../ui/DataDisplay";
import type {
  AnomalyModelStatus,
  AnomalyScopeResult,
  FeatureSchema,
} from "../../types/pipeline";

/**
 * What the offline model reported for one assessment scope.
 *
 * Shown only when the anomaly layer produced output. Model status, version,
 * schema version, verdict, score and feature availability are displayed as the
 * backend reported them.
 *
 * Two things this component will not do. It will not write an explanation the
 * backend did not provide: the model status, verdict reason and the model's own
 * explanation are the only text shown. And it will not describe a feature the
 * backend marked unavailable as a value, because there is no value.
 */
export function AnomalyIntelligence({
  scope,
  modelStatus,
  featureSchema,
  limitations,
}: {
  scope: AnomalyScopeResult | null;
  modelStatus: AnomalyModelStatus | null;
  featureSchema: FeatureSchema | null;
  limitations: string[];
}) {
  if (!modelStatus) {
    return (
      <Card>
        <EmptyState
          title="No anomaly output"
          description="The pipeline result contains no anomaly model status for this dataset."
        />
      </Card>
    );
  }

  if (!scope) {
    return (
      <Card>
        <EmptyState
          title="No anomaly result for this scope"
          description="The anomaly layer produced no result for this assessment scope."
        />
      </Card>
    );
  }

  const verdict = anomalyVerdict(scope.verdict);
  const available = availableFeatureCount(scope);
  const unavailable = scope.unavailable_features ?? [];
  // The backend nests the model's account of the verdict in an object. It is
  // read from there and nowhere else, so what is displayed is what the detector
  // wrote, including the state where it wrote nothing.
  const explanation = scope.explanation ?? null;

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <div className="grid grid-cols-2 gap-x-8 px-4 py-3">
          <div>
            <DataRow
              label="Model status"
              value={
                <StatusBadge
                  tone={signalStatus(modelStatus.status).tone}
                  label={signalStatus(modelStatus.status).label}
                  raw={modelStatus.status}
                />
              }
            />
            <DataRow
              label="Model version"
              value={<Token>{optionalText(scope.model_version)}</Token>}
            />
            <DataRow
              label="Feature schema"
              value={<Token>{optionalText(scope.feature_schema_version)}</Token>}
            />
          </div>
          <div>
            <DataRow
              label="Verdict"
              value={
                <StatusBadge tone={verdict.tone} label={verdict.label} raw={scope.verdict} />
              }
            />
            <DataRow
              label="Anomaly score"
              value={
                scope.anomaly_score === null ? (
                  <span className="text-text-tertiary italic">
                    Not produced
                  </span>
                ) : (
                  <span className="tabular">
                    {formatNumber(scope.anomaly_score, 4)}
                  </span>
                )
              }
            />
            <DataRow
              label="Features available"
              value={
                available === null ? (
                  <span className="text-text-tertiary italic">
                    {NOT_AVAILABLE}
                  </span>
                ) : (
                  <span className="tabular">
                    {available} of {scope.features.length}
                  </span>
                )
              }
            />
          </div>
        </div>

        <p className="border-t border-border px-4 py-2.5 text-[13px] leading-relaxed text-text">
          {scope.reason}
        </p>
      </Card>

      {explanation ? (
        <Card>
          <div className="px-4 py-3">
            <div className="section-label mb-1.5">Explanation</div>
            <p className="text-[13px] font-medium leading-relaxed text-text">
              {explanation.narrative}
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-text-secondary">
              {explanation.explanation}
            </p>
            {explanation.evidence_concepts.length > 0 ? (
              <div className="mt-2.5">
                <DataRow
                  label="Evidence concepts"
                  value={
                    <ConceptList
                      concepts={explanation.evidence_concepts}
                      collapsed={6}
                    />
                  }
                />
              </div>
            ) : null}
            <p className="mt-2.5 border-t border-border pt-2.5 text-xs leading-relaxed text-text-tertiary">
              {explanation.score_semantics}
            </p>
          </div>
        </Card>
      ) : null}

      {unavailable.length > 0 ? (
        <Card>
          <div className="px-4 py-3">
            <div className="section-label mb-1.5">
              Unavailable features
            </div>
            <p className="mb-2 text-xs text-text-secondary">
              These features could not be built from the submitted evidence.
              The model was not given an invented value for any of them.
            </p>
            <ul className="flex flex-col gap-1.5">
              {unavailable.map((item) => (
                <li key={item.feature_id} className="text-xs">
                  <span className="font-mono text-text">{item.feature_id}</span>
                  <span className="text-text-tertiary"> — {item.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      ) : null}

      {featureSchema ? (
        <FeatureVectorCard scope={scope} />
      ) : null}

      {limitations.length > 0 ? (
        <Card>
          <div className="px-4 py-3">
            <div className="section-label mb-1.5">Limitations</div>
            <ul className="list-inside list-disc space-y-1 text-xs leading-relaxed text-text-secondary">
              {limitations.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

/**
 * The feature values behind a verdict, collapsed by default.
 *
 * The full audit profile is available but not foregrounded: an examiner
 * usually needs the verdict and its reason, and reaches for the vector only
 * when checking the model's work.
 */
function FeatureVectorCard({ scope }: { scope: AnomalyScopeResult }) {
  const [open, setOpen] = useState(false);

  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left"
        aria-expanded={open}
      >
        <span className="section-label">Feature profile</span>
        <span className="micro text-text-secondary">
          {open ? "Hide" : "Show"} {scope.features.length} features
        </span>
      </button>

      {open ? (
        <div className="border-t border-border">
          <table className="w-full text-xs">
            <thead className="bg-subtle">
              <tr>
                <th
                  scope="col"
                  className="px-3 py-1.5 text-left micro font-semibold uppercase tracking-[0.06em] text-text-tertiary"
                >
                  Feature
                </th>
                <th
                  scope="col"
                  className="px-3 py-1.5 text-right micro font-semibold uppercase tracking-[0.06em] text-text-tertiary"
                >
                  Value
                </th>
                <th
                  scope="col"
                  className="px-3 py-1.5 text-left micro font-semibold uppercase tracking-[0.06em] text-text-tertiary"
                >
                  Source concepts
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {scope.features.map((feature) => (
                <tr
                  key={feature.feature_id}
                  className={cn(!feature.available && "bg-canvas/60")}
                >
                  <td className="px-3 py-1.5 font-mono micro text-text">
                    {feature.feature_id}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 text-right tabular",
                      feature.available
                        ? "text-text"
                        : "text-text-tertiary italic",
                    )}
                  >
                    {feature.available
                      ? formatNumber(feature.value, 4)
                      : "Not available"}
                  </td>
                  <td className="px-3 py-1.5 micro text-text-secondary">
                    {feature.source_concepts.length > 0
                      ? feature.source_concepts.join(", ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Card>
  );
}
