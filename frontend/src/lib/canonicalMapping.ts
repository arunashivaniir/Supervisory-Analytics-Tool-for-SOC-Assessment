/**
 * Context-aware candidate filtering for the C.1 canonical mapping review.
 *
 * Pure functions over transported backend data only:
 *
 *   source column category (profile) + candidate_mappings (authoritative
 *   ranking) + canonical_contract (datatype/category/pipeline/path).
 *
 * No second registry, no second ranking engine: the backend's candidate
 * order is preserved, and this module only filters/groups/explains it.
 * Safety guards mirror `framework/mapping/schema_mapper.py` (actor-like
 * `*_by` source columns must never become timestamp concepts) so the UI
 * cannot offer a choice the mapper would reject.
 */

import type {
  CanonicalCandidate,
  CanonicalContractEntry,
  CanonicalMappingDecision,
  CanonicalMappingState,
} from "../types/pipeline";

export const UNMAPPED = "UNMAPPED";

/** A reviewer mapping choice kept beside (never over) the automatic one. */
export interface ReviewerOverride {
  concept: string | null;
  previousConcept: string | null;
  previousState: CanonicalMappingState;
  newState: CanonicalMappingState;
  source: "REVIEWER_OVERRIDE";
  updatedAt: string;
  reason: string;
}

/** Build the override record for an accepted reviewer choice. */
export function reviewerRecord(
  decision: CanonicalMappingDecision,
  next: string | null,
): ReviewerOverride {
  return {
    concept: next,
    previousConcept: decision.canonical_concept ?? null,
    previousState: decision.mapping_state,
    newState: next === null ? "UNMAPPED" : "MAPPED",
    source: "REVIEWER_OVERRIDE",
    updatedAt: new Date().toISOString(),
    reason:
      next === null
        ? "Reviewer left the field intentionally unmapped."
        : `Reviewer override of automatic ${decision.mapping_state}.`,
  };
}

/** Timestamp concepts the actor-column guard applies to (mirrors backend). */
export const TIMESTAMP_CONCEPTS: ReadonlySet<string> = new Set([
  "RESOLUTION_TIME",
  "EVENT_TIMESTAMP",
  "TRIGGERED_AT",
  "ACKNOWLEDGED_AT",
  "CLOSED_AT",
  "WORKFLOW_EVENT_AT",
]);

/** Source datatypes the profiler emits. */
function sourceKind(category: string): string {
  const lowered = (category ?? "").toLowerCase();

  if (lowered.includes("datetime") || lowered.includes("timestamp")) {
    return "timestamp";
  }

  if (lowered === "numeric") {
    return "numeric";
  }

  if (lowered === "boolean") {
    return "boolean";
  }

  return "other";
}

function contractDatatype(
  concept: string,
  contract: Record<string, CanonicalContractEntry>,
): string {
  return (contract[concept]?.datatype ?? "").toLowerCase();
}

/**
 * Whether a concept is structurally compatible with a source column.
 *
 * Compatibility is advisory, never an absolute rule: a candidate the
 * backend ranked stays selectable even when datatypes differ, because a
 * string field can carry a numeric semantic. Only two hard blocks exist:
 * unknown concepts (not in the transported registry) and the
 * actor-to-timestamp guard. Everything else is ranked, not removed, except
 * concepts the contract declares with a strongly incompatible datatype
 * that the backend never ranked for this field.
 */
export function isCompatible(
  concept: string,
  sourceCategory: string,
  contract: Record<string, CanonicalContractEntry>,
  ranked: boolean,
): boolean {
  if (!(concept in contract)) {
    return false;
  }

  if (ranked) {
    return true;
  }

  const kind = sourceKind(sourceCategory);
  const datatype = contractDatatype(concept, contract);

  if (kind === "timestamp" && datatype !== "" && datatype !== "timestamp") {
    return false;
  }

  if (kind === "boolean" && datatype !== "" && datatype !== "boolean" && datatype !== "categorical" && datatype !== "text") {
    return false;
  }

  return true;
}

