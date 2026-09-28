"""Start the supervisory assessment tool locally.

The React interface is the primary surface. It is served by the local adapter
in ``backend/app.py``, which also serves the built interface when
``frontend/dist`` exists, so in normal use this starts one process and opens
one URL.

Three modes, chosen by flags rather than guessed:

    python launcher.py                 adapter only, with the built interface
    python launcher.py --dev           adapter plus the Vite dev server
    python launcher.py --streamlit     the original Streamlit dashboard

Nothing here decides anything about an assessment. The adapter runs the same
pipeline the dashboard runs; the launcher only starts processes and opens a
browser.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser

PROJECT = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(PROJECT, "frontend")
STREAMLIT_APP = os.path.join(PROJECT, "dashboard", "SAT-SA_Portal.py")

API_PORT = 8000
VITE_PORT = 5173
STREAMLIT_PORT = 8501
STREAMLIT_URL = f"http://127.0.0.1:{STREAMLIT_PORT}"


def _port_is_free(port: int) -> bool:
    """True when nothing is already listening on the port."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _wait_for(url: str, seconds: int = 30) -> bool:
    """Poll a URL until it answers, so the browser is not opened too early."""

    import urllib.error
    import urllib.request

    deadline = time.time() + seconds

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)

    return False


def start_adapter() -> subprocess.Popen | None:
    """Start the local adapter, which also serves the built interface."""

    if not _port_is_free(API_PORT):
        print(f"[!] Port {API_PORT} is already in use; leaving it alone")
        return None

    print(f"[+] Starting the local service on port {API_PORT}")

    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
        ],
        cwd=PROJECT,
    )


def start_dev_server() -> subprocess.Popen | None:
    """Start Vite alongside the adapter, for interface work in progress."""

    npm = "npm.cmd" if os.name == "nt" else "npm"

    if not _port_is_free(VITE_PORT):
        print(f"[!] Port {VITE_PORT} is already in use; leaving it alone")
        return None

    print(f"[+] Starting the interface development server on port {VITE_PORT}")

    return subprocess.Popen(
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(VITE_PORT)],
        cwd=FRONTEND,
    )


def start_streamlit() -> subprocess.Popen | None:
    """Start the original dashboard. Kept as a fallback, not removed."""

    if not _port_is_free(STREAMLIT_PORT):
        print(f"[!] Port {STREAMLIT_PORT} is already in use; leaving it alone")
        return None

    print("[+] Starting the Streamlit dashboard")

    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            STREAMLIT_APP,
            "--server.port",
            str(STREAMLIT_PORT),
            "--server.address",
            "127.0.0.1",
        ],
        cwd=PROJECT,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dev",
        action="store_true",
        help="start the interface development server as well as the service",
    )
    parser.add_argument(
        "--streamlit",
        action="store_true",
        help="start the original Streamlit dashboard instead",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser",
    )
    options = parser.parse_args()

    started: list[subprocess.Popen] = []

    def adopt(process: subprocess.Popen | None) -> None:
        """Track a process, ignoring one that was never started.

        A start function returns None when something already holds the port. That
        is worth reporting, not a reason to crash later while waiting on it.
        """

        if process is not None:
            started.append(process)

    try:
        if options.streamlit:
            url = STREAMLIT_URL
            adopt(start_streamlit())

            if not options.no_browser and _wait_for(url, seconds=45):
                webbrowser.open(url)
        else:
            if options.dev:
                adopt(start_dev_server())
                adopt(start_adapter())
                url = f"http://127.0.0.1:{VITE_PORT}"
            else:
                built = os.path.isdir(os.path.join(FRONTEND, "dist"))

                if not built:
                    print(
                        "[!] The interface has not been built yet.\n"
                        "    Run: cd frontend && npm install && npm run build\n"
                        "    Or start the development server with --dev."
                    )
                    return 1

                adopt(start_adapter())
                url = f"http://127.0.0.1:{API_PORT}"

            if not options.no_browser and _wait_for(url):
                webbrowser.open(url)

        if not started:
            print("[!] Nothing was started: the ports above are already in use.")
            return 1

        print("")
        print(f"[+] SAT-SA is running at {url}")
        print("[+] Press Ctrl-C to stop")

        for process in started:
            process.wait()

    except KeyboardInterrupt:
        print("")
        print("[+] Stopping")

    finally:
        for process in started:
            if process.poll() is None:
                process.terminate()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
