# R-07: Internet search provider for the first release

**Issue:** #9 · **Module:** M3 · **Requirements:** REQ-05 (also REQ-02, REQ-20) · **Date:** 2026-11-01
**Inputs:** `docs/02-requirements.md` 2.4 answer 12 (search budget zero, self-hosted first), G11; `docs/03-architecture.md` 3.2 (internet search row), 3.5, 3.8; `docs/contracts/connectors.yaml` `search_query`; `docs/modules/M3-capture-framework.md`.

## Question

Which internet search provider should the M3 `search_query` connector use in the first release (Phase 2)?

## Answer in brief

Use **self-hosted SearXNG** (official image, unmodified, separate `search` container) as the Phase 2 provider, but only as a discovery supplement to the RSS, web page and API feed connectors, and with the engine set and pacing below. It is the only option that costs nothing at 200 to 500 queries a day and fits the license policy. It is fragile: in this benchmark 7 of 9 configured upstream engines were blocked or broken, and almost every useful result came from DuckDuckGo (and Yahoo when its page parsed). DuckDuckGo started serving CAPTCHAs after 7 queries, and in a repeat run only answered 9 of 20 queries. Fallback: the **Exa** or **Brave Search API** free tier behind the same provider interface, for a small set of high-value queries (about 30 to 80 a day), after the owner accepts the terms noted in the comparison. Neither free tier covers the full volume.

## 1. Benchmark query set (written before any query ran)

Grading: **O** relevant official source (government, regulator, legislature, official journal, official CERT); **S** relevant secondary source (law firm, reputable press, legal information institute, Wikipedia article on the instrument); **I** irrelevant, generic or off-topic. A "good result" lists what an analyst would expect in the top 10.

| ID | Jurisdiction | Topic | Query | Good result looks like |
| --- | --- | --- | --- | --- |
| Q01 | EU | product security | Cyber Resilience Act vulnerability reporting obligations ENISA single reporting platform | EUR-Lex Regulation (EU) 2024/2847; digital-strategy.ec.europa.eu CRA pages; enisa.europa.eu |
| Q02 | EU | AI governance | EU AI Act general-purpose AI model obligations code of practice | digital-strategy.ec.europa.eu GPAI code and guidelines; EUR-Lex Regulation (EU) 2024/1689 |
| Q03 | EU | cloud and outsourcing | DORA ICT third-party service providers register of information | EUR-Lex Regulation (EU) 2022/2554 and ITS; EBA, EIOPA, ESMA pages |
| Q04 | US | incident reporting | CIRCIA final rule cyber incident reporting critical infrastructure | cisa.gov CIRCIA page; federalregister.gov docket |
| Q05 | US | incident reporting | SEC cybersecurity incident disclosure Form 8-K Item 1.05 | sec.gov final rule 33-11216, fact sheet, C&DIs |
| Q06 | US | supply chain security | NIST SP 800-161 cybersecurity supply chain risk management | csrc.nist.gov publication page; nist.gov C-SCRM |
| Q07 | UK | critical infrastructure | Cyber Security and Resilience Bill | bills.parliament.uk bill page; gov.uk collection and factsheets |
| Q08 | UK | product security | PSTI Act security requirements for consumer connectable products | gov.uk guidance; legislation.gov.uk 2022 c.46 and SI 2023/1007 |
| Q09 | CA | critical infrastructure | Bill C-8 Critical Cyber Systems Protection Act | parl.ca LEGISinfo; publicsafety.gc.ca or canada.ca backgrounder |
| Q10 | CA | data protection | PIPEDA breach of security safeguards reporting requirements | priv.gc.ca guidance and form; laws-lois.justice.gc.ca regulations |
| Q11 | AU | incident reporting | Cyber Security Act 2024 ransomware payment reporting | homeaffairs.gov.au, cyber.gov.au; legislation.gov.au Act and rules |
| Q12 | AU | digital identity | Digital ID Act 2024 accreditation rules | digitalidsystem.gov.au; legislation.gov.au; finance.gov.au |
| Q13 | JP | critical infrastructure | Japan active cyber defense law critical infrastructure incident reporting | cas.go.jp or nisc.go.jp; reputable secondary acceptable |
| Q14 | JP | AI governance | Japan AI Promotion Act | cao.go.jp or cas.go.jp; e-Gov law text; reputable secondary |
| Q15 | SG | cybersecurity | Singapore Cybersecurity (Amendment) Act 2024 | csa.gov.sg; sso.agc.gov.sg; parliament.gov.sg |
| Q16 | IN | data protection | Digital Personal Data Protection Rules 2025 notified MeitY | meity.gov.in; egazette.gov.in; pib.gov.in |
| Q17 | IN | incident reporting | CERT-In directions six hours cyber incident reporting | cert-in.org.in directions and FAQ; meity.gov.in |
| Q18 | BR | incident reporting | ANPD regulamento de comunicação de incidente de segurança | gov.br/anpd page for Resolução CD/ANPD 15/2024; in.gov.br |
| Q19 | CN | cybersecurity | 网络安全法 修正 2025 施行 | npc.gov.cn amendment decision; cac.gov.cn; gov.cn |
| Q20 | CN | cross-border data transfer | CAC provisions on promoting and regulating cross-border data flows | cac.gov.cn provisions; reputable English translations (S) |