/** Actor-like source columns name a person, never an instant. */
export function guardBlocks(sourceField: string, concept: string): string | null {
  if (
    TIMESTAMP_CONCEPTS.has(concept) &&
    sourceField.toLowerCase().endsWith("_by")
  ) {
    return (
      `Actor-like field '${sourceField}' cannot map to timestamp ` +
      `concept '${concept}'. Left unmapped rather than mis-mapped.`
    );
  }

  return null;
}

export interface RankedOption {
  concept: string;
  confidence: number | null;
  group: "recommended" | "compatible";
  explanations: string[];
}

function explanationsFor(
  candidate: CanonicalCandidate,
  sourceField: string,
  sourceCategory: string,
  contract: Record<string, CanonicalContractEntry>,
  isTop: boolean,
): string[] {
  const out: string[] = [];
  const entry = contract[candidate.concept];

  if (!entry) {
    return out;
  }

  const kind = sourceKind(sourceCategory);
  const datatype = (entry.datatype ?? "").toLowerCase();

  if (
    (kind === "timestamp" && datatype === "timestamp") ||
    (kind === "numeric" && (datatype === "numeric" || datatype === "categorical")) ||
    (kind === "boolean" && (datatype === "boolean" || datatype === "categorical"))
  ) {
    out.push("datatype compatible");
  } else if (datatype !== "") {
    out.push(`contract datatype ${entry.datatype}`);
  }

  if (isTop) {
    out.push(`automatic candidate ${candidate.confidence.toFixed(2)}`);
  } else {
    out.push(`candidate ${candidate.confidence.toFixed(2)}`);
  }

  const lowered = sourceField.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const conceptTokens = candidate.concept.toLowerCase().split("_");

  if (lowered.length > 0 && conceptTokens.some((token) => lowered.includes(token))) {
    out.push("source field name match");
  }

  if (entry.category) {
    out.push(`${entry.category.toLowerCase()} concept`);
  }

  return out;
}

/**
 * Ranked dropdown options for one source field.
 *
 * RECOMMENDED = strongest valid automatic candidate(s): the backend's
 * best-first candidate that survives the guard. OTHER COMPATIBLE = the
 * remaining ranked candidates that survive the guard, plus contract
 * concepts sharing the winner's canonical datatype family when the
 * backend ranked nothing else. UNMAPPED is always handled by the caller.
 */
export function rankedOptions(
  decision: CanonicalMappingDecision,
  sourceCategory: string,
  contract: Record<string, CanonicalContractEntry>,
): RankedOption[] {
  const candidates = [...(decision.candidate_mappings ?? [])].sort(
    (a, b) => b.confidence - a.confidence,
  );

  const valid = candidates.filter(
    (candidate) =>
      candidate.concept in contract &&
      guardBlocks(decision.source_field, candidate.concept) === null,
  );

  const options: RankedOption[] = valid.map((candidate, index) => ({
    concept: candidate.concept,
    confidence: candidate.confidence,
    group: index === 0 ? "recommended" : "compatible",
    explanations: explanationsFor(
      candidate,
      decision.source_field,
      sourceCategory,
      contract,
      index === 0,
    ),
  }));

  if (options.length === 0) {
    return fallbackOptions(decision, contract);
  }

  // Widen with same-datatype contract concepts only when the backend
  // ranked a single candidate: the reviewer still sees genuine
  // alternatives without facing all ~50 concepts.
  if (valid.length === 1) {
    const winnerDatatype = contractDatatype(valid[0].concept, contract);
    const seen = new Set(valid.map((item) => item.concept));

    if (winnerDatatype !== "") {
      for (const [name, entry] of Object.entries(contract)) {
        if (seen.has(name)) {
          continue;
        }

        if ((entry.datatype ?? "").toLowerCase() !== winnerDatatype) {
          continue;
        }

        if (guardBlocks(decision.source_field, name) !== null) {
          continue;
        }

        if (!isCompatible(name, sourceCategory, contract, false)) {
          continue;
        }

        options.push({
          concept: name,
          confidence: null,
          group: "compatible",
          explanations: [
            `contract datatype ${entry.datatype}`,
            "not ranked for this field",
          ],
        });

        if (options.length >= 8) {
          break;
        }
      }
    }
  }

  return options;
}

/** Actor-like sources name a person: suggest identifier concepts first. */
const ACTOR_FALLBACK_ORDER = [
  "ANALYST_ID",
  "WORKFLOW_ACTOR",
  "USER_IDENTIFIER",
];

