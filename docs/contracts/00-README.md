# Contracts

These files are the shared agreements that parallel sessions build against. They are written once, before Phase 1, and changed only through a pull request that references a `CP-nn` change-proposal issue (section 6.5). An agent that finds a contract wrong does not work around it; it opens the CP issue and keeps building to the contract until the change merges.

| File | Contract | Consumed by |
| --- | --- | --- |
| `M0-tooling.md` | Languages, package managers, project layout, lint and test configuration, make targets, Compose services, CI jobs, version lines | M0 writes them; every module uses them |
| `../../openapi/regwatch.v1.yaml` | HTTP API: paths, schemas, error format, pagination, auth | M1 to M9 API sessions and the web client (generated types) |
| `schema.sql` | Canonical PostgreSQL DDL for section 4; Alembic revisions and SQLAlchemy models must match it | M0 migration 0001, all modules |
| `registries.yaml` | Permission keys, settings keys, feature flags, Celery task names, domain events | All modules |
| `env.example` | Every environment variable with a comment | M0, M10, operators |
| `connectors.yaml` | JSON Schema for each connector's `config` and `extraction_rules` | M3 connector sessions, admin UI |
| `screens.md` | Screen inventory, regions and components per screen, design brief with tokens | M6, M7, M9 |
| `fixtures.md` | Test fixture inventory and the task card to build it | M3, M4, M5 tests |

Precedence when documents disagree: contracts in this folder, then module specs, then the numbered sections. Report the disagreement as a CP issue either way.
