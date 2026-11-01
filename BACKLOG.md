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
| BL-25 | Per-deployment boundary worldview built from a Natural Earth 1:10m worldview file (for example `_iso`) with the same script | R-05 (#7) | feature | M6 | research agent | open | | | default stays NE default view plus neutral disputed overlay (ADR-0004) |
| BL-26 | ISO 3166-2 subdivision layer, loaded per country, from NE 1:10m admin-1 (4,407 usable codes) | R-05 (#7) | feature | M6, M2 | research agent | open | | | 1:50m admin-1 covers only 9 countries |
| BL-13 | Node `ipp` has no LICENSE file and no commits since 2019; choose a licensed, maintained IPP client or browser print only | R-01 (#3) | risk | M8 | research agent | open | | | resolve in R-04; register row stays S |
| BL-14 | Add register rows for email-validator and croniter (named in the M8 spec, missing from 3.6) | R-01 (#3) | change | M8 | research agent | open | | | verify LICENSE files when added |