function fallbackOptions(
  decision: CanonicalMappingDecision,
  contract: Record<string, CanonicalContractEntry>,
): RankedOption[] {
  const out: RankedOption[] = [];
  const seen = new Set<string>();
  const push = (concept: string, explanations: string[]) => {
    if (seen.has(concept) || !(concept in contract)) {
      return;
    }

    if (guardBlocks(decision.source_field, concept) !== null) {
      return;
    }

    seen.add(concept);
    out.push({ concept, confidence: null, group: "compatible", explanations });
  };

  // The guard's inverse: a field rejected as a timestamp is most likely
  // an actor. Offer identifier concepts so the §13 correction flow
  // (resolved_by → ANALYST_ID) is possible without free text.
  if (decision.source_field.toLowerCase().endsWith("_by")) {
    for (const concept of ACTOR_FALLBACK_ORDER) {
      push(concept, ["actor-like field; identifier concept", "not ranked for this field"]);
    }

    for (const [name, entry] of Object.entries(contract)) {
      if (out.length >= 8) {
        break;
      }

      if ((entry.datatype ?? "").toLowerCase() === "identifier") {
        push(name, ["identifier concept", "not ranked for this field"]);
      }
    }

    return out;
  }

  // Otherwise fall back to alias/name token overlap with the registry.
  const tokens = new Set(
    decision.source_field.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean),
  );

  const scored: Array<{ name: string; score: number }> = [];

  for (const name of Object.keys(contract)) {
    if (guardBlocks(decision.source_field, name) !== null) {
      continue;
    }

    const nameTokens = name.toLowerCase().split("_");
    const score = nameTokens.filter((token) => tokens.has(token)).length;

    if (score > 0) {
      scored.push({ name, score });
    }
  }

  scored
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
    .slice(0, 8)
    .forEach(({ name }) =>
      push(name, ["source field name match", "not ranked for this field"]),
    );

  return out;
}

export interface OverrideCheck {
  ok: boolean;
  reason: string | null;
}

/**
 * Validate a reviewer override without bypassing canonical safety rules.
 *
 * Blocks: unknown concepts, the actor-to-timestamp guard, concepts with
 * no canonical_path, and collisions where another field already holds
 * the same canonical_path via automatic mapping or another override.
 */
export function validateOverride(
  sourceField: string,
  concept: string | null,
  decisions: CanonicalMappingDecision[],
  overrides: Record<string, string | null>,
  contract: Record<string, CanonicalContractEntry>,
): OverrideCheck {
  if (concept === null || concept === UNMAPPED) {
    return { ok: true, reason: null };
  }

  const entry = contract[concept];

  if (!entry) {
    return { ok: false, reason: `'${concept}' is not a known canonical concept.` };
  }

  const guard = guardBlocks(sourceField, concept);

  if (guard) {
    return { ok: false, reason: guard };
  }

  if (!entry.canonical_path) {
    return {
      ok: false,
      reason: `'${concept}' has no canonical_path, so there is nowhere to write it.`,
    };
  }

  const path = entry.canonical_path;

  for (const decision of decisions) {
    if (decision.source_field === sourceField) {
      continue;
    }

    const override = overrides[decision.source_field];
    const effectiveConcept =
      override !== undefined ? override : decision.canonical_concept;
    const effectiveApplied =
      override !== undefined && override !== null
        ? true
        : decision.applied;

    if (!effectiveApplied || !effectiveConcept) {
      continue;
    }

    const otherPath = contract[effectiveConcept]?.canonical_path;

    if (otherPath !== undefined && otherPath === path) {
      return {
        ok: false,
        reason:
          `Collision on '${path}': '${decision.source_field}' already ` +
          `claims it. Resolve the existing claim first rather than ` +
          `silently overwriting it.`,
      };
    }
  }

  return { ok: true, reason: null };
}

/** Fields needing review: low-confidence, ambiguous, invalid, unmapped. */
export function needsAttention(state: string): boolean {
  return (
    state === "LOW_CONFIDENCE" ||
    state === "AMBIGUOUS" ||
    state === "INVALID" ||
    state === "UNMAPPED"
  );
}
