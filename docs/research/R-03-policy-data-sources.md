# R-03: Policy trackers and open legal datasets as data sources and seed taxonomies

**Issue:** #5 · **Modules:** M2, M3 · **Requirements:** REQ-02, REQ-03, REQ-05 · **Date:** 2026-11-01
**Policy:** `docs/03-architecture.md` 3.5 · **Protocol:** 3.8 · **Connector kinds:** `docs/contracts/connectors.yaml` · **Etiquette:** `docs/08-security-compliance.md` 8.3

## Question

Can the OpenSSF Global Cyber Policy working group material, the UNCTAD Global Cyberlaw Tracker and at least three similar sources serve the application as data sources or seed taxonomies (not as code), and how?

Fit codes: **(a)** capture source for M3 (connector kind named), **(b)** seed for M2 facets and terms, **(c)** jurisdiction reference only, **(d)** not usable.

## Method and limits

1. GitHub-hosted material was read from a clone at a recorded commit (`git clone --depth`); the commit and the files read are listed in each block. Licenses and terms are quoted from those files.
2. **Network limit.** This session's network policy refused every host other than GitHub (proxy `connect_rejected` for `unctad.org`, `policy.openssf.org`, `openssf.org`, `eur-lex.europa.eu`; DNS refusal for `unctad.org` in the fetch tool). No live endpoint, terms page or `robots.txt` on those hosts could be opened. Where a block depends on such a page it says **not verified** and states nothing about content, license or cadence. Search-engine snippets were seen for UNCTAD but are **not** used as evidence.
3. **Follow-up pass (BL-24, 2026-11-01, later the same day).** The environment's network access was widened, and C7 to C15 were then read live. Pages were fetched with `curl` using a descriptive User-Agent (`regwatch-research/0.1 (R-03)`); pages that render in the browser were read with headless Chromium (Playwright). Each site's `robots.txt` was read before its content pages. The UNCTAD tracker was tried once directly and gave no response. An Internet Archive fallback could not be run from this session, so C2 stays unverified. Sites that answered with a block or a timeout are recorded as such, and no attempt was made to get around them.
4. Candidate discovery used GitHub repository search for official owners (`usnistgov`, `usgpo`, `legislation`) and for regulation trackers. Third-party trackers without a license are included only to record why they are rejected.

## Summary

