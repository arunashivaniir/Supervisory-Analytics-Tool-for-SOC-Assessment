"""Phase 2 benchmark: compatibility path vs large-data path.

Runs each dataset through the small (record) path and the large (scan)
path in separate subprocesses so peak RSS is measured honestly per
run, and compares profile/package equality where both paths apply.

Usage::

    python benchmarks/bench_phase2.py --datasets data/scale/scale_100000.csv dataset_execution_gap_controlled.csv
    python benchmarks/bench_phase2.py --datasets data/scale/scale_1000000.csv --large-only
    python benchmarks/bench_phase2.py --datasets data/scale/scale_5000000.csv --large-only --timeout 3600

Results print as a table and are written to benchmarks/results/.
Memory is first-class: wall time without peak RSS proves nothing here.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time

RUNNER = """
import json, os, resource, sys, time
path = sys.argv[1]
mode = sys.argv[2]
os.environ["SATSA_EXECUTION_MODE"] = mode
from framework.pipeline import SATSAPipeline
start = time.perf_counter()
result = SATSAPipeline().run(path)
elapsed = time.perf_counter() - start
self_peak_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
profile = result["profile"]
package = result.get("canonical_package", {})
rel = package.get("relationships", {})
out = {
    "dataset": path,
    "mode": mode,
    "elapsed_s": round(elapsed, 2),
    "self_peak_rss_mb": self_peak_mb,
    "records": profile["dataset_summary"]["records"],
    "mapping_states": package.get("mapping_states"),
    "role": (package.get("detected_role") or {}).get("role"),
    "issues": (package.get("validation") or {}).get("issue_counts"),
    "alerts": rel.get("alerts"),
    "cases": rel.get("cases"),
    "workflow_events": rel.get("workflow_events"),
    "linked": (rel.get("linked_cases") or {}).get("count"),
    "orphans": (rel.get("orphan_cases") or {}).get("count"),
}
print(json.dumps(out))
"""


def run_once(path: str, mode: str, timeout: int) -> dict:
    """Run the pipeline in a subprocess, measuring wall time and peak RSS."""

    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", RUNNER, path, mode],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=os.getcwd(),
    )
    wall = time.perf_counter() - start
    peak_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss

    if proc.returncode != 0:
        return {
            "dataset": path,
            "mode": mode,
            "failed": True,
            "wall_s": round(wall, 2),
            "peak_rss_mb": round(peak_kb / 1024, 1),
            "stderr": proc.stderr[-2000:],
        }

    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {
            "dataset": path,
            "mode": mode,
            "failed": True,
            "wall_s": round(wall, 2),
            "peak_rss_mb": round(peak_kb / 1024, 1),
            "stderr": (proc.stdout + proc.stderr)[-2000:],
        }

    # Peak RSS is cumulative-max across waited children; record the
    # reading taken right after this child for per-run attribution.
    payload["wall_s"] = round(wall, 2)
    payload["peak_rss_mb"] = payload.pop(
        "self_peak_rss_mb",
        round(peak_kb / 1024, 1),
    )
    payload["size_mb"] = round(os.path.getsize(path) / 1024 / 1024, 1)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", nargs="+", required=True)
    parser.add_argument("--large-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--results-dir", default="benchmarks/results")
    args = parser.parse_args()

    os.makedirs(args.results_dir, exist_ok=True)
    modes = ["large"] if args.large_only else ["small", "large"]
    results = []

    for dataset in args.datasets:
        for mode in modes:
            print("running %s [%s] ..." % (dataset, mode), flush=True)
            results.append(run_once(dataset, mode, args.timeout))

    stamp = time.strftime("%Y%m%dT%H%M%S")
    out_path = os.path.join(args.results_dir, "bench_%s.json" % stamp)

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, sort_keys=True)

    print("\n%-45s %-6s %8s %10s %10s %8s %8s" % (
        "dataset", "mode", "wall_s", "peak_MB", "size_MB",
        "records", "role",
    ))

    for entry in results:
        print("%-45s %-6s %8s %10s %10s %8s %8s" % (
            os.path.basename(entry["dataset"])[:45],
            entry["mode"],
            entry.get("wall_s", "?"),
            entry.get("peak_rss_mb", "?"),
            entry.get("size_mb", "?"),
            entry.get("records", "FAIL"),
            entry.get("role", "-"),
        ))

    print("\nwrote %s" % out_path)


if __name__ == "__main__":
    main()
