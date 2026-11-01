# Test fixtures

The fixtures referenced by sections 7.2 and the module test plans do not exist yet. They are built in Phase 1 by the task below, before M3, M4 and M5 tests need them.

## Inventory and acceptance

| Path | Content | Built how | Acceptance |
| --- | --- | --- | --- |
| `tests/fixtures/corpus/` | 200 documents as `NNN.json` `{url, title, language, published_at, text, source_kind, expected: {jurisdictions: [codes], terms: {facet: [keys]}, severity}}` | Hand-collected from public-domain or openly licensed official sources (Federal Register, EUR-Lex summaries under its reuse notice, legislation.gov.uk under OGL, agency press pages that permit reuse); at least 20 each in en, de, fr, es, pt, ja, zh; each entry's licence and retrieval date in `corpus/NOTICES.md` | A validation script checks every entry against the JSON schema and that every expected term exists in the seed taxonomy |
| `tests/fixtures/feeds/` | `valid_rss.xml`, `valid_atom.xml`, `malformed.xml`, `huge_10mb.xml` (generated), `hostile.xml` (script in titles, external entities, deep nesting), `encoding_latin1.xml`, `future_dates.xml` | Hand-written plus generator script | feedparser tests cover each; hostile fixtures never execute or hang |
| `tests/fixtures/pages/` | `page_v1.html`, `page_v2.html` (5 percent change), `page_v3.html` (status line change only), `listing.html` with 30 links, `js_rendered.html` (content injected by script), `robots_allow.txt`, `robots_disallow.txt`, `robots_crawl_delay.txt`, `redirect_chain` config, `private_redirect` config, `zip_bomb.html.gz` | Hand-written; gzip bomb generated at build time, never committed | Change-detection tests show unchanged, changed, status-changed sequences |
| `tests/fixtures/synthetic/generate.py` | Deterministic generator (seed 42) for N items across 250 jurisdictions with realistic distributions of topics, dates, severities; writes SQL COPY files | Python script | 1 million items load in under 10 minutes; used by perf tests only |
| `tests/support/fixture_server.py` | aiohttp or FastAPI app serving the fixtures with configurable status codes, delays, redirect targets (including `127.0.0.1` and `169.254.169.254`), `Content-Length` lies, slow bodies, and gzip bombs | Python | Used by M3 integration and security tests; starts in under 2 seconds |
| `tests/security/payloads/` | XSS strings, prompt-injection passages, CSV formula injections, email header injections, oversized inputs | Text files, one payload per line with a comment header | Replayed by security tests and the adversarial record |

## Task card: Build test fixtures

**Module:** M0 (owned), consumed by M3, M4, M5 · **Phase:** P1 · **Requirements:** REQ-25 · **Labels:** `module:M0`, `phase:P1`, `type:test`

Goal: every path in the inventory exists with the stated acceptance met, and `make test-integration` can run against the fixture server. Licences for corpus entries are recorded; nothing non-redistributable is committed. Out of scope: performance runs themselves.
