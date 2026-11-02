# Assumptions log

Every answer an agent assumed because the owner had not answered by the time work started. Each row links the questioning issue; the owner confirms or overrides at the next gate.

| Date | Module or phase | Question | Assumed answer | Issue | Owner decision |
| --- | --- | --- | --- | --- | --- |
| 2026-11-01 | P0 | Gaps G1 to G17 in `docs/02-requirements.md` | Defaults recorded in section 2.2 | #1 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 | Q5: may a model classify captured text? | No; rules only. Owner answered about translation instead (translation accepted, provider selectable) | #1 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 | Q13: license for the application's own code | None chosen; repository private | #1 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 | Q14: phase dates and pilot group | Unset; set at G0 | #1 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 | Container registry | GHCR | #1 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 (M6) | R-05 Q1: which disputed-borders point of view does the map use? | Natural Earth default view, with NE's disputed and breakaway areas drawn neutral on top and a non-endorsement statement on the legal page | #7 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 (M6) | R-05 Q2: do overseas regions drawn inside France (GF, GP, MQ, RE, YT) shade with FR? | No; they are list-only jurisdictions with no geometry | #7 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 (M6) | R-05 Q3: is Antarctica drawn? | Yes, neutral, as code AQ | #7 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 (M7) | R-02: does "keyboard-only drag and drop" (REQ-18, WCAG 2.2 AA) require keyboard dragging itself? | No; keyboard alternatives (select, Move up and Move down, Add) satisfy WCAG 2.1.1 and 2.5.7 | #4 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 (R-06) | License of Federal Register API data | US government work, no reuse restriction (as in 4.5); the FR legal-status page could not be read from automation | #8 | accepted at G0 (2026-11-02) |
| 2026-11-01 | P0 (M4) | Item size for translation load (R-08) | Title plus summary about 700 characters; full text about 15,000 characters; about 200 non-English items a day | #11 | accepted at G0 (2026-11-02) |
| 2026-11-02 | P1 (M0) | Q5: any corporate proxy or air-gapped constraint for builds? | None. Builds use the public registries and package indexes; a TLS-intercepting proxy is supported without code changes by passing its CA as the optional `build_ca` build secret (`deploy/README.md`) | #24 | |
| 2026-11-02 | P1 (M0) | Which PostgreSQL driver may the application use, given `postgresql+psycopg://` in env.example and psycopg's LGPL-3.0? | asyncpg (Apache-2.0); the contract URL is accepted and only its scheme is rewritten; see CP-01 | #28, #39 | |
| 2026-11-02 | P1 (M0) | How do the schema.sql comments expand (citext, `-- std` triggers, `regwatch_app` grants)? | As described in CP-01 points 1 to 3: citext created, triggers on `jurisdiction` and the 13 `-- std` tables only, `regwatch_app` NOLOGIN with INSERT and SELECT only on `audit_log` | #28, #39 | |
| 2026-11-02 | P1 (M0) | Seed semantics on re-run | Rows are inserted only when missing, so admin edits survive; permission text follows the registry. registries.yaml text split at commas is rejoined (CP-01 point 4) | #28 | |
| 2026-11-02 | P1 (M2) | Jurisdiction names, regions and view-selector facets in the seed | Names are i18n-iso-countries' first (official) English name; `region_code` is the M49 sub-region, with TW → 030 and XK → 039 because M49 lists neither; AQ has none; supranational bodies have no region or geometry; topic, industry, technology and regulation_type are in the view selector, control_framework is not; M49 codes may be used as identifiers (UN terms page unreachable) | #28 | |
