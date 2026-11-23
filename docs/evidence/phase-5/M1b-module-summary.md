# M1b Sign-in with the organisation's account, and two-factor sign-in: module status record

**Branch:** `feat/M10-operations` (after M10) · **Date:** 2026-11-21 · **Status:**
- **Scope:** the ADR-0007 decisions taken at G0 (Q1 to Q5), and enhancement E7 (TOTP) brought into Phase 5 by Q4.
- **Acceptance:** every decision is built. Q5, naming the identity provider, waits for the owner; the build works with any standard OpenID Connect provider.
- **Security:** every slice was signed off by the independent reviewer, with the fixes re-verified. The findings were three Lows and two Infos on OIDC, Infos on the Keycloak profile, two Lows on TOTP, and two Mediums on the policy. The G5 application-level review added one Low (sign-in settings).
- **Tests:** see the test plan below.

## Decisions as criteria (ADR-0007, owner decisions at G0)

| # | Decision | Status | Evidence |
| --- | --- | --- | --- |
| Q1 | Link automatically by a verified email, only from the configured identity provider, with an audit entry | **Met** | `identity/services.py` `sso_sign_in`: <ul><li>accounts are matched by a digest of issuer and subject;</li><li>an account is linked on a first sign-in only by an email the provider marks verified, audited `auth.sso_linked`;</li><li>no account is ever created; refusals are audited `auth.sso_refused`;</li><li>an account already linked elsewhere is never taken over;</li><li>an administrator's account is never linked by email (review).</li></ul>Tests: `tests/integration/test_oidc.py` (11), `tests/unit/test_oidc.py` (37), and `web/e2e/oidc.spec.ts` against Keycloak. |
| Q2 | Password sign-in stays for administrators only, as a recovery path | **Met** | With SSO on, other users get `403 sso-required`, after a correct password only. Test: `test_with_sso_on_passwords_are_for_administrators_only`. |
| Q3 | No role mapping from the provider; roles stay in the application | **Met** | Only the subject, email, `email_verified` and name are read from the ID token. Group claims mapping is a follow-up (BL-147). |
| Q4 | Multi-factor authentication (TOTP) in Phase 5, before user evaluation, for local accounts | **Met** | <ul><li>BL-148, CP-38, migration 0012: enrolment with the password again, 10 recovery codes, the second step after a correct password, wrong codes counted toward the lockout, no code accepted twice, and an administrator's reset.</li><li>The policy `auth.mfa_required` (none, admins, everyone; CP-40, migration 0013).</li><li>`regwatch-admin reset-mfa` and `rotate-mfa-secrets`.</li></ul>Tests: `tests/integration/test_mfa.py` (16), `tests/unit/test_mfa.py` (14), and `web/e2e/mfa.spec.ts`, on QA and on the production stack. |
| Q5 | The owner names the identity provider | **Waiting for the owner** | The build is generic OpenID Connect: discovery, the authorization code flow with PKCE, and a client secret. Keycloak is the reference provider for tests (the `oidc-test` profile). Recorded in `ASSUMPTIONS.md`. |

## Test plan

| Item | Result |
| --- | --- |
| A mock provider, unit and integration | Tokens are signed by the mock's own keys and served through an httpx MockTransport, with no network. These are refused: <ul><li>a state mismatch, a replayed code, a wrong PKCE verifier;</li><li>algorithm confusion (HS256), `alg=none`, a foreign key;</li><li>a wrong issuer, audience or `azp`; an expired token; a missing `iat`; a wrong nonce;</li><li>a subject that is too long or not a string.</li></ul>A key rotated at the provider is fetched once more. |
| A real provider | Keycloak 26.8.2 in the `oidc-test` profile on QA. A verified user signs in; an unverified one is turned back with the reason. Recreating the container keeps the links, because the users have fixed ids. |
| TOTP end to end | On QA and on the production stack: a new account enrols from the User tab, keeps its recovery codes, and the next sign-in asks for a code, computed as an authenticator app would (RFC 6238). |
| The policy | <ul><li>A covered administrator is held to set-up only, then let through.</li><li>A new account under `everyone` changes its temporary password, then enrols.</li><li>A linked account on a password session is covered; an SSO session is exempt.</li></ul> |
| Key rotation | `rotate-mfa-secrets` re-encrypts every secret, which then opens with the new key alone. The state cookie and the pending cookie also accept the previous key. |
| The production stack | 14 e2e journeys, including the CSP journey under the strict policy, axe in three themes, and the TOTP journey. |

## Built

| Slice | What | Commits |
| --- | --- | --- |
| M1b.1 | The OIDC client: PKCE, the signed state cookie, discovery and keys, ID-token checks, capped and timed calls to the provider | `b905e15` |
| M1b.2 | `GET /auth/sso`, `/auth/oidc/login`, `/auth/oidc/callback` (CP-37); linking; passwords for administrators only | `8fe5cdc` |
| M1b.3 | The login page's "Sign in with your organisation's account" | `9d77d7c` |
| M1b.4 | The `oidc-test` profile (Keycloak, loopback only, its own network) and its journey | `23e9cec`, `72a1946`, `7d4c752` |
| BL-148 | TOTP at rest (0012), the flows (CP-38), the screens, the journey | `c7267bd`, `debfba7`, `f33e23d`, `a1b8c27` |
| BL-148 (f) | `auth.mfa_required` and `session.method` (CP-40, 0013), the forced set-up page | `8e3cf4a`, `d3ce162` |
| Licences | Reviewed entries for Authlib, joserfc and segno (the scan had not been run when they were added) | `eb463da` |
| G5 review | `settings.manage` counts as privileged; sign-in settings and `auth.oidc` also need `users.manage` and `roles.manage` (Low 1) | `2c22f00` |

## Decisions (on recommendation; for the owner at G5)
- **TOTP is optional per user** until `auth.mfa_required` says otherwise. It defaults to none, so an upgrade locks no one out.
- **A password reset does not remove an authenticator.** An administrator's reset, or the operator command, does.
- **Recovery codes cannot be re-keyed** in a secret-key rotation. Users get new ones before the previous key is removed (the runbook).
- **CP-37, CP-38, CP-40;** migrations 0012 and 0013.

## Open
- **The owner:** name the identity provider (Q5); single-tenant only.
- **BL-147:**
  - an administrator-initiated link for privileged accounts;
  - mapping groups from the provider's claims;
  - signing out at the provider;
  - Authlib's next major (its httpx integration is deprecated).
- **BL-148 (g):** WebAuthn passkeys.
- **BL-149, parked by the owner:** Tailwind 4 and daisyUI 5 on `feat/M6-tailwind4`.
