# R-03: Policy trackers and open legal datasets as data sources and seed taxonomies

**Issue:** #5 · **Modules:** M2, M3 · **Requirements:** REQ-02, REQ-03, REQ-05 · **Date:** 2026-11-01
**Policy:** `docs/03-architecture.md` 3.5 · **Protocol:** 3.8 · **Connector kinds:** `docs/contracts/connectors.yaml` · **Etiquette:** `docs/08-security-compliance.md` 8.3

## Question

Can the OpenSSF Global Cyber Policy working group material, the UNCTAD Global Cyberlaw Tracker and at least three similar sources serve the application as data sources or seed taxonomies (not as code), and how?

Fit codes: **(a)** capture source for M3 (connector kind named), **(b)** seed for M2 facets and terms, **(c)** jurisdiction reference only, **(d)** not usable.

## Method and limits

1. GitHub-hosted material was read from a clone at a recorded commit (`git clone --depth`); the commit and the files read are listed in each block. Licenses and terms are quoted from those files.
2. **Network limit.** This session's network policy refused every host other than GitHub (proxy `connect_rejected` for `unctad.org`, `policy.openssf.org`, `openssf.org`, `eur-lex.europa.eu`; DNS refusal for `unctad.org` in the fetch tool). No live endpoint, terms page or `robots.txt` on those hosts could be opened. Where a block depends on such a page it says **not verified** and states nothing about content, license or cadence. Search-engine snippets were seen for UNCTAD but are **not** used as evidence.
3. Candidate discovery used GitHub repository search for official owners (`usnistgov`, `usgpo`, `legislation`) and for regulation trackers. Third-party trackers without a license are included only to record why they are rejected.

## Summary

| # | Candidate | Owner | Access | License or terms (as read) | Last update seen | Verified at | Fit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | OpenSSF Global Cyber Policy WG repository | OpenSSF (Linux Foundation) | Git repository (Markdown tables, PDFs); Jekyll site `policy.openssf.org` | `LICENSE` Apache-2.0; `CHARTER.md`: documentation CC-BY-4.0, data CDLA-Permissive-1.0 | 2026-09-25 (repo); regulations table 2025-04-18; CRA tables 2025-12-01 | `3e45ac6` | (b) CRA terms; (c) EU/UK index; (a) optional `rss` on commits, secondary |
| C2 | UNCTAD Global Cyberlaw Tracker | UNCTAD | not verified | not verified | not verified | host blocked | provisional (c), pending verification |
| C3 | legislation.gov.uk API and Publication Log | The National Archives (UK) | Atom feeds (`/data.feed`), CLML XML (`/data.xml`), HTML | Open Government Licence v3.0; EU-origin items also Commission Decision 2011/833/EU; fair-use policy (3,000 requests per 5 min) | docs repo 2025-07-01; live feed not fetched | docs `2812c7a` | (a) `rss` or `api_feed` (`legislation_gov_uk`) |
| C4 | govinfo bulk data (Federal Register, CFR, eCFR, bills) | US Government Publishing Office | Bulk XML; directory listings as XML or JSON (`/bulkdata/json/...`) | US government works not subject to copyright; no downstream restriction except representing an official version | guide repo 2026-06-11; live listing not fetched | guide `83a8517` | (a) `api_feed` (`generic_json`) for CFR and eCFR; complements the Federal Register API starter |
| C5 | NIST OSCAL content (CSF 2.0, SSDF SP 800-218, AI RMF 1.0, SP 800-53) | NIST | Git repository; OSCAL catalogs in XML, JSON, YAML | Public domain in the US plus CC0-1.0 worldwide | 2026-10-22 | `f0de6d8` | (b) seed for a control-framework facet and topic match rules |
| C6 | Asenion (Fairly AI) AI regulation and policy tracker | Fairly AI (company) | README pointing to a Google My Maps map | no stated license | 2026-09-18 | `ab887aa` | (d) not usable |

**Coverage of day-one jurisdictions.** The verified candidates cover the EU (C1, and via C3's EU-origin copies), the UK (C1, C3) and US federal (C4, C5). None of them covers Canada, Australia, Japan, Singapore, India, Brazil or China. Sources for those (and UNCTAD) sit on hosts this session could not reach; BL-24 carries that verification.

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
**License or terms:** **not verified.** `unctad.org` was refused by the session network policy, so the tracker page, any download, the UNCTAD terms of use and `robots.txt` were not opened. · **Policy result:** unknown

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
| Machine access and etiquette | 5 | `fair-use.md`: identify with a User-Agent with contact, "follow the rules in our robots.txt", "must not exceed ... 3,000 requests in any 5 minute period", conservative crawl rate "e.g. 10 requests per 5-10 seconds" if no crawl-delay. The live `robots.txt` was not reachable; the `robots.txt` in the docs repo applies to the documentation site only |

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
| Machine access | 3 | bulk download; `govinfo.gov` `robots.txt` and site terms not reachable |

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

### Leads not assessed (hosts unreachable from this session)

Named so BL-24 can pick them up; no claims are made about them here: EuroVoc thesaurus (EU Publications Office) as an M2 seed; national gazettes or law portals for Canada, Australia, Japan, Singapore, India, Brazil and China; the starter-list agencies in `docs/04-data-model.md` 4.5.

## Recommendation

### Starter sources (proposed changes to `docs/04-data-model.md` 4.5; not edited here)

1. **Keep** legislation.gov.uk and make the entry concrete: `rss` source on the Publication Log filtered to legislation and drafts, for example `https://www.legislation.gov.uk/update/legislation/data.feed` and `https://www.legislation.gov.uk/update/draft/data.feed`; `credibility=official`; `config.terms_url` = OGL v3.0 reuse page; per-host limit at or below 8.3 defaults (well under 3,000 requests per 5 min). The URLs come from `api/publication-log.md`; check them live in Phase 2 per 4.5.
2. **Do not add** OpenSSF, UNCTAD or govinfo to the day-one starter list. OpenSSF is secondary and EU-only; UNCTAD is unverified; govinfo is a later-phase complement (BL-22, BL-23, BL-24).

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

- No code enters the repository from these sources, so no component register row is needed now. When `seed/` takes derived data, add data rows (C1 CC-BY-4.0, C3 OGL-UK-3.0, C5 CC0-1.0) to 3.6; not done here because `docs/03-architecture.md` is being edited by other sessions.
- 3.5 names CC-BY-4.0 for data but not OGL-UK-3.0, CDLA-Permissive-1.0, EU Commission Decision 2011/833/EU reuse terms or US public domain government works. BL-20 proposes an ADR to list them.
- No existing ADR is changed by this finding; ADR-0003 (license policy) is the one BL-20 would amend.
