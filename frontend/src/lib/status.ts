/**
 * Presentation-only status vocabulary.
 *
 * Everything in this file maps a status string the backend already produced
 * onto a colour and a label. It never combines statuses, ranks them, compares
 * counts, or decides that one value is "worse" than another.
 *
 * The muted palette is deliberate. Status colour is used only where the
 * backend has actually stated a status; a neutral surface is the correct
 * answer for anything the backend did not evaluate.
 */

export type Tone =
  | "neutral"
  | "info"
  | "positive"
  | "caution"
  | "critical";

export interface StatusPresentation {
  tone: Tone;
  label: string;
}

/**
 * Capability evidence states.
 *
 * These are evidence states. A capability with insufficient evidence is not a
 * failed control, and a capability that was not assessed is not a low-risk
 * one. The labels are worded to keep that distinction visible.
 */
const CAPABILITY_STATUS: Record<string, StatusPresentation> = {
  AVAILABLE: { tone: "positive", label: "Available" },
  INSUFFICIENT_EVIDENCE: { tone: "caution", label: "Insufficient evidence" },
  NOT_ASSESSED: { tone: "neutral", label: "Not assessed" },
};

/** Anomaly verdicts. Distances from a reference population, not severities. */
const ANOMALY_VERDICT: Record<string, StatusPresentation> = {
  POTENTIAL_OPERATIONAL_ANOMALY: { tone: "caution", label: "Potential anomaly" },
  NO_ANOMALY: { tone: "positive", label: "No anomaly" },
  NOT_EVALUABLE: { tone: "neutral", label: "Not evaluable" },
};

/**
 * Signal-family statuses. Each family uses its own vocabulary, so each is
 * listed separately rather than merged into a single severity scale. The
 * backend deliberately does not combine these families, and neither does the
 * interface.
 */
const SIGNAL_STATUS: Record<string, StatusPresentation> = {
  // execution gaps
  POTENTIAL_EXECUTION_GAP: { tone: "critical", label: "Potential execution gap" },
  // negative space
  PARTIAL_NEGATIVE_SPACE: { tone: "caution", label: "Partial absence" },
  COMPLETE_NEGATIVE_SPACE: { tone: "critical", label: "Observed absence" },
  EXPECTATION_NOT_TRIGGERED: { tone: "neutral", label: "Expectation not triggered" },
  // evaluation states that mean "this layer could not decide"
  NOT_EVALUABLE: { tone: "neutral", label: "Not evaluable" },
  // model availability
  AVAILABLE: { tone: "positive", label: "Available" },
  UNAVAILABLE: { tone: "neutral", label: "Unavailable" },
  NOT_TRAINED: { tone: "neutral", label: "Not trained" },
};

/**
 * Peer baseline statuses, as the benchmarking layer reports them.
 *
 * UNAVAILABLE and LIMITED are deliberately different colours. "No cohort"
 * and "a cohort too small to lean on" are different statements about the
 * evidence, and collapsing them would let a weak comparison read like a sound
 * one.
 */
const BASELINE_STATUS: Record<string, StatusPresentation> = {
  ROBUST: { tone: "positive", label: "Robust baseline" },
  LIMITED: { tone: "caution", label: "Limited baseline" },
  UNAVAILABLE: { tone: "neutral", label: "No baseline" },
};

/**
 * Descriptive deviation bands over the absolute modified Z-score.
 *
 * These are not severities. The band selects wording; it never created a
 * finding and the interface must not promote one into a severity.
 */
const DEVIATION_BAND: Record<string, StatusPresentation> = {
  WITHIN_COHORT_SPREAD: { tone: "neutral", label: "Within cohort spread" },
  NOTABLE: { tone: "info", label: "Notable deviation" },
  MATERIAL: { tone: "caution", label: "Material deviation" },
  NOT_EVALUABLE: { tone: "neutral", label: "Not evaluable" },
};

/** Statistical availability of a peer statistic. */
const STATISTICAL_STATUS: Record<string, StatusPresentation> = {
  COMPUTED: { tone: "neutral", label: "Computed" },
  NOT_COMPUTABLE: { tone: "neutral", label: "Not computable" },
};

const FALLBACK: StatusPresentation = { tone: "neutral", label: "" };

