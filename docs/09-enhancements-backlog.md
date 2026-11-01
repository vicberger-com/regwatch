# 9. Suggested enhancements and initial backlog (REQ-22)

Suggestions are ranked by value to the stated goal (seeing what changed, where, and reporting it) against effort. Each becomes a `BACKLOG.md` row with status `open` for the owner's decision at G0.

| ID | Enhancement | Why it helps | Module | Effort | Suggested phase |
| --- | --- | --- | --- | --- | --- |
| E1 | Alerts and digests: daily or weekly email digest per saved view, plus optional webhook | Users do not need to open the map to learn about changes | M8, M5 | M | P4 |
| E2 | Source health dashboard with success-rate chart and last-error drill-down | Capture silently failing is the biggest operational risk | M3, M6 | S | P2 |
| E3 | Email alert when a source is unhealthy for 24 hours | Same | M3, M8 | S | P4 |
| E4 | Model-generated summaries and obligation extraction (who must do what by when) behind the flag | Turns documents into actionable items for compliance teams | M4 | L | P5 or later |
| E5 | Semantic search with pgvector | Finds related regulations across wording and languages | M5 | M | later |
| E6 | Natural-language query box that compiles to the query DSL | Lowers the barrier for occasional users | M5, M6 | M | later |
| E7 | Multi-factor authentication (TOTP) | Expected in corporate tools | M1 | S | P5 |
| E8 | OpenID Connect single sign-on (M1b) | Corporate identity integration | M1 | M | P5 |
| E9 | Machine translation of titles and summaries to English with a selectable provider | Global coverage without language skills; owner-requested (question 5) | M4 | M | P2 (in M4 scope) |
| E10 | Multilingual taxonomy labels and UI locales | Non-English teams | M2, M9 | M | later |
| E11 | Map colouring weighted by severity and confidence, with an uncertainty pattern | Avoids false alarms from low-confidence tagging | M6, M4 | S | P3 |
| E12 | Timeline view of changes per jurisdiction or topic | Shows trajectory, not just current state | M6 | M | P4 |
| E13 | Comparison matrix of several jurisdictions on selected topics | Common analyst task | M6, M7 | M | P4 |
| E14 | Watchlists with badges and per-user follow of jurisdictions, topics or regulations | Personal relevance | M6, M9 | S | P3 |
| E15 | Command palette with keyboard shortcuts | Power-user speed; accessibility win | M6 | S | P3 |
| E16 | Scheduled report runs | Monday-morning packs without manual work | M8 | S | P4 (in M8 scope) |
| E17 | Report parameters at print time (choose jurisdiction, period) | One layout serves many uses | M7 | S | P4 |
| E18 | Excel export of tables (openpyxl, MIT) | Analysts work in spreadsheets | M8 | S | P4 |
| E19 | Webhooks and chat notifications (Apprise, BSD-2) | Fits existing team channels | M8 | S | later |
| E20 | Regulatory calendar: effective dates, consultation deadlines extracted to a calendar view and ICS feed | Deadlines are what teams act on | M4, M6 | M | later |
| E21 | Public read-only API tokens for downstream systems (GRC tools) | Integration | M1, M5 | S | later |
| E22 | Regulation record curation workflow (link items to a regulation, set status) with review queue | Turns raw items into a maintained register | M4, M6 | L | later |
| E23 | Side-by-side version diff with change highlighting inside the jurisdiction panel | Faster review of what changed | M6 | S | P3 (in M6 scope) |
| E24 | Data quality page: untagged items, low-confidence tags, duplicates to merge | Keeps the taxonomy useful | M4, M6 | S | P4 |
| E25 | Devcontainer and one-command demo dataset | Faster onboarding of agents and evaluators | M0 | S | P1 |
| E26 | Branding configuration (logo, title, company fields) and company legal page with required markings insertable into reports and emails | Owner-requested (question 9); corporate look | M1, M6, M7, M8 | M | P1 settings, P3 UI, P4 reports |

## Initial BACKLOG.md seed

| BL-id | Title | Origin | Type | Module | Decision |
| --- | --- | --- | --- | --- | --- |
| BL-01 | Kubernetes manifests and Helm chart | design (G1) | deferral | M10 | open |
| BL-02 | Phone-width layout | design (G16) | deferral | M6 | open |
| BL-03 | Authenticated and paywalled sources | design | deferral | M3 | open |
| BL-04 | Excel and DOCX export | design (question 10) | deferral | M8 | open |
| BL-05 | Syslog or SIEM forwarding of audit log | design (M1) | deferral | M1 | open |
| BL-06 | Sitemap and PDF gazette connectors | design (M3) | feature | M3 | open |
| BL-07 | Meilisearch adapter if latency targets fail | design (ADR-0002) | risk | M5 | open |
| E1 to E25 | as above | design | feature | various | open |

## Research items for Phase 0

| ID | Question to settle | Owner agent |
| --- | --- | --- |
| R-01 | Verify every component register row against its LICENSE file; record commit hashes | research, backend |
| R-02 | Confirm Puck supports keyboard-only drag and drop and server-side rendering of its data model; otherwise plan dnd-kit fallback (ADR-0005) | research, frontend |
| R-03 | Evaluate OpenSSF Global Cyber Policy working group repository and the UNCTAD cyberlaw tracker as data sources or seed taxonomies, not as code | research, capture |
| R-04 | Confirm an MIT or Apache licensed IPP client (Node `ipp` or alternative) prints to a test IPP server; otherwise browser print only at launch | research, backend |
| R-05 | Measure MapLibre choropleth performance with 1:50m versus 1:110m Natural Earth and choose the vendored resolution | research, frontend |
| R-06 | Check EUR-Lex, Federal Register, legislation.gov.uk API terms and rate limits; document in source configs | research, capture |
| R-07 | Decide self-hosted SearXNG versus commercial search API for the first release based on quality on 20 benchmark queries | research, capture |
| R-08 | Evaluate translation providers: Argos Translate (MIT, local), LibreTranslate (AGPL, unmodified service), hosted APIs; verify per-language model licenses; benchmark on 30 regulatory passages in zh, ja, de, fr, es, pt | research, capture |
