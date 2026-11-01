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
| BL-12 | Replace or vendor world-atlas topology (upstream repository archived; last push 2021-08) | R-01 (#3) | risk | M6 | research agent | resolved by R-05: replace; build a GeoJSON from Natural Earth 1:50m with mapshaper; drop world-atlas and topojson-client | research agent (R-05, #7); owner confirms with ADR-0004 | 2026-11-01 | see `docs/research/R-05-map-boundaries.md` |
| BL-13 | Node `ipp` has no LICENSE file and no commits since 2019; choose a licensed, maintained IPP client or browser print only | R-01 (#3) | risk | M8 | research agent | resolved by R-04: browser print only at launch; server print bridge deferred | research agent (R-04, #6); owner confirms at phase gate | 2026-11-01 | `ipp` rejected; no Node client passes the gate; see `docs/research/R-04-ipp-client.md` |
| BL-14 | Add register rows for email-validator and croniter (named in the M8 spec, missing from 3.6) | R-01 (#3) | change | M8 | research agent | open | | | verify LICENSE files when added |
| BL-15 | Server-side printing through a Python IPP client (ippx preferred, aioipp fallback) instead of the Node `print-bridge/` | R-04 (#6) | change | M8, M0 | research agent | open | | | needs a `CP-nn` to `M0-tooling.md`; re-score both clients when scheduled; aioipp >=0.19 needs Python 3.14 |
| BL-20 | ADR amending the license policy for data terms: OGL-UK-3.0, OGL-Canada, Japan PDL1.0, CDLA-Permissive-1.0, EU Commission Decision 2011/833/EU, US public domain government works; mark CC BY-ND and all-rights-reserved sources as internal monitoring only | R-03 (#5) | change | M2, M3 | research agent | open | | | amends ADR-0003 and 3.5; see `docs/research/R-03-policy-data-sources.md` |
| BL-21 | `control_framework` facet seeded from NIST CSF 2.0 OSCAL catalog (CC0), withdrawn entries filtered; SSDF and AI RMF IDs as match rules | R-03 (#5) | feature | M2 | research agent | open | | | answers M2 question bank item 1; source commit `f0de6d8` |
| BL-22 | govinfo bulk data connector (`api_feed` `generic_json`) for CFR and eCFR status | R-03 (#5) | feature | M3 | research agent | open | | | US public domain; complements the Federal Register API starter source |
| BL-23 | OpenSSF Global Cyber Policy WG commit feed as a secondary `rss` source; CRA term seeds taken from EUR-Lex with OpenSSF as index | R-03 (#5) | feature | M2, M3 | research agent | open | | | CC-BY-4.0 attribution if table text is copied |
| BL-24 | Remaining R-03 checks (narrowed after the 2026-11-01 follow-up, which verified CA, AU, JP, SG (CSA), BR (ANPD) and CN): UNCTAD tracker (no response; Internet Archive fallback not run); an Indian official source (India Code, e-Gazette and MeitY timed out or denied access); Singapore Statutes Online (HTTP 403); LexML SRU (HTTP 503) and terms; documentation of the Australian legislation API; EuroVoc | R-03 (#5) | risk | M2, M3 | research agent | open | | | try from a network these sites accept, or ask the publishers |
| BL-25 | Per-deployment boundary worldview built from a Natural Earth 1:10m worldview file (for example `_iso`) with the same script | R-05 (#7) | feature | M6 | research agent | open | | | default stays NE default view plus neutral disputed overlay (ADR-0004) |
| BL-26 | ISO 3166-2 subdivision layer, loaded per country, from NE 1:10m admin-1 (4,407 usable codes) | R-05 (#7) | feature | M6, M2 | research agent | open | | | 1:50m admin-1 covers only 9 countries |
