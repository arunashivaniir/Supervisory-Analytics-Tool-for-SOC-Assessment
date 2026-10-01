# SAT-SA v4 — Current Baseline (preserved)

Date: 2026-09-28. This document records what existed before the controlled
MVP UI refinement. Nothing listed here was removed.

## Pipeline (`framework/`)

- Ingestion: CSV/structured loaders, dataset profiling, schema validation.
- Entity / period / scope resolution (`framework/assessment`).
- Canonical mapping with confidence bands (`framework/mapping`,
  `framework/canonical`); per-run `mapping_report` (high/medium/low,
  unmapped columns, overall confidence).
- Capability assessment: AVAILABLE / INSUFFICIENT_EVIDENCE / NOT_ASSESSED
  with evidence detail and traceability.
- Signal layers: execution-gap detection, negative-space detection,
  operational-pattern detection, offline anomaly layer (Isolation Forest,
  verdicts are distances, never severities).
- Evidence integrity: SHA-256 register, preserved original vs controlled
  working copy, analysis gating (`framework/evidence`,
  `backend/evidence_store.py`).
- Exports: aggregate (`export.json`) and full (`export-full.json`) per run.

## Adapter (`backend/`)

- `GET /api/health`, `GET /api/datasets`, `POST /api/analyses`,
  `GET /api/analyses`, `GET /api/analyses/{id}` (+ 2 export routes),
  `GET /api/evidence`, `GET /api/evidence/{id}`,
  `POST /api/evidence/{id}/verify`.
- Path containment on dataset resolution; evidence gate refuses tampered
  submissions with 409 instead of analysing them.
- Serves the built React bundle; SPA fallback for deep links.

## Frontend (`frontend/src`)

- 5 screens + detail: Overview, Assessments, AssessmentDetail (`:id`),
  Findings (drawer detail), Evidence (integrity panel + capability states),
  Reports (printable record, JSON exports, run history).
- Shared analysis state with pending-run promotion; no invented scores.
- Honesty vocabulary: "Not available", "Not evaluated", unresolved
  entity/period stated with reasons; zero shown as 0, never as a dash.

## Other surfaces (intact, not MVP focus)

- Streamlit dashboard (`dashboard/`), dataset generator
  (`dataset-generator/`), `validation/`, `schemas/`, `configs/`.

## Baseline verification (pre-change)

- `pytest backend framework`: **822 passed**.
- `tsc -b`: clean. `vite build`: clean.