Coverage: all ten day-one jurisdictions; eleven topics; three non-English queries (Q18 Portuguese, Q19 Chinese) or queries whose best sources are not in English (Q13, Q14, Q20).

## 2. SearXNG measurement

### 2.1 Setup

- Image: `searxng/searxng:latest`, digest `sha256:4b106e61eeb9e216ac96c85591338c1e9ceb5a84c26f72cd18b8ba8f0f52093c`, version label `2026.11.1-8b35dcd2e` (revision `8b35dcd2e312`). Not modified, not rebuilt; configuration by mounted `settings.yml` only.
- Host: a cloud container (Docker 29.9.2) whose egress leaves through a shared datacenter proxy. Upstream engines see a datacenter address, as they would from a hosted Linux server (G1); a residential address would likely be blocked less. This is the main limit on how far the numbers generalise.
- Engines enabled: google, bing, duckduckgo, brave, startpage, qwant, mojeek, yahoo, wikipedia. Startpage and Mojeek never ran: the upstream default settings mark both `inactive: true` because they now use proof-of-work CAPTCHAs, so they cannot be enabled from configuration.
- Run 1: the 20 queries in order, one every ~9 s, `categories=general`, no time range (the connector default `month` would hide the stable official pages this benchmark looks for). Run 2: the same set repeated after a 20-minute pause, one every ~16 s, to check repeatability.

Configuration excerpt (`settings.yml`, mounted read-only at `/etc/searxng/settings.yml`; the secret came from `SEARXNG_SECRET` and is not recorded):

```yaml
use_default_settings:
  engines:
    keep_only: [google, bing, duckduckgo, brave, startpage, qwant, mojeek, yahoo, wikipedia]
server:
  bind_address: "127.0.0.1"
  port: 8888
  limiter: false          # private instance; only the worker calls it
  public_instance: false
  image_proxy: false
search:
  safe_search: 0
  formats: [html, json]
outgoing:
  request_timeout: 6.0
  max_request_timeout: 12.0
  proxies:
    all://: http://127.0.0.1:40783   # this test host's egress proxy; not needed in production
engines:
  - {name: google, disabled: false}
  - {name: bing, disabled: false}
  # ... same for duckduckgo, brave, startpage, qwant, mojeek, yahoo, wikipedia
```

Commands:

```sh
docker pull searxng/searxng:latest
docker run -d --name r07-searxng --network host \
  -e SEARXNG_SECRET="$(openssl rand -hex 32)" \
  -e GRANIAN_HOST=127.0.0.1 -e GRANIAN_PORT=8888 \
  -v "$PWD/settings.yml:/etc/searxng/settings.yml:ro" \
  -v /root/.ccr/ca-bundle.crt:/usr/local/share/ca-certificates/egress-ca.crt:ro \
  searxng/searxng:latest
# per query (runner: 8 s or 15 s pause between queries, 30 s client timeout)
curl -s "http://127.0.0.1:8888/search?q=<urlencoded query>&format=json&categories=general"
```

Two host-specific details: `GRANIAN_HOST` overrides the image default `::` because the test host has no IPv6, and the CA mount lets the image's own `update-ca-certificates` step trust the test egress proxy. Neither is needed on a normal host.

### 2.2 Run 1 scores (top 10 per query)

Position string: one letter per rank 1 to 10 (O, S, I as in section 1). "Answering engines" are the engines that contributed any top-10 result.

