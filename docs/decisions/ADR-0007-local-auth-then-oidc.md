# ADR-0007: Local accounts and server-side sessions first, OpenID Connect in Phase 5

**Status:** accepted at Gate G0 on 2026-11-02 · **Date:** 2026-11-02 · **Requirements:** REQ-14, REQ-16 (also REQ-20)
**Research:** R-01 rows 42 to 45 (#3); `docs/02-requirements.md` G13 and 2.4 answer 8; `docs/modules/M1-identity-access-admin.md`; `docs/contracts/registries.yaml`, `schema.sql`, `env.example`, `openapi/regwatch.v1.yaml`

## Context

- **Owner answer.** Local accounts at launch, with OpenID Connect in Phase 5 (2.4 answer 8, G13). Phase 5 holds M1b, "SSO optional" (6.1), and E8 is OpenID Connect single sign-on (section 9).
- **M1 spec (Phase 1):**
  - Login sets an `HttpOnly; Secure; SameSite=Lax` session cookie. Sessions are stored server-side.
  - Passwords use Argon2id, with a minimum of 12 characters and an optional breach check routed through a worker, because the API makes no outbound calls.
  - Accounts lock after 10 failures in 15 minutes and unlock after 30 minutes or by an admin.
  - Idle timeout is bounded by an admin maximum; the absolute session lifetime is 12 hours.
  - Out of scope: self-registration, SSO (M1b) and multi-factor authentication (E7).
- **What the contracts already prepare:**
  - `schema.sql`: `user.password_hash` is nullable ("NULL for SSO-only users"), `user.external_subject` is unique ("OIDC subject"), and `session.token_hash` holds the sha256 of the cookie.
  - `registries.yaml`: the `auth.*` and `sessions.*` settings, and the flag `auth.oidc` ("Enable OpenID Connect login (M1b)").
  - `env.example`: `REGWATCH_OIDC_ISSUER`, `REGWATCH_OIDC_CLIENT_ID` and `REGWATCH_OIDC_CLIENT_SECRET`.
  - OpenAPI: the cookie `rw_session`, an Origin check on mutating requests, `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/password` and `/me/sessions`. There are no OIDC paths.
- **Controls** (8.1, 8.2): login is limited to 5 attempts per minute per IP and per account; sessions rotate on login; a revocation list exists; every admin action is audited.
- **Licenses:** argon2-cffi MIT (`1fcae4f`), Authlib BSD-3 (`46b9487`), Keycloak Apache-2.0 (`24ed1da`, tooling and optional service), pycasbin Apache-2.0 (`f858158`), all at status V (R-01). No research item studied authentication beyond licenses.

## Decision

1. **Phase 1 (M1) ships local accounts only**, exactly as the M1 spec and the contracts define them: Argon2id hashes, server-side sessions in PostgreSQL, the `rw_session` cookie, the Origin check, and lockout and timeouts taken from the `auth.*` and `sessions.*` settings. There is no self-registration.
2. **Authorization is independent of how a user signs in.** Roles and permissions in PostgreSQL (`registries.yaml`) are the only source of rights. An identity provider, when added, authenticates users but does not assign roles. This keeps 3.2's promise that SSO arrives "without changing the permission model".
3. **Phase 5 (M1b) adds OpenID Connect** through Authlib, using the authorization-code flow, behind the `auth.oidc` flag and the `REGWATCH_OIDC_*` variables. Users are matched by `external_subject`, and SSO-only users have no `password_hash`. The login and callback endpoints are added to OpenAPI through a `CP-nn` at that time. Keycloak is used only as the test identity provider.
4. **Phase 1 builds nothing for OIDC** beyond the hooks the contracts already contain.

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **Local accounts in Phase 1; OIDC through Authlib in Phase 5 (chosen)** | MIT (argon2-cffi), BSD-3 (Authlib), all V | Matches the owner's answer; smallest Phase 1; the schema is already SSO-ready | The application holds password credentials until Phase 5; no MFA until E7 |
| Keycloak from day one as the only login | Apache-2.0 (V) | SSO, MFA and password policy from an existing product | A second service with its own database and admin console on one host (G1) for 50 users; the owner chose local first |
| Local accounts and OIDC both in Phase 1 | as chosen | SSO available early | Enlarges M1; no identity provider has been named; contradicts the phase answer |
| OIDC only, through the organisation's identity provider | n/a | No passwords stored in the application | No identity provider is established; no local fallback for setup or recovery |

## Consequences

- **Positive:** Phase 1 stays small. The permission model, audit and admin UI do not change when SSO arrives. Every contract hook for M1b already exists.
- **Negative:**
  - Until Phase 5 the application stores and checks passwords itself, so the M1 controls (Argon2id, lockout, rate limits, the optional breach check) carry the whole credential risk.
  - The M1 spec's 15-minute failure window has no settings key in `registries.yaml` (BL-50).
  - Account linking and the fate of local login once OIDC is on are not yet decided (open questions).
- **Follow-up backlog rows:** BL-05 (audit log forwarding), BL-50 (lockout window). E7 (MFA) and E8 (OIDC) remain enhancements in section 9.

## Open questions for the owner

1. When OIDC arrives, how are existing local users linked: automatically by verified email on first SSO login, or only by an admin?
2. With OIDC on, does password login stay for every user, only for administrators as a recovery path, or for no one?
3. Should group claims from the identity provider ever map to roles? This ADR says no: roles stay managed in the application.
4. Should multi-factor authentication (E7) come before Phase 5, with OIDC, or not at all?
5. Which identity provider does the organisation use? This is not established and is needed before M1b.


## Owner decisions at Gate G0 (2026-11-02)

The owner accepted the recommended default for every open question above:

- Q1: automatic linking by verified email, only from the configured identity provider, with an audit entry.
- Q2: password login stays for administrators only, as a recovery path.
- Q3: no; roles stay managed in the application.
- Q4: multi-factor authentication (TOTP) in Phase 5, before user evaluation, for local accounts.
- Q5: not known yet; the owner names the identity provider before M1b.
