# Security review record: M1 Identity, access control and administration

**Scope (PRs, routes, tasks):** branches `feat/M1-auth-core` through `feat/M1-branding-legal` (#31, #32), the 12 commits in `main..feat/M1-branding-legal`. Code: `api/src/regwatch/core/{security,services,models,db}.py`, `api/{openapi,app,main}.py`, `identity/{permissions,services,router,schemas,admin_cli,models}.py`, `admin/{router,services,schemas,models}.py`. Routes: `POST /auth/login`, `/auth/logout`, `GET /auth/me`, `POST /auth/password`, `GET|DELETE /me/sessions[/{id}]`, `/admin/users*`, `/admin/roles*`, `GET /admin/permissions`, `/admin/settings*`, `/admin/feature-flags*`, `GET /branding`, `PUT /admin/branding`, `PUT /admin/legal`, `GET /admin/audit`, and the app-wide gate on all 91 operations. CLI: `regwatch-admin create-user`. Production configuration read: `api/Dockerfile`, `deploy/compose.yaml`, `deploy/Caddyfile`, `docs/contracts/env.example`. · **Reviewer session label:** M1 independent review · **Date:** 2026-11-13 · **Author sessions excluded from review:** yes

## Data flows touched
- **Browser to API (untrusted to trusted).** JSON bodies on login, password change and admin writes; the `rw_session` cookie (256-bit `token_urlsafe(32)`, only its sha256 stored in `session.token_hash`); the `Origin` header (CSRF); `User-Agent` (stored, cut to 512 characters); the client IP from `request.client.host` after uvicorn's `ProxyHeadersMiddleware` applies `X-Forwarded-For` from `REGWATCH_TRUSTED_PROXIES`.
- **Reverse proxy (Caddy) to API.** Caddy adds `X-Forwarded-For`; it is trusted only if Caddy's container address is in `REGWATCH_TRUSTED_PROXIES`. Caddy sets no request-body limit.
- **API to PostgreSQL.** `user`, `session`, `role`, `role_permission`, `user_role`, `setting`, `feature_flag`, `audit_log`; all queries parameterised through SQLAlchemy. The application connects as the owner `regwatch`; the `regwatch_app` role is NOLOGIN and unused.
- **API to response.** `Me` (email, roles, permissions); one-time temporary passwords in `POST /admin/users` and `/reset-password`; audit rows with before and after values, IP and actor email to `audit.read`; branding and legal strings to every authenticated user, later in report and email footers (M7, M8).
- **API to logs.** structlog JSON on stdout: method, path, status, duration; unhandled exceptions log the full traceback, including SQLAlchemy statement parameters.
- **Operator CLI to PostgreSQL.** `regwatch-admin create-user`; password from a no-echo terminal or stdin, never an argument.
- **Not crossed by M1:** workers, external sources, email, printers, model provider (the breach check is deferred, BL-66).

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | Login, sessions, cookie | Argon2id (argon2-cffi 25.1 defaults t=3, m=64 MiB, p=4); dummy-hash verify for unknown or disabled accounts; 256-bit token, sha256 stored; cookie `Secure; HttpOnly; SameSite=Lax; Path=/`; old cookie revoked on login; all sessions revoked and the current one rotated on password change; logout revokes server-side; idle timeout bounded by an admin maximum; absolute `expires_at`; disabled or locked status rejected on every request; cookies over 128 characters answer 401. Verified. | Lockout can be outrun with concurrent bursts; lockout state reveals which emails exist; with a wrong proxy trust setting the per-IP limit is global | 1, 4, 5 |
| Tampering | CSRF; admin writes; LIKE search | Every POST/PUT/PATCH/DELETE, login included, needs `Origin` equal to `REGWATCH_BASE_URL`; missing, empty, `null`, wrong scheme, wrong port and suffix-host origins rejected; default port and case normalised (a userinfo origin is accepted, but browsers never send one). LIKE metacharacters escaped; role keys pattern-checked; unknown roles and permissions refused. | The settings API bypasses the branding and legal schema limits | 8 |
| Repudiation | `audit_log` | Same-transaction audit rows for login, failure, lock, unlock, logout, session revoke, password change and failure, user create, update and reset, role create, update and delete, setting, flag, branding and legal changes, with before and after values; unknown emails stored only as sha256 | Audit rows are mutable at runtime (owner login, BL-61); IP attribution depends on the proxy trust setting; `user.create` from the API carries no IP | 6, 5, 12 |
| Information disclosure | Errors, logs, responses | Generic 500 bodies; validation errors echo field names and messages, not values; audit viewer behind `audit.read`; OpenAPI not served in production, `/docs` only in development | Database errors log emails and Argon2 hashes in clear; temporary-password responses lack `Cache-Control: no-store`; unsalted sha256 email digests let an `audit.read` holder confirm a guessed email (meets the 8.2 wording; info) | 7, 11 |
| Denial of service | Login, request bodies, limiter | 5 per minute per IP and per account, checked and counted synchronously; passwords over 1,024 characters refused before hashing; page size capped at 200; integer auth settings bounded | No request-size limit, and bodies are parsed before the gate; with a wrong proxy trust setting one client exhausts the global per-IP limit; Argon2 64 MiB per verify across up to 40 threads (info); targeted 30-minute lockout with 10 guesses is the accepted trade-off in the spec (info) | 3, 5 |
| Elevation of privilege | Gate, `/admin/users`, `/admin/roles` | Global, deny-by-default gate; the live OpenAPI has exactly 3 public operations (`GET /health`, `GET /version`, `POST /auth/login`), matching the contract; every `/admin/*` operation carries `x-permission`; temporary-password restriction; permissions re-read per request; system admin role frozen; last-manager guard; no self-disable | Holders of `users.manage` or `roles.manage` can grant themselves every permission; the last-manager guard can be raced | 2, 9 |

## Checklist
- [x] Input validation on every field (types, sizes, enumerations): reviewed; **not met** (findings 7, 8, 10)
- [ ] Output encoding in UI, templates, emails, CSV: outside the M1 API scope; branding strings rendered by later layers not reviewed
- [x] Authentication and authorization on every route and task: verified (91 operations, 3 public, every `/admin/*` with a permission), except finding 2
- [x] Session handling (cookie flags, rotation, revocation): verified by tests and reading
- [x] Secrets not logged or committed: passwords and tokens never logged; **not met** for hashes and emails in error logs (finding 7)
- [ ] Outbound requests only through SafeFetcher or registered services: not applicable (no outbound calls in M1; BL-66)
- [ ] File and body size limits; content-type checks: **not met** (finding 3); logo upload is a 501 stub (BL-68)
- [ ] Logging excludes sensitive data; audit rows written: audit rows verified; logging fails on database errors (finding 7)
- [ ] Dependency, image and license scans attached and clean: not run in this review

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | medium | **Concurrent bursts outrun the lockout.** `failed_logins += 1` is an ORM read-modify-write with no row lock (`identity/services.py`, `login`), `_failures_in_window` takes `min(audit_count, failed_logins)`, and `check_login_rate` admits 5 requests per minute at once. Five parallel wrong passwords per minute raise the counter by 1 instead of 5: after 30 attempts the counter was 6 and the account unlocked (M1 acceptance 3). With N workers the gain grows about N times (BL-65). | `sec/M1-lockout` | yes: `test_concurrent_bursts_still_lock` (fails without the row lock) |
| 2 | medium | **Delegated administrators can escalate to full admin.** `update_user` lets any `users.manage` holder assign any role, `admin` included, to anyone including themselves; `reset_password` lets them reset an administrator's password and receive it; `update_role` lets a `roles.manage` holder add any permission to any non-admin role, their own included. Nothing checks that the actor already holds what they grant. Default roles do not expose this (only `admin` holds these keys), but the role editor exists to create such roles. | `sec/M1-escalation` | yes: `test_delegated_admins_cannot_escalate` (fails without the guard) |
| 3 | medium | **No request-body size limit; bodies are parsed before the gate.** FastAPI reads and decodes the body before the `authorize` dependency runs; no limit exists in the application, uvicorn or Caddy (8.2 requires 2 MB). An anonymous client with no cookie and no Origin gets 422 for malformed JSON on `POST /admin/roles`, and a 20 MiB body is read in full before the 403. | `sec/M1-input-limits` | yes: `test_declared_oversize_body_is_413_before_the_gate`, `test_streamed_oversize_body_is_413` |
| 4 | medium | **Lockout responses reveal which emails exist, by timing and by lock length.** A real locked account answers 423 at once without hashing; an unknown account runs the dummy Argon2 verify first (measured about 4 ms against about 70 ms). The unknown-account lock is a 15-minute in-memory window, the real lock `auth.lockout_minutes` (30): after 16 minutes the real account still answers 423 and the unknown one 401. A restart or another worker resets only the unknown counter. Breaks M1 acceptance 3. | `sec/M1-lockout` | yes: `test_locked_answers_cost_the_same_and_last_as_long` |
| 5 | medium | **With the contract default `REGWATCH_TRUSTED_PROXIES=10.0.0.0/8`, every client has the proxy's IP behind the shipped Caddy,** because Docker gives the Compose networks `172.16.0.0/12` addresses. The per-IP login limit becomes site-wide (5 bad logins a minute block every user with 429) and audit and session rows record the proxy address. | `sec/M1-trusted-proxy` (BL-73) | yes: `test_dev_env_trusts_exactly_the_proxy`, `test_uvicorn_takes_the_client_address_only_from_the_proxy`; author fix, not yet re-verified; the full Compose stack was not run |
| 6 | medium | **The audit log is mutable at runtime.** Migration 0001 grants `regwatch_app` only SELECT and INSERT on `audit_log`, but the application logs in as the owner `regwatch`, so UPDATE and DELETE work. Contradicts the M1 design note and 8.1. Tracked as BL-61 (open). | `sec/M1-db-roles` (BL-61, CP-05) | yes: `test_api_login_inserts_but_cannot_change_audit_rows`, `test_start_up_refuses_an_owner_login_in_production`; author fix, not yet re-verified |
| 7 | low | **Emails and password hashes are logged in clear on database errors.** The engine lacks `hide_parameters=True` and the unhandled-error handler logs the traceback with bound parameters. Without authentication, `POST /auth/login` with a NUL byte in the email answers 500 and logs the email; an admin create with a NUL in the display name logs the email and the `$argon2id$` hash of the temporary password. Any IntegrityError race logs the same way. Breaks 8.2 ("emails hashed"). | `sec/M1-input-limits` | yes: `test_nul_in_login_email_is_422_and_not_logged`, `test_input_limits_and_no_store` |
| 8 | low | **The generic settings API bypasses branding and legal validation.** `PUT /admin/settings/{key}` accepts any string up to 200,000 characters for `branding.primary_color`, `general.site_title`, `legal.required_markings` and `branding.logo_ref`, which `BrandingWrite` and `LegalWrite` limit (hex colour pattern, 80 and 2,000 characters). A `settings.manage` holder can store `red;}</style><script>…` as the primary colour, served to every user and planned for CSS (`web/src/styles/tokens.css`); `logo_ref` accepts `../../../etc/passwd` ahead of BL-68. | `sec/M1-input-limits` | yes: `test_input_limits_and_no_store` |
| 9 | low | **The last-manager guard can be raced.** `_ensure_a_manager_remains` counts in the same READ COMMITTED transaction with no lock; two administrators removing each other at the same moment can both pass, leaving nobody with `users.manage` (recovery then needs the CLI). From code reading; the concurrent proof of concept did not hit the window. | `sec/M1-escalation` | yes: transaction advisory lock; `test_admins_removing_each_other_leave_one_manager` |
| 10 | low | **Missing size and format checks on identity inputs.** `Email` is a plain string; `POST /admin/users` accepted `""`, `"not an email"` and a 100,000-character email. `UserCreate.display_name` has no minimum (PATCH requires 1 to 120). `UserCreate.roles`, `RoleWrite.permissions` (a 200,000-entry list was accepted), `RoleWrite.label`, `Login.password` and `PasswordChange.current_password` are unbounded; no NUL rejection anywhere. | `sec/M1-input-limits` | yes: `test_input_limits_and_no_store`, `test_invalid_emails`, `test_admin_cli_rejects_invalid_email` |
| 11 | low | **Temporary-password responses can be cached.** `POST /admin/users` and `POST /admin/users/{id}/reset-password` return a working credential without `Cache-Control: no-store`. | `sec/M1-input-limits` | yes: `test_input_limits_and_no_store` |
| 12 | info | (a) `admin_create_user` audits `user.create` without the actor IP. (b) `auth.breach_check_enabled` can be set but nothing reads it (BL-66). (c) Argon2 at 64 MiB across up to 40 threads means about 2.5 GiB peak from many-IP login floods. (d) An automatic lock leaves sessions unrevoked: rejected while locked, usable again after the lock expires. Acceptable but undocumented. | (a) and (d) `sec/M1-escalation`, `sec/M1-lockout`; (b) BL-66; (c) accepted | partly |

**Sign-off:** not given. No high or critical findings open; 6 medium findings open (1 to 6); findings 1 to 4 should be fixed before Gate G1. · M1 independent review · 2026-11-13

## Evidence
- Baseline: unit tests 375 passed; database integration tests 24 passed.
- Proofs of concept ran from `/tmp` against the repository's integration fixtures and a throwaway PostgreSQL; the repository was not modified.
- 1: proof of concept, six rounds of 5 concurrent wrong passwords with the limiter cleared between rounds: all 401, `failed_logins` 1 to 6, never locked.
- 2: proof of concept. A role with only `users.manage`: `/admin/settings` 403, self-PATCH to admin 200, `/admin/settings` 200, reset of the original admin's password 200 with the password returned. A role with only `roles.manage`: added `users.manage`, `settings.manage`, `audit.read` to itself, then `/admin/users` 200.
- 3: proof of concept, malformed JSON without cookie or Origin answered 422; 20 MiB body read, then 403. No limit in application, uvicorn or Caddy (code reading).
- 4: proof of concept, 423 latency 3.7 to 5.3 ms (real) against 66.7 to 75.2 ms (unknown); after shifting the window by 16 minutes the real account answered 423 and the unknown one 401.
- 5: proof of concept with `ProxyHeadersMiddleware` trusting `10.0.0.0/8`: peer `172.18.0.4` with `X-Forwarded-For: 203.0.113.7` gave client `172.18.0.4`; peer `10.0.0.4` gave `203.0.113.7`. Compose subnet behaviour from code reading and Docker defaults; the full stack was not run.
- 6, 9 and 12: code reading only.
- 7: proof of concept, both 500s captured with the parameters shown in the log line.
- 8, 10, 11: proofs of concept as described in each finding.
- Passed checks: the live OpenAPI from `create_app()` lists 91 operations, 3 public, every `/admin/*` with `x-permission`; `origin_allowed` checked on 11 inputs; cookie flags, rotation, logout replay, temporary-password gate and viewer 403 covered by the passing integration tests; LIKE escaping, per-request permissions and token storage by code reading.

## Author response (M1 session, 2026-11-13)
- Finding 5: `make env` (`scripts/dev-env.sh`) writes `REGWATCH_TRUSTED_PROXIES=172.16.0.0/12,192.168.0.0/16,10.0.0.0/8`, so the development stack does see client addresses. The finding holds for any deployment that keeps the contract default `10.0.0.0/8`; the fix belongs in the `env.example` comment and the production overrides (M10), plus a start-up warning when the proxy peer is outside the trusted ranges.
- Findings 1 to 11 are accepted for fixing in `sec/M1-*` branches before Gate G1; each fix PR fills its row here.

## Re-verification (M1 independent review, 2026-11-13)
Against `sec/M1-lockout`, `sec/M1-escalation` and `sec/M1-input-limits`: unit 391 passed, database 32 passed; original proofs of concept re-run, bypasses attempted.

| # | Verdict | Evidence |
| --- | --- | --- |
| 1 | fixed | bursts of 5 concurrent wrong passwords now lock on the 10th failure; unknown emails too |
| 2 | fixed | self-grant, admin creation, admin reset, admin disable, widening one's own role and creating a `settings.manage` role all 403 |
| 3 | fixed | 3 MiB with Content-Length, chunked, `Content-Length: -1` and a GET with a body all 413 before parsing (ASGI level) |
| 4 | fixed at default settings | 423 latency 57 to 64 ms real against 59 to 69 ms unknown; both 423 after 16 minutes and 401 after 31 |
| 5 | deferred | BL-73 open, not yet accepted by the owner |
| 6 | deferred | BL-61 open |
| 7 | fixed | NUL in login email, list `q`, audit filters, settings, role label and user email all 422; logs hold no parameters, emails or hashes; unique race 409 |
| 8 | partly fixed | branding and legal keys refused through the settings API; other string keys still took any text (N3) |
| 9 | fixed (code reading) | advisory lock before any read; the race was not reproduced on either version |
| 10 | fixed | email, name, role, permission, label and password limits enforced; control characters were still accepted in emails |
| 11 | fixed | both responses carry `no-store` |
| 12 | partly fixed | (a) and (d) fixed; (b) BL-66; (c) not addressed |

New issues from the re-verification:
- **N1 (low):** with `auth.lockout_minutes` under 15 the unknown-account failure count outlived its lock, so after the lock the two kinds of account answered differently.
- **N2 (low):** `update_role` checked only added permissions and `delete_role` none, so a role manager could remove permissions they do not hold from other roles.
- **N3 (low):** string settings other than branding and legal took control characters, for example `general.contact_email` with `\r\nBcc:` and `capture.user_agent` with a header line.
- **(low, not raised before):** wrong current passwords on `POST /auth/password` did not count toward the lockout.
- **(info):** since 12d, ten wrong passwords against an email also end that user's sessions; this is the accepted lockout trade-off and is recorded in ASSUMPTIONS.md.

**Sign-off:** no high or critical open; medium open: 5 (BL-73) and 6 (BL-61), both deferred and not yet accepted by the owner; low open at re-verification: N1, N2, N3 and password-change guessing · M1 independent review · 2026-11-13

## Author follow-up (M1 session, 2026-11-13), branch `sec/M1-review-followups`
Fixed after the re-verification and covered by tests, not yet re-verified by the reviewer:
- N1: the unknown-account failure count restarts when its lock begins, as `failed_logins` does for real accounts (`test_short_lockout_does_not_reveal_accounts`).
- N2: changing a role needs every added or removed permission held, and deleting one needs all its permissions held (`test_review_followups_for_roles_and_settings`; `test_delegated_admins_cannot_escalate` now expects 403 for removal).
- N3: string settings refuse control characters (newlines allowed only in `legal.page_markdown`, `legal.required_markings` and `branding.company_address`), list entries included; `general.contact_email` must be an email address or empty; emails refuse control characters (`test_review_followups_for_roles_and_settings`).
- Password-change guessing: a wrong current password is a counted failure (`auth.login_failed` with reason `password_change`), locks at the threshold and ends the sessions (`test_wrong_current_password_counts_toward_lockout`).
