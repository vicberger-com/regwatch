# M5 Search and query API

**Phase:** P2 · **Size:** M · **Parallelism:** one session; M6 consumes it through the generated client.
**Requirements:** REQ-03, REQ-09, REQ-11 (data side), REQ-15 (query outputs)

## Purpose
One query model used by the toolbar search, filters, the map aggregation, saved views, report data sources and output jobs.

## Scope
In: full-text search with ranking and highlighting, faceted filters on taxonomy and jurisdictions, date ranges, sort, pagination, query DSL as JSON, saved views, map aggregation endpoint, CSV export streaming, facet counts.
Out: semantic search (optional pgvector, E5), natural-language query (E6).

## Interfaces
- `POST /search` body `Query{q?, filters: {jurisdictions[], regions[], terms{facet: [keys]}, sources[], status[], severity[], published: {from,to}, changed: {from,to}}, sort, page, page_size, highlight}` returns `{items[], total, facets{}, took_ms}`.
- `GET /map/activity?period_days=&filters=` returns per-jurisdiction `{code, count, last_changed_at, max_severity}`.
- `GET|POST|PATCH|DELETE /views` (saved views), `POST /search/export.csv` streaming.
- Python `QueryCompiler.compile(Query) -> SQLAlchemy Select` reused by M7 and M8.

## Data
`item`, `item_term`, `item_jurisdiction`, `change_event`, `saved_view`, materialized `jurisdiction_activity`.

## Open-source components
PostgreSQL full-text search with `websearch_to_tsquery`, pg_trgm for fuzzy title match, pgvector optional, Meilisearch (MIT) as a future adapter behind the same interface.

## Design notes
- Language-aware text search configurations per `item.language` (english, german, french, spanish, portuguese, simple fallback).
- Query DSL is validated with Pydantic and limited: at most 20 filter values per facet, page size 200, export cap 50 000 rows (admin-configurable).
- Facet counts computed with a single grouped query per facet, cached for 30 seconds per distinct query hash.
- Every search is logged (query hash, user, took_ms) for performance tuning; no raw query text in logs unless debug.

## Acceptance criteria
1. Searching "NIS2 incident" returns items with both terms ranked above items with one, with highlights.
2. Filtering by region Europe and topic data protection in the last 30 days returns the same count the map shows for the sum of European jurisdictions.
3. p95 latency under 300 ms for search and 150 ms for map activity on a 1 million item synthetic dataset.
4. CSV export of 50 000 rows streams without exhausting memory (under 300 MB worker RSS).

## Test plan
- Unit: compiler produces expected SQL for each filter; DSL validation.
- Integration: ranking fixtures, facet counts, export streaming.
- Load: k6 against search with 10 concurrent users.
- Security: SQL injection fixtures through the DSL, authorization filters (users without `items.read` get 403).

## Question bank
1. Which languages need stemming? Default: the six listed.
2. Is export of full text needed or metadata only? Default: metadata plus summary.
3. Should saved views be shareable across users? Default: yes, with `shared` flag and admin curation.

## Enhancements to propose
E5 semantic search with pgvector; E6 natural-language to query DSL; alerting on saved views (E1).
