#!/usr/bin/env bash
# Build kanjo-cli.zip for release / Windows installation.
# Contains:
#   kanjo/
#   pricing.json
#   pricing_overrides.json
# Excludes tests and __pycache__.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT="${1:-${REPO_ROOT}/kanjo-cli.zip}"

STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGE_DIR}"' EXIT

mkdir -p "${STAGE_DIR}/kanjo"
cp -R "${REPO_ROOT}/cli/kanjo/"* "${STAGE_DIR}/kanjo/"
find "${STAGE_DIR}/kanjo" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${STAGE_DIR}/kanjo" -name "*.pyc" -delete 2>/dev/null || true

cp "${REPO_ROOT}/cli/pricing.json" "${STAGE_DIR}/"
cp "${REPO_ROOT}/cli/pricing_overrides.json" "${STAGE_DIR}/"

rm -f "${OUTPUT}"
(cd "${STAGE_DIR}" && zip -r -q "${OUTPUT}" .)

echo "Created: ${OUTPUT} ($(du -h "${OUTPUT}" | cut -f1))"
