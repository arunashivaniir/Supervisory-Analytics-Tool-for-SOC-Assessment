"""Packaged-build verification for SAT-SA (Batch packaging).

Usage:  python3 packaging/verify.py /path/to/executable [--port 8191]
        python3 packaging/verify.py /path/to/executable --browser-only --port 8191

Spins the executable up in an isolated directory (no source tree, no
project environment), then checks the ten jury-demo requirements:

 1. launch succeeds            5. dataset discovery/loading
 2. backend starts              6. Step 2 preview
 3. frontend loads              7. no internet required (see note)
 4. /assessments/new works      8. no missing deps / broken paths
                                9. canonical mapping + roles + validation render
                               10. clean exit

Browser checks need Chromium at /usr/bin/chromium (or CHROMIUM env).
Network note: full radio-off isolation needs `unshare -rn`, which needs
privileges this script may not have. The offline property itself is
established by construction (relative /api base, vendored bundle, no
external URLs anywhere in the served frontend) plus a runtime check
that every URL the page requests stays on 127.0.0.1.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

EXE = sys.argv[sys.argv.index(__file__) + 1] if __file__ in sys.argv else None


def get(url: str, timeout: int = 30):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read()


def post(url: str, payload: dict, timeout: int = 120):
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read())


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    browser_only = "--browser-only" in sys.argv
    port = 8191

    for index, token in enumerate(sys.argv):
        if token == "--port" and index + 1 < len(sys.argv):
            port = int(sys.argv[index + 1])

    if not args:
        print("usage: verify.py /path/to/executable [--port N] [--browser-only]")
        return 2

    exe = os.path.abspath(args[0])
    base = f"http://127.0.0.1:{port}"
    failures = []

    def check(condition: bool, message: str) -> None:
        print(("  ok   " if condition else "  FAIL ") + message)

        if not condition:
            failures.append(message)

    workdir = tempfile.mkdtemp(prefix="satsa-verify-")
    target = os.path.join(workdir, os.path.basename(exe))
    shutil.copyfile(exe, target)
    os.chmod(target, 0o755)

    env = dict(os.environ, HOME=workdir)
    proc = subprocess.Popen(
        [target, "--no-browser", "--port", str(port)],
        cwd=workdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        # 1-2. Launch + backend readiness.
        ready = False

        for _ in range(120):
            try:
                status, body = get(f"{base}/api/health", timeout=2)

                if status == 200 and json.loads(body)["status"] == "ok":
                    ready = True
                    break
            except (urllib.error.URLError, OSError):
                pass

            if proc.poll() is not None:
                break

            time.sleep(1)

        check(ready and proc.poll() is None, "launch succeeds, backend starts")

        # 3. Frontend bundle served from the executable.
        status, body = get(f"{base}/")
        check(status == 200 and b'id="root"' in body, "frontend loads")
        check(b"/assets/" in body, "bundled assets referenced")

        # 5. Dataset discovery (starter data seeded beside the exe).
        status, body = get(f"{base}/api/datasets")
        datasets = json.loads(body)["datasets"]
        names = [item["path"] for item in datasets]
        check(
            any("dataset_noisy.csv" in name for name in names),
            f"starter datasets discovered ({len(datasets)} files)",
        )

        # 8. Preview endpoint reachable (import surface intact).
        first = names[0]
        status, preview = post(f"{base}/api/previews", {"datasets": [first]})
        entry = (preview.get("previews") or [{}])[0]
        check(status == 200 and "error" not in entry, "preview endpoint works")
        check(
            entry.get("record_count", 0) > 0
            and entry.get("detected_role", {}).get("role") in (
                "ALERTS", "CASES", "WORKFLOW_EVENTS", "ASSETS", "UNKNOWN",
            ),
            "preview carries count, role, decisions",
        )
        check(
            bool(entry.get("mapping_decisions"))
            and bool(entry.get("canonical_contract")),
            "canonical mapping + registry transported",
        )

        # Full single-dataset analysis still works end to end.
        status, started = post(f"{base}/api/analyses", {"dataset": first})
        job = started.get("job_id")
        check(status == 200 and bool(job), "analysis starts")
        done = False

        for _ in range(240):
            status, state = get(f"{base}/api/analyses/{job}")
            current = json.loads(state).get("status")

            if current == "complete":
                done = True
                break

            if current == "error":
                break

            time.sleep(2)

        check(done, "analysis completes")

        # 4/6/9. Browser: wizard, preview, mapping, roles, validation.
        if os.environ.get("SKIP_BROWSER") != "1":
            try:
                from verify_browser import run_browser_checks  # type: ignore

                for ok, message in run_browser_checks(base):
                    check(ok, message)
            except ImportError:
                check(False, "verify_browser helper missing (repo only)")
        else:
            print("  skip  browser checks (SKIP_BROWSER=1)")
    finally:
        # 10. Clean exit on SIGINT, like Ctrl-C at a terminal.
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)

            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                failures.append("clean exit (had to SIGKILL)")

        output, _ = proc.communicate()
        check(proc.returncode in (0, -2), "application exits cleanly")
        shutil.rmtree(workdir, ignore_errors=True)

    print("PACKAGING_VERIFY_PASS" if not failures else f"PACKAGING_VERIFY_FAIL: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
