# SAT-SA — Local Changelog (LOCAL ONLY, DO NOT PUSH)

All entries are local. No commit in this file's history has been or will be
pushed; there are no PRs, releases, or remote branches associated with it.

## 2026-09-28 — PHASE 1: Canonical contract + Pipeline 1/2 (complete)

- Added `framework/canonical/` contract, decisions, normalize, validate,
  roles, relationships, package modules (see status doc for details).
- Extended schema/mappings/patterns additively (50 concepts total);
  only THREAT_CATEGORY negatives changed (documented).
- Wired package build into `SATSAPipeline.run` as new `canonical_package`
  result key; transported via `backend/jobs.py` (+1 key, exports intact).
- `map_record` accepts schema decisions (AMBIGUOUS/INVALID blocked),
  reads records case-insensitively, extended `*_by` actor guard.
- Added `framework/tests/test_canonical_phase1.py` (56 tests, A–O).
- Updated 2 pinned tests with documented reasons (key count 16→17;
  noisy mapping set +2 genuine recalls).
- Found and fixed 5 regressions during development (theft, guard bypass,
  ties, shadowing bug) — all covered by tests.
- Verified: 878 passed; tsc/oxlint/build clean; API smoke pass;
  pre-existing MVP frontend work preserved untouched.
- Modified (UI): NONE. New dependencies: NONE. Pushed: NOTHING.
- Next: await approval → Phase 2 (scalable ingestion).

## 2026-09-28 — PHASE 0: Baseline / inspection (complete)

- Inspected: repo structure, git state (branch `satsa-mvp-improvement`,
  uncommitted MVP-refinement work preserved), pipeline orchestration,
  ingestion, profiling, semantic inference, schema mapping, canonical
  schema, ontology, features, all four signal engines + anomaly,
  entity aggregation, attention/risk scorers, jobs/transport, API routes,
  frontend routes/components/selectors, upload/selection behaviour,
  both frontend check scripts.
- Ran: `pytest backend framework` → 822 passed; `tsc -b` clean;
  `oxlint` 0 errors; `vite build` clean; API smoke (health, datasets
  listing = 48 files, one analysis run → complete in ~0.9 s, 404 on
  unknown dataset).
- Identified 7 top scalability bottlenecks with file:line evidence
  (see LOCAL_IMPLEMENTATION_STATUS.md).
- Identified missing canonical coverage: no case/workflow/acknowledgement/
  closure/escalation-level fields; ambiguity handling weak
  (winner-take-all, silent collisions).
- Confirmed: entity attention output computed but never rendered;
  browser payload bounded only by key exclusion; check scripts pin nav
  order and screen text.
- Created: `docs/LOCAL_IMPLEMENTATION_STATUS.md` (this tracking pair).
- Modified (code): NONE. This phase made zero source changes.
- Next: await approval → Phase 1 (canonical contract + Pipeline 1/2).

## 2026-09-28 — PHASE 1: Canonical contract + Pipeline 1/2 (complete)

- Added `framework/canonical/` contract, decisions, normalize, validate,
  roles, relationships, package modules (see status doc for details).
- Extended schema/mappings/patterns additively (50 concepts total);
  only THREAT_CATEGORY negatives changed (documented).
- Wired package build into `SATSAPipeline.run` as new `canonical_package`
  result key; transported via `backend/jobs.py` (+1 key, exports intact).
- `map_record` accepts schema decisions (AMBIGUOUS/INVALID blocked),
  reads records case-insensitively, extended `*_by` actor guard.
- Added `framework/tests/test_canonical_phase1.py` (56 tests, A–O).
- Updated 2 pinned tests with documented reasons (key count 16→17;
  noisy mapping set +2 genuine recalls).
- Found and fixed 5 regressions during development (theft, guard bypass,
  ties, shadowing bug) — all covered by tests.
- Verified: 878 passed; tsc/oxlint/build clean; API smoke pass;
  pre-existing MVP frontend work preserved untouched.
- Modified (UI): NONE. New dependencies: NONE. Pushed: NOTHING.
- Next: await approval → Phase 2 (scalable ingestion).

## 2026-09-29 — PHASE 2: Scalable ingestion foundation (complete)

- Added scan layer (`ingestion/scan.py`), scan profiler, path selector,
  scale fixture generator (100K/1M/5M, gitignored), benchmark harness,
  `test_phase2.py` (28 tests A–M).
- SQL joins/validation over scans (no Python ID sets); single-column
  inventory queries + 512MB pool + spill keep memory pool-dominated.
- Pipeline runs large path pre-load with DEFERRED analytic markers;
  small path byte-identical (all 878 prior tests green untouched).
- Found and fixed 3 scale-data bugs (quoting column-shift,
  alerts_without_case set confusion, manifest counter) — all tested.
- Measured: small path fails 100K (binomial OverflowError — Phase 3
  target); large path manifest-exact at 100K/1M/5M (8 s / ~25 s / 90 s;
  313 MB / ~1 GB / 1.57 GB).
- Verified: 906 passed; tsc/oxlint/build clean; API smoke pass.
- Modified (UI): NONE. New dependencies: duckdb (embedded/offline).
  Pushed: NOTHING.
- Next: await approval → Phase 3 (scalable analytics).
