#!/usr/bin/env bash
# Re-apply local patches over installed Python packages.
# Run this after a fresh pip install / venv rebuild.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="$ROOT/venv/lib/python3.12/site-packages"

if [ ! -d "$SITE" ]; then
  echo "venv not found at $SITE — create it first (python -m venv venv)" >&2
  exit 1
fi

cp "$ROOT/vendored_patches/dialekt_manifest_schema.py" \
   "$SITE/dialekt_manifest/schema.py"
echo "patched dialekt_manifest/schema.py"