| # | Candidate | Owner | Access | License or terms (as read) | Last update seen | Verified at | Fit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | OpenSSF Global Cyber Policy WG repository | OpenSSF (Linux Foundation) | Git repository (Markdown tables, PDFs); Jekyll site `policy.openssf.org` | `LICENSE` Apache-2.0; `CHARTER.md`: documentation CC-BY-4.0, data CDLA-Permissive-1.0 | 2026-09-25 (repo); regulations table 2025-04-18; CRA tables 2025-12-01 | `3e45ac6` | (b) CRA terms; (c) EU/UK index; (a) optional `rss` on commits, secondary |
| C2 | UNCTAD Global Cyberlaw Tracker | UNCTAD | not verified | not verified | not verified | blocked, then no response (2026-11-01) | provisional (c), pending verification |
| C3 | legislation.gov.uk API and Publication Log | The National Archives (UK) | Atom feeds (`/data.feed`), CLML XML (`/data.xml`), HTML | Open Government Licence v3.0; EU-origin items also Commission Decision 2011/833/EU; fair-use policy (3,000 requests per 5 min) | docs repo 2025-07-01; live feed not fetched | docs `2812c7a` | (a) `rss` or `api_feed` (`legislation_gov_uk`) |
| C4 | govinfo bulk data (Federal Register, CFR, eCFR, bills) | US Government Publishing Office | Bulk XML; directory listings as XML or JSON (`/bulkdata/json/...`) | US government works not subject to copyright; no downstream restriction except representing an official version | guide repo 2026-06-11; live listing not fetched | guide `83a8517` | (a) `api_feed` (`generic_json`) for CFR and eCFR; complements the Federal Register API starter |
| C5 | NIST OSCAL content (CSF 2.0, SSDF SP 800-218, AI RMF 1.0, SP 800-53) | NIST | Git repository; OSCAL catalogs in XML, JSON, YAML | Public domain in the US plus CC0-1.0 worldwide | 2026-10-22 | `f0de6d8` | (b) seed for a control-framework facet and topic match rules |
| C6 | Asenion (Fairly AI) AI regulation and policy tracker | Fairly AI (company) | README pointing to a Google My Maps map | no stated license | 2026-09-18 | `ab887aa` | (d) not usable |
| C7 | Canada: Justice Laws consolidated Acts and regulations (XML) | Department of Justice Canada | Git repository of XML (`justicecanada/laws-lois-xml`); HTML site | `LICENSE.md`: Open Government Licence - Canada; Reproduction of Federal Law Order (quoted in FAQ) | repo 2026-10-15; site "current to 2026-09-30" | `0507465`, site 2026-11-01 | (a) `rss` on the repository's commit feed, plus fetch from the clone or site |
| C8 | Australia: Federal Register of Legislation | Office of Parliamentary Counsel | HTML; PDF, DOC, ePub downloads | CC BY 4.0 with prescribed attribution wording | not stated | site 2026-11-01 | (a) `web_page` (listing) |
| C9 | Japan: e-Gov 法令検索 (Law Search) and Law API | Digital Agency | Law API v1 and v2; XML bulk download; HTML | 公共データ利用規約 第1.0版 (PDL1.0) | API v1 spec dated 2024-07-29 | site 2026-11-01 | (a) `api_feed` (`generic_json`, API v2) |
| C10 | Singapore: CSA legislation pages | Cyber Security Agency | HTML | all rights reserved; written permission needed to reproduce | page "Last updated on 25 February 2026" | site 2026-11-01 | (a) `web_page`, internal monitoring only |
| C11 | India: India Code, e-Gazette, MeitY | Government of India | not reached | not verified | not verified | timeout or access denied | unverified |
| C12 | Brazil: LexML portal | Senado Federal (LexML network) | HTML search; SRU interface (`/sru`) | not found | not stated | site 2026-11-01 (SRU 503) | (c), (a) pending SRU and terms |
| C13 | Brazil: ANPD (data protection authority) | ANPD on gov.br | HTML | gov.br footer: CC BY-ND 3.0 | not stated | site 2026-11-01 | (a) `web_page`; no derived seeds |
| C14 | China: CAC 政策法规 (policy and regulation) listing | Cyberspace Administration of China | HTML listing, rendered in the browser | "© 版权所有" (all rights reserved); no reuse licence stated | listing entries to 2026-10-23 | site 2026-11-01 | (a) `web_page` (listing, `render_js`), internal only |
| C15 | China: national laws and regulations database `flk.npc.gov.cn` | NPC Standing Committee | HTML | `robots.txt` forbids automated collection | not stated | `robots.txt` 2026-11-01 | (c) reference only; no capture |

**Coverage of day-one jurisdictions.**
- **EU:** C1, and the EU-origin copies in C3.
- **UK:** C1 and C3.
- **US federal:** C4 and C5.
- **Canada:** C7.
- **Australia:** C8.
- **Japan:** C9.
- **Singapore:** C10. The statutes portal `sso.agc.gov.sg` returned HTTP 403 to this session.
- **Brazil:** C12 and C13.
- **China:** C14 and C15.
- **India:** no source verified (C11). The starter list in 4.5 also has no Indian source.

## Evaluation blocks

Each block follows `docs/templates/COMPONENT_EVALUATION.md`, adapted for data: the "License" line quotes the terms, and the scoring rows score source quality rather than code quality.

### C1 OpenSSF Global Cyber Policy working group

