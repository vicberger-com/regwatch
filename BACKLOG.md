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
| BL-40 | CP proposal: ship `translation.provider` values `libretranslate` and `http` only at launch; `argos` in-process is blocked (argostranslate 1.11+ requires AGPL minisbd; 1.10.0 downloads a CC BY-SA spaCy model at import) | R-08 (#11) | change | M4 | research agent | open | | | open a CP issue; enum unchanged until decided |
| BL-41 | Draft ADR-0009 translation provider strategy from R-08 (LibreTranslate default, hosted by key, `titles_summaries`) | R-08 (#11) | change | M4 | research agent | open | | | deferred from R-08 to keep scope |
| BL-42 | Argos de→en 1.3 and ja→en 1.1 packages state no license; owner decision or replace with converted Helsinki-NLP opus-mt-de-en / ja-en (Apache-2.0 per model card) and re-benchmark | R-08 (#11) | risk | M4 | research agent | open | | | Japan is a day-one jurisdiction |
| BL-43 | Normalise input before translation (U+2019 truncated fr output) and flag suspect output (length ratio, CJK punctuation) as low confidence | R-08 (#11) | feature | M4 | research agent | open | | | fixture: R-08 passage fr-4 |
| BL-44 | Route ja (and optionally zh) sources to a hosted provider by per-source override once an 8.4 basis is recorded; measure Azure EU and Google v3 EU on the R-08 passages | R-08 (#11) | feature | M4 | research agent | open | | | needs API key and owner basis |
| BL-45 | Legal-term glossary per language for post-edit checks (deployer, essential entity, 国家网信部门, 個人情報保護委員会) | R-08 (#11) | feature | M4 | research agent | open | | | |
