#!/usr/bin/env bash
# Runs the app from source (for testing before/instead of building the .app).
set -euo pipefail
source .venv/bin/activate
python3 -m app.main