**Capability needed:** CRA and global cyber-policy index; seed terms for product security · **Module:** M2, M3 · **URL:** https://github.com/ossf/wg-globalcyberpolicy (site https://policy.openssf.org, from `docs/CNAME`) · **Version evaluated:** `main` at `3e45ac6860f2aaa75db9f935a24cd86a49c77a91` (2026-09-25)
**License (from files at that commit):** `LICENSE` is Apache-2.0. `CHARTER.md` section on IP: "All new inbound code contributions ... must be made using the Apache License, Version 2.0"; "Documentation will be received and made available by the Technical Initiative under the Creative Commons Attribution 4.0 International License"; "To the extent a contribution includes or consists of data, any rights in such data shall be made available under the CDLA-Permissive 1.0 License." The README heading "Intellectual Property" ends at "work produced by this group is licensed as follows:" with nothing after it. · **Policy result:** CC-BY-4.0 allowed for data with attribution; CDLA-Permissive-1.0 is not named in 3.5 (review, BL-20).

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 4 | CC-BY-4.0 documentation; CDLA-Permissive-1.0 data clause needs a policy line |
| Activity last 12 months | 4 | commits through 2026-09-25 (site restructure, checklists) |
| Authority | 2 | community working group, not an official publisher; every row links to the official text (EUR-Lex, gov.uk) |
| Coverage | 2 | `documents/regulations.md` has 3 rows (EU CRA, EU Blue Guide, UK Cyber Security and Resilience Bill); depth is the EU CRA |
| Structure | 3 | Markdown tables: `CRA_Terms+Definitions.md` (Art. 3 terms), `CRA_Product_Groups.md` (26 rows, Annex III and IV classes), `CRA_Related_Dossiers.md` (38 rows of related EU acts, most with EUR-Lex ELI links), `CRA_Timeline.md` (application dates) |
| Update cadence | 2 | not stated; `regulations.md` last changed 2025-04-18; CRA tables last changed 2025-12-01 |
| Machine access | 3 | git clone; GitHub's commit Atom feed (`https://github.com/ossf/wg-globalcyberpolicy/commits/main.atom`) not fetched in this session; `policy.openssf.org` and its `robots.txt` not reachable |

**Decision:** (b) seed and (c) reference; optional (a) `rss` on the commit feed with `credibility=secondary`.
**Reasoning:** The tables are a good index of CRA vocabulary and linked EU acts, but the authority is EUR-Lex, so seed term labels and match rules from the CRA text itself (reusable under Decision 2011/833/EU) and cite OpenSSF as the index; the 3-row regulations table is too thin to be a jurisdiction source.
**Notices required:** yes if any table text is copied into `seed/` (CC-BY-4.0 attribution to OpenSSF); none if terms are taken from EUR-Lex directly.

### C2 UNCTAD Global Cyberlaw Tracker

**Capability needed:** worldwide jurisdiction reference for cyber-related law · **Module:** M2 (jurisdictions), M3 · **URL:** https://unctad.org/page/global-cyberlaw-tracker (from issue #5 and R-03 wording; page not opened) · **Version evaluated:** none
**License or terms:** **not verified.** `unctad.org` was first refused by the session network policy. In the follow-up pass, one direct request got no HTTP response, and an Internet Archive fallback could not be run from this session. The tracker page, any download, the UNCTAD terms of use and `robots.txt` were therefore not opened. · **Policy result:** unknown

| Criterion | Score | Evidence |
| --- | --- | --- |
| All criteria | n/a | page not reachable from this session |

**Decision:** provisional (c) jurisdiction reference, pending BL-24.
**Reasoning:** Its coverage, format, cadence and terms must be read from UNCTAD's own pages before any use; nothing about it enters `seed/` or the starter list until then.
**What BL-24 must record:** law areas covered and how status per country is expressed; whether a file download exists and its format; the date the data were last updated; the exact terms-of-use text and link; `robots.txt` for the tracker path.

### C3 legislation.gov.uk API and Publication Log