| ID | Latency (s) | Answering engines | Positions 1-10 | O | S | I | Best official hit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Q01 | 3.31 | bing, ddg | IOIOIOISIO | 4 | 1 | 5 | digital-strategy.ec.europa.eu/en/policies/cra-reporting |
| Q02 | 1.20 | bing, ddg | IOISIOISIO | 3 | 2 | 5 | digital-strategy.ec.europa.eu/en/policies/contents-code-gpai |
| Q03 | 1.23 | bing, ddg, yahoo | SSSIOISIOO | 3 | 4 | 3 | eba.europa.eu ITS on the register of information |
| Q04 | 6.01 | bing | IIIIIIIIII | 0 | 0 | 10 | none (ten Microsoft support pages) |
| Q05 | 1.37 | bing, ddg | IOIOISISIS | 2 | 3 | 5 | sec.gov small-business compliance guide |
| Q06 | 1.20 | bing, ddg, yahoo | OOIOIOSISI | 4 | 2 | 4 | csrc.nist.gov/pubs/sp/800/161/r1/upd1/final |
| Q07 | 0.79 | bing, ddg | IOIOIOISIO | 4 | 1 | 5 | bills.parliament.uk/bills/4035 |
| Q08 | 0.70 | bing, yahoo | IOIOISISIO | 3 | 2 | 5 | gov.uk/guidance/regulations-consumer-connectable-product-security |
| Q09 | 6.01 | bing | IIIIIIIIII | 0 | 0 | 10 | none (bill.com, utility bill pages) |
| Q10 | 1.02 | bing, ddg | IOIOISISIO | 3 | 2 | 5 | laws-lois.justice.gc.ca SOR-2018-64 |
| Q11 | 0.85 | bing | IIIIIIIIII | 0 | 0 | 10 | none (dictionary pages for "cyber") |
| Q12 | 0.75 | bing, ddg | IOIOIOIOIS | 4 | 1 | 5 | legislation.gov.au/F2024L01438 |
| Q13 | 0.81 | bing | IIIIIIIIII | 0 | 0 | 10 | none (Japan travel pages) |
| Q14 | 0.89 | bing | IIIIIIIIII | 0 | 0 | 10 | none (Japan travel pages) |
| Q15 | 0.87 | bing, ddg | IOIOIOISIO | 4 | 1 | 5 | sso.agc.gov.sg Acts-Supp/19-2024 |
| Q16 | 0.80 | bing, ddg | IOIOIOISIS | 3 | 2 | 5 | meity.gov.in DPDP Rules 2025 page |
| Q17 | 0.82 | bing, ddg | ISISISISIO | 1 | 4 | 5 | cert-in.org.in/Directions70B.jsp |
| Q18 | 0.36 | bing | IIIIOIIIII | 1 | 0 | 9 | gov.br/anpd home page only |
| Q19 | 0.91 | bing | IIIIIIIIII | 0 | 0 | 10 | none (unrelated Reddit threads) |
| Q20 | 0.75 | bing | IIIIIIIIII | 0 | 0 | 10 | none (US military Common Access Card) |
| **Total** | median 0.88, max 6.01 | | | **39** | **25** | **136** | 13 of 20 queries have an official hit |

Scoring notes: Q06 rank 3 (`csrc.nist.rip`, an unofficial mirror) is scored I, because the connector must not treat lookalike domains as official. Agency home pages with no link to the instrument (sec.gov, nist.gov) are I; Q18's gov.br/anpd home page is scored O as the only pointer to the right agency.

Per engine, run 1 (top-10 slots filled, and how many were O or S; a result found by two engines counts for both): Bing 137 slots, 2 relevant; DuckDuckGo 58 slots, 57 relevant; Yahoo 16 slots, 15 relevant. From this host, Bing answers but ignores most of the query (often matching only the first word: "cyber", "Japan", "Bill", "CAC"), so its results push relevant ones down and fill whole pages when DuckDuckGo is missing.

### 2.3 Failures, blocking and CAPTCHAs

| Engine | Run 1 (20 queries) | Run 2 (20 queries, after 20 min) |
| --- | --- | --- |
| Google | access denied on all 20; suspended | same, all 20 |
| Qwant | access denied on all 20; suspended | same, all 20 |
| Brave (web scraping, not the API) | HTTP 429 on all 20; suspended | same, all 20 |
| DuckDuckGo | answered 11; first CAPTCHA at Q08 (about 1 minute in), then CAPTCHA on 7 and timeout on 2 of the remaining 13 | answered 9 (a different set, including Q04, Q18, Q20); CAPTCHA 7, timeout 4 |
| Yahoo | parsing error 16, HTTP 500 1; answered 3 | parsing error 16; answered 4 |
| Wikipedia | HTTP 429 on 19 | HTTP 429 on 20 |
| Bing | always answered; results mostly off-topic (2.2) | always answered; again off-topic, and different off-topic pages for the same query (Q08, Q19 overlap 0 of 10 with run 1) |
| Startpage, Mojeek | not loadable (`inactive` upstream, proof-of-work CAPTCHA) | same |

