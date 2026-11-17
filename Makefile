# Root targets fixed by docs/contracts/M0-tooling.md.
COMPOSE := docker compose -f deploy/compose.yaml
UNIT_MARKERS := not integration and not security and not perf
# Integration tests that start their own throwaway PostgreSQL in Docker; `stack` ones need
# the Compose stack and run in test-integration only.
DB_MARKERS := integration and not stack

.PHONY: help dev stop migrate seed lint lint-api lint-web test test-api test-web \
        test-unit test-integration e2e openapi licenses security backup restore env

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

env: ## Create deploy/.env from docs/contracts/env.example if missing
	@scripts/dev-env.sh

dev: env ## Start the development stack with hot reload (http://localhost)
	$(COMPOSE) up --build

stop: ## Stop the development stack
	$(COMPOSE) down

migrate: env ## Apply database migrations as the owner (one-off migrate container, BL-61)
	$(COMPOSE) run --rm --build migrate

seed: env ## Load seed data (idempotent; regwatch-seed in the api container)
	$(COMPOSE) run --rm --build api regwatch-seed

lint: lint-api lint-web ## Ruff, mypy, ESLint and the TypeScript compiler

lint-api:
	cd api && uv sync --frozen --quiet && uv run ruff check . && uv run ruff format --check . && uv run mypy src

lint-web:
	cd web && pnpm install --frozen-lockfile --silent && pnpm lint && pnpm typecheck

test: test-api test-web ## Unit and database tests with coverage gates (needs Docker)

# 7.1 as amended by CP-04: the 85 percent floor counts unit and database integration tests
# together; the 100 percent floor on security-critical modules counts unit tests only.
test-api: ## Unit tests, then database integration tests; both coverage floors
	cd api && uv sync --frozen --quiet && \
		uv run pytest -m "$(UNIT_MARKERS)" --cov=regwatch --cov-report= && \
		uv run coverage json -q -o coverage-unit.json && \
		python3 -I ../scripts/coverage_critical.py coverage-unit.json && \
		uv run pytest -m "$(DB_MARKERS)" --cov=regwatch --cov-append --cov-fail-under=85

test-unit: ## Unit tests only, no Docker and no coverage floor (quick local loop)
	cd api && uv run pytest -m "$(UNIT_MARKERS)"

test-web:
	cd web && pnpm install --frozen-lockfile --silent && pnpm test -- --coverage

test-integration: env ## Start the stack, wait for health checks, run integration tests
	$(COMPOSE) up -d --build --wait
	cd api && uv run pytest -m integration

e2e: ## Playwright end-to-end tests
	@echo "make e2e: lands in Phase 3 (Playwright with axe-core)"; exit 1

openapi: ## Export the live OpenAPI document, diff it with the contract, regenerate the web client
	cd api && uv sync --frozen --quiet && uv run python -m tests.openapi_semantic \
		../openapi/regwatch.v1.yaml --write "$${TMPDIR:-/tmp}/regwatch.v1.live.json"
	cd web && pnpm install --frozen-lockfile --silent && \
		pnpm exec openapi-typescript ../openapi/regwatch.v1.yaml -o src/lib/api/schema.d.ts

connectors: ## Regenerate the admin UI's connector forms from docs/contracts/connectors.yaml
	cd api && uv run python -I ../scripts/gen_connector_forms.py

licenses: ## License inventory and allow-list check
	scripts/license-scan.sh

security: ## Bandit, Semgrep, pip-audit, pnpm audit, gitleaks
	scripts/security-scan.sh

backup: ## Back up PostgreSQL and the object store
	@echo "make backup: lands with M10 operations hardening"; exit 1

restore: ## Restore from FILE=
	@echo "make restore: lands with M10 operations hardening"; exit 1

.PHONY: fixtures-check fixture-server
fixtures-check: ## Validate the test corpus and run the fixture smoke tests (#12)
	cd api && uv run python -m tests.fixtures.validate_corpus && uv run pytest -q tests/unit/test_fixture_corpus.py tests/unit/test_fixture_feeds_pages.py tests/unit/test_fixture_server.py tests/unit/test_fixture_synthetic_payloads.py

fixture-server: ## Run the fixture HTTP server on 127.0.0.1:8099 (raw listener 8098)
	cd api && uv run python -m tests.support.fixture_server --port 8099 --raw-port 8098