**Capability needed:** UK primary and secondary legislation, changes and drafts · **Module:** M3 · **URL:** https://www.legislation.gov.uk (documentation https://github.com/legislation/data-documentation) · **Version evaluated:** documentation `main` at `2812c7af46d405cab145f768bdcb2f6e6ec84aa7` (2025-07-01)
**License (from `reuse-licence.md`):** "All content on legislation.gov.uk, and on our Github page, is available under the Open Government Licence v3.0." Attribution required; suggested wording: "© Crown and database right. Derived from content available under the Open Government Licence v3.0 from legislation.gov.uk." EU-origin items: "both of which apply simultaneously": Commission Decision 2011/833/EU and OGL v3.0. · **Policy result:** OGL v3.0 is not named in 3.5; it is an attribution licence comparable to CC-BY-4.0 (review, BL-20). Captured content is used internally (8.3), which OGL permits.

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 4 | OGL v3.0, attribution only |
| Activity | 4 | docs updated 2025-07-01; live feed not fetched |
| Authority | 5 | official publisher (The National Archives, King's Printer) |
| Coverage | 4 | `what-we-have.md`: "almost all UK primary and secondary legislation published since 1988"; UK only, plus EU-origin copies |
| Structure | 5 | Atom feeds for every list and search (`/data.feed`); CLML XML for documents (`/data.xml`) |
| Update cadence | 3 | not stated as a schedule; `api/overview.md`: website and API "updated at the same time", with caching delay |
| Machine access and etiquette | 5 | `fair-use.md`: identify with a User-Agent with contact, "follow the rules in our robots.txt", "must not exceed ... 3,000 requests in any 5 minute period", conservative crawl rate "e.g. 10 requests per 5-10 seconds" if no crawl-delay. Live `robots.txt` (read 2026-11-01): `User-agent: *` with `Crawl-delay: 5` and sitemaps, and no `Disallow`. The `robots.txt` in the docs repo applies to the documentation site only |

**Decision:** (a) `rss` for the Publication Log, `api_feed` provider `legislation_gov_uk` for document fetch.
**Reasoning:** The Publication Log (`https://www.legislation.gov.uk/update/data.feed`, filterable by date, content type `legislation|draft|associated-documents|changes` and document type per `api/publication-log.md`) is a better change signal than per-type feeds; the docs say not to poll the unfiltered feed. M3's defaults (8.3: one request per 2 s) sit well under the fair-use limit.
**Notices required:** yes, OGL attribution line in the source's `config.terms_url` and in any external output.

### C4 govinfo bulk data (US GPO)

**Capability needed:** US federal regulations (CFR, eCFR), Federal Register issues, bill text · **Module:** M3 · **URL:** https://www.govinfo.gov/bulkdata (guides https://github.com/usgpo/bulk-data) · **Version evaluated:** guide `main` at `83a85170ce0bdd0cf218f6290bd739df8748e2ea` (2026-06-11)
**Terms (from `FR-XML_User-Guide.md`):** "In general, there are no restrictions on re-use of information in Federal Register documents because U.S. Government works are not subject to copyright. OFR and GPO do not restrict downstream uses of Federal Register data, except that independent providers should be aware that only the OFR and GPO are entitled to represent that they are the providers of the official versions". Re-publishers may not use the NARA seal or Federal Register logos. The guide repository itself has no LICENSE file. · **Policy result:** public domain (allowed).

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | US government work |
| Activity | 3 | guide updated 2026-06-11; live listing not fetched |
| Authority | 5 | official publisher (GPO, with OFR) |
| Coverage | 3 | US federal only; collections named in README: FR, CFR, BILLS; guides for eCFR and bill summaries |
| Structure | 4 | listings as XML or JSON by adding `/xml` or `/json` (README; `Accept` header required or HTTP 406); documents in published XML schemas |
| Update cadence | 2 | not stated in the guides |
| Machine access | 3 | bulk download. Live `robots.txt` (read 2026-11-01) disallows paths such as `/core/` and `/app/search/*`, does not disallow `/bulkdata`, and publishes bulkdata sitemaps for FR, CFR and ECFR. Site terms page not read |

**Decision:** (a) `api_feed` provider `generic_json` against the JSON listings, later phase (BL-22).
**Reasoning:** The Federal Register API already in the starter list covers new rules; govinfo adds the codified CFR and eCFR, which matter for "status" rather than "change", so it can wait until the starter set runs.
**Notices required:** no; record the "not an official version" wording in `config.terms_url` notes.

### C5 NIST OSCAL content

**Capability needed:** controlled vocabulary for a control-framework facet (M2 question bank item 1) and keyword rules for supply chain security and AI governance · **Module:** M2 · **URL:** https://github.com/usnistgov/oscal-content · **Version evaluated:** `main` at `f0de6d8d8c059d374f15e0ae07508d82e370fc1d` (2026-10-22)
**License (from `LICENSE.md`):** "As a work of the United States government, this project is in the public domain within the United States ... Additionally, we waive copyright and related rights in the work worldwide through the CC0 1.0 Universal public domain dedication." · **Policy result:** CC0 / public domain (allowed).

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | CC0-1.0 |
| Activity | 5 | commits 2026-10-18 to 2026-10-22 (OSCAL 1.2.3 update) |
| Authority | 5 | NIST |
| Coverage | 3 | catalogs, not laws: CSF 2.0 (`src/nist.gov/CSF/v2.0/xml/NIST_CSF_v2.0_catalog.xml`, catalog version 1.2.1, 6 functions, 22 active categories, 12 withdrawn CSF 1.1 categories), SSDF SP 800-218 v1.1, AI RMF 1.0, SP 800-53 rev4 and rev5, SP 800-171/172 rev3 |
| Structure | 5 | OSCAL XML, JSON, YAML; `status=withdrawn` property marks retired entries |
| Update cadence | 3 | not stated; follows NIST publication changes and OSCAL releases |
| Note | n/a | the README links `nist.gov/CSF/v2.0` but CSF is present only under `src/` (XML) at this commit |

**Decision:** (b) seed, later phase (BL-21).
**Reasoning:** CC0 catalogs give stable IDs (for example `GV.SC` Cybersecurity Supply Chain Risk Management, `RS.CO` Incident Response Reporting and Communication) for mapping items to frameworks, which M2 already lists as a future facet; import from the catalog with withdrawn entries filtered out.
**Notices required:** no (CC0); keep the source commit in the seed file header.

### C6 Asenion (Fairly AI) AI regulation and policy tracker

**URL:** https://github.com/fairlyAI/fairly-regulation-policy-tracker · **Version evaluated:** `ab887aa47cb276f1050a57f0b753f4d399654496` (2026-09-18) · **License:** no stated license (the repository holds only `README.md`; no LICENSE file).
Covers AI and AI-adjacent regulation in categories (general, generative AI, data and privacy, employment, government and military, health, finance and insurance, other) with a status colour legend; the data live in a Google My Maps map linked from the README, not in the repository.
**Decision:** (d) not usable. **Reasoning:** no license, data held on a third-party map service, and the "Policy and Framework Tracker" section of the README is empty; its category list is noted only as a cross-check for the AI governance topic.

### Day-one jurisdictions (C7 to C15, follow-up pass 2026-11-01)

These blocks use the same fields as the blocks above, in a shorter form. "robots" is the site's live `robots.txt` as read on the date shown.

#### C7 Canada: Justice Laws Website and XML repository
- **Owner and URLs:** Department of Justice Canada. Site: https://laws-lois.justice.gc.ca. XML: https://github.com/justicecanada/laws-lois-xml at `0507465` ("Laws Site Update 2026-10-15").
- **Coverage:** consolidated federal Acts and regulations in English and French, plus annual statutes. The site says "both language versions being equally authoritative".
- **Format and access:** XML in a Git repository (`eng/`, `fra/`, DTD and XSLT included); HTML site. The site FAQ names the repository as the download for "all consolidated federal Acts and regulations".
- **Cadence:** the FAQ says "The Justice Laws Website is generally updated every two weeks". The home page said "current to 2026-09-30". Recent repository commits: 2026-09-22, 2026-09-28, 2026-10-15.
- **Terms:**
  - Repository `LICENSE.md`: "Open Government Licence - Canada", linking http://open.canada.ca/en/open-government-licence-canada. The file does not state a version.
  - Site FAQ quoting the Reproduction of Federal Law Order: "anyone may, without charge or request for permission, reproduce enactments and consolidations of enactments of the Government of Canada ... provided due diligence is exercised in ensuring the accuracy of the materials reproduced and the reproduction is not represented as an official version."
- **robots:** `/robots.txt` returns the site's "Page not Found" page, so no robots file is served. Using the repository avoids crawling the site at all.
- **Fit:** (a). Use `rss` on the repository's commit Atom feed as the change signal, then fetch the changed XML. `connectors.yaml` has no git connector kind; a sitemap or git connector is already a backlog idea (BL-06).

#### C8 Australia: Federal Register of Legislation
- **Owner and URL:** Office of Parliamentary Counsel. https://www.legislation.gov.au
- **Coverage:** Commonwealth Constitution, Acts, legislative and notifiable instruments, gazettes, Administrative Arrangements, prerogative instruments, and Norfolk Island (from the site menu).
- **Format and access:** HTML. "Downloads from the website are usually offered in a choice of file formats (pdf, doc and ePub)".
  - An OData endpoint at `api.prod.legislation.gov.au` answered a `$metadata` request. No documentation or terms for it were found on the pages read, so treat it as undocumented.
- **Cadence:** not stated.
- **Terms** (https://www.legislation.gov.au/terms-of-use):
  - "With the exception of the Commonwealth Coat of Arms, and where otherwise noted, all content on the Federal Register of Legislation ... is provided under Creative Commons Attribution 4.0 International (the CC BY 4.0 licence)".
  - Attribution must include "Sourced from the Federal Register of Legislation at [full date of download]" (unchanged content) or "Based on content from ..." (changed content).
- **robots:** `User-agent: *`, `Crawl-delay: 10`, `Disallow: /assets/`. The listed sitemap is a placeholder ("This is an example sitemap.xml").
- **Fit:** (a) `web_page` in listing mode at one request per 10 s. Switch to `api_feed` (`generic_json`) only after OPC documents the API (BL-24).

#### C9 Japan: e-Gov 法令検索 (Law Search) and Law API
- **Owner and URL:** Digital Agency (デジタル庁). https://laws.e-gov.go.jp
- **Coverage:** current national law (憲法・法律・政令・勅令・府省令・規則: constitution, acts, cabinet and imperial orders, ministerial ordinances and rules).
  - The API v1 page lists calls for the law list by type, laws updated on a given date (「日付を指定 指定した日付に更新した法令名一覧」), full text, and single articles.
  - The site also links the Japanese Law Translation database.
- **Format and access:** 法令API Version1 (XML; spec 「2024年7月29日更新」, updated 2024-07-29); 法令API Version2 (OpenAPI page `lawapi-v2-oas`); XML bulk download (「XML一括ダウンロード」); and an updated-laws list (「更新法令一覧」).
- **Cadence:** not stated as a schedule. Changes are queryable by update date.
- **Terms** (https://laws.e-gov.go.jp/terms/):
  - 「本サイトの著作権は、特記されていない限りデジタル庁に帰属し、権利表記の記載がない限り「公共データ利用規約（第1.0版）」（PDL1.0）が適用されています」 ("unless otherwise noted, copyright belongs to the Digital Agency and the Public Data License 1.0 applies").
  - Users must cite the source, must mark edits, and must not present edited content "as if the State created it".
- **robots:** `/robots.txt` returns the application page, so no robots file is served.
- **Fit:** (a) `api_feed` (`generic_json`) against API v2, with daily queries by update date. Content is Japanese; translation per M4.

#### C10 Singapore: Cyber Security Agency legislation pages
- **Owner and URL:** CSA. https://www.csa.gov.sg/legislation/
- **Coverage:** Cybersecurity Act, Codes of Practice, notices, forms and consultations. The page says "Last updated on 25 February 2026".
- **Format and access:** HTML. No feed was found.
- **Cadence:** not stated.
- **Terms** (https://www.csa.gov.sg/terms-of-use/): "Except as otherwise provided, the Contents of this website shall not be reproduced, republished, uploaded, posted, transmitted or otherwise distributed in any way, without the prior written permission of CSA."
- **robots:** `Allow: /`, `Disallow: /search`.
- **Fit:** (a) `web_page` in single mode with change detection, for internal monitoring only. No text goes into seeds, and nothing goes into external outputs without CSA permission.
- **Not reached:** Singapore Statutes Online (`sso.agc.gov.sg`) answered HTTP 403 "Request blocked" (CloudFront) to this session. The PDPC site loads but was not assessed.

#### C11 India: no official source reached
`www.indiacode.nic.in` timed out with no bytes on two tries (25 s and 40 s), and `egazette.gov.in` timed out on one try. `www.meity.gov.in` served `robots.txt` (`Allow: /`) but answered its home page with "Access Denied" (Akamai). **Fit:** unverified. India is a day-one jurisdiction, and neither 4.5 nor this research has a working source for it (BL-24).

#### C12 Brazil: LexML portal
- **Owner and URL:** a national network run from the Senado Federal. https://www.lexml.gov.br
- **Coverage:** an aggregator. `desc_acervo.html` lists providers and counts: for example, Senado Federal 291,420 documents (federal legislation and bills) and Câmara dos Deputados 258,444, plus state, municipal, court and agency collections.
- **Format and access:** HTML search; an SRU interface at `/sru`, which returned HTTP 503 when checked; URN resolution at `/urn`.
- **Cadence:** not stated.
- **Terms:** not found. The documentation host `projeto.lexml.gov.br` did not resolve.
- **robots:** `Disallow: /busca/`, `/doc/`, `/linker/`; `Allow: /urn` and `/sru`; `Crawl-delay: 5`; the `Python-Requests` User-Agent is disallowed (the SafeFetcher User-Agent is descriptive, per 8.3).
- **Fit:** (c) reference now. Becomes (a) `api_feed` (`generic_json` over SRU) once SRU answers and terms are found.

#### C13 Brazil: ANPD (national data protection authority)
- **Owner and URL:** ANPD, on gov.br. https://www.gov.br/anpd/pt-br
- **Coverage:** the authority's own site. Its content pages were not read in this pass, so coverage is not stated here.
- **Format and access:** HTML. No RSS link was found on the page.
- **Cadence:** not stated.
- **Terms:** the gov.br footer says 「Todo o conteúdo deste site está publicado sob a licença Creative Commons Atribuição-SemDerivações 3.0 Não Adaptada」 ("all content is published under CC BY-ND 3.0").
- **robots:** `gov.br/robots.txt` allows anonymous areas and does not disallow `/anpd`.
- **Fit:** (a) `web_page` in listing mode. Because of the no-derivatives (ND) clause, no seed text is derived from it; internal monitoring is unaffected.

#### C14 China: Cyberspace Administration of China, policy and regulation listing
- **Owner and URL:** CAC. https://www.cac.gov.cn/wxzw/zcfg/A093703index_1.htm
- **Coverage:** the listing has tabs for 法律, 行政法规, 部门规章, 司法解释, 规范性文件, 政策文件 and 政策解读 (laws, administrative regulations, departmental rules, judicial interpretations, normative documents, policy documents, interpretations).
- **Format and access:** HTML; the listing is rendered in the browser. Entries seen were dated up to 2026-10-23.
- **Cadence:** not stated.
- **Terms:** the footer reads "© 版权所有" (all rights reserved). No reuse licence was found.
- **robots:** disallows only `/zfz/`, `/wxb_zfz/`, `/wxzf/` and `/vmsfile/newVideo.html?vid=*`.
- **Fit:** (a) `web_page` in listing mode with `render_js`, language zh with translation, internal monitoring only. One plain request was reset by the peer, so keep a low rate and allow retries.

#### C15 China: national laws and regulations database (国家法律法规数据库)
- **URL:** https://flk.npc.gov.cn
- **robots:** begins 「#禁止使用任何自动化工具、脚本、爬虫程序采集或复制网站数据」 ("the use of any automated tool, script or crawler to collect or copy site data is prohibited"), followed by `User-agent: *` and `Disallow: /`.
- **Fit:** (c) reference only, for analysts' manual lookup. M3 must not capture it, and no robots override is acceptable.

## Recommendation

### Starter sources (proposed changes to `docs/04-data-model.md` 4.5; not edited here)

1. **Keep** legislation.gov.uk and make the entry concrete: `rss` source on the Publication Log filtered to legislation and drafts, for example `https://www.legislation.gov.uk/update/legislation/data.feed` and `https://www.legislation.gov.uk/update/draft/data.feed`; `credibility=official`; `config.terms_url` = OGL v3.0 reuse page; per-host limit at or below 8.3 defaults (well under 3,000 requests per 5 min). The URLs come from `api/publication-log.md`; check them live in Phase 2 per 4.5.
2. **Make the national entries concrete** (each with `config.terms_url` set to the terms page quoted above):
   - **Canada:** add Justice Laws XML (C7) beside Canada OPC.
   - **Australia:** add the Federal Register of Legislation (C8) beside OAIC, at one request per 10 s.
   - **Japan:** add the e-Gov Law API v2 (C9) beside Japan NISC.
   - **Singapore:** add the CSA legislation page (C10) beside Singapore CSA news.
   - **Brazil:** keep Brazil ANPD as a `web_page` listing (C13).
   - **China:** point "China CAC" at the 政策法规 listing (C14).
3. **Flag in 4.5:**
   - China's `flk.npc.gov.cn` (C15) must not be captured.
   - Singapore, Australia and China terms limit use to internal monitoring.
   - India has no verified source (C11).
4. **Do not add** OpenSSF, UNCTAD, govinfo or LexML to the day-one starter list:
   - OpenSSF is secondary and EU-only.
   - UNCTAD is unverified.
   - govinfo is a later-phase complement (BL-22, BL-23).
   - LexML's SRU and terms are unconfirmed (BL-24).

### Taxonomy seeds (proposed changes to 4.5 and the M2 seed YAML; not edited here)

| Facet | Proposed term or rule | Source and license |
| --- | --- | --- |
| `regulation_type` | add `implementing act`, `delegated act`, `harmonised standard` | instrument kinds used in C1 `CRA_Basics.md` (implementing and delegated acts), `CRA_Related_Dossiers.md` (Regulation (EU) No 1025/2012 on harmonised standards) and `CRA_Conformity_Assessment.md`; label text from EUR-Lex |
| `topic` > `product security` | child terms `important product class I`, `important product class II`, `critical product`; match rules `Cyber Resilience Act`, `2024/2847`, `products with digital elements` | CRA Annex III and IV via C1 `CRA_Product_Groups.md` (CC-BY-4.0); cite EUR-Lex |
| `topic` > `incident reporting` | match rules `NIS2`, `2022/2555`, `actively exploited vulnerability`, `severe incident` | C1 `CRA_Related_Dossiers.md`, `CRA_Timeline.md` |
| `topic` > `supply chain security` | match rules `SSDF`, `SP 800-218`, `software bill of materials`, `SBOM` | C5 SSDF catalog (CC0) |
| `topic` > `AI governance` | match rules `AI RMF`, `AI 100-1` | C5 AI RMF catalog (CC0) |
| new `control_framework` (custom, multi, not required) | CSF 2.0 functions `GV ID PR DE RS RC` and the 22 active categories, keys = OSCAL IDs | C5 CSF 2.0 catalog (CC0); later phase, BL-21 |

### Register and policy

- No code enters the repository from these sources, so no component register row is needed now. When `seed/` takes derived data, add data rows (C1 CC-BY-4.0, C3 OGL-UK-3.0, C5 CC0-1.0, and C7, C8 or C9 if their text is used) to 3.6; not done here because `docs/03-architecture.md` is being edited by other sessions.
- 3.5 names CC-BY-4.0 for data, but not these terms: OGL-UK-3.0, Open Government Licence - Canada, Japan's PDL1.0, CDLA-Permissive-1.0, EU Commission Decision 2011/833/EU reuse terms, or US public domain government works. BL-20 proposes an ADR to list them, and to record CC BY-ND 3.0 (C13) and all-rights-reserved sites (C10, C14) as "monitor internally, never derive or redistribute".
- No existing ADR is changed by this finding; ADR-0003 (license policy) is the one BL-20 would amend.
