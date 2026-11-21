# M10 Operations, observability, hardening and deployment: module status record

**Branch:** `feat/M10-operations` (on `feat/M7-reports`, after G4) · **Date:** 2026-11-21 · **Status:**
- **Acceptance:** all five criteria are met; criterion 2 is judged by the header set, until a public host can be scanned.
- **Security:** every slice (10.1 to 10.6), every fix and the chaos and load commits are signed off by the independent reviewer, with the fixes re-verified.
- **Tests:**
  - `make test-api`: 1,575 unit tests at 95.17% coverage, and 482 database tests with 1 skipped, at `f48c2cb`. Later changes were run on their own suites.
  - `make test-web` passes; `make lint` is clean.
  - e2e: 13 journeys on the production stack, including the CSP journey; 14 on QA.
  - promtool alert tests pass.

## Acceptance criteria (`docs/modules/M10-operations-hardening.md`)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A restore drill from last night's backup on a clean host brings the application up with identical item counts, documented step by step | **Met** | `docs/operations/restore-drill.md`: QA restored into a fresh project with fresh volumes, twice, the second time after the review's fixes. Identical counts for items, versions, sources, users, outputs, audit rows and stored files, in 18 s. The drill also found the queue probe bug (`4fc1014`). |
| 2 | Security headers score A on a header scanner; CSP blocks inline scripts except the theme bootstrap nonce | **Met, pending a public scan** | `deploy/Caddyfile.prod` sends HSTS, a CSP with no `'unsafe-inline'` (there is no inline script, so no nonce is needed), X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, COOP and CORP: the set a header scanner grades A. The CSP journey (`e2e/csp.spec.ts`) finds no violation on eight pages and the report preview. ZAP's baseline found 0 failures. A header scanner can be run once the site has a public name. |
| 3 | CI blocks a PR introducing a critical CVE in an image or dependency, or a prohibited license | **Met, local proof** | `images`: Trivy fails on CRITICAL, and on HIGH with a fix, in the release images, the monitoring images and the lockfiles, with accepted findings expiring. `licenses` fails on a prohibited license. `security` runs `make security`. The first GitHub run comes after the push. |
| 4 | Dashboards show capture success rate and output failures; an alert fires when a source is unhealthy for 24 hours | **Met** | The `monitoring` profile's "regwatch overview" dashboard, every panel checked against QA's data. `SourceUnhealthyFor24Hours` is proven by promtool tests (pending at 5 minutes, firing at 9), which also run in CI. |
| 5 | SBOM published with each release | **Met, local proof** | `release.yml` publishes CycloneDX SBOMs of both images and the source tree, with sums, for each `vX.Y.Z` tag on `main`. `make sbom` produced CycloneDX 1.7 files: API 729 components, proxy 183, source 218. |

## Test plan

| Item | Result |
| --- | --- |
| The production profile boots with read-only root filesystems | Every service healthy; every root filesystem read-only except `pdf`, whose Chromium writes; the api runs as `regwatch`. Found and fixed: the release image's missing `packaging` (`2679f64`). |
| Health and readiness under outage | Valkey stopped: `/ready` answers 503 `queue: unavailable`; pages and search keep working; requesting an output was a 500 and is now accepted and delivered later (`e98bf8b`); capture's run-now answers 503 "try again". |
| OWASP ZAP baseline | 64 passed, 0 failed, 4 warnings: the help text's example network, cacheable static files, the single-page-app note, no COEP. The full scan against staging is for G5. |
| Semgrep with OWASP rules | `make security`, now on every pull request. |
| Manual review of the Caddy configuration | By the independent reviewer: caching, compression, body size and framing fixed (`9c519df`). |
| Load (k6): 10 users browsing the map and searching for 15 minutes | 4,897 requests, 0 failed; map p95 23 ms (budget 150); search p95 30 ms (budget 300). On the QA-sized data: M5's 1-million-item test remains the volume measure. |
| Chaos: a worker killed mid-run | A PDF job interrupted mid-render was marked "interrupted, try again" after 5 minutes, and the retry produced the file. |
| Chaos: Valkey killed | As above, under health and readiness. |

## Built

| Slice | What | Commits |
| --- | --- | --- |
| 10.1 | `/ready` (CP-34), cached for 2 s; Prometheus metrics on an internal listener | `32040d1`, `c982457`, `6d46a16` |
| 10.2 | `make backup`, `make restore`, the drill; the queue probe authenticates (with TLS for `rediss`) | `4fc1014`, `9943bc9`, `e4e001a`, `1feda51` |
| 10.3 | The production stack: TLS, the strict CSP, read-only roots; the preview by URL (CP-35); the missing `packaging` | `2679f64`, `e62007f`, `9b8a8a3`, `9c519df` |
| 10.4 | CI gates on the release images and lockfiles, `security` job, SBOMs per release (CP-36); Caddy 2.11.9; base images pinned | `630fcdb`, `5045662` |
| 10.5 | The `monitoring` profile: alerts with tests, dashboard, its own network | `7833600`, `2da2b53` |
| 10.6 | Runbooks, release process, `SECURITY.md`; key rotation; `revoke-sessions` | `f48c2cb`, `dc85418`, `c0f6507` |
| Checks | Outputs accepted with the queue down; the k6 scenario | `e98bf8b`, `fb4bbcf` |

## Decisions (on recommendation; for the owner at G5)
- **The four M10 questions** take their defaults (`ASSUMPTIONS.md`).
- **The CI gate** fails on CRITICAL, and on HIGH with a fix. Unreleased upstream fixes are accepted for 30 days at a time.
- **Grafana** (AGPL) runs as an unmodified, optional, loopback-only service.
- **One API process per container.**
- **CP-34** (`/ready`), **CP-35** (the GET preview), **CP-36** (CI jobs and the release workflow).

## Open
- **Owner actions:**
  - a tag ruleset for `v*`;
  - GitHub private vulnerability reporting;
  - the security contact in `SECURITY.md`;
  - a header scan and the ZAP full scan once there is a staging or public host.
- **BL-146:**
  - the `pdf` service's writable root;
  - alert delivery (E19);
  - build-provenance attestations when images are published.
- **Carried from earlier phases:**
  - the vitest 4 upgrade (the pnpm audit moderates);
  - the valkey timing flake (BL-144);
  - BL-143 k (unreferenced files);
  - the BL-144 minors.
