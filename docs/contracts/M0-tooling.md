# M0 tooling decisions

Fixed choices for the scaffold. Where a version line is given, the agent pins the latest patch release inside that line in the lockfile and records it in the component register.

## Languages and package managers

| Area | Decision |
| --- | --- |
| Python | 3.12. Project in `api/` with `pyproject.toml`; dependency and environment management with `uv` (Apache-2.0 or MIT; verify); `uv.lock` committed. |
| Node | 22 LTS. Project in `web/` with `pnpm` 9 (MIT); `pnpm-lock.yaml` committed. `print-bridge/` is a second Node package with its own lockfile. |
| Containers | Docker Engine 26 or later, Compose v2 file format in `deploy/compose.yaml` (development) and `deploy/compose.prod.yaml` (production overrides). |

## Python project

- Package name `regwatch`, src layout: `api/src/regwatch/`. Sub-packages: `core` (settings, db, security, errors, events), `identity`, `taxonomy`, `capture`, `processing`, `search`, `reports`, `outputs`, `admin`, `api` (FastAPI app factory and routers).
- Each sub-package exposes `router.py` (APIRouter), `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `services.py`, `tasks.py` (Celery), `permissions.py` (keys registered from `docs/contracts/registries.yaml`).
- Lint and format: Ruff (MIT) with rules `E, F, I, B, UP, S, N, ASYNC`, line length 100, format with `ruff format`. Type check: mypy (MIT) in strict mode for `core`, `identity`, `capture`; gradual (`check_untyped_defs`) elsewhere until Phase 5.
- Tests: pytest, pytest-asyncio, pytest-cov, Hypothesis, pytest-recording, Schemathesis. Layout `api/tests/unit`, `api/tests/integration`, `api/tests/security`, `api/tests/perf`. Markers: `integration`, `security`, `perf` (deselected by default; CI selects them in their jobs).
- Migrations: Alembic in `api/alembic/`; revision files named `NNNN_short_name.py`; `0001_baseline.py` creates everything in `docs/contracts/schema.sql`.
- Entry points: `regwatch-api` (uvicorn), `regwatch-worker` (celery worker), `regwatch-beat` (celery beat), `regwatch-seed` (idempotent seed loader), `regwatch-admin create-user`.
- Settings: `regwatch.core.settings.Settings` (pydantic-settings) reading the variables in `docs/contracts/env.example`; fails fast on a missing required variable.
- Logging: structlog JSON to stdout; `request_id` from the `X-Request-Id` header or generated; never log request bodies.

## Web project

- Vite 6 (MIT), React 18, TypeScript 5 in strict mode, path alias `@/` to `web/src`.
- Layout: `src/app` (router, providers, shell), `src/features/<module>` (pages, hooks, components), `src/components/ui` (shadcn copies), `src/lib/api` (generated client), `src/lib/i18n`, `src/styles` (tokens, themes), `e2e/` (Playwright).
- API client: types generated with `openapi-typescript` (MIT) from `openapi/regwatch.v1.yaml` into `src/lib/api/schema.d.ts`, fetch wrapper `src/lib/api/client.ts` using `openapi-fetch` (MIT). Generated files are committed; CI fails if regeneration differs.
- Lint: ESLint 9 flat config with `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-jsx-a11y`; Prettier with defaults (double quotes off: `singleQuote: false` is the default, keep it). Stylelint not used.
- Styling: Tailwind CSS 3.4 with tokens from `src/styles/tokens.css` exposed as CSS variables; themes via `html[data-theme="light|dark|high-contrast"]`; shadcn/ui components copied with `pnpm dlx shadcn@latest add`.
- Tests: Vitest with jsdom and Testing Library; Playwright with `@axe-core/playwright`; Lighthouse CI config in `web/lighthouserc.json`.
- Fonts: Inter self-hosted under `web/public/fonts/` with its SIL OFL licence file beside it.

## Make targets (root `Makefile`)

| Target | Does |
| --- | --- |
| `make dev` | `docker compose -f deploy/compose.yaml up --build` with hot reload for api and web |
| `make stop` | `docker compose ... down` |
| `make migrate` | `uv run alembic upgrade head` inside the api container |
| `make seed` | `uv run regwatch-seed seed/` |
| `make lint` | `uv run ruff check . && uv run ruff format --check . && uv run mypy src` in api; `pnpm lint && pnpm typecheck` in web |
| `make test` | in api (CP-04): `uv run pytest -m "not integration and not security and not perf" --cov=regwatch`, the 100 percent floor on security-critical modules from that unit run (`scripts/coverage_critical.py`), then `uv run pytest -m "integration and not stack" --cov=regwatch --cov-append --cov-fail-under=85` (needs Docker; tests start a throwaway PostgreSQL); `pnpm test -- --coverage` in web |
| `make test-unit` | the api unit run alone, without Docker or a floor |
| `make test-integration` | starts the test services and runs `pytest -m integration` (including `stack` tests, which need the Compose stack) |
| `make e2e` | `pnpm exec playwright test` against the running dev stack |
| `make openapi` | exports the live OpenAPI document to `openapi/regwatch.v1.yaml` and regenerates the web client; CI runs it and diffs |
| `make licenses` | `scripts/license-scan.sh` (pip-licenses, license-checker, allow-list check) |
| `make security` | `uv run bandit -r src`, `semgrep --config p/owasp-top-ten`, `pip-audit`, `pnpm audit`, `gitleaks detect` |
| `make backup` / `make restore FILE=` | `scripts/backup.sh` and `scripts/restore.sh` |

## Compose services (names are part of the contract)

`proxy` (caddy:2), `api`, `worker`, `beat`, `db` (postgres:16), `queue` (valkey/valkey:9), `pdf` (gotenberg/gotenberg:8), `search` (searxng/searxng, profile `search`), `print-bridge` (profile `print`), `mailpit` (axllent/mailpit, development only), `translate` (profile `translate`, LibreTranslate or an Argos service as decided by R-08). Internal network `regwatch`; only `proxy` publishes 80 and 443; `mailpit` publishes 8025 in development. Volumes `pgdata`, `objectstore`, `caddy-data`.

## CI (`.github/workflows/ci.yml`)

Jobs, all required on pull requests to `main`: `lint-api`, `lint-web`, `test-api` (unit and database integration tests, coverage gates, CP-04), `test-web`, `migrations` (upgrade head, downgrade base, upgrade head on empty PostgreSQL), `openapi` (regenerate and diff), `contract` (Schemathesis against the running api), `licenses`, `secrets` (gitleaks), `images` (Trivy on built images). `e2e` runs on pushes to `main` and on pull requests labelled `run-e2e`. `security.yml` runs nightly: full Semgrep, pip-audit, pnpm audit, ZAP baseline against a staging stack started in the job.

## Version lines

FastAPI 0.115 or later, Pydantic 2, SQLAlchemy 2.0, Alembic 1.13 or later, Celery 5.4 or later, httpx 0.27 or later, trafilatura 1.12 or later (never below 1.8), feedparser 6, Scrapy 2.11 or later, Playwright 1.45 or later; React 18.3, Vite 6, TanStack Query 5, TanStack Router 1, TanStack Table 8, Tailwind 3.4, MapLibre GL JS 4 or later, ECharts 5, Puck latest 0.x at the time of M7 start (record the exact version in ADR-0005).
