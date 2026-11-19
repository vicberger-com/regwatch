# Security review record: M5 search slice (query compiler, `POST /search`, highlights)

**Scope:** commit `163a98e`: `search/query.py`, `search/services.py`, `search/router.py` (`POST /search`), tests `test_search.py` and `test_search_highlight.py`. · **Reviewer session label:** M5 search independent review · **Date:** 2026-11-19 · **Author sessions excluded from review:** yes

## Method

Read against the contract, the M5 spec and `docs/08-security-compliance.md`; probes against the suite's throwaway PostgreSQL (`/tmp/m5-review/search/`): 3,018 fuzzed queries through the tsquery cast, planner timings by facet count, bind-parameter and offset limits, highlight properties. One probe (300 term facets) put that throwaway PostgreSQL into crash recovery, which is finding 1. Read-only otherwise.

## Findings

| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | critical | Unbounded term facets: each a four-table EXISTS; planning grew to 30 s and more at 300 facets, with no statement timeout; one 4 KB request crashed PostgreSQL. | at most 10 facets, resolved to term ids (`IN`), unknown facet 400; `SET LOCAL statement_timeout = '5s'` per search | verified (re-verification 1) |
| 2 | high | No search rate limit (8.2: 60 a minute per user). | 60 a minute per user, 429 with `Retry-After` | verified (re-verification 1) |
| 3 | medium | Unbounded lists and `page` gave 500s (bind-parameter limit, int8 offset). | at most 50 values a list, a 10,000-result window, 400 | verified (re-verification 1) |
| 4 | medium | Deep paging cost scaled with the offset. | the window cap; keyset paging later (BL-114 (c)) | verified (re-verification 1) |
| 5 | medium | The count kept the ORDER BY and ranked every match. | `order_by(None)`, capped at 10,001 | verified (re-verification 1) |
| 6 | medium | No `change_event(item_id)` index. | CP-20 (owner approved), migration 0006 (`068b994`) | pending (landed after re-verification 1) |
| 7 | medium | Repeating one word outranked having both. | matched distinct words first, then `ts_rank_cd` | verified (re-verification 1) |
| 8 | medium | `q` ignored the contract's websearch syntax. | websearch when the query uses it, else any-word; ASSUMPTIONS row | verified (re-verification 1) |
| 9 | medium | Severity ignored the query period. | events inside `filters.changed`, for the filter and the output | verified (re-verification 1) |
| 10 | medium | Region Europe missed EU-level items. | 150 includes EU and COE; ASSUMPTIONS row | verified (re-verification 1) |
| 11 | low | `casefold` and decomposed accents broke highlights. | `lower`, NFC on both sides, word boundaries by lookaround | verified (re-verification 1) |
| 12 | low | No highlights for English translations. | `title_en`, `summary_en` highlighted | verified (re-verification 1) |
| 13 | low | The logged query hash was an unkeyed SHA-256. | HMAC with the secret key | verified (re-verification 1) |
| 14 | low | Lone surrogates outside `q` gave 500. | every DSL string checked, 400 | verified (re-verification 1) |
| 15 | low | Test gaps (literal `\x00`, incorrect terms, a matching term filter). | tests added | verified (re-verification 1) |
| 16 | info | ASSUMPTIONS rows missing a column; a deleted item could raise `KeyError`. | rows fixed; skipped | verified (re-verification 1) |

## Checked and found fine

Bound parameters everywhere (the regconfig is a constant); no operator ever escapes the tsquery cast (3,018 inputs); highlight escaping (only `<mark>` tags ever appear); regex cost; authorization (anonymous 401, viewer allowed, Origin check); disabled sources' items stay searchable (ASSUMPTIONS row); filter logic; continent expansion; dates and time zones; NUL bytes 422; sort tie-breaks; no raw query text in logs.

**Sign-off at review:** not signed off (findings 1 to 3 blocking).

## Re-verification 1 (364e428): signed off

**Signed off for security.** Blocking findings 1 to 3 fixed (every cap at once plans in 116 ms; the timeout holds per transaction); 2, 4, 5, 7, 9, 10, 12 to 16 fixed; 8 and 11 partly. Not blocking, before M5 acceptance:

| # | Severity | Description | Fix | Verified |
| --- | --- | --- | --- | --- |
| N1 | medium | Relevance sorting computed up to 20 word tests and `ts_rank_cd` for every match: 2.4 s for 60k matching items, about 40 s projected at 1M, past the 5 s timeout. | only the first 10,000 matches (the most `total` says) are ranked; to be proven in the 1M-item load test (roadmap 5.6) | pending |
| N2 | low | A statement timeout reached the client as a 500. | 503 `busy` with `Retry-After` | pending |
| N3 | low | In websearch syntax `or` and excluded words were ranked and highlighted. | dropped from the words | pending |
| 11 (rest) | low | `İ` split by `lower()`; combining marks without a precomposed form split words. | words kept as written and matched ignoring case; words include combining marks | pending |
| 15 (rest) | low | No test that a user without `items.read` gets 403. | test added | pending |
