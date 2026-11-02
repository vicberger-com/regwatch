# Root targets fixed by docs/contracts/M0-tooling.md.
COMPOSE := docker compose -f deploy/compose.yaml
UNIT_MARKERS := not integration and not security and not perf

.PHONY: help dev stop migrate seed lint lint-api lint-web test test-api test-web \
        test-integration e2e openapi licenses security backup restore env

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

env: ## Create deploy/.env from docs/contracts/env.example if missing
	@scripts/dev-env.sh

dev: env ## Start the development stack with hot reload (http://localhost)
	$(COMPOSE) up --build

stop: ## Stop the development stack
	$(COMPOSE) down

migrate: ## Apply database migrations
	@echo "make migrate: lands in #28 (baseline migration 0001)"; exit 1

seed: ## Load seed data
	@echo "make seed: lands in #28 (seed loader and registry seeding)"; exit 1

lint: lint-api lint-web ## Ruff, mypy, ESLint and the TypeScript compiler

lint-api:
	cd api && uv sync --frozen --quiet && uv run ruff check . && uv run ruff format --check . && uv run mypy src

lint-web:
	cd web && pnpm install --frozen-lockfile --silent && pnpm lint && pnpm typecheck

test: test-api test-web ## Unit tests with coverage gates

test-api:
	cd api && uv run pytest -m "$(UNIT_MARKERS)" --cov=regwatch --cov-fail-under=85

test-web:
	cd web && pnpm install --frozen-lockfile --silent && pnpm test -- --coverage

test-integration: env ## Start the stack, wait for health checks, run integration tests
	$(COMPOSE) up -d --build --wait
	cd api && uv run pytest -m integration

e2e: ## Playwright end-to-end tests
	@echo "make e2e: lands in Phase 3 (Playwright with axe-core)"; exit 1

openapi: ## Export the OpenAPI document and regenerate the web client
	@echo "make openapi: lands in #30 (route stubs and generated client)"; exit 1

licenses: ## License inventory and allow-list check
	@echo "make licenses: lands in #29 (CI pipeline)"; exit 1

security: ## Bandit, Semgrep, pip-audit, pnpm audit, gitleaks
	@echo "make security: lands in #29 (CI pipeline)"; exit 1

backup: ## Back up PostgreSQL and the object store
	@echo "make backup: lands with M10 operations hardening"; exit 1

restore: ## Restore from FILE=
	@echo "make restore: lands with M10 operations hardening"; exit 1

.PHONY: fixtures-check fixture-server
fixtures-check: ## Validate the test corpus and run the fixture smoke tests (#12)
	cd api && uv run python -m tests.fixtures.validate_corpus && uv run pytest -q tests/unit/test_fixture_corpus.py tests/unit/test_fixture_feeds_pages.py tests/unit/test_fixture_server.py tests/unit/test_fixture_synthetic_payloads.py

fixture-server: ## Run the fixture HTTP server on 127.0.0.1:8099 (raw listener 8098)
	cd api && uv run python -m tests.support.fixture_server --port 8099 --raw-port 8098
