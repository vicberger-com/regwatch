# Sourced by CI jobs that start the app or run Alembic (#29). Throwaway values for the
# required settings (docs/contracts/env.example); the secret key is generated per run.
export REGWATCH_ENV=test
export REGWATCH_SECRET_KEY="$(openssl rand -hex 32)"
export REGWATCH_DATABASE_URL="postgresql+psycopg://regwatch_api:${CI_APP_DB_PASSWORD:-ci-app-only}@127.0.0.1:5432/regwatch"
# The owner URL is not exported: pass it to migration steps only, as
#   REGWATCH_MIGRATION_DATABASE_URL="$CI_OWNER_DATABASE_URL" uv run alembic ...
# so the API process never holds owner credentials (BL-61).
CI_OWNER_DATABASE_URL="postgresql+psycopg://regwatch:${CI_DB_PASSWORD:-ci-only}@127.0.0.1:5432/regwatch"
export REGWATCH_QUEUE_URL="valkey://127.0.0.1:6379/0"
export REGWATCH_BASE_URL="http://localhost"
