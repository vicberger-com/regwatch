# ADR-0001: Modular monolith API and worker pool in one Python codebase, with third-party services as HTTP sidecars

**Status:** accepted at Gate G0 on 2026-11-02 · **Date:** 2026-11-02 · **Requirements:** REQ-01, REQ-04, REQ-05 (also REQ-19, REQ-20, REQ-27)
**Research:** R-02 (#4), R-04 (#6), R-07 (#9), R-08 (#11); `docs/03-architecture.md` 3.1 to 3.3; `docs/contracts/M0-tooling.md`

## Context

- **Scale and operation.** Up to 50 named users and 10 concurrent users, single tenant (G2). Docker Compose on one Linux host operated by the owner (2.4 answer 6, G1). Modules ship in phases (REQ-01, 6.1), with up to five sessions working in parallel (6.2).
- **One backend language.** 3.2 chose Python because the scraping ecosystem is Python, and rejected Node/NestJS "to avoid two backend languages". `M0-tooling.md` fixes one Python package (`api/src/regwatch/`) with per-module sub-packages and three entry points from it: `regwatch-api`, `regwatch-worker` and `regwatch-beat`. The only other server-side package in the contract is the Node `print-bridge/`.
- **Network boundary.** The API never reaches the internet; workers do all outbound fetching through SafeFetcher, which rejects private, loopback and link-local addresses (3.1, 8.1, M3).
- **Compose services are contract names** (`M0-tooling.md`): `proxy`, `api`, `worker`, `beat`, `db`, `queue`, `pdf`, `search` (profile), `print-bridge` (profile), `mailpit` (development), `translate` (profile).
- **Pressures from research on the one-language rule:**
  - **R-02, BL-17:** render reports with Puck's `Render` in an internal Node render worker, so the canvas, preview, PDF and email share one set of components, with ECharts SSR in the same process. The alternative, Jinja2 per component, produced byte-identical HTML but means about 12 components written twice with a parity test. R-02 estimates 3 to 4 developer-days for the worker and 4 to 6 for Jinja2, growing with each component (estimates, not measured). ADR-0005 keeps Jinja2 until the owner accepts BL-17.
  - **R-04, BL-15:** no Node IPP client passed the license gate (`ipp` has no license file; `@sealsystems/ipp` has no reachable repository). Python clients (`ippx`, `aioipp`, both MIT) printed in the live test. A Python print path would remove the contract's only other Node service, but needs a `CP-nn`.
  - **R-08:** in-process Argos is blocked (F1: argostranslate 1.11+ requires AGPL `minisbd`; F2: 1.10.0 downloads a CC BY-SA model at import). The local provider is therefore the official LibreTranslate 1.9.6 image as the `translate` sidecar (AGPL-3.0, unmodified). It fetched 14 model packages (1.66 GB) at first start and peaked at 1.5 GiB with 1 worker and 5.9 GiB (sampled) with 4.
  - **R-07:** the `search` sidecar (SearXNG) makes its own outbound requests to upstream engines, and its engines break as those sites change (R-07 2.4).

## Decision

1. **One Python codebase for all project-owned server logic**, deployed from one image as three process types: `api` (FastAPI), `worker` (Celery, scaled 1 to N) and `beat` (exactly one). Modules are the sub-packages listed in `M0-tooling.md`. A module uses another module through that module's `services.py` and the events in `docs/contracts/registries.yaml`, not by querying its tables. There are no per-module services and no per-module databases.
2. **Third-party services run as sidecars:** unmodified official images, pulled by digest (8.6 item 4), on the internal network. Each has a contract Compose name, a URL variable in `env.example`, a health check, and a setting or feature flag that turns it off. The application reaches a sidecar only over its network API and never imports its code. Current sidecars: `db`, `queue`, `pdf` (Gotenberg), `search` (SearXNG), `translate` (LibreTranslate), `proxy` (Caddy) and `mailpit` (development only).
3. **Two network classes.** *Internal-only* sidecars have no route to the internet: `pdf`, and the render worker if BL-17 is accepted. *Egress* sidecars need the internet: `search` always, and `translate` while it downloads models. An egress sidecar sits on its own network segment that can reach the internet and be reached by `worker`, but cannot reach `db`, `queue` or the object store. This changes the Compose contract and needs a `CP-nn` (BL-48).
4. **Two HTTP clients.** SafeFetcher stays the only client for external hosts, including hosted APIs (`translation.provider: http`, commercial search keys). Calls to sidecars use an internal client bound to the URL variables in `env.example`: fixed hosts, no redirects off that host, and SafeFetcher's timeouts and body caps.
5. **Project-owned code in another server-side language** is allowed only as an internal-only sidecar that is stateless, holds no database, queue or object-store credentials, receives input already validated by the Python side, and has a contract test in CI. Each such sidecar needs its own ADR, a `CP-nn` to `M0-tooling.md` and the owner's acceptance. This ADR accepts none. The Node render worker (BL-17) is the only current candidate.
6. **Printing adds no second-language service.** If server printing is scheduled (BL-15), it runs from the Python worker or a Python bridge. Until a `CP-nn` merges, the contract's `print-bridge/` entry stands, `outputs.server_print` stays off and nothing is built for it (R-04).

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **Modular monolith plus worker pool; third-party services as HTTP sidecars (chosen)** | own code; sidecar licenses in 3.6 | One language, one image, one migration stream; fits one host and 10 concurrent users; reuses AGPL services lawfully and unmodified (ADR-0003) | Sidecars add memory (LibreTranslate alone 1.5 GiB with 1 worker, R-08); module boundaries rest on review, not process isolation |
| Microservices per connector or module | n/a | Independent deploys and scaling | No load reason at 50 users on one host (G2); one deployable, network contract and database per service for every parallel session; more surface for 8.1 |
| Serverless functions | n/a | Scale per call | Conflicts with the single-host Compose deployment (G1, answer 6); poor fit for long crawls and Playwright rendering; ties the product to a vendor runtime |
| Strict single language, no sidecars | n/a | Smallest operational surface | Rules out Gotenberg, SearXNG and LibreTranslate; in-process Argos is blocked (R-08 F1, F2), so local translation would be impossible |
| Second backend language wherever convenient | n/a | Best library per task | Two toolchains for every session; contradicts 3.2; R-04 found no licensed Node IPP client |

## Consequences

- **Positive:**
  - Every module session works in one language with one lint, type and test setup (`M0-tooling.md`).
  - One backup covers all project data (PostgreSQL plus the object store, M10).
  - The sidecar rule gives a single test for the R-02, R-04 and R-08 proposals, so each is decided on its merits instead of case by case.
- **Negative:**
  - SearXNG fetches on its own behalf, so "workers do all outbound fetching" (3.1) no longer holds for search, and SafeFetcher's robots and rate-limit controls do not cover its upstream requests. Pacing is enforced from the connector side instead (R-07: one query at a time, at least 60 s apart; ADR-0006).
  - LibreTranslate needs either egress at first start or a model volume filled in advance. Which one is not decided. Two of the models it would fetch (de 1.3, ja 1.1) state no license (R-08 F3, BL-42).
  - Host sizing is not established. Known figures: LibreTranslate image 1.0 GB plus 1.66 GB of models, 1.5 GiB RAM with 1 worker (R-08); SearXNG is one small container (R-07). Gotenberg and the stack as a whole were not measured.
  - R-01 read each project's own LICENSE file, not the contents of its container image. Sidecar images need a license scan as well (BL-52).
  - Module boundaries inside one process are kept by review and the per-module layout; nothing stops a direct import at runtime.
- **Follow-up backlog rows:** BL-15 and BL-17 (owner decisions, unchanged); BL-48 (Compose network classes and internal sidecar client, `CP-nn`); BL-49 (3.3 topology text drift); BL-52 (license scan of sidecar images).

## Open questions for the owner

1. Do you accept the sidecar rule (decisions 2 to 5), including the conditions under which project code in a second server-side language may exist?
2. BL-17: accept the Node render worker (one Node service, under decision 5), or keep Jinja2 in the API (no Node service)?
3. BL-15: when server printing is scheduled, should it use a Python path instead of the contract's Node `print-bridge/`?
4. Should SearXNG and LibreTranslate sit on a separate egress network segment, and should LibreTranslate get its models from egress at first start or from a volume prepared offline?
5. Do you confirm that calls to internal sidecars use the fixed-URL internal client rather than SafeFetcher? `CLAUDE.md` says all outbound HTTP in workers goes through SafeFetcher, and SafeFetcher rejects private addresses by design.


## Owner decisions at Gate G0 (2026-11-02)

The owner accepted the recommended default for every open question above:

- Q1 accepted: the sidecar rule, decisions 2 to 5.
- Q2 (BL-17) deferred to the M7 builder spike in Phase 4; Jinja2 stays the contract until then.
- Q3 (BL-15) accepted in principle: a future server print path is Python; nothing is built now.
- Q4 accepted: SearXNG and LibreTranslate on a separate egress segment; LibreTranslate downloads its models once at first start into a persistent volume, then runs without egress (BL-48).
- Q5 accepted: sidecar calls use the fixed-URL internal client; CLAUDE.md now limits SafeFetcher to external hosts.
