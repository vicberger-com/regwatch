#!/usr/bin/env bash
# Start an empty PostgreSQL for the migrations and contract jobs (#29), using the image
# digest pinned in deploy/compose.yaml so CI and the dev stack run the same server.
set -euo pipefail
image="$(grep -oE 'postgres:16@sha256:[0-9a-f]{64}' "$(dirname "$0")/../../deploy/compose.yaml" | head -1)"
docker run -d --name ci-db -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=regwatch -e POSTGRES_DB=regwatch -e POSTGRES_PASSWORD="${CI_DB_PASSWORD:-ci-only}" \
  "$image" >/dev/null
for _ in $(seq 1 30); do
  docker exec ci-db pg_isready -U regwatch -d regwatch -q && exit 0
  sleep 1
done
docker logs ci-db
exit 1
