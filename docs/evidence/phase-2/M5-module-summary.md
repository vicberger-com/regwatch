# M5 Search and query: module completion record

**Branch:** `feat/M5-search`, then `feat/M5-map` (stacked on M4). · **Date:** 2026-11-19 · **Status:** acceptance 1 to 4 met: 1, 2 and 4 by tests, 3 by the 1M-item load test on OpenSearch (ADR-0011). **Security:** every M5 slice is signed off (`M5-search-review.md`): search and views, slice 2 (map, export, facets, stemming), and the OpenSearch slices at `f831214`. No high or medium finding is open. At 10 concurrent users acceptance 3 is not met (search p95 814 ms, map p95 185 ms; BL-118).

## Acceptance criteria (`docs/modules/M5-search-query.md`)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | "NIS2 incident" ranks items with both terms above items with one, with highlights | **Met** | `tests/integration/test_search.py::test_more_of_the_words_rank_first_with_highlights`, `test_repeating_a_word_never_beats_having_both`, `test_an_old_item_with_every_word_is_still_the_best_match` |
| 2 | Region Europe, topic data protection, last 30 days: the search count equals the map's sum over European jurisdictions | **Met** | `tests/integration/test_map_activity.py::test_europes_map_rows_sum_to_the_search_total` |
| 3 | p95 under 300 ms for search and 150 ms for map activity on a 1 million item synthetic dataset | **Met on OpenSearch** | `tests/integration/test_perf_search.py` with `REGWATCH_PERF=1 REGWATCH_PERF_INDEX=1`: search p95 254 ms, map p95 48 ms, after a warm-up pass (cold: median 369 ms, worst 2.5 s); sequential. With 10 concurrent users: search p95 814 ms, map p95 185 ms, not met (BL-118). PostgreSQL alone measured p95 about 5 s (BL-118), hence ADR-0011 |
| 4 | A CSV export of 50,000 rows streams without exhausting memory (under 300 MB worker RSS) | **Met** | the load test: 50,000 rows with 17 MB peak Python allocations; the review measured 12.4 MB; `test_search_export.py` |

## Built

- **Query compiler** (`search/query.py`):
  - bound parameters only;
  - DSL limits enforced as 400s;
  - facets resolved to term ids;
  - websearch syntax;
  - severity in the query period;
  - M49 continents;
  - per-language stemming on the stored `search_vector_stemmed` (CP-21).
- **`POST /search`:**
  - ranking by the words matched, then `ts_rank_cd`, over a bounded candidate set;
  - escaped `<mark>` highlights;
  - facet counts, cached for 30 seconds;
  - 60 searches a minute per user;
  - a 5-second statement timeout, after which the route answers 503;
  - a keyed query hash in the logs.
- **Saved views** (`/views`): private views, plus shared views that need curation and are audited.
- **`GET /map/activity`:** by country or region, for a period, with the search's filters.
- **`POST /search/export.csv`:** streamed in short transactions, 20 an hour per user, one export at a time per user, audited, with formulas escaped.
- **Migrations:** 0006 (CP-20 indexes) and 0007 (CP-21 stemmed vector).
- **The OpenSearch index** (ADR-0011, CP-22; `search/index.py`, `indexed.py`, `tasks.py`):
  - a Compose service on the internal network with no published port (profile `index`), with the security plugin on, the stack's own CA, and two least-privilege users: `regwatch_search` for the API, read only, and `regwatch_indexer` for the worker;
  - documents fed from PostgreSQL by the pipeline, reprocessing and tag edits; `python -m regwatch.search.tasks` rebuilds every document;
  - search, facets and the map run on the index when it is configured; PostgreSQL answers when it is not configured or cannot be reached, and a slow index answers 503 after at most 4 s, with no database connection held while waiting.

## Decisions

- **ADR-0011 and CP-22:** OpenSearch as a sidecar (owner decision 2026-11-19).
- **CP-20** (owner approved).
- **CP-21** (accepted under the owner's standing instruction to take default recommendations; the owner may veto at G2).
- **Assumptions confirmed by the owner:** websearch syntax, the `total` cap, disabled sources staying searchable, and Europe including the EU and the Council of Europe.
- **Further assumption rows** cover map semantics, export order, candidate sets and stemming.

## Open

- **BL-118:** the k6 run with 10 concurrent users (acceptance 3 was measured sequentially).
- **BL-120:** index freshness after admin changes outside the pipeline.
- **BL-113:** a column for `saved_view.q`.
- **BL-114:** residual search findings.
- **BL-116:** using `jurisdiction_activity` for unfiltered maps; view by regulation or facet.
