#!/usr/bin/env bash
# The weekly DEBRIS refresh, run on the droplet by debris-weekly.service (path A) or
# on the Studio by the launchd plist (path B, with --local).
#
# Every stage is resumable and logs to data/manifests/; a failure in one stage leaves
# the previous week's database and JSON bundles serving untouched.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTHON="${DEBRIS_PYTHON:-./.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

MODE="${1:---remote}"
echo "==> DEBRIS weekly refresh $(date -u +%FT%TZ) (${MODE})"
"$PYTHON" -m pipeline.weekly "$MODE"
echo "==> Weekly refresh finished $(date -u +%FT%TZ)"
