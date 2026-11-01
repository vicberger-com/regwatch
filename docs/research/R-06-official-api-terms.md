# R-06: Terms, rate limits and access patterns of the official legal APIs

**Issue:** #8 · **Module:** M3 · **Requirements:** REQ-04, REQ-05 · **Date read:** 2026-11-01 (all pages and live requests, UTC times in the evidence log)
**Question:** What are the terms of use, authentication, rate limits, data licenses and practical access patterns for EUR-Lex (RSS, SPARQL/Cellar, web services), the US Federal Register API and legislation.gov.uk, and how should each be configured as a starter source?

This record covers data sources, not code. The template in `docs/templates/COMPONENT_EVALUATION.md` is used with the license row reading "data license" and the activity, tests and size rows marked n/a. Related work: R-03 (PR #16) assessed legislation.gov.uk as a data set from its GitHub documentation. This file adds live terms, robots and endpoint checks and does not repeat R-03's Publication Log analysis.

**Method.** Requests were made with `curl` from the session's cloud egress, User-Agent `regwatch-research/0.1 (R-06; +https://github.com/vicaberger/regwatch)`, at least 2 seconds apart per host (5 seconds for legislation.gov.uk). Totals: EUR-Lex and Publications Office 18, Federal Register 15, legislation.gov.uk 11. Statements marked *quoted* were read in the response body. Statements marked *index excerpt* come from a search engine's copy of an official page that this environment could not open; treat them as unverified. A limit that no readable page states is written "not stated".

## Summary

| | EUR-Lex / Cellar | Federal Register API | legislation.gov.uk |
| --- | --- | --- | --- |
| Authentication | None for RSS and SPARQL (verified live). SOAP web service: not verified (help page unreadable) | None (verified live; docs *index excerpt*: "do not require API keys") | None (verified live) |
| Rate limit | Not stated on any page read | Not stated on any page read | *Quoted:* 1,500 requests per 5 minutes per user; robots.txt `Crawl-delay: 5` |
| Data license | Commission Decision 2011/833/EU reuse notice (*quoted* from the Decision via Cellar and from the data.europa.eu record) | US government work; the legal-status page could not be read. The RSS channel states the site is an "unofficial web version" (*quoted*) | Open Government Licence v3.0; EU-derived items also under 2011/833/EU (*quoted*) |
| Attribution | Acknowledge the source (Art. 6(2)(a)); EUR-Lex wording *quoted* only as reproduced by legislation.gov.uk | Not stated (none required for US government works; say "unofficial" when showing text) | OGL attribution; suggested wording *quoted* for mixed UK/EU items |
| robots.txt | eur-lex.europa.eu: unreadable (WAF challenge). publications.europa.eu redirects to op.europa.eu: no rule covers `/webapi/` or `/resource/` | Disallows `/documents/search`, `/articles/search`, `/documents/current` and others; `/api/` is not disallowed | `Crawl-delay: 5`; disallows `*/data.pdf`, `*/data.docx`, `/defralex` |
| User-Agent rule | Not stated | Not stated | *Quoted:* identifiable UA required; contact details "strongly recommended" |
| Access blockers | **Website HTML (documents, help, legal notice, robots.txt) answers `202` with `x-amzn-waf-action: challenge`.** RSS and Cellar answer normally | **All HTML, including full-text `.txt` and `.html` links, redirects to `unblock.federalregister.gov` (CAPTCHA).** API JSON and RSS answer normally | None |
| Recommended source | `api_feed` provider `eur_lex` over Cellar SPARQL plus Cellar content negotiation; EUR-Lex RSS as a disabled metadata-only fallback | `api_feed` provider `federal_register`, metadata and abstract only until BL-27 is decided | `api_feed` provider `legislation_gov_uk` (title-term search feeds); R-03's Publication Log stays the change-tracking option |

## 1. EUR-Lex, Cellar and the Publications Office

**Terms and license.**
- Commission Decision 2011/833/EU, fetched from Cellar (`/resource/celex/32011D0833`, E-EU-9). Article 4 (*quoted*): "All documents shall be available for reuse: (a) for commercial or non-commercial purposes under the conditions laid down in Article 6; (b) without charge ...; and (c) without the need to make an individual application". Article 6(2) (*quoted*) allows conditions including "(a) the obligation for the reuser to acknowledge the source of the documents; (b) the obligation not to distort the original meaning or message of the documents; (c) the non-liability of the Commission for any consequence stemming from the reuse."
- The data.europa.eu record "Sparql and RESTful API access to European Union law and publications (CELLAR)" (E-EU-11) gives every distribution, including `http://publications.europa.eu/webapi/rdf/sparql`, the license "European Commission reuse notice" (`http://data.europa.eu/eli/dec/2011/833/oj`). It also states that Cellar "provides also an RSS feed" for new and updated documents.
- EUR-Lex legal notice (`https://eur-lex.europa.eu/content/legal-notice/legal-notice.html`): **not read**. It returned a WAF challenge to both curl and the fetch tool. legislation.gov.uk reproduces it (*quoted*, E-UK-4): "Except where otherwise stated, reuse of the EUR-Lex data for commercial or non-commercial purposes is authorised provided the source is acknowledged ('© European Union, https://eur-lex.europa.eu, 1998-2019')". The year range in that copy is probably outdated. Confirm the current wording from a browser (BL-28).
- EUR-Lex SOAP web service: registration terms and quotas **not verified**, because the help page (`/content/help/data-reuse/webservice.html`) was challenged. It is not needed for the recommended configuration.

**Rate limits.** None stated on any page read. The Cellar knowledge-graph page (E-EU-12) shows example queries that end in `LIMIT 1000`; that is an example, not a published cap. The endpoint is OpenLink Virtuoso (*index excerpt*: the query editor exposes an execution-timeout field). Proposed: at most 10 requests per minute and one SPARQL query per run.

**robots.txt.**
- `eur-lex.europa.eu/robots.txt` answered `202` with an empty body and `x-amzn-waf-action: challenge` on two attempts (E-EU-1, E-EU-2). Under RFC 9309 an empty 2xx body allows everything. Protego will read it that way, but the app should log it as "robots unreadable" rather than "allowed".
- `publications.europa.eu/robots.txt` redirects (301) to `op.europa.eu/robots.txt` (E-EU-3, E-EU-4). That file has `Allow: /` and disallows portal paths such as `*requestAction=rdf` and `/webdav/*`. No rule covers `/webapi/rdf/sparql` or `/resource/`.

**Live checks.**
- Cellar SPARQL `GET https://publications.europa.eu/webapi/rdf/sparql?query=...` with `Accept: application/sparql-results+json` returned 200 JSON with no authentication (E-EU-5 to E-EU-8).
- The EuroVoc labels were resolved to these concept URIs in the same endpoint: cyber resilience `17280`, information security `c_04ae3ba8`, computer crime `3027`, data protection `5181`, personal data `5595`, protection of privacy `2828`, artificial intelligence `3030`, electronic signature `6370`, cryptography `6778`, cloud computing `c_433922a6`, Internet of Things `c_b12a760a`, digital technology `7219`. EuroVoc has no English preferred label "cybersecurity". The closest concepts are "cyber resilience" and "information security", and `7938` is the ENISA agency.
- The topic query (shape below) returned 50 rows (its LIMIT) for works dated on or after 2026-07-01. Examples: `32026R2354` "Commission Implementing Regulation (EU) 2026/2354 ... on formats for submit[ting] ...", plus corrigenda such as `32023R2854R(07)` (Data Act corrigendum, no English title bound). Noise found: merger notices (`52026M...`) and restrictive-measure notices (`52026XG...`). Exclude the `M` notices with a regex and leave the rest to M4 classification.
- Content: `GET https://publications.europa.eu/resource/celex/32026R2354` with `Accept: application/xhtml+xml` and `Accept-Language: eng` answered `303` to `http://publications.europa.eu/resource/cellar/<uuid>.0006.03/DOC_1`, then 200 XHTML (152 KB) (E-EU-9). The redirect target is **plain http**; the same path over https returned 200 (E-EU-13). The adapter should rewrite it to https before it reaches SafeFetcher.
- EUR-Lex RSS `https://eur-lex.europa.eu/EN/display-feed.rss?rssId=162` ("1 - All Parliament and Council legislation") and `rssId=161` ("4 - Commission proposals and related documents") returned 200 RSS 2.0, 100 items each (E-EU-14, E-EU-16). Items look like `CELEX:32026L2450: Directive (EU) 2026/2450 ...`. Each `link` points to `legal-content/AUTO/?uri=CELEX:...`, and those document pages were WAF-challenged (E-EU-15). Subject-specific RSS ("EUR-Lex RSS by subject" in 4.5) needs a saved search on a registered EUR-Lex account, which section 8.3 rules out (no logins). The help page that lists predefined feeds was challenged, so the topic feed IDs remain unverified.

SPARQL query shape (the adapter fills the dates and the concept list from `params`):
```sparql
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?work ?celex ?date ?title WHERE {
  VALUES ?concept { <http://eurovoc.europa.eu/17280> <http://eurovoc.europa.eu/c_04ae3ba8> ... }
  ?work cdm:work_is_about_concept_eurovoc ?concept ; cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date .
  FILTER(?date >= "2026-07-01"^^<http://www.w3.org/2001/XMLSchema#date>)
  FILTER(REGEX(STR(?celex), "^[35]"))
  OPTIONAL { ?expr cdm:expression_belongs_to_work ?work ;
                   cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
                   cdm:expression_title ?title . }
} ORDER BY DESC(?date) LIMIT 500
```

## 2. US Federal Register API

**Terms and license.**
- The developer documentation (`/developers/documentation/api/v1`), the REST API reader aid and every other HTML page redirected (302) to `https://unblock.federalregister.gov`. The fetch tool and the Wayback Machine were refused too, so **no FR documentation page was read directly**.
- The unblock page (*quoted*, E-FR-5): "Due to aggressive automated scraping of FederalRegister.gov and eCFR.gov, programmatic access to these sites is limited to access to our extensive developer APIs."
- RSS channel description (*quoted*, E-FR-10): "The documents in this feed originate from FederalRegister.gov which displays an unofficial web version of the daily Federal Register. The official electronic version in PDF format is also available as a link from the FederalRegister.gov website. For more information, please see https://www.federalregister.gov/reader-aids/policy/legal-status." That URL is the proposed `terms_url`.
- *Index excerpts* of the official docs: "FederalRegister.gov APIs do not require API keys"; "you can only paginate through the first 2000 results. For more, use the date range filters." (both unverified).
- Data license: not stated on any page read. Federal Register text is a work of the US government. Section 4.5 already records "public domain", which is consistent with this but was not re-read here.
- Attribution: not stated. Rate limit: not stated. No `x-ratelimit-*` or `retry-after` header appeared on any API response (E-FR-6). User-Agent requirement: not stated.

**robots.txt** (E-FR-1, *quoted*): `Disallow: /documents/current`, `/documents/email-a-friend`, `/articles/search`, `/documents/search`, `/public-inspection/search`, `/regulations/search`, `/my/`, `/auth/`. `/api/v1/` is not disallowed.

**Live checks** (base `https://www.federalregister.gov/api/v1`, no key):
- `documents.json?per_page=5&order=newest&conditions[term]=cybersecurity` returned 200 JSON with `count` 4706, `total_pages` 50 and `next_page_url`, with no authentication (E-FR-6).
- `per_page=1000` was honoured: 1,000 results and `total_pages` 5 (E-FR-7). With `per_page=20`, `total_pages` is capped at 50, and `page=50` returns a `previous_page_url` with no next link (E-FR-12).
- **`page=100` and `page=101` silently returned page 1** (identical document numbers, `next_page_url` pointing at page 2) instead of an error (E-FR-8, E-FR-9). The adapter must follow `next_page_url` only and bound each run with `conditions[publication_date][gte]`.
- A boolean term query (`cybersecurity | "artificial intelligence" | "personal data"`) with `conditions[type][]=RULE,PRORULE,NOTICE` and `publication_date[gte]=2026-10-01` returned `count` 80 (E-FR-11). Results included DHS "Notice of Order Regarding Exclusion and Removal of Acronis Products ..." and also ITC trade notices (noise for M4). `fields[]` limits the payload.
- The alternative `conditions[topics][]=computer-technology&conditions[topics][]=privacy` since 2026-09-01 returned 13 documents, mostly off-topic (FOIA, child support) (E-FR-13). Term search is the better day-one filter.
- `documents.rss?conditions[term]=cybersecurity&order=newest` returned 200 RSS 2.0 with 50 items, defaulting to the last 30 days (E-FR-10).
- **Full text is blocked:** the API's `raw_text_url` (`/documents/full_text/text/2026/10/30/2026-22215.txt`) redirected to the CAPTCHA (E-FR-14). The block may depend on the IP range (the unblock page offers to "request a wider IP range"). Until BL-27 is resolved, the connector stores the API's `abstract` and metadata as `RawDocument.text` and links `html_url` for readers.

## 3. legislation.gov.uk

**Terms and license.**
- Fair use policy (`https://www.legislation.gov.uk/fair-use-policy`, E-UK-3, *quoted*):
  - "If you are not using a browser, you must identify yourself ... with a legitimate user agent string ... Anonymous user agents are not accepted ... It is strongly recommended you add contact details to your user agent".
  - "You must follow the rules in the site's robots.txt file".
  - "You must not exceed the request rate limit of 1,500 requests in any 5-minute period ... This limit applies to users not IP addresses".
  - "If the crawl-delay setting is not provided, use a conservative crawl rate (e.g. 10 requests per 5-10 seconds)".
  - It recommends "the New Legislation feed" or "the Publication Log feed" instead of crawling.
  - Contact: `data.legislation@nationalarchives.gov.uk`.
- **Discrepancy with R-03 (PR #16):** R-03 records "3,000 requests per 5 minutes" from the GitHub documentation. The live policy says 1,500. Configure to the live figure (BL-29).
- License (E-UK-2, E-UK-4, *quoted*): "All content is available under the Open Government Licence v3.0 except where otherwise stated". For EU-derived items: "You may re-use UK law derived from the EU ... and comply with both licences by acknowledging these two sources and not claiming any official endorsement". Suggested wording: "Crown © and database right material re-used under the Open Government Licence ... Material derived from the European Institutions © European Union, 1998-2019 and re-used under the terms of the Commission Decision 2011/833/EU."
- Authentication: none (no page mentions a key, and every request succeeded without one).

**robots.txt** (E-UK-1, *quoted*): `User-agent: *`, `Crawl-delay: 5`, `Disallow: */data.pdf`, `Disallow: */data.docx`, `Disallow: /defralex`. `data.xml` and `data.feed` are allowed.

**Live checks.**
- `/new/data.feed` returned an Atom feed whose self link is `/all/data.feed?sort=published`. It has 20 entries per page (`openSearch:itemsPerPage`), `leg:morePages` and a `rel="next"` link (E-UK-6).
- Title search `/all/data.feed?title=cyber` returned 17 results (E-UK-7).
- `title=data+protection&sort=published` returned 149 results, newest first, for example "The Data Protection Act 2018 (Code of Practice on Artificial Intelligence and Au[tomated Decision-Making]) ..." published 2026-04-21 (E-UK-10).
- Full-text search `text="network and information systems"` returned 55 results, but mostly appropriation acts (E-UK-8). Title terms are more precise.
- Each entry links `/id/...`, the made or point-in-time HTML, and `.../data.xml`.
- The Publication Log `/update/data.feed` is documented at a fixed 20 entries per page with filters (E-UK-9). R-03 covers its use.

## 4. Proposed starter-source configurations

`seed/sources/` does not exist, so the proposals live here. Shape: `SourceWrite` with a nested `job` (`CaptureJobWrite`) from `openapi/regwatch.v1.yaml`.

`terms_url` is the top-level source field (`docs/contracts/schema.sql` `source.terms_url`, OpenAPI `SourceWrite.terms_url`). It is not part of `config`: `connectors.yaml` sets `additionalProperties: false`, and a negative test confirmed that `config.terms_url` is rejected. The M3 spec's "`config.terms_url`" is drift (BL-30).

Each `config` and `extraction_rules` value was validated with `jsonschema` (Draft 2020-12) against `docs/contracts/connectors.yaml`, and job values were checked against the `CaptureJobWrite` bounds. All four passed. Validation had to skip the meta-schema check because of a contract defect (BL-31).

```yaml
- name: Federal Register - IT and cybersecurity documents
  kind: api_feed
  url: https://www.federalregister.gov/api/v1/documents.json
  terms_url: https://www.federalregister.gov/reader-aids/policy/legal-status
  credibility: official
  robots_policy: respect
  language: en
  default_jurisdiction_codes: [US]
  config:
    provider: federal_register
    params:
      conditions[term]: 'cybersecurity | "information security" | "critical infrastructure" | "artificial intelligence" | privacy | "personal data" | "incident reporting" | encryption | "supply chain risk"'
      conditions[type][]: [RULE, PRORULE, NOTICE, PRESDOCU]
      conditions[publication_date][gte]: "{last_success_date - 3 days}"  # adapter fills; keeps runs far below the paging cap
      order: newest
      per_page: 100
      fields[]: [document_number, title, type, abstract, publication_date, html_url, pdf_url, agencies, topics, effective_on, comments_close_on, cfr_references]
  extraction_rules: {}
  job: { cron: "20 7 * * 1-5", timezone: America/New_York, max_items_per_run: 500, rate_limit_per_minute: 10, render_js: false, change_threshold_pct: 5, enabled: true }

- name: EUR-Lex via Cellar SPARQL - EuroVoc IT and cybersecurity concepts
  kind: api_feed
  url: https://publications.europa.eu/webapi/rdf/sparql
  terms_url: https://eur-lex.europa.eu/content/legal-notice/legal-notice.html
  credibility: official
  robots_policy: respect
  language: en
  default_jurisdiction_codes: [EU]
  config:
    provider: eur_lex
    params:
      method: sparql
      sparql_endpoint: https://publications.europa.eu/webapi/rdf/sparql
      eurovoc_concepts: [http://eurovoc.europa.eu/17280, http://eurovoc.europa.eu/c_04ae3ba8, http://eurovoc.europa.eu/3027, http://eurovoc.europa.eu/5181, http://eurovoc.europa.eu/5595, http://eurovoc.europa.eu/2828, http://eurovoc.europa.eu/3030, http://eurovoc.europa.eu/6370, http://eurovoc.europa.eu/6778, http://eurovoc.europa.eu/c_433922a6, http://eurovoc.europa.eu/c_b12a760a, http://eurovoc.europa.eu/7219]
      celex_sectors: ["3", "5"]            # legal acts, preparatory acts
      exclude_celex_regex: "^5\\d{4}M"     # merger-control notices
      lookback_days: 14
      limit: 500
      content_language: ENG
      content_url_template: "https://publications.europa.eu/resource/celex/{celex}"  # Accept application/xhtml+xml, Accept-Language eng; rewrite http redirect to https
      display_url_template: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
  extraction_rules: {}
  job: { cron: "40 6 * * 1-6", timezone: Europe/Luxembourg, max_items_per_run: 500, rate_limit_per_minute: 10, render_js: false, change_threshold_pct: 5, enabled: true }

- name: EUR-Lex RSS - Parliament and Council legislation (metadata only)
  kind: rss
  url: https://eur-lex.europa.eu/EN/display-feed.rss?rssId=162
  terms_url: https://eur-lex.europa.eu/content/legal-notice/legal-notice.html
  credibility: official
  robots_policy: respect
  language: en
  default_jurisdiction_codes: [EU]
  config: { feed_url: "https://eur-lex.europa.eu/EN/display-feed.rss?rssId=162", fetch_full_page: false, max_entries: 100, etag_conditional: true }
  extraction_rules: {}
  job: { interval_seconds: 21600, max_items_per_run: 100, rate_limit_per_minute: 6, render_js: false, change_threshold_pct: 5, enabled: false }  # fallback; rssId=161 is the Commission-proposals twin

- name: legislation.gov.uk - new legislation by IT and cybersecurity title terms
  kind: api_feed
  url: https://www.legislation.gov.uk/all/data.feed
  terms_url: https://www.legislation.gov.uk/fair-use-policy
  credibility: official
  robots_policy: respect
  language: en
  default_jurisdiction_codes: [GB]
  config:
    provider: legislation_gov_uk
    params:
      feed: search                         # /{type}/data.feed?title=...&sort=published, 20 entries per page
      type: all
      title_terms: [cyber, "network and information systems", "data protection", "electronic communications", "telecommunications security", "product security", "artificial intelligence", "digital", "online safety", "electronic identification", "privacy"]
      sort: published
      max_pages_per_term: 2
      fetch_format: data.xml               # robots.txt disallows only */data.pdf and */data.docx
  extraction_rules: {}
  job: { cron: "10 8 * * *", timezone: Europe/London, max_items_per_run: 200, rate_limit_per_minute: 10, render_js: false, change_threshold_pct: 5, enabled: true }  # Crawl-delay 5 allows at most 12/min
```

Adapter notes for M3:
1. All three hosts work with the default `capture.user_agent` (`regwatch/{version} (+{contact_email})`). legislation.gov.uk rejects anonymous agents, so do not enable that source while `general.contact_email` is empty (BL-29).
2. Treat a `202` response with `x-amzn-waf-action` and a redirect to `unblock.federalregister.gov` as a typed `blocked_by_provider` failure. Do not count them as content, and never retry around them (section 8.3: no CAPTCHA solving).
3. Federal Register: follow `next_page_url` only; never compute page numbers.

## 5. Evaluation records

| Source | Data license | Policy result (3.5) | Auth | Stated rate limit | Decision | Reasoning |
| --- | --- | --- | --- | --- | --- | --- |
| EUR-Lex / Cellar | Commission Decision 2011/833/EU (acknowledge source, no distortion) | allowed for captured data, stored internally with attribution | none | not stated | service (external API) | Cellar SPARQL and content negotiation are open and unchallenged, unlike the EUR-Lex website. |
| Federal Register API | US government work (legal-status page unread) | allowed | none | not stated | service (metadata only) | JSON API works without a key, but full text is behind a CAPTCHA for this client. |
| legislation.gov.uk | OGL v3.0 (+ 2011/833/EU for EU-derived) | allowed with attribution | none | 1,500 / 5 min; Crawl-delay 5 | service | Clear published limits; Atom search feeds fit the `api_feed` adapter directly. |

## 6. Evidence log (2026-11-01, UTC)

| ID | Request | Result |
| --- | --- | --- |
| E-EU-1, 2 | `GET https://eur-lex.europa.eu/robots.txt` (22:37:31, 22:42:18) | 202, empty, `x-amzn-waf-action: challenge` |
| E-EU-3, 4 | `GET https://publications.europa.eu/robots.txt`; `https://op.europa.eu/robots.txt` | 301 to op.europa.eu; 200 text, 1,989 B |
| E-EU-5 to 8 | `GET .../webapi/rdf/sparql` (recent CELEX; EuroVoc labels ×2; topic query) | 200 JSON each; topic query 50 rows |
| E-EU-9 | `GET https://publications.europa.eu/resource/celex/32026R2354`, then `.../32011D0833` | 303 to http Cellar item, then 200 XHTML; 200 XHTML 48 KB |
| E-EU-10 | `GET eur-lex.europa.eu/content/legal-notice/legal-notice.html` (curl and fetch tool) | 202 WAF challenge / empty |
| E-EU-11 | `GET https://data.europa.eu/api/hub/search/datasets/sparql-cellar-of-the-publications-office` | 200 JSON, license COM_REUSE (2011/833) |
| E-EU-12 | `GET https://op.europa.eu/en/web/cellar/cellar-data/metadata/knowledge-graph` | 200 HTML |
| E-EU-13 | `GET https://publications.europa.eu/resource/cellar/e1722c19-...0006.03/DOC_1` | 200 XHTML 152 KB |
| E-EU-14, 16 | `GET https://eur-lex.europa.eu/EN/display-feed.rss?rssId=162`, `rssId=161` | 200 RSS, 100 items each |
| E-EU-15 | `GET eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R2354`; `.../help/search/predefined-rss.html`; `.../help/data-reuse/webservice.html` (fetch tool) | 202 WAF challenge / empty |
| E-FR-1 | `GET https://www.federalregister.gov/robots.txt` | 200 text |
| E-FR-2 to 5 | `GET /developers`, `/developers/documentation/api/v1`, a reader-aids page; `GET https://unblock.federalregister.gov/` | 302 to unblock; 200 CAPTCHA page |
| E-FR-6 | `GET /api/v1/documents.json?per_page=5&order=newest&conditions[term]=cybersecurity` | 200 JSON, count 4706 |
| E-FR-7 | same with `per_page=1000&fields[]=document_number` | 200, 1,000 results, total_pages 5 |
| E-FR-8, 9 | `per_page=20&page=101`, `page=100` | 200, page 1 returned silently |
| E-FR-10 | `GET /api/v1/documents.rss?conditions[term]=cybersecurity&order=newest` | 200 RSS, 50 items |
| E-FR-11 | boolean term + types + `publication_date[gte]=2026-10-01` + `fields[]` | 200, count 80 |
| E-FR-12 | `per_page=20&page=50` | 200, last page, previous link only |
| E-FR-13 | `conditions[topics][]=computer-technology&...=privacy`, since 2026-09-01 | 200, count 13 |
| E-FR-14 | `GET /documents/full_text/text/2026/10/30/2026-22215.txt` | 302 to unblock |
| (other) | `GET /api/v1`, `/api/v1/swagger.json` | 404 |
| E-UK-1 | `GET https://www.legislation.gov.uk/robots.txt` | 200 text |
| E-UK-2 to 5 | `GET /developer`, `/fair-use-policy`, `/contributors`, `/developer/feeds` | 200 HTML each (`/developer/feeds` says "Coming Soon") |
| E-UK-6 | `GET /new/data.feed` | 200 Atom, 20 entries |
| E-UK-7 | `GET /all/data.feed?title=cyber` | 200 Atom, 17 results |
| E-UK-8 | `GET /all/data.feed?text="network and information systems"&sort=published` | 200 Atom, 55 results |
| E-UK-9 | `GET https://legislation.github.io/data-documentation/api/publication-log.html` | 200 HTML |
| E-UK-10 | `GET /all/data.feed?title=data+protection&sort=published` | 200 Atom, 149 results |
| (other) | Fetch tool on `/help#fairuse`; Wayback Machine for FR docs (curl reset, fetch tool refused); `api.github.com` for the FR source repo (403, outside session scope) | no content used |
