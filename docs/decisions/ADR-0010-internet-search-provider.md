# ADR-0010: SearXNG, self-hosted and unmodified, as the internet search provider, for discovery only

**Status:** accepted by the owner on 2026-11-18 · **Date:** 2026-11-18 · **Requirements:** REQ-04, REQ-05, REQ-20
**Research:** R-07 (#9); BL-32, BL-33, BL-34, BL-46, BL-48; ADR-0001; ADR-0003 decision 2; `docs/modules/M3-capture-framework.md`

## Context

- **The connector.** M3's `search_query` connector runs a query (`connectors.yaml` `search_query`: query, site filters, languages, time range, at most 200 results, official domains only) and turns the results into candidates.
- **R-07.** The research measured SearXNG and compared commercial APIs on paper.
  - SearXNG is the only option that costs nothing at 200 to 500 queries a day and fits the license policy.
  - It is fragile. In R-07's benchmark 7 of 9 upstream engines were blocked or broken, and almost every useful result came from DuckDuckGo, which began serving CAPTCHAs after 7 queries.
  - The Exa and Brave free tiers cover only about 30 to 80 queries a day.
  - Brave's terms forbid keeping a database of results without a storage-rights plan.
- **The service boundary.** SearXNG is AGPL-3.0. ADR-0003 decision 2 allows it as a separate, unmodified service, pulled by digest and reached only over its API.
- **The network.** Two rules meet here:
  - SafeFetcher refuses private addresses, so the API cannot reach a sidecar through it. ADR-0001 says sidecars are called through a fixed-URL internal client.
  - SearXNG needs internet access, which the internal `regwatch` network does not give (BL-48).

## Decision

1. **Provider.** SearXNG, from the official image, unmodified, configured only by a mounted `settings.yml`, and pinned by digest. It runs in its own `search` container under the Compose profile `search`, off by default.
2. **Discovery only.** Search results are candidates with `credibility=secondary`, unless the domain is on the official-domains list. Official sources keep coming through the `rss`, `web_page`, `web_crawl` and `api_feed` connectors. Each result's page is fetched through SafeFetcher like any captured page, with robots.txt and rate limits; SearXNG is never asked for page content.
3. **Engines and pacing** (R-07 section 4):
   - DuckDuckGo, plus whichever of Brave, Google and Qwant answer from the production address. Bing and Wikipedia are off.
   - One query at a time across the deployment, at least 60 s apart with random extra spacing.
   - Search jobs default to daily or weekly.
4. **Health.** Each run stores SearXNG's `unresponsive_engines` with the run. A run where no engine answered, or only Bing, is a failed run, so the existing rule marks a source unhealthy after repeated failures (BL-33).
5. **No fallback key now** (BL-34). No query text leaves the deployment except through SearXNG's upstream engines. An Exa or Brave key behind the same provider interface can be added later by a new decision.
6. **Network (CP-18, BL-48).** Compose gets a second network, `egress`, which only the `search` container joins. The API and workers reach `search` on the internal `regwatch` network through the fixed-URL internal client (ADR-0001): one configured base URL, no redirects, a response size cap, timeouts, and only the JSON search endpoint. That client is never used for captured content.
7. **The soak test** (BL-32) stays open. If DuckDuckGo blocks at production pace, this ADR is revisited.

## Alternatives considered

| Option | Cost | Pros | Cons |
| --- | --- | --- | --- |
| **SearXNG, self-hosted (chosen)** | none | Within budget at the stated volume; covered by ADR-0003's service exception | Fragile upstream engines; CAPTCHAs; needs pacing and an egress network |
| SearXNG with an Exa or Brave free-tier fallback | none at free tier | Better coverage for priority queries | Query text leaves the deployment; Brave's storage terms; free tiers too small for the full volume |
| A paid API (Mojeek Business, Brave with storage rights) | about £15 to £50 a month | Stable; storage rights | Outside the zero budget (2.4 answer 12) |
| No search connector at launch | none | No fragile dependency | M3 scope names a search connector |

## Consequences

- The `search` service is pinned to `searxng/searxng@sha256:0b9f3ddd85efc8df189e6543d65702abfa8f3ed1c32229a53f7707cd12b554ef` (tag `2026.11.17-b99cf7496`, read from Docker Hub on 2026-11-18). Its register row is updated to match.
- CP-18 changes `deploy/compose.yaml`: the `egress` network, `search` on both networks, and its settings file mounted read-only.
- The search connector, the internal client and their tests come in their own pull requests, each reviewed like every capture slice.
