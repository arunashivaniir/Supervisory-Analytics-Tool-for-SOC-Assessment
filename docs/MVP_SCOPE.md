# SAT-SA MVP Scope

The MVP narrows the *experience*, not the system. Rule: improve UX and
limit what is prominent; never delete working functionality to look small.

## IMPLEMENTED (v4 baseline, untouched)

Execution-gap / negative-space / operational-pattern / anomaly layers,
evidence-integrity register and analysis gating, canonical mapping,
dataset handling, aggregate + full exports, all APIs, all tests,
Streamlit dashboard, Reports screen.

## IMPLEMENTED (this refinement, frontend-only)

- Overview: run strip (status, last run, short data hash, integrity);
  "Review these first" deterministic table (position, entity, sector —
  stated unavailable when absent — records, signals, primary signal,
  evidence, action); zero-signal rows stay visible with "No supervisory
  signal identified in available evidence" (never "safe"/"low risk");
  "Signal summary"; "Evidence status" (register: verified / mismatch /
  blocked + capability states).
- Assessments: added Primary signal column (existing filters kept).
- AssessmentDetail: added "Review first" (≤5 findings with record
  references, gaps and negative space first).
- Findings: Review-status filter + Review column; drawer keeps detail and
  adds examiner review control.
- Finding detail: "Why was this flagged?" (backend reason verbatim) +
  "Source record" (`record_reference` as stated; missing reads
  "Not available in submission").
- Examiner review: Confirmed gap / False positive / Needs deeper review +
  note, in `localStorage` per run. Evidence never modified.
- Evidence screen: new "Canonical mapping" section (incoming field,
  canonical concept, confidence, band; unmapped listed, never guessed).
- Navigation: Overview / Assessments / Findings / Evidence + prominent
  New assessment action. Reports kept intact under "Records".
- New assessment dialog: Select → Validate (file facts + what the
  pipeline checks) → Mapping (mapping observed on loaded run) → Confirm
  → Run. No external ingestion.
- Top bar: dataset, last run, short hash, status. No filesystem exposure
  beyond the repository-relative dataset path already shown.

## PARTIAL (shown honestly, not completed)

- Sector: pipeline entities carry no sector; UI states "Not available in
  submission".
- Severity filter: pipeline reports no severity; deliberately not
  invented. Review-status filter added instead.
- Mapping preview/correction: shown as observed post-run output; manual
  correction needs backend working-mapping persistence.

## FUTURE (not built, not removed where existing)

Peer benchmarking, PDF reporting system, remediation tracker, national
command-centre views, new ML models, LLM/chat, live SIEM / STIX / feeds,
RBAC, enterprise workflow, complex trends, distributed infrastructure.

## Non-goals upheld

Offline (no remote URLs in `frontend/src`), no invented scores, no
"cyber command centre" aesthetic, aggregates first / record detail on
demand.
