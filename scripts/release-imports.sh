#!/usr/bin/env bash
# The release image's import check (M10.4; CI `images`): placeholder settings only, so the
# Celery app can be built; no secret, no network, nothing kept. Usage: release-imports.sh <image>
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm --network none \
  -e REGWATCH_SECRET_KEY="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" \
  -e REGWATCH_DATABASE_URL="postgresql://placeholder@127.0.0.1:1/placeholder" \
  -e REGWATCH_QUEUE_URL="valkey://127.0.0.1:1/0" -e REGWATCH_BASE_URL="https://localhost" \
  -v "$root/scripts/release_imports.py:/check.py:ro" --entrypoint python "${1:?image}" /check.py
