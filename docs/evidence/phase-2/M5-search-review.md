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

## Slice 2 review (map `12aef60`, export `b5cf9a4`, facets `fcede35`, stemming `970161a`): not signed off

| # | Severity | Description | Fix | Verified |
| --- | --- | --- | --- | --- |
| S1 | high | An export held one pooled connection and an open transaction for the whole download, with no deadline; about 15 stalled downloads starve the pool. | the ids (at most the cap) in one statement, then a short transaction per batch; a 10-minute deadline; one export per user and four in all (429); slots of streams that never start expire | pending |
| S2 | medium | Export used the search rate and wrote no audit row (8.2: outputs 20 an hour, audited). | its own 20-an-hour window; `search.export` audited with the query hash and columns | pending |
| S3 | high | Stemmed matching recomputed `to_tsvector` per ranked candidate: 8-word and phrase searches 503 at 5 s on 55,000 items. | CP-21: a stored generated `search_vector_stemmed` with a GIN index (migration 0007, rewritten before release); ranking tests words against stored vectors only | pending |
| S4 | medium | A map severity filter always gave 500 (EXISTS auto-correlated to nothing). | every filter EXISTS has its own aliases and correlates to `item` | pending |
| S5 | medium | On the map, jurisdiction filters bound to the event's jurisdiction; the region view dropped EU and COE events. | the same item-tag meaning as search; the region view lists bodies with no region by their code; ASSUMPTIONS row | pending |
| S6 | medium | An export by relevance stopped silently at 10,000 rows. | exports by relevance are written newest change first, said in `X-Regwatch-Order` | pending |
| S7 | low | A naive `from` or `to` gave 500. | naive times are UTC | pending |
| S8 | low | Formula starts behind a space, a format character, or full-width signs were not escaped. | the check skips leading spaces and `Cf` characters; full-width `＝＋－＠` count | pending |
| S9 | low | Timeouts outside the page query gave 500s or a silently cut file. | map 503; facets omitted; export ends with a `#export stopped` line | pending |
| S10 | low | Language patterns were bound parameters, so a generic plan could not use the partial indexes. | constants (and the partial indexes are gone with CP-21) | pending |
| S11 | low | Facet counts under `jurisdictions`, not the contract's `jurisdiction`; sampling past 10,000 undocumented. | `jurisdiction`; documented | pending |

Checked and found fine: map filter JSON abuse all 400; map cost bounded; map contract shape; export format, BOM, CRLF, escaping, memory (12.4 MB peak for 50,000 rows) and client disconnect cleanup; the cursor timeout; index definitions and BitmapOr plans; 7,565 fuzzed queries across the configurations with no error; facet cost and cache.

**Sign-off at review:** not signed off (S1 to S4 blocking).

## Slice 2 re-verification (04a377e): signed off

**Signed off for security and correctness.** S1 to S11 fixed (S8 and S9 with small leftovers). Fixed after sign-off:

| # | Severity | Fix | Verified |
| --- | --- | --- | --- |
| R1 | medium | relevance candidates: the newest matches with every word plus the newest with any word; relevance `total` and paging are that set (ASSUMPTIONS row) | pending (M5 completion review) |
| R2 | low | each export frees its own slot | pending |
| R3 | info | ASSUMPTIONS wording | done |
| S8 rest | low | any space, line or paragraph separator, or format character before a formula start | pending |

Also after sign-off: `search_vector_stemmed` now holds the simple lexemes too, so one combined query uses one GIN index (BL-118 tuning).

## OpenSearch slices review (d9675b0, 5e806fa, a28f80d, 69d41b0): not signed off

An independent static review of the index sidecar, its client, the adapter and the indexing tasks (ADR-0011, CP-22). There were two blocking Medium findings:
- **1:** a slow index held pooled database connections, with no deadline on the index side.
- **2:** `regwatch_index` was wider than the code needs and was shared by the API and the worker.

There were six Low findings:
- **3:** passwords appeared on command lines.
- **4:** `--force` did not rotate passwords on an existing node.
- **5:** an unneeded internal superuser, and the admin key on the node.
- **6:** a malformed answer gave a 500.
- **7:** `title_asc` sorted by date.
- **8:** some changes never reached the index.

Two were Info: **9**, `index.env` reached beat and migrate; **10**, `or` was rewritten inside phrases.

The review also found these fine: no published port; the security plugin on with no demo configuration; the client's TLS, path allowlist and caps; fixed error texts; JSON-built queries with restricted `simple_query_string` flags; bounded aggregations; and the request cache keyed by the full body.

## OpenSearch re-verification (f831214): signed off

Findings 1 to 7, 9 and 10 are fixed. Finding 8 is BL-120. A live-node test (`test_the_api_reads_and_only_the_worker_writes`) checks the role split.

Remaining, not blocking:
- **The index name was not bumped.** The mapping gained `title.sort` while the index stays `regwatch-items-v1`. No stack outside the tests has built the index yet (the owner's `index-setup.sh` step is pending), so v1 stands.
- **Hash failures:** `index-setup.sh` now stops if a hash is empty.
- **Facet labels:** the label lookup in `_labelled` runs before the statement timeout is set. It is two small indexed queries, accepted.
