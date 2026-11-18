# M3 Data capture framework and connectors

**Phase:** P2 · **Size:** XL · **Parallelism:** framework core first (one session), then one session per connector in parallel.
**Requirements:** REQ-02, REQ-04, REQ-05

## Purpose
Fetch data from configured sources on individual schedules with individual settings, store raw snapshots, and hand normalized candidates to the processing pipeline (M4).

## Scope
In: connector plugin interface, scheduler integration (Celery Beat reading `capture_job`), connectors: RSS and Atom, single web page with change detection, bounded web crawl, search query (metasearch or commercial API), API feeds (Federal Register, EUR-Lex SPARQL or RSS, legislation.gov.uk), manual upload (URL or file); per-job configuration UI; run history and source health; robots.txt and rate-limit enforcement; snapshot storage.
Out: authenticated or paywalled sources (backlog), browser automation beyond page rendering, social media.

## Interfaces
- Connector protocol (Python): `class Connector(Protocol): kind: str; config_schema: type[BaseModel]; async def discover(job, ctx) -> AsyncIterator[Candidate]; async def fetch(candidate, ctx) -> RawDocument; def health(job) -> HealthReport`.
- `Candidate{url, title?, published_at?, external_id?, hints: dict}`; `RawDocument{url, fetched_at, status, headers, body_ref, mime, text?, metadata}`.
- `GET|POST|PATCH /sources`, `POST /sources/{id}/test` (dry run returns first 5 candidates), `GET|POST|PATCH /capture-jobs`, `POST /capture-jobs/{id}/run-now`, `GET /capture-runs?job=&status=`, `GET /sources/{id}/health`.
- Celery tasks: `capture.run_job(job_id)`, `capture.fetch_candidate(run_id, candidate)`, `capture.schedule_tick()`.
- Event: `item.candidate` to M4 with `RawDocument` reference.

## Data
`source`, `capture_job`, `capture_run`, object store keys `snapshots/{item_id}/{version}.html`.

## Open-source components
feedparser (BSD-2), httpx (BSD-3), html5lib (MIT) with the project's own selectors and main-text heuristic (ADR-0009; trafilatura and readability-lxml dropped), Playwright Python (Apache-2.0) for `render_js`, changedetection.io (Apache-2.0, pattern), SearXNG (AGPL, service), protego (BSD-3, robots parser), tenacity (Apache-2.0) retries.

## Design notes
- All outbound HTTP goes through one `SafeFetcher` that resolves DNS, rejects private and link-local ranges, limits redirects to 5, enforces per-host rate limits in Valkey, sets a descriptive User-Agent with contact address from settings, honours robots.txt via protego unless `robots_policy=override` with a recorded reason, caps body size (default 10 MB) and timeouts (connect 10 s, read 30 s).
- Scheduling: Beat runs `schedule_tick` every minute; it enqueues jobs whose `next_run_at` has passed, with jitter and a per-source concurrency of 1.
- Single-page change detection: fetch, extract with rules or the built-in main-text heuristic (ADR-0009), normalize whitespace and strip volatile elements (dates, counters by selector), hash; unchanged hash short-circuits before M4.
- Crawl connector: seed URL, allowed domains, include and exclude regex, max depth 3, max pages 200 per run, politeness delay from job config; the project's own breadth-first crawl on SafeFetcher and the extraction child (ADR-0009 amendment 2; Scrapy dropped).
- Search connector: query string plus optional site filters and language; dedupes against known `url_hash`; results become candidates with `credibility=secondary` unless the domain is in an official-domains list.
- API feed connectors are thin adapters mapping provider JSON to `Candidate` and `RawDocument`; each documents the provider's terms in `config.terms_url`.
- Failures never retry more than 3 times per run; a source with 5 consecutive failed runs is flagged `unhealthy` and surfaces in the admin dashboard and daily digest.

## Acceptance criteria
1. An admin creates an RSS source, sets a 30-minute interval, runs it now and sees new items within 2 minutes; the run record shows counts.
2. A web page source with a CSS selector reports unchanged on a second run when the page is identical and changed when text differs beyond the threshold.
3. A URL pointing to `169.254.169.254` or `127.0.0.1` is rejected at configuration time and at fetch time.
4. A site disallowing the path in robots.txt is skipped with status `skipped` and reason recorded; an admin override requires a reason and is audited.
5. Rate limit of 10 requests per minute per host is respected under a crawl of 200 pages (verified by a local test server).
6. A search job against the metasearch service yields candidates deduplicated against existing items.

## Test plan
- Unit: SafeFetcher address validation, robots decisions, normalization and hashing, each connector's mapping with recorded fixtures (VCR-style cassettes via `pytest-recording`, MIT).
- Integration: local test HTTP server with feeds, pages and robots; Playwright rendering of a JavaScript page.
- E2E: source creation through UI to item visible in list.
- Security: SSRF suite, decompression bomb, oversized body, redirect to private range, HTML with script in extracted content (must be stripped before storage), malformed feeds.
- Load: 100 jobs due at once complete within 10 minutes on 2 workers.

## Question bank
1. Which sources are mandatory on day one? Default: starter list in section 4.5.
2. Is JavaScript rendering acceptable given its CPU cost? Default: yes, per-job opt-in.
3. May the application bypass robots.txt for any source? Default: admin override with reason only.
4. Which search provider and budget? Default: self-hosted metasearch; commercial key optional.
5. Should raw HTML snapshots be kept and for how long? Default: keep latest 10 versions per item.
6. Contact email for the User-Agent string? Default: admin email from settings.

## Enhancements to propose
E2 source health dashboard with uptime chart; E3 email alerts on unhealthy sources; sitemap connector; PDF document connector (official gazettes) using pdfminer.six (MIT).
