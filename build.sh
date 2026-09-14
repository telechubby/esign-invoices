#!/usr/bin/env bash
# Run this on macOS/Linux, from the project folder.
set -euo pipefail

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

pip install -r requirements.txt
python3 -m pytest tests -q

pyinstaller build.spec

echo
echo "Build finished. The app is in dist/EsignInvoices/ (dist/EsignInvoices.app on macOS)."
