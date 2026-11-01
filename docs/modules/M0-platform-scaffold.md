# M0 Platform scaffold and developer experience

**Phase:** P1 · **Size:** M · **Parallelism:** must finish before any other module merges; one session owns it.
**Requirements:** REQ-01, REQ-19, REQ-20, REQ-26, REQ-27

## Purpose
Create the monorepo, build, test and CI skeleton that every other module plugs into, so parallel sessions share one set of conventions from day one.

## Scope
In: repository layout (section 6.4), Docker Compose for development, API skeleton with health endpoint, frontend skeleton with design tokens and theme switch, database with migration 0001 (extensions, `uuidv7()` function, `updated_at` trigger), seed loader command, CI pipeline (lint, type-check, unit tests, migrations check, OpenAPI diff, license scan, secret scan, image scan), pre-commit hooks, templates in `docs/templates/`, `CHANGELOG.md`, `BACKLOG.md`, `THIRD_PARTY_NOTICES.md`.
Out: any business feature.

## Interfaces
- `GET /api/v1/health` returns `{status, version, db, queue}`; `GET /api/v1/version`.
- `make dev`, `make test`, `make lint`, `make migrate`, `make seed`, `make e2e`, `make licenses`.
- CI workflow `ci.yml` runs on every PR; `release.yml` builds images on tags.

## Open-source components
FastAPI, SQLAlchemy, Alembic, Celery, Valkey, PostgreSQL, Vite, React, Tailwind, shadcn/ui, Ruff, mypy, ESLint, Prettier, pytest, Vitest, Playwright, gitleaks, Trivy, pip-licenses, license-checker.

## Contracts to implement
`docs/contracts/M0-tooling.md` (exact tooling), `docs/contracts/schema.sql` (migration 0001), `docs/contracts/registries.yaml` (seed permissions, roles, settings, flags), `docs/contracts/env.example` (settings model), `openapi/regwatch.v1.yaml` (route stubs returning 501 until each module lands, so the web client can be generated on day one), `docs/contracts/fixtures.md` (fixture task, separate issue).

## Design notes
- Python package `regwatch/` with sub-packages `api`, `core`, `capture`, `processing`, `search`, `reports`, `outputs`, `identity`, `taxonomy`; each module in this package exposes `router`, `models`, `services`, `tasks`.
- Frontend `web/src/` with `app/` (shell, routing), `features/<module>/`, `components/ui/` (shadcn copies), `lib/api/` (generated client from OpenAPI via openapi-typescript, MIT).
- Design tokens in `web/src/styles/tokens.css`: colour, spacing, radius, type scale; three themes (`light`, `dark`, `high-contrast`) as `data-theme` attributes on `html`.
- Generated OpenAPI committed; CI fails if the generated file differs from the committed one.

## Acceptance criteria
1. A fresh clone runs `make dev` and serves the SPA with a working health check within 10 minutes on a machine with Docker.
2. CI is green on an empty PR and red when a test fails, when coverage drops below floor, when a GPL dependency is added, or when a secret-like string is committed.
3. Theme switch cycles light, dark and high-contrast without a reload and persists in `localStorage` until M9 moves it to server preferences.
4. Migration 0001 applies and downgrades cleanly on an empty database.

## Test plan
- Unit: settings model validation, uuidv7 function monotonicity, health endpoint.
- Integration: Compose stack starts and all health checks pass (CI job).
- Security: gitleaks, Trivy and license scan wired and proven with a deliberate failing fixture in a throwaway branch.

## Question bank (post as `Questions: M0`)
1. Repository name and default branch? Default: owner's existing repository, `main`.
2. Is GitHub Actions available on the repository, and are there minutes limits? Default: yes, free tier.
3. Container registry for images (GitHub Container Registry or other)? Default: GHCR.
4. Python and Node versions mandated by the owner's environment? Default: Python 3.12, Node 22 LTS.
5. Any corporate proxy or air-gapped constraint for builds? Default: none.

## Enhancements to propose
Devcontainer definition for one-click environments; Renovate for dependency updates with license check in the bot's PR.
