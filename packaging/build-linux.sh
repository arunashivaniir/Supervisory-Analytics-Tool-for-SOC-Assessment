#!/usr/bin/env bash
# Build the Linux single-file SAT-SA executable.
#
# Usage (repository root):  bash packaging/build-linux.sh
# Output:                   dist/satsa/SAT-SA-linux
#
# Requires at build time (build machine only, never the target):
#   python3, pip, node, npm, strip (binutils).
# The target machine needs nothing but a compatible Linux on the same
# architecture and an installed browser.
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT"

echo "[+] Rebuilding the frontend bundle"
(cd frontend && npm run build)

echo "[+] Build dependencies (isolated venv inheriting runtime packages)"
if [ ! -x /tmp/opencode/pyi-venv/bin/python ]; then
  python3 -m venv --system-site-packages /tmp/opencode/pyi-venv
fi
/tmp/opencode/pyi-venv/bin/python -m pip install --quiet pyinstaller

echo "[+] Freezing"
rm -rf /tmp/opencode/pyi-build
/tmp/opencode/pyi-venv/bin/python -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "$PROJECT/dist/satsa" \
  --workpath /tmp/opencode/pyi-build \
  "$PROJECT/packaging/satsa-linux.spec"

echo "[+] Artifact"
ls -la "$PROJECT/dist/satsa/SAT-SA-linux"
file "$PROJECT/dist/satsa/SAT-SA-linux"
