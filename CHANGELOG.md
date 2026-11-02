# Changelog

All notable changes to this project are recorded here. Format: Keep a Changelog; every line ends with issue and requirement IDs. A release section is cut at every phase gate.

## [Unreleased]

### Changed
- Claude Code GitHub Actions disabled (manual dispatch only); issue work runs as cloud sessions billed to the cloud session credit (REQ-26)
- Component register: 50 of 51 rows upgraded from S to V with the commit SHAs at which each LICENSE file was read. `ipp` (npm) stays at S because its repository has no LICENSE file. Register text corrected for the Puck package name (`@puckeditor/core`), the structlog dual license (MIT OR Apache-2.0) and the ScanCode data license (CC-BY-4.0) (#3, REQ-19, REQ-20)
- Owner approved the design package and the recorded Phase 0 answers; commit `6636de1` marks the baseline (#2, REQ-21, REQ-23)
- Owner answers to the Phase 0 questions recorded: China added to day-one jurisdictions, supply chain security added to topics, translation with a selectable provider added to M4, branding configuration and legal page added to M1, M6 and M7 (#1, REQ-02, REQ-03, REQ-16, REQ-17)

### Added
- ADR-0001 to ADR-0003 and ADR-0006 to ADR-0008 proposed (modular monolith with HTTP sidecars, PostgreSQL search, license policy and data terms, Celery and Valkey scheduling, local authentication then OpenID Connect, Gotenberg PDF), each with open questions for the owner; ADR index in `docs/decisions/README.md` and status column in 3.7 (#10, REQ-19, REQ-20, REQ-21)
- Research item R-08 results: `docs/research/R-08-translation-providers.md` benchmarks Argos Translate and LibreTranslate on 30 official passages in six languages, verifies code and model licenses and compares four hosted APIs; recommends LibreTranslate as the default provider, a hosted API by key, and `titles_summaries` scope; register rows added for translation components (#11, REQ-02, REQ-20)
- Research item R-07 search provider: SearXNG benchmark on 20 regulatory queries, commercial API comparison, recommendation of self-hosted SearXNG with a free-tier API fallback in `docs/research/R-07-search-provider.md` (#9, REQ-05)
- Research item R-04 IPP client: eight Node and Python clients evaluated, with a live `Print-Job` test against a local IPP reference server. `ipp` (npm) rejected; the first release ships browser printing only and the server print bridge is deferred (BL-13, BL-15) (#6, REQ-15, REQ-20)
- Research item R-05 map boundaries: Natural Earth 1:50m admin-0 simplified to a build-time GeoJSON, measured with MapLibre GL JS 6.16.0 against 1:110m, 1:10m, TopoJSON and PMTiles; ADR-0004 proposed; world-atlas and topojson-client dropped (BL-12, BL-25, BL-26) (#7, REQ-06, REQ-18)
- Research item R-06 official API terms: `docs/research/R-06-official-api-terms.md` records terms, licenses, robots rules and live endpoint checks for EUR-Lex/Cellar, the Federal Register API and legislation.gov.uk, with four contract-validated starter-source configurations (#8, REQ-04, REQ-05)
- Research item R-03 policy data sources: OpenSSF, UNCTAD, legislation.gov.uk, govinfo, NIST OSCAL and one AI tracker assessed as data sources or seeds; official sources for Canada, Australia, Japan, Singapore, Brazil and China verified in a follow-up pass; UNCTAD and India still unverified; starter-source and taxonomy changes proposed (BL-20 to BL-24) (#5, REQ-02, REQ-03, REQ-05)
- Claude Code GitHub Actions: interactive `@claude` and `claude`-label workflow, automatic pull request review workflow, root `CLAUDE.md` with the session rules (REQ-26)
- Contracts set for parallel sessions: M0 tooling decisions, OpenAPI 3.1 contract (68 paths, 58 schemas, validated), canonical DDL, registries (permissions, roles, settings, flags, tasks, events), environment variable contract, connector configuration schemas, screen inventory with design brief, fixtures inventory (REQ-01, REQ-25)
- Research item R-01 license verification: `docs/research/R-01-license-verification.md` covers 71 upstream repositories with release tag, commit SHA, license file and SPDX ID (#3, REQ-19, REQ-20)
- Research item R-02 report builder: Puck 0.24.0 has no keyboard drag and drop but its overrides allow keyboard alternatives, and its `Render` produces server HTML in Node; scored against dnd-kit, react-grid-layout and GrapesJS; ADR-0005 proposed (BL-16 to BL-19) (#4, REQ-12, REQ-13, REQ-18)
- Research item R-08 translation providers (#1, REQ-02)
- Design package `docs/` with requirements, architecture, data model, eleven module specifications, process, testing, security and backlog (REQ-01, REQ-19 to REQ-27)
- Agent templates for task cards, handoffs, ADRs, questioning issues, pull requests, component evaluations, security reviews, adversarial records and use-testing scripts (REQ-23, REQ-25)
- GitHub bootstrap script for labels and Phase 0 issues (REQ-26)
