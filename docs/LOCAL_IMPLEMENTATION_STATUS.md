# SAT-SA — Local Implementation Status (LOCAL ONLY, DO NOT PUSH)

## Current phase

**PHASE 2 — Scalable ingestion + large-data execution foundation.
COMPLETE. STOPPED — awaiting approval before Phase 3. NOT PUSHED.**

## Phase 1 results (2026-09-28)
| Check | Result |
|---|---|
| `pytest backend framework` | **878 passed** (822 baseline + 56 new), 0 failed |
| `tsc -b` (frontend, untouched) | clean |
| `oxlint` | 0 errors |
| `vite build` | clean |
| API smoke (run → complete, `canonical_package` transported) | pass |
| Existing findings on controlled data (gaps 2, neg 1) | unchanged |

### Files added (7 new modules + 1 test file)

- `framework/canonical/contract.py` — 50 concepts (29 existing + 21
  new), mapping states, thresholds, role requirements.
- `framework/canonical/decisions.py` — schema-level decisions:
  MAPPED/LOW_CONFIDENCE/AMBIGUOUS/UNMAPPED/INVALID, margin rule (0.10),
  same-slot merge, collision demotion.
- `framework/canonical/normalize.py` — severity/escalation/disposition
  vocabularies (originals kept), timestamp parsing (naive = assumed UTC,
  flagged), chronology checks.
- `framework/canonical/validate.py` — structured issues
  {code, severity, entity, field, source, message}; error/warning/info
  policy documented in module.
- `framework/canonical/roles.py` — ALERTS/CASES/WORKFLOW_EVENTS/ASSETS/
  UNKNOWN detection + explicit-role respect.
- `framework/canonical/relationships.py` — set-based joins, capped
  samples with exact counts, assessability flags.
- `framework/canonical/package.py` — package builder + provenance.
- `framework/tests/test_canonical_phase1.py` — 56 tests, categories A–O.

### Files modified

- `canonical_schema.json` (+case/workflow sections, +alert/asset/
  monitoring fields; nothing removed), `mappings.json` (+21 concepts),
  `semantic_patterns.json` (+21 patterns; only THREAT_CATEGORY changed:
  asset/host/device/server negatives so `asset_type` resolves correctly).
- `semantic_inference.py` (+`infer_with_candidates`; `infer()` untouched),
  `schema_mapper.py` (optional decisions filter, case-insensitive record
  read, `*_by` actor guard for timestamp concepts; existing
  RESOLUTION_TIME rules intact), `pipeline.py` (+`canonical_package`
  key, decisions passed to projection), `backend/jobs.py`
  (+1 transported key).
- `test_anomaly_model.py` (key count 16→17, documented),
  `test_capability.py` (noisy set +ALERT_ID/+CLOSED_AT, documented).

### Regressions found and fixed during Phase 1

1. `analyst_findings` stolen by new ANALYST_ID (0.75 strict win) →
   added text negatives to ANALYST_ID; op-pattern counts restored.
2. `escalation_level` test: reverted ESCALATION_STATUS negatives;
   value patterns (L1/L2) discriminate level vs status instead.
3. `closed_by`→CLOSED_AT bypassed the actor guard → generalized guard
   to all timestamp concepts + schema-level INVALID via guard hook.
4. `asset_type` tied THREAT_CATEGORY/ASSET_TYPE → asset negatives on
  THREAT_CATEGORY.
5. Guard-filter shadowing bug in decisions.py (fixed, test covers).

### Known limitations (Phase 1)

- `semantic_mapping` (legacy list) still includes AMBIGUOUS entries;
  decisions are authoritative for application, legacy list frozen for
  compat. UI mapping section reads the legacy report (documented).
- Validation/relationships run over in-memory records (current scale);
  the API is shaped for a future chunked implementation (Phase 2).
- No review queue, no scoring changes, no frontend changes, no new
  dependencies.

## Baseline results (2026-09-28, branch `satsa-mvp-improvement`)

| Check | Result |
|---|---|
| `pytest backend framework` | **822 passed**, 0 failed, 0 skipped |
| `tsc -b` (frontend) | clean |
| `oxlint` (frontend) | 0 errors (warnings only, incl. pre-existing patterns) |
| `vite build` | clean (JS 444.79 kB / gzip 130.37 kB) |
| Runtime smoke (`POST /api/analyses` → complete, tiny fixture) | complete, ~0.9 s |
| API 404 on unknown dataset | correct 404 |

## Pre-existing uncommitted work (MUST PRESERVE)

Previous MVP UI refinement, uncommitted on this branch. Do not discard:

- Modified: AppShell, DatasetSwitcher, FindingDetail, Sidebar, TopBar,
  AssessmentDetail, Assessments, Evidence, Findings, Overview
- New: `frontend/src/app/reviews.ts`,
  `frontend/src/components/findings/ReviewControl.tsx`,
  `frontend/src/services/evidenceRegister.ts`
- New docs: `docs/current-baseline.md`, `docs/MVP_SCOPE.md`, `docs/UI_WORKFLOW.md`

## Architecture inventory (from Phase 0 inspection)

- Pipeline stages (`framework/pipeline.py:139-474`): load → profile →
  semantic inference → context → mapping report → scoping → 5 supervision
  layers → per-record canonicalization → per-record features →
  supervisory findings → entity assessment.
- Canonical vocab has `alert_context` but **no** `case_id` / workflow /
  acknowledgement / closure-disposition / escalation-level fields.
