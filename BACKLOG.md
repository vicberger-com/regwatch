# Backlog

Rows are added by agents with decision `open`; the owner decides at the next phase gate. Accepted rows become GitHub issues. Enhancement details are in `docs/09-enhancements-backlog.md`.

| BL-id | Title | Origin | Type | Module | Proposed by | Decision | Decided by | Date | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BL-01 | Kubernetes manifests and Helm chart | design (G1) | deferral | M10 | design session | open | | | |
| BL-02 | Phone-width layout | design (G16) | deferral | M6 | design session | open | | | |
| BL-03 | Authenticated and paywalled sources | design | deferral | M3 | design session | open | | | |
| BL-04 | Excel and DOCX export | design (question 10) | deferral | M8 | design session | open | | | E18 covers Excel |
| BL-05 | Syslog or SIEM forwarding of the audit log | design (M1) | deferral | M1 | design session | open | | | |
| BL-06 | Sitemap and PDF gazette connectors | design (M3) | feature | M3 | design session | open | | | |
| BL-07 | Meilisearch adapter if latency targets fail | design (ADR-0002) | risk | M5 | design session | open | | | |
| BL-08 | Enhancements E1 to E25 | design (section 9) | feature | various | design session | open | | | one row per enhancement once accepted |
| BL-09 | E9 translation with selectable provider | owner (question 5) | feature | M4 | owner | accepted | owner | 2026-11-01 | in M4 scope; research R-08 |
| BL-10 | E26 branding configuration and legal page with markings | owner (question 9) | feature | M1, M6, M7, M8 | owner | accepted | owner | 2026-11-01 | in M1, M6, M7 scope |
| BL-11 | Add China to day-one jurisdictions and supply chain security to topics | owner (questions 2, 3) | change | M2, M3 | owner | accepted | owner | 2026-11-01 | seeds updated |
| BL-12 | Replace or vendor world-atlas topology (upstream repository archived; last push 2021-08) | R-01 (#3) | risk | M6 | research agent | open | | | ISC license fine; maintenance input for ADR-0004 |
| BL-13 | Node `ipp` has no LICENSE file and no commits since 2019; choose a licensed, maintained IPP client or browser print only | R-01 (#3) | risk | M8 | research agent | open | | | resolve in R-04; register row stays S |
| BL-14 | Add register rows for email-validator and croniter (named in the M8 spec, missing from 3.6) | R-01 (#3) | change | M8 | research agent | open | | | verify LICENSE files when added |
| BL-27 | Federal Register HTML and full-text links redirect automated clients to a CAPTCHA (`unblock.federalregister.gov`); capture API metadata and abstracts only. Decide on full text via the govinfo API (api.data.gov key) or an OFR IP-range request; re-read the FR API docs and legal-status page from a browser | R-06 (#8) | risk | M3 | research agent | open | | | rate limit and license wording not stated on any page readable from automation |
| BL-28 | EUR-Lex website (documents, robots.txt, legal notice, help pages) answers non-browser clients with an AWS WAF challenge; use Cellar SPARQL and content negotiation; confirm the current legal-notice wording, SOAP web-service terms and subject RSS feed IDs from a browser | R-06 (#8) | risk | M3 | research agent | open | | | |
| BL-29 | legislation.gov.uk fair-use limit is 1,500 requests per 5 minutes (live page), not 3,000 as recorded in R-03; block enabling sources that require a contact User-Agent while `general.contact_email` is empty | R-06 (#8) | change | M3, M1 | research agent | open | | | correct R-03 text when PR #16 merges |
| BL-30 | M3 spec says `config.terms_url`; the contracts store `terms_url` on `source` (schema.sql, OpenAPI). Correct the spec line | R-06 (#8) | change | M3 | research agent | open | | | doc drift only, contract is right |
| BL-31 | CP proposal: `connectors.yaml` `api_feed.config.field_map` description is an unquoted flow-mapping value containing commas, so it parses into null-valued keywords (`title: null` ...) and fails JSON Schema meta-validation; quote the description | R-06 (#8) | change | M3 | research agent | open | | | needs a CP issue; validators must skip check_schema until fixed |
