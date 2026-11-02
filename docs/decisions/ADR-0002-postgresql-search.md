# ADR-0002: PostgreSQL 16 as the system of record and the first search engine, with Meilisearch as a measured fallback

**Status:** accepted at Gate G0 on 2026-11-02 · **Date:** 2026-11-02 · **Requirements:** REQ-03, REQ-09, REQ-11 (also REQ-15, REQ-20)
**Research:** R-01 rows 5 and 6 (#3), R-07 (#9), R-08 (#11); `docs/03-architecture.md` 3.2; `docs/04-data-model.md` 4.3, 4.4; `docs/modules/M5-search-query.md`; `docs/contracts/schema.sql`

## Context

- **One store.** The data model has a fixed relational core, JSONB `attributes` validated against runtime facets (4.3, REQ-03, REQ-11) and a generated `search_vector`. 3.2 chose PostgreSQL to avoid running a search cluster for 50 users (G2).
- **Targets:**
  - Search under 300 ms p95 and map activity under 150 ms p95, on 1 million synthetic items (M5 acceptance criterion 3; 4.4).
  - A 50,000-row CSV export streamed in under 300 MB worker RSS (M5 criterion 4).
  - Search rate-limited to 60 requests per minute per user (8.2).
  - Gate G2 requires the latency targets to be met (6.1).
- **No measurement exists.** No research item measured PostgreSQL search latency, and the real corpus size is not established. The volume figures in the repository are an assumed 200 non-English items a day (R-08; `ASSUMPTIONS.md`) and 200 to 500 internet search queries a day (R-07). One million items is a design target, not a forecast.
- **What the contract indexes** (`schema.sql`):
  - `item.search_vector` uses the `simple` configuration over `title` plus `title_en` (weight A) and `summary` plus `summary_en` (weight B).
  - M5 adds per-language expression indexes for English, German, French, Spanish and Portuguese.
  - There is a trigram index on `title`, a `jsonb_path_ops` GIN index on `attributes` and the materialized view `jurisdiction_activity`.
  - `item_version.content_text` is not in any search index.
- **Languages without a PostgreSQL text-search configuration.** Chinese and Japanese are day-one languages (2.4 answer 2), and M5 has no configuration for them. R-08 found machine translation usable only for triage in zh and not adequate in ja (3 of 15 adequacy points).
- **Internet search is a weak source.** In R-07's SearXNG benchmark, 7 of 9 upstream engines were blocked or broken, and only 39 of 200 top-10 slots were relevant official sources. Result quality depended on which engine happened to be unblocked. R-07 recommends treating search as discovery only, with results at `credibility=secondary`.
- **Licenses:**
  - PostgreSQL: PostgreSQL License, verified at `REL_16_15` (`7d3e000`). pgvector: PostgreSQL License, verified at `f37c13f` (R-01 rows 5 and 6).
  - Meilisearch: MIT according to 3.2, but it has no register row and R-01 did not read its license file.
  - Elasticsearch: SSPL, ELv2 or AGPL (3.2). SSPL and the Elastic License are prohibited in 3.5.
  - OpenSearch: license not verified (no register row).

## Decision

1. **PostgreSQL 16 is the only system of record.** The object store holds snapshots and artifacts, referenced by key from PostgreSQL rows.
2. **M5 searches with PostgreSQL** and runs no search cluster at launch:
   - full-text search with `websearch_to_tsquery` over the contract's `search_vector`, plus M5's per-language expression indexes;
   - `pg_trgm` for fuzzy title matching;
   - JSONB GIN filters on attributes;
   - the `jurisdiction_activity` rollup for the map.
3. **Languages without a configuration** (zh, ja and others) are found through `title_en` and `summary_en` when translation ran, and through the `simple` vector otherwise. Search quality in those languages therefore depends on translation quality (R-08). This is a known limit, not a defect to fix in M5.
4. **Internet search is a capture source only** (M3 `search_query`). Its results become candidates like any other, deduplicated on `url_hash` and stored at `credibility=secondary` unless the domain is on the official list. The internal search never queries an internet provider at request time. Provider choice belongs to a separate ADR (BL-46).
5. **Measured fallback (BL-07).** Phase 2 runs the M5 benchmark: k6 with 10 concurrent users on the 1-million-item synthetic set from the fixtures task (#12). If search p95 stays above 300 ms after index tuning, M5 adds a Meilisearch adapter as a sidecar (ADR-0001) behind the M5 search service, fed from PostgreSQL. PostgreSQL stays the system of record, and the map aggregation, saved views and exports keep using `QueryCompiler` against PostgreSQL. Meilisearch enters only after its register row reaches status V.
6. **Elasticsearch is excluded on license grounds.** Its AGPL option would not qualify for the service-boundary exception, because permissive alternatives exist (ADR-0003 decision 2c). OpenSearch is not adopted, because no need for it has been shown.

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **PostgreSQL full-text search, pg_trgm, JSONB GIN (chosen)** | PostgreSQL (V) | One store, one backup, transactional consistency between items, tags and the search vector; no sync job | Latency at 1 million items not measured; no typo tolerance beyond title trigrams; no zh or ja tokenisation |
| Meilisearch sidecar | MIT per 3.2 (not verified; no register row) | Typo tolerance and relevance tuning out of the box | A second store to keep in sync; filters and the map rollup would still need PostgreSQL; needs a register row |
| OpenSearch cluster | not verified | Full search engine with language analysers | A cluster service to run and size on one host for 50 users; no need shown |
| Elasticsearch | SSPL, ELv2 or AGPL (3.2) | Same as OpenSearch | SSPL and ELv2 prohibited (3.5); AGPL use fails ADR-0003 decision 2c |

## Consequences

- **Positive:** one backup and restore path (M10); tags, attributes and search update in one transaction; three fewer moving parts at launch (search cluster, sync job, second backup).
- **Negative:**
  - The 300 ms and 150 ms targets are untested until Phase 2, so the BL-07 fallback may be needed late.
  - Under the current contract, only titles and summaries are searchable, not item full text.
  - Searching zh and ja items relies on English translation, which R-08 rated weak for ja.
  - Ranking is plainer than in a dedicated search engine.
- **Follow-up backlog rows:** BL-07 (Meilisearch adapter; trigger stated in decision 5); BL-46 (internet search provider ADR from R-07); BL-44 (route ja to a hosted translator, which would also improve ja search).

## Open questions for the owner

1. Should item full text (`item_version.content_text`) be searchable? The contract indexes titles and summaries only. Adding full text needs a `CP-nn` to `schema.sql`, and its effect on index size and latency is not measured.
2. Is search through English translations acceptable for zh and ja items, given R-08's finding on ja quality?
3. Do you accept the BL-07 trigger: search p95 above 300 ms at 1 million items with 10 concurrent users, after index tuning, with Meilisearch added as a sidecar while PostgreSQL stays the system of record?


## Owner decisions at Gate G0 (2026-11-02)

The owner accepted the recommended default for every open question above:

- Q1: not at launch; titles, summaries and English translations are searchable; revisit after the Phase 2 search benchmark.
- Q2: yes for Chinese; Japanese items also match their original-language title until a hosted provider is chosen (BL-44).
- Q3 accepted: the BL-07 trigger.
