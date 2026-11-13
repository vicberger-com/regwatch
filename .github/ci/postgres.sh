#!/usr/bin/env bash
# Start an empty PostgreSQL for the migrations and contract jobs (#29), using the image
# digest pinned in deploy/compose.yaml so CI and the dev stack run the same server.
set -euo pipefail
image="$(grep -oE 'postgres:16@sha256:[0-9a-f]{64}' "$(dirname "$0")/../../deploy/compose.yaml" | head -1)"
docker run -d --name ci-db -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=regwatch -e POSTGRES_DB=regwatch -e POSTGRES_PASSWORD="${CI_DB_PASSWORD:-ci-only}" \
  "$image" >/dev/null
for _ in $(seq 1 30); do
  if docker exec ci-db pg_isready -U regwatch -d regwatch -q; then
    # Same roles as deploy/db-init/10-api-login.sh: the API logs in as regwatch_api (BL-61).
    sleep 1
    docker exec -i ci-db psql -v ON_ERROR_STOP=1 -q -U regwatch -d regwatch \
      -v app_password="${CI_APP_DB_PASSWORD:-ci-app-only}" <<'SQL'
CREATE ROLE regwatch_app NOLOGIN;
SELECT format('CREATE ROLE regwatch_api LOGIN PASSWORD %L IN ROLE regwatch_app', :'app_password')
\gexec
SQL
    exit 0
  fi
  sleep 1
done
docker logs ci-db
exit 1
