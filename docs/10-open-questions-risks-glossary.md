# 10. Open questions, risks and glossary

## 10.1 Decisions the owner must make at G0

| # | Decision | Default in this design | Where it bites |
| --- | --- | --- | --- |
| D1 | Deployment target and operator | Docker Compose on one Linux host | M0, M10 |
| D2 | Day-one jurisdictions and topics | Answered: defaults plus China and supply chain security | M2 seeds, M3 sources |
| D3 | Language model use and provider | Translation: yes, admin-selectable provider (R-08). Classification by model: still disabled, owner to decide | M4, section 8.4 |
| D4 | Search provider and budget | Self-hosted metasearch | M3, R-07 |
| D5 | SMTP relay, allowed recipient domains, printers | Admin-configured; browser print at launch | M8 |
| D6 | Identity: local only or SSO at launch | Local, SSO in P5 | M1 |
| D7 | License policy exceptions (AGPL services) | Allowed unmodified behind a network boundary | ADR-0003 |
| D8 | Branding and theme assets | Answered: neutral palette and Inter, plus branding configuration and legal page (E26) | M1, M6, M7 |
| D9 | Toolbar placement and default map encoding | Left rail; recency | M6 |
| D10 | Retention periods | Items indefinite, artifacts 90 days, audit 2 years | M8, M10 |
| D11 | Phase dates and pilot group | Unset | Section 6 |
| D12 | Repository name, branch, registry | Answered: vicaberger/regwatch, main; registry GHCR assumed | M0 |
| D13 | License for the application's own code | Open; repository private meanwhile | root LICENSE |

## 10.2 Risks

| Risk | Likelihood | Impact | Mitigation | Trigger to revisit |
| --- | --- | --- | --- | --- |
| Source sites change layout and silently break scrapers | High | Medium | Change-detection health signals, E2 dashboard, selector tests with fixtures, prefer official feeds and APIs | Source unhealthy 24 hours |
| Rule-based classification too noisy, map lights up on irrelevant items | Medium | High | Precision floor 0.8 on the corpus, confidence-weighted colouring (E11), user feedback loop, severity rules | Pilot trust survey below 3 of 5 |
| Puck's layout model does not fit report pages | Medium | Medium | R-02 spike in P0, dnd-kit fallback (ADR-0005) | Spike fails keyboard or SSR criteria |
| Legal exposure from scraping terms of use | Low | High | Robots respect, terms link per source, official sources first, no redistribution | Any source with restrictive terms needed |
| Parallel sessions drift from conventions | Medium | Medium | CI gates, templates, lead review, this document as the only source of truth | Two PRs conflict on schema or OpenAPI |
| PostgreSQL search latency at scale | Low | Medium | Synthetic 1 million item benchmark in P2, Meilisearch adapter (BL-07) | p95 above 300 ms |
| License contamination through transitive dependencies | Medium | High | CI license scan, ScanCode at release, register discipline | Unknown license in scan |
| Printing to network printers unreliable | Medium | Low | Browser print as the always-available path, bridge flagged | R-04 fails |
| Model provider leaks captured text | Low | High | Disabled by default, redaction, admin-recorded basis | Flag enabled |

## 10.3 Glossary

| Term | Meaning in this design |
| --- | --- |
| Item | A canonical captured document (law, bill, guidance, press release, article) with versions |
| Change event | A dated record that an item was created or materially changed, linked to a jurisdiction; drives the map |
| Jurisdiction | A country, subdivision or supranational body that can be highlighted on the map |
| Facet | A taxonomy dimension (topic, industry, technology, regulation type, custom) |
| Term | A controlled value inside a facet, with synonyms and match rules |
| Source | A configured origin of data with a connector kind and settings |
| Capture job | The schedule and settings for one source |
| Connector | A plugin implementing discover and fetch for a source kind |
| SafeFetcher | The single outbound HTTP client enforcing SSRF, robots and rate-limit controls |
| Saved view | A stored combination of view-by attribute, filters, period and colour scheme |
| Stock report | A report template shipped with the application |
| Layout | A user-built report page definition stored as Puck data |
| Output job | A request to render or deliver a report or query result (PDF, email, print, CSV) |
| Gate | An owner decision closing a phase, recorded in a GitHub issue |
| Questioning period | The module or phase kick-off where questions are posted and answers or assumptions recorded |
| Component register | The table of third-party components with verified licenses and reuse modes |
