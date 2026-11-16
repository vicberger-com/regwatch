# 8. Security and compliance design

The application ingests untrusted content from the internet and sends data out by email and print, so the design treats captured content as hostile, confines all outbound traffic to workers, and makes every privileged action auditable.

## 8.1 Threat model summary

| Asset | Threat | Primary control | Module |
| --- | --- | --- | --- |
| Internal network and metadata endpoints | SSRF through source URLs, redirects, DNS rebinding | SafeFetcher: resolve then connect to the resolved address, reject private, loopback, link-local and multicast ranges, re-check on every redirect, no IPv6 to IPv4 mapped bypass, allow-list of schemes http and https | M3 |
| Users' browsers | Stored XSS from captured HTML, feeds, diffs, report text | Sanitize with nh3 at ingestion, escape at render, CSP without unsafe-inline, diff viewer renders text not HTML | M4, M6, M7 |
| Credentials and sessions | Brute force, fixation, theft | Argon2id, lockout, rotation on login, HttpOnly Secure SameSite cookies, origin check, revocation list | M1, M9 |
| Admin functions | Privilege escalation, IDOR | Permission dependency on every route, ownership checks on every id, deny by default, tests per route | M1, all |
| Outbound email and print | Exfiltration, header injection, spam | Recipient domain allow-list, header validation, rate limit per user, audit, attachment caps | M8 |
| PDF renderer | Malicious HTML reaching Chromium, file read | Gotenberg on internal network with no outbound access, HTML assembled server-side from validated layouts, no user-supplied URLs in templates | M7, M8 |
| Workers | Resource exhaustion from huge or slow sources | Body and time caps, per-host rate limits, job concurrency, retries bounded | M3 |
| Model classifier | Prompt injection, data leakage | Output constrained to term list, no tool use, provider disabled by default, redaction of emails and tokens before sending text, logging | M4 |
| Database | Injection, data loss | Parameterised queries only, least-privilege roles (app role cannot alter audit log), backups and restore drill | M5, M10 |
| Supply chain | Malicious or vulnerable dependencies, license contamination | Lockfiles, pip-audit, npm audit, Trivy, Renovate with review, license allow-list in CI, SBOM | M0, M10 |
| Secrets | Leakage in repo or logs | gitleaks, environment or Docker secrets, structured logging with redaction | M0, M10 |

## 8.2 Controls checklist per module (enforced by the security review)

Authentication on every non-public route; authorization by permission key; input validation with Pydantic on every request and task payload; output encoding in Jinja2 autoescape and React; size limits (request 2 MB, upload 25 MB, captured body 10 MB, export 50 000 rows); rate limits (login: failed attempts only, 5 per minute per account and 30 per minute per address; password changes 5 per minute per user; ADR-0007 amendment 1, search 60 per minute per user, outputs 20 per hour per user); audit rows for every admin and output action; no sensitive data in logs (emails hashed, tokens never logged); security headers from Caddy (HSTS, CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame-ancestors none); TLS 1.2 minimum; dependencies pinned.

## 8.3 Scraping legality and etiquette (G12)

- Respect robots.txt by default; store the decision with each run. Overrides require admin permission `sources.override_robots`, a written reason, and appear in the daily digest.
- Identify the crawler with a User-Agent containing product name, version and a contact address.
- Default politeness: 1 request per 2 seconds per host, bursts capped; crawl depth 3, 200 pages per run.
- Only public pages; no login forms, no paywall circumvention, no CAPTCHA solving.
- Store each source's terms-of-use link; the admin UI shows a reminder to review terms before enabling a crawl connector.
- Captured content is stored for internal monitoring; redistribution outside the organisation (for example in emails to external domains) is blocked by the recipient allow-list.

## 8.4 Privacy and data handling

- Personal data held: user accounts (name, email), audit logs (user ids, IPs), captured documents may incidentally contain names of officials. Retention per G15, deletion of a user anonymises audit rows rather than deleting them.
- No analytics or telemetry leaves the deployment.
- Model providers: if a hosted provider is enabled, the admin must record the data-processing basis in settings before the flag can be turned on; the text sent is limited to title and first 4 000 characters and redacted of email addresses and tokens.

## 8.5 Secrets and configuration

Secrets (database password, SMTP credentials, session signing key, search API key, model API key) are read from environment variables populated by Docker secrets or the host's secret store; `env.example` lists every variable with a comment and no values. Session keys rotate via a dual-key window. A secret appearing in logs or git is treated as compromised and rotated.

## 8.6 License compliance program (REQ-20)

1. Allow-list and prohibited list as in section 3.5, encoded in `scripts/license-scan.sh` and run in CI on every PR; unknown licenses fail the build until classified.
2. Every vendored file or snippet carries its original header and a `THIRD_PARTY_NOTICES.md` entry with source URL, commit, license text and copyright line.
3. Pattern reuse (reading a project's approach and rewriting) is documented in the component evaluation as `pattern` with a link, to keep provenance honest even when no license obligation arises.
4. Services run unmodified (SearXNG, Gotenberg, Valkey) are pulled by digest; modifying any AGPL service requires an ADR and publishing the modified source.
5. Data and fonts: Natural Earth (public domain), Inter (SIL OFL 1.1; allowed for fonts only, license file shipped beside the fonts, BL-57), ISO country names (MIT package); CC-BY data requires an attribution line in the application's About dialog.
6. The release pipeline produces a CycloneDX SBOM and a license report attached to each release.

## 8.7 Security review and disclosure

`SECURITY.md` names the contact and response targets (acknowledge in 3 business days). Dependabot or Renovate alerts are triaged weekly by the lead session; critical CVEs patch within 7 days.
