#!/usr/bin/env bash
# `make backup` (M10.2; REQ-01; acceptance 1): the database (pg_dump, custom format) and the
# object store (a tar of its volume) into BACKUP_DIR/<UTC time>/, with a manifest of row
# counts and SHA-256 sums for the restore drill. Backups older than BACKUP_KEEP_DAYS (30) are
# removed, only directories this script names. The database credentials stay inside the db
# container (its own POSTGRES_* environment); nothing secret is read or printed here.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
read -r -a compose <<< "${COMPOSE:-docker compose -f deploy/compose.yaml}"
dest_root="${BACKUP_DIR:-$root/backups}"
keep="${BACKUP_KEEP_DAYS:-30}"
[[ "$keep" =~ ^[0-9]+$ ]] || { echo "BACKUP_KEEP_DAYS must be a number of days" >&2; exit 2; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$dest_root/$stamp"
umask 077  # backups hold every item and user record: readable by their owner only
mkdir -p "$dest"

echo "==> database"
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$dest/db.dump"
echo "==> object store"
"${compose[@]}" exec -T api tar -C /data/objectstore -cf - . > "$dest/objectstore.tar"

echo "==> manifest"
# shellcheck disable=SC2016  # expanded inside the db container
counts="$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F= -c "
  SELECT '\''alembic_version'\'', version_num FROM alembic_version
  UNION ALL SELECT '\''item'\'', count(*)::text FROM item
  UNION ALL SELECT '\''item_version'\'', count(*)::text FROM item_version
  UNION ALL SELECT '\''source'\'', count(*)::text FROM source
  UNION ALL SELECT '\''user'\'', count(*)::text FROM \"user\"
  UNION ALL SELECT '\''output_job'\'', count(*)::text FROM output_job
  UNION ALL SELECT '\''audit_log'\'', count(*)::text FROM audit_log"')"
{
  echo "created_at=$stamp"
  echo "$counts"
  echo "objectstore_files=$(tar -tf "$dest/objectstore.tar" | grep -cv '/$' || true)"
} > "$dest/MANIFEST"
(cd "$dest" && sha256sum db.dump objectstore.tar MANIFEST > SHA256SUMS)

# Only directories named like ours, directly under the backup root.
find "$dest_root" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended \
  -regex '.*/[0-9]{8}T[0-9]{6}Z' -mtime "+$keep" -print -exec rm -rf {} +

echo "backup: $dest"
cat "$dest/MANIFEST"
