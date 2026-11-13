#!/bin/sh
# Runs once, when the db container initialises an empty data volume (docker-entrypoint-initdb.d).
# Creates regwatch_app (the privilege role the migrations grant to) and regwatch_api, the login
# the API uses, so the API never connects as the owner and cannot alter audit_log (BL-61).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$POSTGRES_APP_PASSWORD" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'regwatch_app') THEN
    CREATE ROLE regwatch_app NOLOGIN;
  END IF;
END $$;
SELECT format('CREATE ROLE regwatch_api LOGIN PASSWORD %L IN ROLE regwatch_app', :'app_password')
\gexec
SQL
