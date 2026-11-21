#!/usr/bin/env bash
# `make sbom` and the release workflow (M10.4; M10 acceptance 5): CycloneDX SBOMs of the release
# images (the API and the proxy with the web app) and of the source tree's lockfiles, written
# to sbom/. Trivy (Apache-2.0, pinned in scripts/ci-tools.env) reads them; nothing is uploaded
# here. Usage: scripts/sbom.sh <api image> <proxy image> [version]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=ci-tools.env
source "$root/scripts/ci-tools.env"
api="${1:?api image}" proxy="${2:?proxy image}" version="${3:-dev}"
out="$root/sbom"
mkdir -p "$out" "$HOME/.cache/trivy"

# The SBOM goes to stdout and is written here, so the files belong to the caller, not root.
trivy() {
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$HOME/.cache/trivy:/root/.cache/trivy" \
    -v "$root:/src:ro" "$TRIVY_IMAGE" "$@"
}
trivy image --quiet --format cyclonedx "$api" > "$out/regwatch-api-$version.cdx.json"
trivy image --quiet --format cyclonedx "$proxy" > "$out/regwatch-proxy-$version.cdx.json"
trivy fs --quiet --format cyclonedx --skip-dirs /src/web/node_modules --skip-dirs /src/api/.venv \
  /src > "$out/regwatch-source-$version.cdx.json"
(cd "$out" && sha256sum ./*-"$version".cdx.json > "SHA256SUMS-$version")
ls -l "$out"
