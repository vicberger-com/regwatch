#!/usr/bin/env bash
# License inventory and allow-list check (REQ-20; docs/08-security-compliance.md 8.6 item 1).
# Python: pip-licenses run against the uv environment in api/.venv (all groups).
# Node: `pnpm licenses list` (built into pnpm, MIT) on the installed web/ tree, all and prod.
# Policy: scripts/license_policy.py (3.5 allow-list, ADR-0003); reviewed exceptions in
# scripts/license-exceptions.toml. Fails on any prohibited, review-required or unknown license.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=ci-tools.env
source "$root/scripts/ci-tools.env"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> Python (api/, uv environment)"
(cd "$root/api" && uv sync --frozen --quiet)
uvx --quiet --from "pip-licenses==${PIP_LICENSES_VERSION}" pip-licenses \
  --python "$root/api/.venv/bin/python" --from=mixed --with-system --format=json \
  > "$work/python.json"
# Runtime (bundled) set: what the production image installs (uv sync --no-dev).
(cd "$root/api" && uv export --frozen --no-dev --no-emit-project --no-hashes \
  --format requirements-txt --quiet) | sed -n 's/^\([A-Za-z0-9._-]*\)==.*/\1/p' > "$work/python-prod.txt"

echo "==> Node (web/, pnpm tree)"
(cd "$root/web" && pnpm install --frozen-lockfile --silent)
(cd "$root/web" && pnpm licenses list --json) > "$work/node.json"
(cd "$root/web" && pnpm licenses list --json --prod) > "$work/node-prod.json"

python3 -I "$root/scripts/license_policy.py" \
  --python-inventory "$work/python.json" --python-prod "$work/python-prod.txt" \
  --python-exe "$root/api/.venv/bin/python" \
  --node-inventory "$work/node.json" --node-prod "$work/node-prod.json" \
  --exceptions "$root/scripts/license-exceptions.toml" --repo-root "$root"
