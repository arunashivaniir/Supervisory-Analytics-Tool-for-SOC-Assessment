# SAT-SA UI Workflow

A supervisory evidence-review interface for the stated assessment
workflow. It does not reproduce any official internal system; it makes
the workflow obvious:

```
Overview → Assessment/CSE → Finding → Source Record → Examiner Review
```

## The journey

1. **New assessment** (sidebar) → Select file → Validate (file facts) →
   Mapping (what mapping means here) → Confirm → Run. The loaded
   assessment stays on screen until the new run completes; a failed run
   never blanks the screen.
2. **Overview** answers: what was submitted (dataset, records, scopes),
   what was analysed (status, last run, hash, integrity), what needs
   attention ("Review these first", most signals first — a sort, not a
   score), and why (primary signal family + reason one click away).
3. **Assessments** is the CSE directory: search, entity/period filters,
   evidence posture, signal counts, primary signal, Review action.
4. **AssessmentDetail**: identity → Review first (records to open) →
   capability evidence → signals by family → anomaly intelligence.
5. **Findings**: one dense list across all four families; filter by
   family, entity, period, review status, text. A row opens a drawer so
   filters and position survive.
6. **Finding detail**: why flagged (verbatim) → rule/basis → observed
   evidence → expected/baseline → evidence concepts → source record →
   examiner review.
7. **Source record**: the pipeline's `record_reference` as stated
   (identifiers, timestamps first). Full per-record payload lives in the
   run's full export, not the browser.
8. **Examiner review**: verdict + note, stored per run in the browser,
   separate from evidence. Original submission immutable.
9. **Evidence**: integrity register (SHA-256, original vs working copy,
   permitted/blocked, verify action) → canonical mapping → capability
   evidence → scope counts.
10. **Reports** (under Records): printable record + aggregate/full
    exports + run history. No grading, scoring, or ranking.

## Reading rules (enforced by the UI)

- Absence of findings ≠ security. Zero-signal scopes stay listed.
- Evidence states ≠ risk ratings. Insufficient evidence is not failure.
- Anomaly verdicts ≠ severities. Distances from a reference population.
- Unmapped ≠ wrong. Ambiguous fields stay unmapped; mapping is audited
  on the Evidence screen.
- Reviews ≠ evidence. Examiner metadata never touches the submission.
