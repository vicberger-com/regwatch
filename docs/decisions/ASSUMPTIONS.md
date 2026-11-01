# Assumptions log

Every answer an agent assumed because the owner had not answered by the time work started. Each row links the questioning issue; the owner confirms or overrides at the next gate.

| Date | Module or phase | Question | Assumed answer | Issue | Owner decision |
| --- | --- | --- | --- | --- | --- |
| 2026-11-01 | P0 | Gaps G1 to G17 in `docs/02-requirements.md` | Defaults recorded in section 2.2 | #1 | confirmed by answers to questions 1 to 12 where they overlap; rest pending |
| 2026-11-01 | P0 | Q5: may a model classify captured text? | No; rules only. Owner answered about translation instead (translation accepted, provider selectable) | #1 | pending for classification |
| 2026-11-01 | P0 | Q13: license for the application's own code | None chosen; repository private | #1 | pending |
| 2026-11-01 | P0 | Q14: phase dates and pilot group | Unset; set at G0 | #1 | pending |
| 2026-11-01 | P0 | Container registry | GHCR | #1 | pending |
| 2026-11-01 | P0 (M6) | R-05 Q1: which disputed-borders point of view does the map use? | Natural Earth default view, with NE's disputed and breakaway areas drawn neutral on top and a non-endorsement statement on the legal page | #7 | pending |
| 2026-11-01 | P0 (M6) | R-05 Q2: do overseas regions drawn inside France (GF, GP, MQ, RE, YT) shade with FR? | No; they are list-only jurisdictions with no geometry | #7 | pending |
| 2026-11-01 | P0 (M6) | R-05 Q3: is Antarctica drawn? | Yes, neutral, as code AQ | #7 | pending |
| 2026-11-01 | P0 (M7) | R-02: does "keyboard-only drag and drop" (REQ-18, WCAG 2.2 AA) require keyboard dragging itself? | No; keyboard alternatives (select, Move up and Move down, Add) satisfy WCAG 2.1.1 and 2.5.7 | #4 | pending |
| 2026-11-01 | P0 (R-06) | License of Federal Register API data | US government work, no reuse restriction (as in 4.5); the FR legal-status page could not be read from automation | #8 | pending (BL-27) |
| 2026-11-01 | P0 (M4) | Item size for translation load (R-08) | Title plus summary about 700 characters; full text about 15,000 characters; about 200 non-English items a day | #11 | pending |
