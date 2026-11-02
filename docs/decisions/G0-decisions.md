# Gate G0 decision log

**Date:** 2026-11-02 · **Gate:** #2 · **Decided by:** owner · **Evidence:** `docs/evidence/phase-0/G0-decision-sheet.xlsx`

The owner accepted the recommended default for all 52 open decisions. Each row names where the decision is now recorded.

| ID | Decide by | Decision (recommended default, accepted) | Recorded in |
| --- | --- | --- | --- |
| ADR-0001 | At G0 | Accept | docs/decisions/ADR-0001 |
| ADR-0002 | At G0 | Accept | docs/decisions/ADR-0002 |
| ADR-0003 | At G0 | Accept | docs/decisions/ADR-0003 |
| ADR-0004 | At G0 | Accept | docs/decisions/ADR-0004; R-05 |
| ADR-0005 | At G0 | Accept, except decision 3 (Node render worker), which follows row A1-2 | docs/decisions/ADR-0005; R-02 |
| ADR-0006 | At G0 | Accept | docs/decisions/ADR-0006 |
| ADR-0007 | At G0 | Accept | docs/decisions/ADR-0007 |
| ADR-0008 | At G0 | Accept | docs/decisions/ADR-0008 |
| A1-5 | Before Phase 1 | Yes; reword CLAUDE.md to 'all outbound HTTP to external hosts goes through SafeFetcher' | ADR-0001 Q5; BL-48 |
| A1-1 | Before Phase 1 | Accept | ADR-0001 Q1 |
| A6-3 | Before Phase 1 | Move the contract to Valkey 9 | ADR-0006 Q3; BL-51 |
| A6-2 | Before Phase 1 | Accept | ADR-0006 Q2 |
| A3-4 | Before Phase 1 | No; only you, at the next gate | ADR-0003 Q4 |
| Q13 | Before Phase 1 | Proprietary, all rights reserved, repository private; add a LICENSE file saying so | Issue #1 Q13 |
| Q14 | Before Phase 1 | No fixed dates; phases run back to back; name the pilot group at Gate G5 | Issue #1 Q14 |
| REG | Before Phase 1 | GitHub Container Registry (GHCR) | ASSUMPTIONS.md |
| GAPS | Before Phase 1 | Accept | 02-requirements 2.2 |
| NET | Before Phase 1 | Switch to Custom: package managers plus the official source domains (legislation.gov.uk, eur-lex.europa.eu, federalregister.gov, legislation.gov.au, laws-lois.justice.gc.ca, elaws.e-gov.go.jp) | cloud environment settings |
| BL-21 | Before Phase 1 | Accept | BL-21; R-03 |
| HIST | Before Phase 1 | Leave as is; all later commits comply | CLAUDE.md |
| GHA | Before Phase 1 | Keep disabled while work runs as cloud sessions; re-enable only with a funded Console API key | docs/06-process.md 6.7 |
| A1-4 | Phase 2 | Yes, separate egress segment; LibreTranslate downloads models once at first start into a persistent volume, then runs without egress | ADR-0001 Q4; BL-48 |
| A2-1 | Phase 2 | Not at launch; titles, summaries and English translations only; revisit after the Phase 2 search benchmark | ADR-0002 Q1 |
| A2-2 | Phase 2 | Yes for Chinese; for Japanese, also match the original-language title until a hosted provider is chosen (see BL-44) | ADR-0002 Q2; R-08 |
| A2-3 | Phase 2 | Accept | ADR-0002 Q3; BL-07 |
| A3-1 | Phase 2 | Approve | ADR-0003 Q1 |
| A3-2 | Phase 2 | Accept | ADR-0003 Q2; BL-20 |
| A3-3 | Phase 2 | Yes, titles and summaries only, for internal monitoring, shown with the original and a machine-translation label; take legal advice before any output leaves the organisation | ADR-0003 Q3; R-03 |
| A6-1 | Phase 2 | Keep the 1 request per 2 s default; set 10 per minute only in the Cellar and Federal Register starter sources | ADR-0006 Q1 |
| Q5 | Phase 2 | No for now; rules-only classification; revisit after Phase 2 measures rule precision | Issue #1 Q5 |
| BL-34 | Phase 2 | Defer until the SearXNG soak test (BL-32); budget stays zero | BL-32, BL-34; R-07 |
| BL-42 | Phase 2 | Do not use them; replace with Apache-2.0 opus-mt models or route German and Japanese to a hosted provider; decide in M4 | BL-42; R-08 |
| BL-44 | Phase 2 | Defer until you choose a provider and record a data-processing basis; it costs money per character | BL-44; R-08 |
| BL-27 | Phase 2 | Yes; decide in Phase 2 whether to request a free govinfo (api.data.gov) key for full text | BL-27; R-06 |
| BL-24 | Phase 2 | You or a colleague check their terms from an ordinary browser; until then they are not sources | BL-24; R-03 |
| FEDLIC | Phase 2 | Accept | ASSUMPTIONS.md; BL-27 |
| TLOAD | Phase 2 | Accept | ASSUMPTIONS.md; R-08 |
| BL-41/46 | Phase 2 | Accept | BL-41, BL-46 |
| R5-Q1 | Phase 3 | Natural Earth default view, disputed areas drawn neutral on top, and a non-endorsement statement on the legal page | ASSUMPTIONS.md; ADR-0004 |
| R5-Q2 | Phase 3 | No; list-only jurisdictions with no geometry | ASSUMPTIONS.md; R-05 |
| R5-Q3 | Phase 3 | Yes, neutral, as code AQ | ASSUMPTIONS.md; R-05 |
| A1-2 | Phase 4 | Defer to the M7 builder spike in Phase 4; Jinja2 stays the contract until then | ADR-0001 Q2; ADR-0005; BL-17 |
| A8-3 | Phase 4 | Decide together with A1-2 at the M7 spike | ADR-0008 Q3 |
| R2-KB | Phase 4 | Accept; confirm with an accessibility check during M7 use testing | ASSUMPTIONS.md; R-02 |
| A8-1 | Phase 4 | No; add after M8 verifies it | ADR-0008 Q1 |
| A8-2 | Phase 4 | Accept | ADR-0008 Q2 |
| A1-3 | Phase 4 | Accept in principle; nothing is built now | ADR-0001 Q3; BL-15 |
| A7-5 | Phase 5 | Not known yet: please name it, or write 'none' | ADR-0007 Q5 |
| A7-1 | Phase 5 | Automatically by verified email, only from your configured identity provider, with an audit entry | ADR-0007 Q1 |
| A7-2 | Phase 5 | Administrators only, as a recovery path | ADR-0007 Q2 |
| A7-3 | Phase 5 | No; roles stay managed in the application | ADR-0007 Q3 |
| A7-4 | Phase 5 | Phase 5, before user evaluation, for local accounts | ADR-0007 Q4; E7 |

## Actions outside the repository

- Cloud environment network access: switch from Full to Custom before Phase 1 coding (row NET). The owner changes this in the environment settings.
- Identity provider: still to be named before M1b (row A7-5).
- BL-24 sources: the owner or a colleague checks their terms from an ordinary browser.
