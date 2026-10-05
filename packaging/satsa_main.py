"""Standalone entry point for packaged SAT-SA builds (jury demo).

Runnable from source (behaves like ``launcher.py`` adapter mode) and frozen
by PyInstaller into a single file. In frozen mode:

* bundled resources (frontend build, framework configs) are read from the
  bundle directory,
* the working directory moves there so the pipeline's relative config
  paths resolve,
* ``SATSA_DATA_ROOT`` defaults to the directory beside the executable,
  where starter datasets are seeded on first launch and user files live,
* the adapter serves the UI on a free localhost port, the browser opens
  once the backend answers, and Ctrl-C (or closing the window) exits.

No product behaviour changes: this only starts processes/threads, waits
for readiness and opens a browser.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

FIRST_PORT = 8000
LAST_PORT = 8010
READY_TIMEOUT = 60

# Real repository fixtures shipped as starter data (copies, never the
# originals). Seeded beside the executable on first launch so the demo
# opens with discoverable datasets; user files go next to them.
STARTER_DATASETS = (
    "dataset_noisy.csv",
    "dataset_multi_cse.csv",
    "dataset_execution_gap_controlled.csv",
)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_dir() -> str:
    meipass = getattr(sys, "_MEIPASS", None)

    if meipass:
        return os.path.abspath(meipass)

    return os.path.dirname(os.path.abspath(__file__))


def data_dir() -> str:
    override = os.environ.get("SATSA_DATA_ROOT")

    if override:
        return os.path.abspath(override)

    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))

    here = os.path.abspath(__file__)

    return os.path.dirname(os.path.dirname(here))


def seed_starter_data(target: str) -> None:
    """Copy bundled starter CSVs beside the executable on first launch."""

    destination = os.path.join(target, "data")

    try:
        os.makedirs(destination, exist_ok=True)
    except OSError as error:
        print(f"[!] Cannot create data directory {destination}: {error}")
        return

    bundle = bundle_dir()

    for name in STARTER_DATASETS:
        final = os.path.join(destination, name)

        if os.path.isfile(final):
            continue

        for candidate in (
            os.path.join(bundle, "packaging", "starter-data", name),
            os.path.join(bundle, "starter-data", name),
        ):
            if os.path.isfile(candidate):
                try:
                    shutil.copyfile(candidate, final)
                    print(f"[+] Starter dataset: data/{name}")
                except OSError as error:
                    print(f"[!] Cannot seed {name}: {error}")

                break


def pick_port() -> int:
    for port in range(FIRST_PORT, LAST_PORT + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)

            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port

    raise RuntimeError("No free localhost port in 8000-8010.")


def wait_for(url: str, seconds: int = READY_TIMEOUT) -> bool:
    deadline = time.time() + seconds

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)

    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Serve without opening a browser (verification mode).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Fixed localhost port instead of the first free one.",
    )
    args = parser.parse_args(argv)

    root = data_dir()

    try:
        os.makedirs(root, exist_ok=True)
    except OSError as error:
        print(f"[!] Cannot use data directory {root}: {error}")
        return 1

    os.environ["SATSA_DATA_ROOT"] = root

    if is_frozen():
        # Bundled framework configs are addressed by relative path.
        os.chdir(bundle_dir())
        seed_starter_data(root)
    else:
        # Running from source: make the project root importable no
        # matter where the interpreter was started from.
        project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        if project not in sys.path:
            sys.path.insert(0, project)

    # Imported after the environment is final: evidence paths and the
    # frontend bundle location are computed at import time.
    import uvicorn

    from backend.app import app

    port = args.port or pick_port()
    url = f"http://127.0.0.1:{port}"
    print(f"[+] SAT-SA data directory: {root}")
    print(f"[+] Starting the local service on port {port}")

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(
        target=server.run, name="satsa-adapter", daemon=True
    )
    thread.start()

    if not wait_for(f"{url}/api/health"):
        print("[!] The backend did not become ready; exiting.")
        server.should_exit = True
        return 1

    print(f"[+] SAT-SA is running: {url}")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception as error:  # noqa: BLE001 - browser is best-effort
            print(f"[!] Could not open a browser ({error}); use {url}")

    print("[i] Press Ctrl-C to stop.")

    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n[+] Stopping.")

    server.should_exit = True
    thread.join(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