function lookup(
  table: Record<string, StatusPresentation>,
  value: string | null | undefined,
): StatusPresentation {
  if (value === null || value === undefined || value === "") {
    return FALLBACK;
  }

  return table[value] ?? { tone: "neutral", label: humanise(value) };
}

export function capabilityStatus(status: string | null | undefined): StatusPresentation {
  return lookup(CAPABILITY_STATUS, status);
}

export function anomalyVerdict(verdict: string | null | undefined): StatusPresentation {
  return lookup(ANOMALY_VERDICT, verdict);
}

export function signalStatus(status: string | null | undefined): StatusPresentation {
  return lookup(SIGNAL_STATUS, status);
}

export function baselineStatus(
  status: string | null | undefined,
): StatusPresentation {
  return lookup(BASELINE_STATUS, status);
}

export function deviationBand(
  status: string | null | undefined,
): StatusPresentation {
  return lookup(DEVIATION_BAND, status);
}

export function statisticalStatus(
  status: string | null | undefined,
): StatusPresentation {
  return lookup(STATISTICAL_STATUS, status);
}

/**
 * Evidence integrity states, as the evidence trust layer reports them.
 *
 * These are statements about a file, not about a control and not about risk.
 * ``INTEGRITY_FAILED`` means the digest observed now differs from the digest
 * recorded at registration, so the wording is kept factual rather than
 * accusatory. ``UNAVAILABLE`` means a comparison could not be performed, which
 * is deliberately not the same as ``VERIFIED``: a file that could not be checked
 * has not been shown to be intact.
 */
const INTEGRITY_STATUS: Record<string, StatusPresentation> = {
  VERIFIED: { tone: "positive", label: "Verified" },
  INTEGRITY_FAILED: { tone: "critical", label: "Digest mismatch" },
  MISSING: { tone: "critical", label: "Missing" },
  UNAVAILABLE: { tone: "neutral", label: "Not checked" },
};

export function integrityStatus(
  status: string | null | undefined,
): StatusPresentation {
  return lookup(INTEGRITY_STATUS, status);
}

/** Capability status counts, for the evidence posture distribution. */
export function capabilityCountTone(
  status: string,
  count: number,
): Tone | null {
  // Colour follows the backend's own state. A zero count of a state is not a
  // reason to show that state's colour, so it stays neutral rather than
  // implying a count that reads as a signal.
  if (count === 0) {
    return null;
  }

  return lookup(CAPABILITY_STATUS, status).tone;
}

/**
 * Turn an UPPER_SNAKE token the backend produced into a readable label.
 * Falls back to the backend's own string when it is already prose, so no
 * information is lost for a status this application has not seen.
 */
export function humanise(value: string): string {
  if (/^[A-Z0-9_]+$/.test(value)) {
    return value
      .toLowerCase()
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  return value;
}

/**
 * The four signal families, with the pipeline result key each one comes from.
 * This is a map from a UI label to a backend key, not a taxonomy of our own.
 */
export const SIGNAL_FAMILIES = [
  {
    id: "execution_gap",
    key: "execution_gap_findings",
    label: "Execution Gaps",
    singular: "Execution Gap",
    description:
      "Contradictions between an expected control and the evidence submitted for it.",
  },
  {
    id: "negative_space",
    key: "negative_space_findings",
    label: "Negative Space",
    singular: "Negative Space",
    description:
      "Observable absence of evidence that a configured expectation says should be present.",
  },
  {
    id: "operational_pattern",
    key: "operational_pattern_findings",
    label: "Operational Patterns",
    singular: "Operational Pattern",
    description:
      "The shape of activity within an assessment scope, judged against that scope's own population.",
  },
  {
    id: "anomaly",
    key: "anomaly_findings",
    label: "Anomalies",
    singular: "Anomaly",
    description:
      "How far a scope's operational feature profile sits from a reference population.",
  },
] as const;

export type SignalFamilyId = (typeof SIGNAL_FAMILIES)[number]["id"];

/**
 * A metric's direction, in the words the backend's declaration implies.
 *
 * This is what makes a percentile interpretable, and it is the reason no screen
 * can present a high number as bad on its own initiative. The backend declares
 * the direction per metric; this only gives the declaration words.
 */
export function directionLabel(direction: string): string {
  return direction === "higher_is_adverse"
    ? "Higher is the less favourable value"
    : "Higher is the more favourable value";
}