No request to SearXNG itself failed; it always returned within 6.1 s, because blocked engines are suspended rather than retried. The failure mode is silent: a JSON response with fewer or worse results and an `unresponsive_engines` list.

Run 2 (median latency 1.27 s, max 6.01 s, no errors) was not hand-scored again; it is used for repeatability. Top-10 overlap with run 1 averaged about 6 of 10 URLs. Results from DuckDuckGo or Yahoo filled 55 top-10 slots in run 2 against 63 in run 1; in run 1, 62 of those 63 were relevant (O or S). Across both runs, a non-Bing engine answered 15 of the 20 queries at least once. Run 2 found the expected official sources for three queries that got nothing in run 1: Q04 (cisa.gov CIRCIA pages, federalregister.gov docket 2026-02948), Q18 (in.gov.br Resolução CD/ANPD 15/2024, gov.br/anpd) and Q20 (english.www.gov.cn and chinalawtranslate.com). So result quality depends on which engine happens to be unblocked, not on the query. Q09, Q11, Q13, Q14 and Q19 (Canada, Australia, both Japan queries, Chinese-language) never reached a working engine, so this benchmark says nothing about DuckDuckGo's quality for them.

### 2.4 Operational burden

- Upstream engines treat a self-hosted instance as a scraper. From a datacenter address, Google, Qwant and Brave refused from the first query, and DuckDuckGo started CAPTCHAs within about a minute of steady use. SearXNG's engine code changes with the upstream sites; the project ships near-daily images, and engines get marked `inactive` when a site adds proof-of-work checks (Startpage, Mojeek). Expect to pull new images often and re-check which engines still work.
- At 200 to 500 queries a day the steady rate is one query every 3 to 7 minutes, far gentler than this benchmark. Whether DuckDuckGo tolerates that over weeks is not measured here (BL-27).
- Because degradation is silent, the connector has to read `unresponsive_engines` and record it in `capture_run`; otherwise a source looks healthy while returning dictionary pages.
- Running costs: one small container, no key, no fee. AGPL-3.0 is acceptable as an unmodified service behind the network boundary (3.5); the register row is unchanged.

## 3. Commercial search APIs (documentation only; nothing measured)

No API key was available, so none of these was queried. Volume assumed: 200 to 500 queries a day, about 6,000 to 15,000 a month. Pages read 2026-11-01.

| Provider | Price | Free tier | Free tier at 6k to 15k/month? | Rate limit | Storing results | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Brave Search API (Search plan) | $5 per 1,000 | $5 credit per month (about 1,000 queries) | No; about $25 to $70 a month beyond credit | 50 qps | Terms 3(b)(i): may not "store, cache, or create a database of Search Results", except transient storage; storage rights only "with a plan that includes storage rights" (sales); no AI training use (3(b)(xiii)) | Independent index; zero data retention only on Enterprise |
| Exa | $4 per 1,000 (`lite`/`instant`) to $7 (`auto`/`fast`) | $10 credit, reset monthly (up to 2,500 lite searches); no card | No; about $14 to $50 a month beyond credit (lite) | not published (custom on Enterprise) | No clause found restricting storage of Output; Exa takes a perpetual licence to store and use queries and Output to improve its services | Neural index; zero data retention only on Enterprise |
| Tavily | 1 credit basic, 2 advanced; $0.008 per credit pay-as-you-go; plans from $30 (4,000) to $500 (100,000) | 1,000 credits per month | No; about $40 to $112 a month | not published on the credits page | No explicit storage rule; internal business use only; Tavily may retain and use queries with no stated period | Built for LLM agents |
| Mojeek Web Search API | £2 per 1,000 (Startup), £3 (Business) | one-off free credit; card required | No; about £12 to £45 a month | 5 qps and 100,000/day (Startup) | Startup: cache results for one hour; Business: storage rights with indefinite retention; 90-day standard retention, ZDR on request | Independent index; clearest storage terms |
| Google Programmable Search (Custom Search JSON API) | $5 per 1,000 after 100/day, cap 10,000/day | 100 queries a day | Partly (100/day) | 10,000/day | n/a | "Closed to new customers"; existing customers must move by 2027-01-01. Excluded |
| Bing Web Search API | n/a | n/a | n/a | n/a | n/a | Retired 2025-08-11; successor "Grounding with Bing Search" works only inside Azure AI Agents and does not return raw results. Excluded |

