# SAT-SA — Local Benchmarks, Phase 2 (LOCAL ONLY, DO NOT PUSH)

Machine: container, 12G tmpfs, 232G disk free. DuckDB 1.5.6, pool
capped at 512MB (`SATSA_DUCKDB_MEMORY`), disk spill enabled.
Method: `benchmarks/bench_phase2.py` runs each dataset in a fresh
subprocess; wall time is wall-clock, peak RSS is the child's own
high-water mark (interpreter + libraries included, ~150MB baseline).

Raw JSON: `benchmarks/results/` (gitignored).

## Results

| dataset | size | rows | mode | wall | peak RSS | outcome |
|---|---|---|---|---|---|---|
| execution_gap_controlled | 1 KB | 8 | small | 1.6 s | 171 MB | complete, gaps 2 / neg 1 |
| execution_gap_controlled | 1 KB | 8 | large | 1.6 s | 230 MB | same package, DEFERRED analytics |
| scale_100000 | 10.8 MB | 100,100 | small | 16 s | 412 MB | **FAILS**: `OverflowError` in `_binomial_upper_tail` (math.comb on n=100K) |
| scale_100000 | 10.8 MB | 100,100 | large | 8.1 s | 313 MB | complete package, manifest-exact |
| scale_1000000 | 108 MB | 1,001,000 | large | 22–30 s | ~1.0 GB | complete package, manifest-exact |
| scale_5000000 | 541 MB | 5,005,000 | large | 90 s | 1.57 GB | complete package, manifest-exact |

(1M variance 22–30 s across runs: page-cache warmth.)

## What the numbers say

- The small path cannot do 100K rows at all: it dies in the
  operational-pattern binomial tail (`math.comb` overflow at n=100K),
  before memory even becomes the question. Small-path full analytics
  are correct only at small scale — that is the Phase 3 mandate,
  measured, not assumed.
- The large path is slower than small on tiny files (engine load
  ~60MB, query planning) and faster where it matters; memory is
  pool-dominated (~flat 0.9–1.6GB from 100K to 5M rows, i.e.
  sub-linear in rows, bounded by entity cardinality for exact joins).
- No multi-GB claim: largest tested is 541MB / 5M rows. The 5M run is
  benchmark-only, never in the unit suite.
- Profile/package equality (scan vs records) holds exactly on
  execution_gap_controlled and dataset_noisy fixtures (test J).

## Stage costs (1M rows, large path)

Profile ~11 s, package ~9 s, semantic trivial. Profiler touches each
column with one narrow aggregation (single-column COUNT DISTINCT +
nulls) plus a top-10 first-appearance query; wide multi-column
DISTINCT was removed after it spiked transient state. Joins run as
SQL; Python holds only capped samples.
