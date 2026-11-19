# Decisions

Architecture decision records use `docs/templates/ADR.md` and are numbered `ADR-nnnn-title.md`. The eight ADRs to write in Phase 0 are listed in `docs/03-architecture.md` section 3.7. `ASSUMPTIONS.md` logs every questioning-period answer that was assumed rather than given by the owner.

## Index

All eight ADRs were accepted at Gate G0 (#2) on 2026-11-02; ADR-0005 decision 3 is deferred with BL-17. The full decision log is in `G0-decisions.md`. Questions that need the owner are listed at the end of each ADR (ADR-0001 to 0003 and 0006 to 0008) or in `ASSUMPTIONS.md` (ADR-0004 and 0005).

| ADR | Title | Status | Requirements | Research |
| --- | --- | --- | --- | --- |
| [ADR-0001](ADR-0001-modular-monolith.md) | Modular monolith API and worker pool in one Python codebase, with third-party services as HTTP sidecars | accepted | REQ-01, REQ-04, REQ-05 | R-02, R-04, R-07, R-08 |
| [ADR-0002](ADR-0002-postgresql-search.md) | PostgreSQL 16 as the system of record and the first search engine, with Meilisearch as a measured fallback | accepted | REQ-03, REQ-09, REQ-11 | R-01, R-07, R-08 |
| [ADR-0003](ADR-0003-license-policy.md) | License policy, the service-boundary exception for unmodified AGPL services, and data terms | accepted | REQ-19, REQ-20 | R-01, R-03, R-04, R-07, R-08 |
| [ADR-0004](ADR-0004-map-boundaries.md) | Natural Earth 1:50m admin-0 as a build-time GeoJSON for the MapLibre choropleth | accepted | REQ-06, REQ-18 | R-01, R-05 |
| [ADR-0005](ADR-0005-report-builder.md) | Puck for the report builder, with a project-owned keyboard layer and server rendering through Puck's Render | accepted (decision 3 deferred, BL-17) | REQ-12, REQ-13, REQ-18 | R-01, R-02 |
| [ADR-0006](ADR-0006-celery-valkey-scheduling.md) | Celery and Valkey for scheduling, with per-host politeness enforced in SafeFetcher | accepted | REQ-04, REQ-05 | R-01, R-03, R-06, R-07 |
| [ADR-0007](ADR-0007-local-auth-then-oidc.md) | Local accounts and server-side sessions first, OpenID Connect in Phase 5 | accepted | REQ-14, REQ-16 | R-01 |
| [ADR-0008](ADR-0008-gotenberg-pdf.md) | Gotenberg for PDF from the same server-rendered HTML; browser print only at launch | accepted | REQ-10, REQ-15 | R-01, R-02, R-04 |
| [ADR-0009](ADR-0009-own-html-extraction.md) | Own HTML extraction on html5lib, instead of trafilatura and readability-lxml | accepted 2026-11-17 (owner) | REQ-04, REQ-05, REQ-20 | R-01 |

| [ADR-0010](ADR-0010-internet-search-provider.md) | SearXNG, self-hosted and unmodified, as the internet search provider, for discovery only | accepted 2026-11-18 (owner) | REQ-04, REQ-05, REQ-20 | R-07 |
| [ADR-0011](ADR-0011-search-engine-fallback.md) | A search engine beside PostgreSQL for M5 latency (ADR-0002 decision 5) | proposed 2026-11-19 | REQ-03, REQ-09 | BL-118 load test |

Proposed but not yet written: ADR for translation providers (BL-41) and the server print path (BL-47).
