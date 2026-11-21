#!/usr/bin/env bash
# `make e2e` (M0 tooling): the Playwright tests in web/e2e, run in the official Playwright image
# (pinned by digest) against a running stack. The container joins the host network as a client
# only, so it can reach a stack published on 127.0.0.1; it listens on nothing, runs as the
# calling (unprivileged) user, who can read the credential file, with no capabilities, and keeps its own IPC namespace.
#   E2E_BASE_URL     the stack under test (required): a loopback address, or with
#                    E2E_ALLOW_REMOTE=1 an https one; setup adds a test source and two items there
#   E2E_PRINT_TEST   set to run the acceptance 3 journey against the print-test profile's printer
#   E2E_OIDC_ENV     the oidc-test profile's deploy/keycloak.env, to run the M1b sign-in journey
#   E2E_CREDENTIALS  a file with the lines "admin email: …" and "admin password: …" (required),
#                    kept outside web/ (which is mounted into the container)
set -euo pipefail
root="$(realpath "$(dirname "$0")/..")"  # resolved, so the web/ check below cannot be sidestepped
image="mcr.microsoft.com/playwright@sha256:1507cbfc550a63a6b7396791ca4f00df17beb56342d2447b3f106c306f525579"  # v1.65.1-noble
creds="${E2E_CREDENTIALS:?set E2E_CREDENTIALS to the admin credential file of the stack under test}"
base="${E2E_BASE_URL:?set E2E_BASE_URL to the stack under test, e.g. http://localhost:8180}"
if [[ ! "$base" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?/?$ ]]; then
  if [[ "${E2E_ALLOW_REMOTE:-}" != "1" || ! "$base" =~ ^https:// ]]; then
    echo "refusing $base: only a loopback stack, or an https one with E2E_ALLOW_REMOTE=1" >&2
    exit 1
  fi
fi
case "$(realpath "$creds")" in
  "$root/web"/*) echo "keep the credential file outside web/ (it is mounted into the container)" >&2; exit 1 ;;
esac
oidc=()
if [[ -n "${E2E_OIDC_ENV:-}" ]]; then
  case "$(realpath "$E2E_OIDC_ENV")" in
    "$root/web"/*) echo "keep E2E_OIDC_ENV outside web/" >&2; exit 1 ;;
  esac
  oidc=(-e E2E_OIDC_ENV=/creds/keycloak.env -v "$(realpath "$E2E_OIDC_ENV"):/creds/keycloak.env:ro")
fi
exec docker run --rm --network host --shm-size=2g \
  --user "$(id -u):$(id -g)" -e HOME=/tmp --cap-drop ALL --security-opt no-new-privileges \
  -e E2E_BASE_URL="$base" -e E2E_CREDENTIALS=/creds/admin.txt -e CI=1 \
  -e E2E_ALLOW_REMOTE="${E2E_ALLOW_REMOTE:-}" -e E2E_CANARY="${E2E_CANARY:-}" \
  -e E2E_MAILPIT_URL="${E2E_MAILPIT_URL:-}" -e E2E_PRINT_TEST="${E2E_PRINT_TEST:-}" \
  "${oidc[@]}" \
  -v "$root/web:/work:ro" -v "$(realpath "$creds"):/creds/admin.txt:ro" \
  -w /work "$image" \
  node node_modules/@playwright/test/cli.js test --output=/tmp/e2e-results "$@"
