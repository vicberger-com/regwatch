# M3 Capture framework: module completion record

**Prepared by:** lead session · **Build under review:** `feat/M3-search` (top of the M3 stack) · **Date:** 2026-11-18 · **Gate:** M3 has no gate of its own; G2 closes Phase 2 after M4 and M5 (`docs/06-process.md`). This record is the M3 input to G2.

## Acceptance criteria (`docs/modules/M3-capture-framework.md`)

| # | Criterion | State | Evidence |
| --- | --- | --- | --- |
| 1 | An admin creates an RSS source with a 30-minute interval, runs it now and sees new items within 2 minutes; the run shows counts | **Met for M3.** The run, its counts and its manifest are M3's. Items are made from the manifest by M4, so "sees new items" is proven at G2 | `tests/integration/test_capture_runs.py::test_an_rss_source_runs_end_to_end`, `test_run_now_queues_once_and_is_audited` |
| 2 | A web page with a CSS selector is unchanged on an identical second run, and changed when the text differs beyond the threshold | **Met for M3, threshold in M4.** Identical text is `unchanged`. Any other text goes to M4 as `changed`; M4's spec owns the threshold (characters, and status changes always count) | `tests/unit/test_connector_web_page.py::test_first_run_then_unchanged_then_every_change`; ASSUMPTIONS 2026-11-18 |
| 3 | URLs to `169.254.169.254` or `127.0.0.1` are refused when saved and when fetched | **Met** | `tests/integration/test_sources.py` (invalid sources); `tests/unit/test_safe_fetch_*.py` (100 % floor) |
| 4 | A path robots.txt disallows is skipped with its reason; an override needs a reason and is audited | **Met** | `tests/unit/test_capture_execution.py::test_the_start_is_refused`; source routes tests; `M3-source-routes-review.md` |
| 5 | 10 requests a minute per host under a 200-page crawl, on a local test server | **Met** | `tests/unit/test_connector_web_crawl.py::test_ten_a_minute_under_a_200_page_crawl` (simulated clock, every request timed; a mutant at 120 a minute fails it) |
| 6 | A search job yields candidates deduplicated against existing items | **Met for M3, existing items in M4.** Results are deduplicated within the run; existing items are M4's table | `tests/unit/test_connector_search_query.py` |

## Connectors and their security reviews

Every slice had an independent security review, with its fixes re-verified before sign-off (CLAUDE.md).

| Slice | Record | Sign-off |
| --- | --- | --- |
| SafeFetcher | `M3-safe-fetch-review.md` | signed off |
| Source routes | `M3-source-routes-review.md` | signed off |
| Scheduler and runs | `M3-scheduler-review.md`, `M3-run-connectors-review.md` | signed off |
| Sources screen | `M3-sources-ui-review.md` | signed off |
| Dry run and job cursor (CP-13, CP-14) | `CP-13-14-review.md` | signed off |
| RSS and Atom | `M3-rss-connector-review.md` | signed off (owner accepted residual risk, BL-91 (e), (f)) |
| API feed: Federal Register | `M3-api-feed-review.md` | signed off |
| API feed: legislation.gov.uk | `M3-legislation-review.md` | signed off |
| API feed: EUR-Lex | `M3-eurlex-review.md` | signed off |
| HTML extraction (ADR-0009) | `M3-html-extract-review.md` | signed off |
| Web page, single mode | `M3-web-page-review.md` | signed off |
| Web page, listing mode | `M3-web-listing-review.md` | signed off (re-verification 3) |
| Bounded crawl (ADR-0009 amendment 2) | `M3-web-crawl-review.md` | signed off (re-verification 9) |
| Manual documents (CP-17) | `M3-manual-upload-review.md` | signed off |
| Search (ADR-0010, CP-18) | `M3-search-review.md` | signed off |

## Not built in M3, by decision

| Item | Decision | Record |
| --- | --- | --- |
| `render_js` (Playwright) | Deferred until after M4 (owner, 2026-11-18) | BL-102 |
| `generic_json` API feed adapter | Not in M3's scope; a later phase | BL-22 |
| `follow_sitemaps` on the crawl | Not built; answers `not-implemented` | BL-101 (a) |

## Decisions made during M3

- **ADRs:** ADR-0006 amendment 1, the run lock in PostgreSQL; ADR-0009 with amendments 1 and 2, own extraction in an isolated child, and own crawl instead of Scrapy; ADR-0010, SearXNG for discovery only.
- **CPs:** CP-11 to CP-18. CP-14 had a null-cursor fix, migration `0004`.
- **Register:**
  - html5lib 1.1 and webencodings 0.5.1 added;
  - trafilatura, readability-lxml and Scrapy marked not used;
  - SearXNG pinned by digest.

## Open follow-ups for M3 (backlog)

BL-88 to BL-105 hold the review follow-ups that were deferred, each accepted by its reviewer. Those that touch M4 or later:
- BL-99 (e) and BL-104 (b): retention of `raw/`, `text/`, `upload/` and `manual/` objects;
- BL-104 (a): any route that serves stored bodies must serve them as attachments with `nosniff` and a sandbox CSP;
- BL-104 (c): M4 must handle `urn:sha256:` URLs, `upload/` keys and `changed` documents with no previous text;
- BL-105 (b): storing `unresponsive_engines` with every run needs a CP.

## Owner items

1. Push the M3 branches, in stack order (listed in the lead session).
2. Run `make migrate` for migration `0004`.
3. Confirm the ASSUMPTIONS rows dated 2026-11-18: the threshold moving to M4, and the official-domains derivation.
4. Set `general.contact_email` in Settings; legislation.gov.uk refuses anonymous user agents.
5. BL-96 (a) and BL-105 (c) need a networked session with the real images and sites.
