#!/usr/bin/env bash
# `make security`: Bandit, Semgrep CLI, pip-audit, pnpm audit and gitleaks (M0-tooling.md).
# Tools run isolated through uvx or a digest-pinned image, so none of them enters the api/
# lockfile; versions live in scripts/ci-tools.env. Semgrep CLI (LGPL-2.1) and its registry
# rules are developer tooling only and never ship (3.5). Runs every scanner, then exits 1 if
# any of them failed.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=ci-tools.env
source "$root/scripts/ci-tools.env"
failed=()
step() {
  local name=$1
  shift
  echo
  echo "==> $name"
  "$@" || failed+=("$name")
}

gitleaks_scan() {
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks git "$root" --redact --verbose --no-banner
  else
    docker run --rm -v "$root:/repo:ro" "$GITLEAKS_IMAGE" git /repo --redact --verbose --no-banner
  fi
}

pip_audit_scan() {
  local req
  req="$(mktemp)"
  (cd "$root/api" && uv export --frozen --no-emit-project --format requirements-txt --quiet) > "$req"
  uvx --quiet --from "pip-audit==${PIP_AUDIT_VERSION}" pip-audit -r "$req" --require-hashes --disable-pip
  local rc=$?
  rm -f "$req"
  return $rc
}

step bandit uvx --quiet --from "bandit==${BANDIT_VERSION}" bandit -q -r "$root/api/src"
step semgrep uvx --quiet --from "semgrep==${SEMGREP_VERSION}" semgrep scan \
  --config p/owasp-top-ten --metrics=off --error --quiet "$root/api/src" "$root/web/src"
step pip-audit pip_audit_scan
step pnpm-audit bash -c "cd '$root/web' && pnpm audit --audit-level high"
step gitleaks gitleaks_scan

echo
if ((${#failed[@]})); then
  echo "make security: FAILED: ${failed[*]}"
  exit 1
fi
echo "make security: all scanners passed"
