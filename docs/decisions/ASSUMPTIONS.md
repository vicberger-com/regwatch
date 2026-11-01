# Assumptions log

Every answer an agent assumed because the owner had not answered by the time work started. Each row links the questioning issue; the owner confirms or overrides at the next gate.

| Date | Module or phase | Question | Assumed answer | Issue | Owner decision |
| --- | --- | --- | --- | --- | --- |
| 2026-11-01 | P0 | Gaps G1 to G17 in `docs/02-requirements.md` | Defaults recorded in section 2.2 | #1 | confirmed by answers to questions 1 to 12 where they overlap; rest pending |
| 2026-11-01 | P0 | Q5: may a model classify captured text? | No; rules only. Owner answered about translation instead (translation accepted, provider selectable) | #1 | pending for classification |
| 2026-11-01 | P0 | Q13: license for the application's own code | None chosen; repository private | #1 | pending |
| 2026-11-01 | P0 | Q14: phase dates and pilot group | Unset; set at G0 | #1 | pending |
| 2026-11-01 | P0 | Container registry | GHCR | #1 | pending |
| 2026-11-01 | P0 (M7) | R-02: does "keyboard-only drag and drop" (REQ-18, WCAG 2.2 AA) require keyboard dragging itself? | No; keyboard alternatives (select, Move up and Move down, Add) satisfy WCAG 2.1.1 and 2.5.7 | #4 | pending |
