# Gate G5 review: Phase 5 Hardening and operations (M10, M1b)

**Prepared by:** lead session · **Build under review:** `feat/M10-operations` (top of the stack, on `feat/M7-reports`) at the commit that adds this record · **Date:** 2026-11-23 · **Decision:** **waiting for the owner**.

**Exit criterion (`docs/06-process.md`, P5):**
- an application-level security review, an adversarial analysis and peer review, signed;
- the restore drill passed;
- a release candidate tagged.

## Exit criterion

| Part | Status | Evidence |
| --- | --- | --- |
| Application-level security review | **Signed off** | An independent reviewer, separate from the per-slice reviews, reviewed the whole application at `d3ce162` against `docs/08-security-compliance.md`, 8.1 and 8.2. <ul><li>**Medium 1:** the schedule check could stall the API. Fixed in `9d422a1`.</li><li>**Low 1:** `settings.manage` alone could weaken sign-in. Fixed in `2c22f00`.</li><li>Both fixes re-verified and signed off.</li><li>Four Info points stay in BL-150: the API's internet egress, the `pdf` sidecar's network and root, the metrics bind, the implicit TLS 1.2 minimum, and the missing log-redaction processor.</li></ul>The controls table is below. |
| Adversarial analysis | **Not yet: the owner's session** | G1, G3 and G4 deferred it to here. It is to run against QA (`docs/07-testing-quality.md` 7.7). Automated attacks are done: a ZAP full scan of the production stack found 141 passes, 0 failures and 2 known warnings (below). That scan was unauthenticated; the signed-in attack paths are the session's. |
| Peer review | **Not yet: on the pull requests** | Due on each PR once the stack is pushed. The branch is not on GitHub yet. |
| Restore drill | **Passed** (M10) | `docs/operations/restore-drill.md`: QA restored into a fresh project twice, with identical counts, in 18 s. |
| Release candidate tagged | **Not yet: the owner** | `release.yml` builds the images and SBOMs for a `vX.Y.Z` tag on `main`. It needs the stack merged to `main`, the tag ruleset for `v*` (M10), and the tag `v1.0.0-rc.1`. |

## Application-level review: the 8.2 controls

| Control | Status |
| --- | --- |
| Authentication on every non-public route | Verified: an app-wide gate, deny by default. Eight public routes, each intended. |
| Authorization by permission key | Verified: every route's permission matches the OpenAPI contract, with per-object checks in the services. No IDOR found. |
| Pydantic validation of requests and task payloads | Requests verified. Tasks take job ids and read the database again. |
| Output encoding | Verified: Jinja2 autoescape and React. The one raw HTML (the legal page) is Markdown with raw HTML off, sanitised by nh3. |
| Size limits | Verified. Uploads are capped tighter than the contract. |
| Login and password-change rate limits | Verified. |
| Search 60/min, outputs 20/h | Verified. Schedule checks are now limited too (Medium 1). |
| Audit rows for admin and output actions | Spot-checked across identity, groups, settings, flags, sources, jobs, taxonomy, printers, outputs and exports. |
| No sensitive data in logs | Confirmed in code; no redaction processor (BL-150 d). |
| Caddy security headers | Verified. The CSP journey passes on the production stack. |
| TLS 1.2 minimum | Caddy's default (BL-150 c). |
| Dependencies pinned | Image digests and lockfiles. |

## Checklist (docs/07-testing-quality.md 7.8)