Keyless access: none of the four live options offers lawful keyless API access, so no commercial query was run.

Sources: brave.com/search/api, api-dashboard.search.brave.com/terms-of-service, exa.ai/pricing, Exa Labs Terms of Service (PDF on exa.ai), docs.tavily.com/documentation/api-credits, tavily.com/terms, mojeek.com/services/search/web-search-api, developers.google.com/custom-search/v1/overview, learn.microsoft.com lifecycle announcement "Bing Search API retirement".

## 4. Recommendation

**Phase 2 provider: SearXNG, self-hosted, unmodified.** It is the only option within the zero budget at the stated volume, and it fits the existing provider interface (G11, 3.2). Conditions for the M3 search connector:

1. Treat search as discovery, not as the system of record for official sources. Day-one official sources come through `rss`, `web_page` and `api_feed` jobs. Search results stay `credibility=secondary` unless the domain is on the official-domains list, as the M3 spec already says.
2. Engine set: DuckDuckGo plus whichever of Brave, Google and Qwant answer from the production address (check at install). Disable Bing unless a check from the production address shows on-topic results; in this benchmark it was 137 off-topic slots out of 200. Wikipedia added nothing here (HTTP 429 on 19 of 20) and can stay off.
3. Pace jobs: one query at a time, randomized spacing of at least 60 s, and default search jobs to daily or weekly. Prefer `site_filters` and `official_domains_only` so each query asks for fewer, better results.
4. Read `unresponsive_engines` from every response, store it with the `capture_run`, and count a run with no answering engine except Bing as failed so the existing 5-failure rule marks the source `unhealthy`.

**Fallback: Exa free tier (first) or Brave Search API free tier**, configured by key in the same provider interface, used only for a short list of priority queries (about 30 to 80 a day) or when SearXNG reports no usable engine. Exa's free credit is larger and its terms found no storage restriction; Brave's index is independent but its terms forbid keeping a database of results without a storage-rights plan, which the connector does by storing candidates. Either needs the owner to accept that query text leaves the deployment (queries are topic strings, not captured content, so G6 is not engaged).

**What would change this:**
- A budget of roughly £15 to £50 or $25 to $75 a month: Mojeek Business (storage rights, published limits) or Brave with storage rights becomes the primary provider, with SearXNG as the free fallback.
- A soak test (BL-27) from the production host showing DuckDuckGo blocks at production pace: SearXNG becomes unusable unattended, and the fallback API becomes primary even at a cost, or search is cut back to free-tier volume.
- Search volume falling below about 30 a day once the feed and API connectors are in place: a free commercial tier alone would cover it with less maintenance.
- A change to Exa's or Brave's free tier or terms; recheck both before Phase 2 starts.

## 5. Component evaluation: SearXNG

**Capability needed:** internet search for the `search_query` connector · **Module:** M3 · **Repository URL:** https://github.com/searxng/searxng · **Version evaluated:** image `2026.11.1-8b35dcd2e`
**License (from LICENSE file at commit 9ded3be, R-01):** AGPL-3.0 · **Policy result:** service-boundary

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 4 | AGPL allowed only as an unmodified service (3.5); no code vendored |
| Activity last 12 months | 5 | image built the day of the test; upstream disables engines as sites change |
| Tests and CI | 4 | upstream CI builds and publishes images; not re-audited here |
| Documentation | 4 | settings and engine docs adequate; inactive engines documented in settings.yml |
| Open security advisories | 4 | none found affecting a private, non-public instance; recheck in M10 |
| API fit | 4 | JSON API maps to `Candidate`; reports `unresponsive_engines` |
| Size or footprint | 4 | one container, no state, no key |

**Decision:** service
**Reasoning:** the only zero-cost option at the needed volume, adequate when DuckDuckGo answers (57 of 58 of its top-10 slots relevant), but upstream blocking makes it unreliable without the conditions in section 4.
**Notices required:** no (not distributed; runs from the official image)
