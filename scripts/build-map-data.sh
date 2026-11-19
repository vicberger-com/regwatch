#!/usr/bin/env bash
# Build the map's boundary files (--accept writes an output whose hash differs from the recorded one) (ADR-0004, R-05) from Natural Earth v5.1.2. Run when the data
# or the simplification changes; the output is committed, so the web build needs no network.
#
# Writes web/public/map/countries.geojson (fields id = ADM0_A3, iso = ISO_A2_EH, name) and
# web/public/map/disputed.geojson (id, name, note = NOTE_BRK), simplified with mapshaper
# (MPL-2.0, run through pnpm dlx, never a dependency) at 25% keep-shapes, 0.001° precision,
# then projected to Equal Earth by scripts/project-equal-earth.mjs (ADR-0004 amendment 1).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tag="v5.1.2"
commit="f1890d9f152c896d250a77557a5751a93d494776"
mapshaper="mapshaper@0.7.101"
# The committed output's hashes; a rebuild that differs is reported (review finding 4).
expected_countries="1c961cb260f5d37aa6d460b6c2ebc606d9568f4cb999832fcd643f8eb57b9ac7"
expected_disputed="eaa40272f43cd3f5e815b734f3fe0f444e0571983d698d14a8e5660d80bc639a"
export npm_config_ignore_scripts=true  # mapshaper's dependencies run no install scripts
out="$root/web/public/map"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git clone --quiet --depth 1 --branch "$tag" --filter=blob:none --no-checkout \
  https://github.com/nvkelso/natural-earth-vector "$work/ne"
got="$(git -C "$work/ne" rev-parse HEAD)"
[[ "$got" == "$commit" ]] || { echo "tag $tag is $got, expected $commit" >&2; exit 1; }
git -C "$work/ne" sparse-checkout set --no-cone \
  geojson/ne_50m_admin_0_countries.geojson geojson/ne_50m_admin_0_breakaway_disputed_areas.geojson
git -C "$work/ne" checkout --quiet

mkdir -p "$out"
cd "$work"
pnpm dlx "$mapshaper" ne/geojson/ne_50m_admin_0_countries.geojson \
  -filter-fields ADM0_A3,ISO_A2_EH,NAME -rename-fields id=ADM0_A3,iso=ISO_A2_EH,name=NAME \
  -simplify 25% keep-shapes -o countries.geojson format=geojson precision=0.001
pnpm dlx "$mapshaper" ne/geojson/ne_50m_admin_0_breakaway_disputed_areas.geojson \
  -filter-fields ADM0_A3,NAME,NOTE_BRK -rename-fields id=ADM0_A3,name=NAME,note=NOTE_BRK \
  -simplify 25% keep-shapes -o disputed.geojson format=geojson precision=0.001
status=0
for f in countries disputed; do
  node "$root/scripts/project-equal-earth.mjs" "$f.geojson" "$work/$f.out.geojson"
  got="$(sha256sum "$work/$f.out.geojson" | cut -d' ' -f1)"
  want="expected_$f"
  echo "$f.geojson: $(stat -c %s "$work/$f.out.geojson") bytes, $(gzip -9 -c "$work/$f.out.geojson" | wc -c) gzip, sha256 $got"
  if [[ "$got" == "${!want}" || "${1:-}" == "--accept" ]]; then
    cp "$work/$f.out.geojson" "$out/$f.geojson"
  else
    echo "  differs from the committed file (${!want}); not written. Review it, then rerun with --accept and update the hash here" >&2
    status=1
  fi
done
exit "$status"
