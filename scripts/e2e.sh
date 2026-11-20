#!/usr/bin/env bash
# `make e2e` (M0 tooling): the Playwright tests in web/e2e, run in the official Playwright image
# (pinned by digest) against a running stack. The container joins the host network as a client
# only, so it can reach a stack published on 127.0.0.1; it listens on nothing.
#   E2E_BASE_URL     the stack's address (default http://127.0.0.1:80, the dev stack)
#   E2E_CREDENTIALS  a file with the lines "admin email: …" and "admin password: …" (required)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
image="mcr.microsoft.com/playwright@sha256:1507cbfc550a63a6b7396791ca4f00df17beb56342d2447b3f106c306f525579"  # v1.65.1-noble
creds="${E2E_CREDENTIALS:?set E2E_CREDENTIALS to the admin credential file of the stack under test}"
base="${E2E_BASE_URL:-http://127.0.0.1:80}"
exec docker run --rm --network host --ipc host \
  -e E2E_BASE_URL="$base" -e E2E_CREDENTIALS=/creds/admin.txt -e CI=1 \
  -v "$root/web:/work:ro" -v "$(realpath "$creds"):/creds/admin.txt:ro" \
  -w /work "$image" \
  node node_modules/@playwright/test/cli.js test --output=/tmp/e2e-results "$@"
