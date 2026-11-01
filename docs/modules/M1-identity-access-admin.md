# M1 Identity, access control and administration

**Phase:** P1 · **Size:** L · **Parallelism:** API and admin UI can be two sessions after the schema PR merges.
**Requirements:** REQ-14 (password change, logout), REQ-16, REQ-07 (settings icon target)

## Purpose
Local accounts, sessions, roles and permissions, the administrator settings area, user management, runtime settings, feature flags and the audit log.

## Scope
In: login, logout, password change, password reset by admin, account lockout, session management, roles and permissions, admin settings UI (users, roles, settings, feature flags, audit viewer), audit logging middleware.
Out: self-service registration (not wanted), SSO (Phase 5, M1b), multi-factor authentication (enhancement E7).

## Interfaces
- `POST /auth/login` (email, password) sets an `HttpOnly; Secure; SameSite=Lax` session cookie; `POST /auth/logout`; `GET /auth/me`.
- `POST /auth/password` (current, new) enforces policy; `POST /admin/users/{id}/reset-password` returns a one-time link token.
- `GET|POST|PATCH /admin/users`, `GET|POST|PATCH /admin/roles`, `GET /admin/permissions`.
- `GET|PUT /admin/settings/{key}`, `GET|PATCH /admin/feature-flags/{key}`.
- `GET /admin/audit?actor=&entity=&from=&to=` paginated.
- Permission dependency: `require("settings.manage")` used by every admin router; the frontend hides what the user cannot do and the API still enforces.

## Data
`user`, `session`, `role`, `permission`, `role_permission`, `user_role`, `setting`, `feature_flag`, `audit_log` (section 4).

## Open-source components
argon2-cffi (MIT), itsdangerous (BSD) for reset tokens, slowapi (MIT) for login rate limiting, Authlib (BSD-3) reserved for M1b, Keycloak (Apache-2.0) as test identity provider in M1b.

## Design notes
- Password policy: minimum 12 characters, checked against the Have I Been Pwned range API only if the admin enables it (outbound call from the API is otherwise forbidden; route through a worker task).
- Lockout after 10 failures in 15 minutes; unlock by admin or after 30 minutes.
- Sessions stored server-side; idle timeout from user preference bounded by an admin maximum; absolute lifetime 12 hours default.
- Every mutating admin request writes an `audit_log` row through a SQLAlchemy event hook; the table has no UPDATE or DELETE grants for the application role.
- Permission keys are the single vocabulary used by the UI, API and reports; new modules register their keys in `permissions.py` and a seed step.

## Acceptance criteria
1. A viewer cannot reach any `/admin/*` route (403) even with a crafted request, and cannot see the settings icon.
2. An admin creates a user with roles, the user logs in, must change the temporary password, then sees only permitted toolbar commands.
3. Ten wrong passwords lock the account and produce an audit row; the response does not reveal whether the email exists.
4. Logout invalidates the server session; replaying the old cookie returns 401.
5. Audit viewer shows before and after values for a role change.

## Test plan
- Unit: password policy, permission resolution, lockout timer, settings cache invalidation.
- Integration: full login and logout flow, role changes applied on next request, audit rows written.
- E2E (Playwright): admin creates user, user logs in and changes password, viewer denied settings.
- Security: OWASP ZAP authenticated scan; session fixation, CSRF (SameSite plus origin check on mutating requests), enumeration, brute force; Semgrep rules for auth.
- Accessibility: login and admin forms pass axe; focus order and error announcement verified.

## Question bank
1. Is self-service registration ever wanted? Default: no.
2. Password policy and rotation rules from corporate policy? Default: 12 characters, no forced rotation, breach check optional.
3. Required session timeout range? Default: 15 minutes to 8 hours idle; 12 hours absolute.
4. Which roles exist on day one and who approves new permissions? Default: admin, editor, analyst, viewer; owner approves.
5. Is an audit export to a SIEM needed? Default: CSV export only; syslog forwarding to backlog.

## Enhancements to propose
E7 multi-factor authentication (TOTP, `pyotp` MIT); E8 OpenID Connect federation (M1b); per-user API tokens for downstream integrations.
