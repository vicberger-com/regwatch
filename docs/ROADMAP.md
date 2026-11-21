# regwatch roadmap: remaining actions

**As of:** 2026-11-19 (updated), branch `feat/M5-map`. Phases, gates and modules follow `docs/06-process.md` 6.1. Every item below cites its module spec, backlog row or review record. Sizes: S is one PR, M two or three, L four or more (each PR about 400 lines).

## Where things stand

| Phase | Status |
| --- | --- |
| P0 Discovery | done: G0 approved |
| P1 Foundation (M0, M1, M2) | done: G1 approved 2026-11-16 |
| P2 Capture and processing (M3, M4, M5) | done: G2 approved 2026-11-19 (acceptance 3 judged sequentially; the 10-user run continues under BL-118) |
| P3 Interface (M6, M9; M11 added) | done: G3 approved 2026-11-20 (adversarial session deferred to G5; manual screen-reader run in use testing round 2) |
| P4 Reports and outputs (M7, M8) | done: G4 approved 2026-11-21 (network printing by the owner's BL-15 decision; the adversarial session and the manual screen-reader run deferred to G5) |
| P5 Hardening (M10; M1b optional) | started 2026-11-21 |
| P6 | not started |

## 1. Owner actions (now)

| # | Action | Why |
| --- | --- | --- |
| O1 | Push in stack order: `sec/M3-web-page-followups`, `feat/M3-search`, then `feat/M4-items` (with `-u`) | agent `git push` is blocked |
| O2 | `make migrate` (applies 0004 and 0005). Check the dev data first if a hostile feed was ever configured, because 0005 marks existing items as fetched. | CP-14 fix, CP-19 |
| O3 | Confirm the M4 ASSUMPTIONS rows (Q1 to Q5 and Q7, recorded as assumed on "continue") | `docs/decisions/ASSUMPTIONS.md` |
| O4 | Set `general.contact_email` in admin settings | the capture user agent carries it |
| O5 | Decide the Argos de→en and ja→en models, whose license is unverified (BL-42), before translation ships | M4 acceptance 6 |

## 2. Finish M4 Processing and enrichment (`docs/modules/M4-processing-enrichment.md`)

| # | Slice | Detail | Size | Needs |
| --- | --- | --- | --- | --- |
| 4.1 | Item routes and N8 | `GET /items/{id}`, `GET /items/{id}/versions`, `GET /items/{id}/diff?from=&to=`, `POST /items/{id}/reprocess`, `POST /items/{id}/tags` (`assigned_by=user`), with permissions and OpenAPI contract tests. Also fix N8: any row that speaks for an item's host versions it whoever owns it, and the page's extracted title wins (BL-109 (a)). | M | none |
| 4.2 | Language detection | lingua-language-detector 2.2.0 (approved). Detect when a row has no language; set `translation_pending`. | S | — |
| 4.3 | Fuzzy near-duplicates | rapidfuzz 3.14.6 (approved). Token-set ratio on title above `processing.near_duplicate_ratio` (92), within the same jurisdiction and a 7-day window. Property test that dedupe is symmetric. | S | — |
| 4.4 | Sanitized HTML snapshot | Store nh3-sanitized HTML as `item_version.content_html_ref` (BL-106 (b)); XSS payload fixtures. | S | nh3 already in the register |
| 4.5 | PDF and XHTML text extraction | Text for body-only items (EUR-Lex XHTML, legislation, PDFs). This closes BL-107 (b) and R15 (BL-109 (b)): a fetched PDF may claim a summary-planted item. | M | a PDF library register row with a license check (owner approval) |
| 4.6 | Effective dates | Extract effective dates from text patterns (dateparser or python-dateutil, which is already in the register). | S | a register row if dateparser |
| 4.7 | Translation | `Translator` protocol with the providers `argos`, `libretranslate` (sidecar through the internal client) and `http`. Settings `translation.provider` and `translation.scope`, with per-source override; failures never block the pipeline. | L | O5; a CP for the compose sidecar |
| 4.8 | Model classifier (off) | `Classifier` protocol, `ModelClassifier` behind `classification.model` (off by default), versioned prompts, results validated against the term list, a network mock proving no call when off, prompt-injection fixtures. | M | — |
| 4.9 | Corpus and quality | A 200-document fixture corpus in 5 languages with expected tags; rule precision of at least 0.8 is reported. | M | — |
| 4.10 | Low residuals | BL-107 (a) index CP, (f) test gaps, (g) N3 sweep claim marker, (h) residuals | S to M | a CP for the index |
| 4.11 | Security reviews and completion | An independent review per slice (4.1, 4.5, 4.7, 4.8 at minimum), the M4 module summary, and a completion record proving acceptance 1 to 6 | M | — |

## 3. M5 Search and query (`docs/modules/M5-search-query.md`)

| # | Slice | Detail | Size |
| --- | --- | --- | --- |
| 5.1 | QueryCompiler | `Query` model to SQLAlchemy `Select`, reused by M7 and M8; facet counts; per-language FTS indexes | M |
| 5.2 | `POST /search` | Ranking, highlights, filters (jurisdictions, regions, terms, sources, status, severity, date ranges), sort, pagination | M |
| 5.3 | Map activity | `GET /map/activity`; refresh of `jurisdiction_activity`; the count matches search (acceptance 2) | S |
| 5.4 | Saved views | `GET`, `POST`, `PATCH` and `DELETE /views` with ownership checks | S |
| 5.5 | CSV export | `POST /search/export.csv`, streaming, 50,000 rows under 300 MB RSS (acceptance 4), CSV injection guarded | S |
| 5.6 | Performance | A 1-million-item synthetic dataset; p95 under 300 ms for search and 150 ms for the map (acceptance 3) | M |
| 5.7 | Reviews and completion | Independent security review and the completion record | S |

## 4. Gate G2 (end of P2)

Starter sources produce tagged, deduplicated items, and search and map activity meet the latency targets. Evidence goes in `docs/evidence/phase-2/`: M3, M4 and M5 completion records, review records, performance results and the change report. The owner approves the `Gate G2` issue, and the v1 API contracts are frozen.

## 5. Later phases (outline)

| Phase | Modules | Main work | Gate |
| --- | --- | --- | --- |
| P3 Interface | M6 shell and map UI, M9 user preferences | Shell, choropleth map, period, view and filter panels, item list and drill-down, three themes, keyboard and screen-reader journeys, use testing round 1 | G3 |
| P4 Reports and outputs | M7 report builder (Puck), M8 outputs (Gotenberg PDF, email, CSV, IPP print flag, schedules) | Stock templates, layouts bound to M5 queries, PDF identical to preview, output history and retention, use testing round 2 | G4 |
| P5 Hardening | M10 operations, M1b optional SSO | Metrics, traces, `/ready`, backup and restore drill, production Compose, Trivy, Semgrep, gitleaks, SBOMs; application-level security review and adversarial analysis | G5, release candidate |
| P6 Evaluation | all | Pilot group, feedback triaged into the backlog | G6, v1.0 |

## 6. Standing open items that cross phases

- BL-104 and BL-105 (M3 manual upload and search follow-ups): serve stored bodies as attachments with `nosniff`; shared-host official matching; store `unresponsive_engines` with each run (CP).
- BL-99 (e) and BL-107 (d): retention for `upload/`, `manual/` and full text copies.
- BL-102: `render_js` (Playwright) deferred.

## Next action

BL-118 (M5 acceptance 3), then the G2 gate: owner review of the phase-2 evidence, pushes in stack order, and `make migrate` (0004 to 0007).
