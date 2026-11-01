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
| BL-16 | Accessibility layer for the Puck editor: keyboard select, Move up and Move down, keyboard insert, live announcements, keyboard panel switcher, iframe title, labels; offer fixes upstream (Puck #1443, #668, #1807) | R-02 (#4) | change | M7 | research agent | open | | | adoption condition in ADR-0005; bar: zero serious or critical axe violations plus a keyboard walkthrough |
| BL-17 | Server rendering through Puck `Render` in an internal Node render worker (with ECharts SSR) instead of Jinja2 templates | R-02 (#4) | change | M7, M8, M0 | research agent | open | | | needs a `CP-nn` to `M0-tooling.md` plus 3.2 and 3.3 updates; Jinja2 stays until accepted |
| BL-18 | Correct the M7 spec and 3.2: drop "Puck supports keyboard sensors; verified"; keep `data_source` beside `layout` (Puck drops extra top-level keys); use `no-external.css`; use `slot` fields, not `DropZone` | R-02 (#4) | change | M7 | research agent | open | | | also confirm the DDL `report_layout.query` column holds the OpenAPI `data_source` object |
| BL-19 | Fallback to a dnd-kit builder if BL-16 misses its bar in the M7 builder spike | R-02 (#4) | risk | M7 | research agent | open | | | about 15 to 25 extra developer-days |
| BL-25 | Per-deployment boundary worldview built from a Natural Earth 1:10m worldview file (for example `_iso`) with the same script | R-05 (#7) | feature | M6 | research agent | open | | | default stays NE default view plus neutral disputed overlay (ADR-0004) |
| BL-26 | ISO 3166-2 subdivision layer, loaded per country, from NE 1:10m admin-1 (4,407 usable codes) | R-05 (#7) | feature | M6, M2 | research agent | open | | | 1:50m admin-1 covers only 9 countries |
| BL-27 | Soak test SearXNG from the production host at production pace (one query per 3 to 7 minutes for 7 days); record engine blocking per day | R-07 (#9) | risk | M3 | research agent | open | | | decides whether SearXNG stays primary |
| BL-28 | M3 search connector: store `unresponsive_engines` per run, count Bing-only or empty answers as failed runs, pace queries at least 60 s apart | R-07 (#9) | change | M3 | research agent | open | | | conditions in R-07 section 4 |
| BL-29 | Owner decision on a fallback search key (Exa or Brave free tier) and acceptance of its terms; recheck prices and terms before Phase 2 | R-07 (#9) | change | M3 | research agent | open | | | Brave terms forbid a database of results without storage rights |
