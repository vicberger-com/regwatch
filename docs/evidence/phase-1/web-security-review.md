# Security review record: Phase 1 web UI (M1 sign-in and users, M2 taxonomy)

**Scope (PRs, routes, tasks):** `feat/M1-web-session`, `feat/M1-web-password`, `feat/M1-web-users`, `feat/M1-web-user-create`, `feat/M2-web-taxonomy`, `feat/M2-web-taxonomy-edit`, `feat/M0-dev-proxy-host` (`sec/M2-reverify-followups..6f503d7`). Client routes `/login`, `/change-password`, `/`, `/admin/users`, `/admin/taxonomy`; `web/src`, `web/vite.config.ts`, `deploy/compose.yaml`, `deploy/README.md`. The API was reviewed separately (M1 and M2 records). · **Reviewer session label:** Web UI independent review · **Date:** 2026-11-15 · **Author sessions excluded from review:** yes

## Data flows touched
- **Browser to API, same origin `/api/v1`:** openapi-fetch with `credentials: "same-origin"`. The browser attaches the `rw_session` cookie (HttpOnly, Secure, SameSite=Lax) and `Origin`. The API checks `Origin` against `REGWATCH_BASE_URL` on mutating requests only.
- **API to browser:** `Me` with permissions, users, roles, facets and term trees, one-time temporary passwords, RFC 9457 problems. All rendered as React text nodes.
- **Browser-held state:** the TanStack Query and Mutation caches, component state (form fields, the shown temporary password), `?next=` in the URL, the theme in localStorage.
- **Development ingress (new):** owner's browser → Midway-authenticated DevSpaces proxy → devbox 127.0.0.1:80 → Caddy → Vite (Host-checked) or the API.

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | Login, session, `next`, dev proxy Host | API session gate is authoritative. `safeNext` and router normalisation keep `next` same-origin (9 encodings tested). Vite `allowedHosts` refuses foreign Hosts | A failed sign-out left the server session live | 1, 7 |
| Tampering | Admin and taxonomy writes | Same-origin fetch, API Origin and permission checks | One-click reset and disable; no `frame-ancestors` | 4, 5 |
| Repudiation | Admin actions | API audit rows (M1) | Audit IPs behind the DevSpaces proxy not verified | none |
| Information disclosure | Caches, temporary password, errors | Sign-out removed queries; problems shown as text; no source maps in the build | Passwords kept in the MutationCache; a new sign-in showed the previous user's cache | 2, 3 |
| Denial of service | Term tree, user list | none client-side | Unbounded recursion; users past 200 unreachable | 8, 9 |
| Elevation of privilege | Route guard, permission checks | `beforeLoad` resolves `me` before rendering; permission gates come before queries; API enforces 401/403 | none found | none |

## Checklist
- [ ] Input validation on every field: this is the API's job (M1 and M2 reviews). The UI sends only schema-typed bodies.
- [x] Output encoding in UI: no `dangerouslySetInnerHTML`, `innerHTML` or data-built `href` in `src/`.
- [x] Authentication and authorization on every route: guard and permission gates verified; the API stays authoritative.
- [ ] Session handling: **not met at review** (findings 1 to 3).
- [x] Secrets not logged or committed: no client logging; `deploy/.env` is ignored.
- [x] Outbound requests only to the same origin.
- [ ] File and body size limits: not applicable to these screens.
- [ ] Logging excludes sensitive data; audit rows written: API side, not re-verified.
- [ ] Dependency scans: production audit clean; register rows missing (finding 6); dev audit not clean (finding 10).

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | medium | **Sign-out reported success when the API refused or failed** (`session.ts`): the response was never checked, so the UI showed the sign-in card while the server session stayed valid. With `REGWATCH_BASE_URL` changed for the proxy, a `localhost` tab's sign-out answered 403 `origin-mismatch`, and the next person at that browser was signed in as the admin. | `sec/web-session-hygiene` | yes (author): `keeps the user signed in, and says so, when the API refuses it`; awaits re-verification |
| 2 | low | **Plaintext passwords stayed in the MutationCache after sign-out:** login variables, reset and create results, and password-change variables, for about 5 minutes. | `sec/web-session-hygiene` | yes (author): `leaves no password or temporary password in the caches`; awaits re-verification |
| 3 | low | **Signing in did not clear the previous user's cached data;** a second user briefly saw the first user's user list. | `sec/web-session-hygiene` | yes (author): `never shows a previous user's cached data to the next user`; awaits re-verification |
| 4 | low | **Reset and Disable fired on one click,** and Reset was offered on one's own row, signing the admin out mid-task. | `sec/web-hardening` | yes (author): confirmations tested, including cancel; no own-row Reset; awaits re-verification |
| 5 | low | **No security headers on the SPA** (`deploy/Caddyfile`), now browsed over HTTPS through the proxy; no `frame-ancestors` made finding 4 clickjackable from a same-site frame. | `sec/web-hardening` (development); BL-76 (production) | yes (author): headers present on `GET /login` after the proxy restart; awaits re-verification |
| 6 | info | Component register not updated for the TanStack runtime packages. | `sec/web-hardening` | row added at S; LICENSE files at release (BL-76) |
| 7 | info | `REGWATCH_DEV_PUBLIC_HOST` was not validated; a leading dot would make Vite accept every subdomain. | `sec/web-hardening` | by code reading (`vite.config.ts` now refuses anything but one host name) |
| 8 | info | The user list stopped at 200, and the role list failed silently for a users-only admin. | `sec/web-hardening` | yes (author): `loads every page of users`, `explains that roles cannot be listed` |
| 9 | info | The term tree rendered recursively without a depth bound; depth 5000 overflowed the stack. | `sec/web-hardening`; API cap BL-76 | yes (author): `draws at most 16 levels and flattens deep trees without recursion` |
| 10 | info | Dev-tooling audit not clean (tinypool, vitest, glob, minimatch); predates this scope; `pnpm audit --prod` clean. | BL-60 | n/a |

Checked and fine:
- **Open redirect:** none; 9 `next` variants stayed same-origin.
- **XSS:** none found.
- **Guard:** fails closed, and nothing sensitive is fetched before it.
- **CSRF:** relies correctly on same-origin fetch and the API Origin check.
- **Forms:** autocomplete attributes, labels and alert regions are correct.
- **Temporary password:** the polite live region holding it is acceptable.
- **README steps:** they do not widen exposure.
- **Binds:** still `127.0.0.1` only.

**Sign-off at review:** no high or critical open; one medium (1) open · Web UI independent review · 2026-11-15

## Evidence (reviewer)
- **Findings 1 to 3:** proof-of-concept component tests with the fake API, under `/tmp/rwpoc`.
- **Findings 4, 6, 7 and 8:** code reading.
- **Finding 5:** read-only `curl -D -` of `/login`, and inspection of the production build (no inline scripts or styles, no eval, no source maps).
- **Finding 9:** jsdom proof of concept at depths 3, 1000 and 5000.
- **Finding 10:** `pnpm audit` and `pnpm audit --prod`.
- **Repository suites:** 32 tests passed; lint and typecheck clean.
