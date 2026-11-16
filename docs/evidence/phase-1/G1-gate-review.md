# Gate G1 review: Phase 1 Foundation (M0, M1, M2)

**Prepared by:** lead session · **Build under review:** `sec/M0-scan-clean` (top of the Phase 1 stack) · **Date:** 2026-11-16 · **Decision:** owner, as the comment `approved` on the `Gate G1` issue (docs/06-process.md 6.1)

**Exit criterion (6.1):** fresh clone to running stack; admin logs in, creates users and taxonomy; CI gates proven.

## Checklist (docs/07-testing-quality.md 7.8)

| Item | Status | Evidence |
| --- | --- | --- |
| Module definitions of done complete and linked | **Mostly.** M0 done. M1 done except the parts other modules own (report and email branding in M7 and M8; SSO is M1b in Phase 5). M2 done. | Module specs in `docs/modules/`; open items are in BACKLOG (below) |
| CI green on the release branch; coverage report attached | **Pending the owner:** every branch passes locally, but CI runs on GitHub once the PRs are opened | Local: `make lint` clean; `make test-api` 523 unit and 99 database tests, combined coverage 96.55% (floor 85%), security-critical modules at 100%; `make test-web` 96 tests, 98.3% lines |
| Contract tests pass against the committed OpenAPI | **Yes** | `python -m tests.openapi_semantic`: 0 differences across 92 operations; Schemathesis passes in `make test-api` |
| End-to-end suite green in three themes; accessibility report | **Not applicable at G1:** `make e2e` lands in Phase 3 (Makefile, M0-tooling) | Component tests use role and label queries; axe and Playwright are not run yet |
| Performance results within budgets | **Not measured.** Phase 1 has no latency budget of its own; the G2 budgets cover search and the map | none |
| Security scans attached; no high or critical open | **Yes, with one owner item:** `make security` passes (bandit, semgrep, pip-audit, pnpm audit at the high threshold, gitleaks). Six moderate advisories remain in test tooling (BL-82). BL-60 records Trivy criticals accepted in `.github/trivy/web.trivyignore.yaml` until 2026-12-02. | Run of 2026-11-16 on `69ddb65` |
| Peer, security, use and adversarial records for every module | **Security and use: yes. Peer and adversarial: not yet.** Use testing (2026-11-16, isolated QA stack, headless Chromium): 39 journeys, 24 passed and 12 failed (M0 4, M1 4, M2 0); findings in BL-83. The adversarial session was stopped by the model provider's safety filter before it ran any test; the owner chooses another session, a human tester, or deferral to G5. | Security: `M1-security-review.md`, `M2-security-review.md`, `web-security-review.md`, `web-admin-security-review.md`, `BL-68-security-review.md`, all signed off after re-verification. Peer review is due on each PR (7.4). Use-testing and adversarial records for M0 to M2 are still to be written (7.6, 7.7). |
| License scan clean; register and notices updated | **Yes** | `scripts/license-scan.sh`: 551 allowed, 1 by reviewed exception, 0 failing; register rows with R-01 addenda B1 to B7; `api/THIRD_PARTY_NOTICES.md` (the full MIT and Apache notice set for nh3's crates is BL-81 a, due before the API image is first distributed) |
| CHANGELOG release section cut; BACKLOG decisions recorded; CP issues summarised | **At the gate:** the release section is cut when the owner approves; decisions are below | `CHANGELOG.md` Unreleased |
| Questioning-period issues closed or assumptions recorded | **Answered:** the owner accepted the defaults for all M0 to M2 bank questions on 2026-11-16 (ASSUMPTIONS.md); the issues still need opening on GitHub | `docs/decisions/ASSUMPTIONS.md` |
| Owner comment `approved` | **Pending** | |

## Owner demonstration (exit criterion)

1. Fresh clone: `git clone` → `make env` → fill `deploy/.env` and `deploy/db.env` → `make migrate` → `make dev`. On this devbox the stack has run since 2026-11-13, and the owner signed in through the DevSpaces proxy on 2026-11-15.
2. The admin signs in, creates a user and a role, and creates a facet with terms on `/admin/taxonomy`.
3. New since then: `/admin/branding` (logo, title, legal page), `/legal`, and the logo on the sign-in page. Rebuild first: `docker compose -f deploy/compose.yaml up -d --build`.

## Proposed changes (CP issues, REQ-24)

| CP | Change | State |
| --- | --- | --- |
| CP-01 (#39) | asyncpg instead of psycopg; citext and triggers in the baseline | Applied |
| CP-02 (#41) | Tighten `/health` and `/version` response schemas to match the live API | Proposed; accepted as a known difference in the semantic diff |
| CP-04 | 85% coverage floor counts unit and database integration tests together | Owner accepted (combined coverage) |
| CP-05, CP-06 | Database login roles; trusted proxy default `10.89.0.2/32` | Applied |
| CP-07 | Public `GET /branding/logo` | Owner approved 2026-11-15; implemented; issue to open |
| BL-31, BL-40, BL-64 | CP proposals recorded in BACKLOG | Open |

## BACKLOG rows awaiting an owner decision

All rows are `open` and are listed in `BACKLOG.md`. Those raised during Phase 1, and the ones that affect G1:
- **Security follow-ups:**
  - BL-60: Trivy criticals accepted until 2026-12-02;
  - BL-65: rate limits held in process memory;
  - BL-67: session token storage;
  - BL-76, BL-77 and BL-81: review follow-ups;
  - BL-82: Vitest upgrade.
- **Behaviour choices:**
  - BL-50: the lockout window has no setting;
  - BL-62: the request id is missing from 500 responses;
  - BL-66: the breach check is not wired in;
  - BL-69: audit rows are written explicitly instead of through an event hook;
  - BL-70: settings have no cache;
  - BL-71: admin errors the contract does not list;
  - BL-80: brand colour contrast.
- **Deferrals to later modules:**
  - BL-54 and BL-55: image commit stamp and worker health checks;
  - BL-68: report and email branding;
  - BL-75;
  - BL-79: S3 store.

## Gaps before G1 can close

1. CI run on GitHub for the stack of PRs (owner opens the PRs; CI evidence is attached here).
2. Peer review on each PR by a session that did not author it (7.4).
3. Use testing is done (records in `docs/evidence/phase-1/use-testing/`); owner decisions on BL-83, whose majors include M1 acceptance 6, where the sign-in page is not branded.
4. Adversarial records for M0 to M2 (7.7): owner decision on how to run them.
5. The `Questions: M0`, `Questions: M1` and `Questions: M2` issues and the `Gate G1` issue on GitHub.
6. BL-60 is decided: zlib1g and tinypool are fixed; tar and esbuild are re-accepted until G2 (expiry 2027-03-01).
