#!/usr/bin/env bash
# `make restore FILE=<backup dir>` (M10.2; acceptance 1): replaces the database and the object
# store of the stack COMPOSE names with a backup from `make backup`, then checks the row counts
# against its manifest. Destructive: everything in that stack's database and object store is
# replaced, so it runs only with CONFIRM=yes. The sums are checked before anything is touched.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
read -r -a compose <<< "${COMPOSE:-docker compose -f deploy/compose.yaml}"
src="${1:?usage: restore.sh <backup directory>}"
[[ -f "$src/SHA256SUMS" && -f "$src/MANIFEST" ]] || { echo "$src is not a backup directory" >&2; exit 2; }
(cd "$src" && sha256sum --quiet -c SHA256SUMS) || { echo "the backup's sums do not match" >&2; exit 2; }
# The archive may hold only regular files and directories, at relative paths without `..`
# (review of 9943bc9): no links, devices or paths that leave the store, whatever tar allows.
if tar -tvf "$src/objectstore.tar" | cut -c1 | grep -qv '^[-d]$'; then
  echo "the object store archive holds something other than files and directories" >&2; exit 2
fi
if tar -tf "$src/objectstore.tar" | grep -qE '^/|(^|/)\.\.(/|$)'; then
  echo "the object store archive holds a path outside the store" >&2; exit 2
fi
if [[ "${CONFIRM:-}" != "yes" ]]; then
  echo "This replaces the database and the object store of: ${compose[*]}" >&2
  echo "Run again with CONFIRM=yes to proceed." >&2
  exit 3
fi

echo "==> stopping the application (the database stays up)"
"${compose[@]}" stop api worker beat
echo "==> database"
"${compose[@]}" exec -T db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --single-transaction' < "$src/db.dump"
echo "==> object store"
# Extracted beside the store first, swapped in only once whole: a failed extract leaves the
# store as it was; a failure while swapping can leave it part-restored. Either way the database
# is already restored: re-run the restore to finish.
trap 'echo "restore stopped: the database is restored; the object store may be partly restored (unchanged if the extract failed). Fix the cause and run the restore again; the application stays stopped." >&2' ERR
"${compose[@]}" run --rm --no-deps -T --entrypoint sh api -c '
  set -e
  staging=/data/objectstore/.restoring
  rm -rf "$staging" && mkdir "$staging"
  tar -C "$staging" --no-same-owner --no-same-permissions -xf -
  find /data/objectstore -mindepth 1 -maxdepth 1 ! -name .restoring -exec rm -rf {} +
  find "$staging" -mindepth 1 -maxdepth 1 -exec mv {} /data/objectstore/ \;
  rmdir "$staging"' < "$src/objectstore.tar"
trap - ERR
echo "==> starting the application"
"${compose[@]}" start api worker beat

echo "==> checking the counts against the manifest"
# shellcheck disable=SC2016
now="$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F= -c "
  SELECT '\''alembic_version'\'', version_num FROM alembic_version
  UNION ALL SELECT '\''item'\'', count(*)::text FROM item
  UNION ALL SELECT '\''item_version'\'', count(*)::text FROM item_version
  UNION ALL SELECT '\''source'\'', count(*)::text FROM source
  UNION ALL SELECT '\''user'\'', count(*)::text FROM \"user\"
  UNION ALL SELECT '\''output_job'\'', count(*)::text FROM output_job
  UNION ALL SELECT '\''audit_log'\'', count(*)::text FROM audit_log"')"
want="$(grep -v -e '^created_at=' -e '^objectstore_files=' "$src/MANIFEST")"
if [[ "$now" != "$want" ]]; then
  echo "restore: the counts differ from the backup's" >&2
  diff <(echo "$want") <(echo "$now") >&2 || true
  exit 1
fi
files="$("${compose[@]}" exec -T api sh -c 'find /data/objectstore -type f | wc -l')"
grep -qx "objectstore_files=${files// /}" "$src/MANIFEST" || {
  echo "restore: the object store holds $files files, not the backup's" >&2; exit 1; }
echo "restore: identical counts"
echo "$now"