- Mapping is per-schema (good) but winner-take-all: no n-best, silent
  concept collisions, lowercased source columns, hard-coded guards.
- No timestamp normalization in canonicalization (verbatim copy);
  only `period.py` parses dates, for scope labels only.
- Browser payload bounded only by key exclusion (no pagination).
- Entity `attention_score`/`risk_level` computed but **never rendered**.
- Frontend check scripts assert exact nav
  `[Overview, Assessments, Findings, Evidence, Reports]` and screen text.

## Top bottlenecks (evidence in subagent reports, this phase)

1. Triple whole-file materialization (CSV→records→DataFrame→CSV→DataFrame).
2. `iterrows()+to_dict()` row loop (`ingestion/base_loader.py:271`).
3. Per-record `deepcopy` canonicalization + feature loops (`pipeline.py:322-354`).
4. Evidence index rebuilt 4–5× per scope (once per layer).
5. Execution-gap `evaluate()` called 2× per record (`execution_gap_engine.py:100,118`).
6. O(n²) pairwise Jaccard text similarity, computed twice
   (`operational_pattern_detector.py:833-843,871-881` + anomaly `feature_builder.py:898-908`).
7. O(E×F) entity aggregation scans (`supervision/entity_evaluator.py:33-42`).

## Scale candidate on disk

`data/demo/incident_event_log.csv` — 46 MB. Synthetic 100K/1M/5M sets
still to be generated (Phase 6).

## Known limitations / risks

- No browser (Chromium) in this container: puppeteer screen checks
  cannot run here; API-level regression used instead.
- Port 8000 occupied by unrelated service; local API testing uses 8123.
- `framework/validation/*` helpers are findings-comparison tools, not
  value normalization — do not mistake for canonical validation.
- Legacy severity scorers (`attention_scorer.py`, `supervisory/*`) are
  dormant parallels; new layers carry no severity by design.

## Checkpoint / rollback

- No commits made in Phase 0. Rollback = `git stash` / working tree as-is.
- Going forward: one local commit per completed phase (NEVER push).
- Remote `origin` untouched; nothing pushed, no PRs, no branches created.

## Phase 2 results (2026-09-29)

| Check | Result |
|---|---|
| `pytest backend framework` | **906 passed** (878 + 28 new), 0 failed |
| `tsc -b` (frontend untouched) | clean |
| `oxlint` | 0 errors |
| `vite build` | clean |
| API smoke (health, 404, run, package, exports) | pass |
| 5M benchmark (large-only) | 90 s, 1.57 GB, manifest-exact |

### Files added

- `framework/ingestion/scan.py` — `DatasetScan` (DuckDB): schema,
  exact counts, samples, projection (capped 10K), filters, streaming
  `iter_rows`, distinct/duplicates/vocabularies, per-column inventory,
  top-N first-appearance samples; RFC-4180 quoting pinned; 512MB pool
  + disk spill; progress bar off.
- `framework/profiling/scan_profiler.py` — legacy-shape profiler over
  scans (equality-tested; numerics within 1 ulp, documented).
- `framework/ingestion/paths.py` — small/large selection (64MB
  default, `SATSA_EXECUTION_MODE`/`SATSA_LARGE_PATH_MB` overrides;
  JSON documents always small).
- `framework/tests/scale/make_fixtures.py` — seeded Pipeline 1/2
  fixtures + ground-truth manifests (100K/1M/5M in `data/scale/`,
  gitignored).
- `benchmarks/bench_phase2.py` — subprocess wall + self-peak-RSS
  comparison harness (results gitignored).
- `framework/tests/test_phase2.py` — 28 tests, categories A–M
  (5M benchmark-only, never in suite).

### Files modified

- `framework/canonical/relationships.py` — streaming core refactor +
  SQL `summarize_scan` (no Python ID sets); fixed real bug found by
  scale data: `alerts_without_case` compared alerts against case IDs
  (Phase-1 test asserted membership only — strengthened to exact).
- `framework/canonical/validate.py` — `validate_scan` (SQL counts,
  bounded vocabularies, streaming chronology).
- `framework/canonical/package.py` — `build_canonical_package_scan`.
- `framework/pipeline.py` — pre-load path selection + `_run_large_scan`
  (profile/mapping/package complete; analytic sections DEFERRED with
  reason, never faked).
- `requirements.txt` (+duckdb floor), `.gitignore` (+scale/benchmark
  outputs), `semantic_patterns.json` (ASSET_TYPE/SOURCE_SYSTEM accept
  identifier_like category — profiler names them so).

### Bugs found by scale data (fixed, tested)

1. DuckDB sniffer disabled `"` quoting → silent column shift on
   quoted commas. Pinned `quote='"'` + regression test comparing
   against the csv module.
2. `alerts_without_case` set confusion (above).
3. Generator manifest `orphan_cases` counter never incremented.

### Key measurement (see LOCAL_BENCHMARKS.md)

Small path fails 100K rows (`OverflowError` in binomial tail) —
Phase 3 mandate, measured. Large path: 100K in 8 s / 313 MB,
1M in ~25 s / ~1 GB, 5M in 90 s / 1.57 GB, all manifest-exact.
Memory is pool-dominated (sub-linear in rows).

### Known limitations

- Large-path analytic sections DEFERRED (Phase 3 owns engines).
- JSON-array documents stay on small path (documented).
- `semantic_mapping` legacy list still authoritative-looking;
  decisions govern application (Phase 1 limitation, unchanged).
- No frontend changes. No new result keys. One new runtime
  dependency (duckdb, embedded/offline).
