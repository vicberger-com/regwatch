# 7. Testing and quality gates

Every module passes five reviews before the owner evaluates it: automated tests, peer review, security review, use testing and adversarial analysis (REQ-25). The whole application passes the same five at Phase 5. Evidence is stored under `docs/evidence/phase-n/` and linked from the gate issue.

## 7.1 Test pyramid and coverage floors

| Level | Tooling | Floor | Where |
| --- | --- | --- | --- |
| Unit, API | pytest, pytest-cov, Hypothesis | 85 percent lines on `regwatch/` excluding generated code; 100 percent on `SafeFetcher`, permission checks, attribute validator, output destination validation | `api/tests/unit` |
| Unit, web | Vitest, Testing Library | 80 percent on `src/features` and `src/lib` | `web/src/**/*.test.tsx` |
| Integration | pytest with Docker services (PostgreSQL, Valkey, Gotenberg, Mailpit, local HTTP fixture server) | every API route exercised at least once; every connector against fixtures | `api/tests/integration` |
| Contract | Schemathesis (MIT) against the committed OpenAPI; generated TypeScript client type-checks | zero schema violations | CI job `contract` |
| End to end | Playwright | every acceptance-criterion journey in every module, in light, dark and high-contrast | `web/e2e` |
| Accessibility | axe-core per route, Lighthouse CI accessibility score 95 or above, manual screen-reader script | zero serious or critical | `web/e2e/a11y` |
| Performance | k6 scenarios; Lighthouse budgets | section 3 and module budgets | `tests/perf` |
| Security | Semgrep, Bandit, ESLint security rules, pip-audit, npm audit, Trivy, gitleaks, OWASP ZAP baseline on PR and full scan nightly on staging | zero high or critical open | CI `security.yml` |
| License | pip-licenses, license-checker, ScanCode on release | zero prohibited | CI `ci.yml` |

## 7.2 Test data

- `tests/fixtures/corpus/`: 200 public-domain or openly licensed regulatory documents (Federal Register entries, EUR-Lex summaries, UK legislation extracts) with expected jurisdictions and terms in `expected.yaml`. Licensing of each fixture is recorded in `corpus/NOTICES.md`.
- `tests/fixtures/feeds/`: valid, malformed, huge, and hostile RSS and Atom files.
- `tests/fixtures/pages/`: static HTML pages with change sequences (v1, v2, v3), robots.txt variants, a JavaScript-rendered page.
- `tests/fixtures/synthetic/`: generator script producing 1 million items across 250 jurisdictions for performance tests (seeded, deterministic).
- Fixture HTTP server (`tests/support/fixture_server.py`) serves these with configurable delays, status codes and redirects, including redirects to private addresses for SSRF tests.

## 7.3 Automated test rules for agents

1. A failing test is never deleted or skipped to make CI green; it is fixed or the issue is reopened with the reason.
2. Tests assert behaviour through public interfaces (API, UI, task results), not private internals, except for pure functions.
3. Every bug fix adds a regression test named after the issue number.
4. Flaky tests are quarantined by label within 24 hours and fixed within the phase; a quarantined test blocks the gate.
5. Snapshots (visual, OpenAPI) are updated only with a reviewer's explicit approval in the PR.

## 7.4 Peer review protocol

A reviewer session that did not write the code checks, in order: requirement traceability (IDs present and tests cover them), correctness against the spec's acceptance criteria, error handling and logging, security surfaces touched (hand to 7.5 if any), tests present and meaningful (would they fail if the feature broke), accessibility of UI changes, documentation and changelog, license register for new dependencies, size and clarity. The reviewer leaves findings as PR comments with severity (blocker, major, minor, nit) and ends with `approve` or `request changes`. Record: PR review itself.

## 7.5 Security review record (per module and at Phase 5)

Template `docs/templates/SECURITY_REVIEW.md`: scope, data flows touched, STRIDE table (spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege) with controls and residual risk, checklist results (input validation, output encoding, authentication, authorization on every route, session handling, secrets, outbound requests through SafeFetcher, file handling and size limits, template rendering escaping, email header injection, logging of sensitive data, dependency and image scan results), tool outputs attached (Semgrep, ZAP), findings with severity and fix PRs, sign-off by a session that did not author the module. No high or critical open findings at module done.

## 7.6 Use testing protocol

For each module, a tester session (or the owner's pilot users in Phase 6) runs the scripted journeys in `docs/evidence/phase-n/use-testing/Mx.md`: preconditions, steps, expected outcome, actual outcome, screenshots, time taken, usability notes using a 1 to 5 ease score. Journeys come from the module's acceptance criteria plus three "realistic day" scenarios written by the lead (for example: "Monday morning, what changed in Europe last week, print it for the team"). Findings become issues labelled `type:usability` and feed BACKLOG rows.

## 7.7 Adversarial analysis protocol

A red-team session with no prior involvement in the module attempts, with a time box of one session, to: break authorization (IDOR on every id-bearing route, role escalation), abuse capture (SSRF, DNS rebinding, slowloris-style sources, zip bombs, redirect loops, robots evasion), poison data (HTML and script injection in captured content rendered in the UI, diff viewer, reports and emails; prompt injection against the model classifier), exfiltrate (email to outside domains, signed URL guessing, CSV formula injection), deny service (unbounded queries, export caps, report rendering loops, scheduler floods), and defeat accessibility claims (keyboard traps, focus loss, contrast). The record lists each attempt, result, and fix issue. Template `docs/templates/ADVERSARIAL_RECORD.md`. Fixes are verified by re-running the attempt.

## 7.8 Phase gate checklist

- [ ] All module definitions of done in the phase are complete and linked
- [ ] CI green on the release branch; coverage report attached
- [ ] Contract tests pass against the committed OpenAPI
- [ ] End-to-end suite green in three themes; accessibility report attached
- [ ] Performance results within budgets attached
- [ ] Security scans attached; no high or critical open
- [ ] Peer, security, use and adversarial records attached for every module
- [ ] License scan clean; component register and notices updated
- [ ] CHANGELOG release section cut; BACKLOG decisions recorded; CP issues summarised
- [ ] Questioning-period issues closed or assumptions recorded
- [ ] Owner comment `approved`

## 7.9 User phased evaluation (Phase 6)

Wave 1: owner plus two analysts, two weeks, map and search only. Wave 2: full pilot group, reports and outputs enabled, two weeks. Wave 3: all intended users. Each wave collects the use-testing script results, a short survey (task success, ease, trust in data), and defect reports; the lead triages daily into fix issues or backlog rows. Exit when wave 3 shows task success above 90 percent on the scripted journeys and no open high-severity defects.
