# ADR-0011: A search engine beside PostgreSQL for M5 latency (ADR-0002 decision 5)

**Status:** proposed, waiting for an owner decision · **Date:** 2026-11-19 · **Requirements:** REQ-03, REQ-09 · **Backlog:** BL-118, BL-07
**Research:** `tests/integration/test_perf_search.py` (1M items, corpus-derived distribution); `BACKLOG.md` BL-118; ADR-0002; ADR-0003; `docs/03-architecture.md` 3.5

## Context

**The target.** M5 acceptance 3 asks for p95 under 300 ms for search and under 150 ms for map activity, on 1 million items. ADR-0002 decision 5 provides for a Meilisearch adapter "if search p95 stays above 300 ms after index tuning".

**Measured on 1 million items** (tuned settings: 2 GB shared buffers, 32 MB work_mem):
- **Before tuning:** search p95 about 5 s, map p95 about 3.4 s.
- **The tuning pass** (owner approved 2026-11-19):
  - facet counts driven from the id list (1.2 s down to 20–250 ms);
  - every match read unordered first, so a rare word costs about 40 ms instead of 5 s;
  - one combined stemmed vector (CP-21);
  - the page ordered from the known ids.
- **After tuning:** search p50 about 1.4 s and p95 about 5 s; map p95 about 3.7 s.
- **What remains is structural:** broad filters (severity, region) are EXISTS joins over hundreds of thousands of items, and each request ranks or counts thousands of matches.

**Licenses checked** (2026-11-19):
- **Meilisearch** is no longer MIT alone. Its `LICENSE` declares `MIT AND OpenLDAP AND BUSL-1.1`.
  - The Enterprise Edition parts (sharding, S3 snapshots, search-rule previews) are under BUSL-1.1 and "not allowed in production without a commercial agreement".
  - The Community Edition is MIT plus OpenLDAP (LMDB, statically linked).
  - BUSL is prohibited in 3.5. OpenLDAP is not on the allowed list.
  - Which edition the published Docker image contains, and how Enterprise code is excluded from a build, is not documented on the pages read.
- **OpenSearch** is Apache-2.0, a JVM service. It is allowed, and heavier to run.

## Options

1. **Meilisearch Community Edition as an unmodified sidecar** (ADR-0002 decision 5).
   - It is fed from PostgreSQL by the pipeline, and search and facets run against it.
   - PostgreSQL stays the system of record; maps, views and exports stay on `QueryCompiler`.
   - This needs:
     - an owner decision on OpenLDAP and on running a repository that contains BUSL code;
     - a verified build or image without Enterprise code;
     - a register row;
     - a CP for the Compose service.
   - About 1 GB RAM for 1 million items.
2. **OpenSearch as a sidecar.**
   - The license is already allowed (Apache-2.0) and it has mature facets and aggregations. It could serve the map too.
   - It costs a JVM: 2 GB or more of heap, and more operations work (index templates, snapshots).
3. **Stay on PostgreSQL and change the target or the request.**
   - Facet counts and totals would come from a separate, cached request.
   - Unfiltered maps would come from the `jurisdiction_activity` rollup (BL-116 (a)).
   - The p95 target would apply to the page of results, not to facets.
   - This needs the owner to amend acceptance 3.

## Recommendation

**Option 2, OpenSearch,** if acceptance 3 must hold as written.
- Its license needs no exception.
- It serves both search and the map's aggregations, which option 1 does not.

**Option 3** if 50 users (the G2 sizing) does not justify a search cluster: it is the smallest change, and ADR-0002 chose to avoid a cluster.

Option 1 is not recommended until Meilisearch documents a production build without BUSL code.

## Consequences (for the option chosen)

- **Option 1 or 2:** a register row, a Compose CP (an internal network only, published nowhere; the builder-security rules apply), an indexing task in M4's pipeline, a reindex command, and an M5 adapter behind `search.services`.
- **Option 3:** an amendment to M5 acceptance 3 in `docs/modules/M5-search-query.md`, and a facets route or flag in a CP.