| Item | Status | Evidence |
| --- | --- | --- |
| Module definitions of done complete and linked | **Yes** | `M10-module-summary.md`: acceptance 1 to 5 met. `M1b-module-summary.md`: the G0 decisions Q1 to Q4 built; Q5 waits for the owner. |
| CI green on the release branch; coverage report attached | **Pending the owner:** local only, until the stack is pushed | See the test run below. |
| Contract tests pass against the committed OpenAPI | **Yes** | P5 contract changes: <ul><li>CP-34 (`/ready`), CP-35 (the GET preview), CP-36 (CI jobs and releases);</li><li>CP-37 (SSO), CP-38 (TOTP), CP-39 (Tailwind 4, parked on its branch), CP-40 (`auth.mfa_required`).</li></ul>0 differences across 123 operations. |
| End-to-end suite green in three themes; accessibility report | **Yes** | On the production stack: 14 journeys, including axe in three themes, the CSP journey, keyboard, print, TOTP and the report builder. On QA: 16, including OIDC against Keycloak and the test printer. |
| Performance results within budgets | **Yes** (M10) | k6 for 15 minutes: map p95 23 ms, search p95 30 ms, 0 failed. |
| Security scans attached; no high or critical open | **Yes** | <ul><li>ZAP full scan of the production stack: `zap/G5-zap-full.html`.</li><li>`make security` (in CI).</li><li>Trivy gates: HIGH with a fix, and CRITICAL.</li><li>Every P5 slice was signed off by the independent reviewer.</li></ul> |
| Peer, security, use and adversarial records for every module | **Security: yes. Use: rounds 1 and 2. Peer and adversarial: not yet.** | See above. |
| License scan clean; register and notices updated | **Yes** | 708 allowed, 0 failing. New in P5: <ul><li>Authlib, joserfc, cryptography, pyotp and segno;</li><li>Keycloak (a QA-only service);</li><li>Prometheus and Grafana (an optional profile);</li><li>Tailwind 4 and daisyUI (on the parked branch).</li></ul> |
| CHANGELOG release section cut; BACKLOG decisions recorded; CP issues summarised | **At the gate** | BL-146 (M10), BL-147 (M1b), BL-148 (TOTP), BL-149 (UI, parked), BL-150 (the review's Info points); CP-34 to CP-40. |
| Questioning-period issues closed or assumptions recorded | **Recorded** | The M10 and M1b defaults, on the owner's standing instruction (`ASSUMPTIONS.md`). |
| Owner comment `approved` | **Waiting** | |

## ZAP full scan (production stack, unauthenticated)

141 rules passed, none failed, with two warnings:
- **COEP header missing.** Not needed: the app embeds nothing cross-origin. It was also a warning in the M10 baseline.
- **Private IP disclosure (`10.20.0.0`).** The example network in the printer help text.

The spider also fetched pages of the dev stack on port 80, which it found linked from the app's code. The dev API saw only its health checks in that window, with no audit rows and no account changes.

## Owner actions before approval

1. **Push the stack:** `git push origin feat/M10-operations` (and `feat/M6-tailwind4`, parked), then open the PRs so CI runs and peer review can start.
2. **The adversarial session** against QA. The lead session prepares the brief on request, and sets QA back from the proxy address to localhost first.
3. **The screen-reader run** (from G3 and G4): sign in, the map list and table, an item's tabs, Reports, New output, the Outputs history, the two-factor screens and the idle warning.
4. **Name the identity provider** (ADR-0007 Q5).
5. **Before the first release:**
   - the tag ruleset for `v*`;
   - private vulnerability reporting;
   - the security contact in `SECURITY.md`;
   - then merge to `main` and tag `v1.0.0-rc.1`.
6. **Confirm or override:**
   - the decisions in `M10-module-summary.md` and `M1b-module-summary.md`;
   - CP-34 to CP-38 and CP-40;
   - BL-150.

## Test run at the gate

`make test-api` at `2c22f00`, on a quiet machine:
- **Unit:** 1,636 passed. Coverage 95.20%, over the 85% floor; the security-critical floors are met, including the sign-in gate at 100%.
- **Database:** 512 of 513 passed, 1 skipped, 1 failed. `test_seed_twice_changes_nothing` still counted 42 settings, and `auth.mfa_required` makes 43. It is corrected and passes.

A run made while ZAP and the web tests loaded the machine failed four web-crawl connector unit tests on their time budget ("too-slow"). They pass alone, three times in a row. They are timing tests, like the Valkey one at G4, to make robust (BL-144).

Other checks:
- `make test-web`: 236 passed.
- `make lint`: clean.
- `make licenses`: 708 allowed, 0 failing.
- `make security`: every scanner passed, after a bandit false positive was resolved: the OAuth method name `client_secret_basic` is now a named constant.
- e2e: 14 on the production stack and 16 on QA.
