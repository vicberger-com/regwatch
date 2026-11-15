# Security review record: Phase 1 web UI, admin screens (M1 roles, flags, audit, settings; M2 jurisdictions, taxonomy transfer, term editing)

**Scope (PRs, routes, tasks):** `feat/M1-web-roles`, `feat/M1-web-flags`, `feat/M1-web-audit`, `feat/M1-web-settings-values`, `feat/M1-web-settings-screen`, `feat/M2-web-jurisdictions`, `feat/M2-web-jurisdictions-edit`, `feat/M2-web-taxonomy-transfer`, `feat/M2-web-term-rules`, `feat/M2-web-rule-test`, `feat/M2-web-term-merge`. Commit range `sec/web-reverify-followups..feat/M2-web-term-merge` = `5ba6bed..1ae3c4e` (11 commits, `web/` only: 27 files, +2967/-10; no dependency changes). Client routes `/admin/roles`, `/admin/flags`, `/admin/audit`, `/admin/settings`, `/admin/jurisdictions`, and the new parts of `/admin/taxonomy` (import, export, term editor, rule tester, merge, delete); `web/src/app/AppShell.tsx`, `web/src/app/router.tsx`, `web/src/test/api.ts`. The API under `api/src/regwatch` was read only as a reference for what the server enforces. · **Reviewer session label:** Web UI independent review · **Date:** 2026-11-15 · **Author sessions excluded from review:** yes

## Method
- Read the full diff and every new source file at `1ae3c4e`, plus the unchanged `lib/api/client.ts`, `lib/auth/session.ts` and `main.tsx` they depend on.
- Matched every API call the new screens make against `x-permission` in `openapi/regwatch.v1.yaml`, then confirmed each route's `perm=` in `api/src/regwatch/*/router.py` and the application-wide gate in `identity/permissions.py`.
- Searched `web/src` for markup sinks (`dangerouslySetInnerHTML`, `innerHTML`, `href`/`src` built from data, `window.open`, `eval`, `RegExp`), for logging and for storage use.
- Checked `openapi-fetch` 0.17.0 path-parameter encoding (`encodeURIComponent`) for the `{key}`, `{code}` and `{id}` paths.
- Read the server-side limits that bound client input: `BodySizeLimitMiddleware` (2 MiB), the setting checks (`MAX_STRING` 200 000, `MULTILINE`, application-owned keys), the rule tester (`maxLength` 50 000, `MAX_EVIDENCE` 5, 40-character snippets), the import caps, and the role "held permission" checks.
- Proof-of-concept component tests with the repository's fake API and real route tree, run from a copy of `web/` under `/tmp/rwpoc3` (the repository was not changed): P1 settings newlines, P2 audit rows after a 401, P3 delete during a merge. A Node check of `Blob.text()` on a Latin-1 file for finding 5.
- `make lint-web test-web` on `feat/M2-web-term-merge`.
- No data was changed on the dev stack; it was not contacted.

## Data flows touched
- **Browser to API, same origin `/api/v1`:** unchanged client (`credentials: "same-origin"`); the browser adds `Origin` to every POST, PUT, PATCH and DELETE, and the API checks it against `REGWATCH_BASE_URL` (`identity/permissions.py`, `core/security.py:88`). New: `POST /taxonomy/import` with a raw `application/yaml` body (a local file the admin picks), `GET /taxonomy/export` read as a blob.
- **API to browser:** roles and the permission catalogue, settings with values and notes, feature flags, audit rows with arbitrary JSON `before` and `after` from the database, jurisdictions and UN M49 regions, rule-test evidence (snippets of the admin's sample text), import summaries, RFC 9457 problems. All rendered as React text nodes.
- **Browser-held state:** new query keys `["admin","roles"|"permissions"|"flags"|"settings"|"audit",…]`, `["jurisdictions",…]`, `["taxonomy",…]`; mutation state holding import documents (up to 2 MiB), sample texts and the export blob; one short-lived blob URL.

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | Admin routes | `beforeLoad` session guard; per-route permission gate before any query; API session gate | none found | none |
| Tampering | Roles, settings, flags, jurisdictions, terms, import | Same-origin fetch and API Origin check; API `x-permission` on every route; confirmations on role delete, import, merge, term delete | Multi-line settings lose their line breaks on edit; imports silently replace undecodable bytes; flags toggle on one click; term edits overwrite concurrent edits | 1, 3, 5, 10 |
| Repudiation | Admin writes | API audit rows for every change (role, setting, flag, term, import per change) | none in the client | none |
| Information disclosure | Audit, settings, caches, errors | Text rendering; `forgetEverything` clears all new queries and mutations on sign-out and sign-in; API 500s carry no detail | Audit rows stay on screen after the session has ended | 2 |
| Denial of service | Audit JSON, term lists, import, rule tester | 2 MiB import pre-check; 50 000-character sample cap matching the API; iterative tree flattening; 16-level tree draw cap | Audit page renders every value in full | 7 |
| Elevation of privilege | Role matrix, route gates | Client gates equal the API's `x-permission` for every call; API refuses granting, removing or deleting permissions the actor does not hold, and keeps the admin role whole | Client gates go stale for up to 30 s after one's own role changes (server still refuses) | 9 |

## Checklist
- [ ] Input validation on every field: the API's job (M1 and M2 reviews). The UI pre-checks integers, numbers, enums, minimum hits, weight and file size; finding 1 is a client-side corruption of valid input.
- [x] Output encoding in UI: no `dangerouslySetInnerHTML`, `innerHTML`, `eval` or data-built `href`/`src` in `src/`; audit JSON and rule evidence render in `<pre>`/`<code>` text nodes.
- [x] Authentication and authorization on every route: all six new gates match `x-permission`, and the API enforces each one.
- [x] Session handling: new caches are cleared on sign-out and sign-in; finding 2 is about an expired session, not sign-out.
- [x] Secrets not logged or committed: no client logging; no secret-typed settings exist in `registries.yaml`.
- [x] Outbound requests only to the same origin.
- [x] File and body size limits: import checked against 2 MiB before reading; sample text capped at 50 000.
- [ ] Logging excludes sensitive data; audit rows written: API side, not re-verified here.
- [x] Dependency scans: no package or lockfile changes in range.

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | low | **Editing a multi-line setting strips its line breaks** (`web/src/features/settings/SettingsPage.tsx:120-137`, with `toText` at `web/src/features/settings/api.ts:68`). Every `string` setting gets a single-line `<input>`, and browsers drop CR and LF from an input's value. The API allows newlines in `legal.page_markdown`, `legal.required_markings` and `branding.company_address` (`admin/services.py:123`). **Scenario:** an admin fixes a typo in the legal page; the paragraphs, headings and lists of the stored Markdown are joined into one line, and the required markings printed in report and email footers are mangled. The API accepts it, so the only trace is the audit row. P1: `"# Legal\n\nLine two\nLine three"` is shown as `"# LegalLine twoLine three"`, and one typed character sends `{"value":"# LegalLine twoLine three!"}`. **Fix:** use a `<textarea>` for the multi-line keys. Better, have the API return a `multiline` hint so the client does not keep its own copy of the list. Add a test that saves a value containing `\n`. | open | reviewer PoC P1 |
| 2 | low | **Audit rows stay on screen after the session has ended** (`web/src/features/audit/AuditPage.tsx:29`, `:97-104`). `placeholderData: keepPreviousData`, plus rendering the table whenever `audit.data` is set, means a refetch that gets a 401 shows the alert above the old rows. Every other new screen returns early on `isError`. **Scenario:** an auditor leaves `/admin/audit` open on a shared machine. The idle timeout ends the session, and the next person at the desk still sees the audit log: who did what, before and after values. Refocusing the window refetches, gets a 401, and the rows stay. P2 confirmed the rows remain after the 401. **Fix:** hide the table when the error is a 401 or 403 (or on any error without `isPlaceholderData`). Better, add a QueryCache `onError` that runs `forgetEverything` and sets `me` to null on a 401, so every screen falls back to the sign-in redirect. | open | reviewer PoC P2 |
| 3 | info | **Feature flags switch on one click, with no confirmation** (`web/src/features/settings/FlagsPage.tsx:39-40`). Security-relevant settings (`auth.lockout_threshold`, `auth.breach_check_enabled`, `sessions.*`) also save without confirmation. Some flags send data off the host or widen what it fetches (`translation.enabled`, `classification.model`, `search.internet`, `capture.js_rendering`). The API has the precondition for hosted translation, writes an audit row, and the change is reversible, so this is not a vulnerability. **Fix:** confirm when turning on a flag that sends data to a third party or reaches the internet, naming the effect. Optionally list a flag's dependencies, as `screens.md` asks. | open (proposal) | by code reading |
| 4 | info | **Merge and Delete on one term can both fire** (`web/src/features/taxonomy/TermActions.tsx:92`, `:100`). Each button is disabled only by its own mutation's pending state. With a merge in flight, Delete stays enabled, and both requests go out (P3: `DELETE /taxonomy/terms/t-a` and `POST …/t-a/merge` were both sent). The server orders them and the loser gets a 404, so no damage was found. Each action is still confirmed, and neither can fire twice. **Fix:** disable both buttons while either mutation is pending. | open | reviewer PoC P3 |
| 5 | info | **Import silently replaces undecodable bytes** (`web/src/features/taxonomy/TaxonomyTransfer.tsx:44`). `file.text()` decodes as UTF-8 with replacement, so a Windows-1252 or Latin-1 YAML arrives as valid UTF-8 containing U+FFFD. That gets past the API's strict `UnicodeDecodeError` check (`taxonomy/transfer.py:62-64`) and is stored in labels and synonyms (`label: Caf\xe9` became `Caf�`). **Fix:** send the file's bytes (`await file.arrayBuffer()` or the `File` itself as the body) so the API's strict decode applies, or decode with `new TextDecoder("utf-8", { fatal: true })` and report the error. | open | Node check of `Blob.text()` |
| 6 | info | **The export blob URL is revoked straight after `click()`** (`web/src/features/taxonomy/TaxonomyTransfer.tsx:11-16`). This is the safe direction: nothing leaks and the URL is never navigated to. But some browsers can cancel the download, and the anchor is not attached to the document. **Fix:** revoke in a `setTimeout` (for example 0 to 1 s) after the click. Optionally check `blob.type` is YAML before saving, so a proxy's HTML page is not saved as `.yaml`. | open (proposal) | by code reading; not tried in a browser |
| 7 | info | **Audit values render in full** (`web/src/features/audit/AuditPage.tsx:180-187`). A string setting can hold 200 000 characters (`MAX_STRING`), and each audit row carries `before` and `after`, so one page of 50 rows can be about 20 MB of `<pre>` text. That is slow but finite, and it needs a `settings.manage` insider. **Fix:** truncate each value (for example to 2 000 characters) with a "show all" toggle. The diff viewer in `screens.md` is a natural place for this. | open (proposal) | by code reading |
| 8 | info | **The settings screen offers edit controls for application-owned keys** `taxonomy.version` and `branding.logo_ref`. The API refuses both (`admin/services.py:135-138`), so the only effect is a confusing error. **Fix:** show them read-only (an API `read_only` hint, or a client list until one exists). | open (proposal) | by code reading |
| 9 | info | **Saving a role does not refresh `me`** (`web/src/features/admin/api.ts:100-105` invalidates only `["admin","roles"]`). After an admin changes a role they hold, the nav links and route gates show the old permissions until `meQuery` goes stale (30 s). The API still answers 403 for anything removed, so the gating is only cosmetic in the meantime. **Fix:** also invalidate `meQuery.queryKey` and `["admin","users"]` on role save and delete. | open (proposal) | by code reading |
| 10 | info | **Term edits overwrite the whole synonym and match-rule lists** (`web/src/features/taxonomy/TermEditor.tsx:45-62`), with no version check. Two managers editing the same term at once lose one set of patterns without any warning. Both edits are audited. **Fix (BACKLOG):** send the `updated_at` or `taxonomy_version` seen, and have the API answer 409 when it has moved on. | BACKLOG proposal | by code reading |

## Checked and fine
- **XSS and markup injection:** no markup sinks. An audit `after` of `<img src=x onerror=alert(1)>` renders as text, which the author's test covers. Rule evidence, including the reflected `language` value, renders in `<code>`. Role, flag, setting, jurisdiction and term values are all text nodes. `window.confirm` messages are plain text. The only `href` set in code is the locally created blob URL.
- **Permission gating vs `x-permission`:**

  | Screen | Client gate | API `x-permission` |
  | --- | --- | --- |
  | Roles, permissions | `roles.manage` | `roles.manage` |
  | Settings, flags | `settings.manage` | `settings.manage` |
  | Audit | `audit.read` | `audit.read` |
  | Jurisdictions list and regions | `taxonomy.read` | `taxonomy.read` |
  | Jurisdiction create and edit | `taxonomy.manage` (`canManage`) | `taxonomy.manage` |
  | Export | `taxonomy.read` | `taxonomy.read` |
  | Import, term edit, test-rules, merge, delete | `taxonomy.manage` | `taxonomy.manage` |

  Every route sets `perm=` (`admin/router.py`, `identity/router.py`, `taxonomy/router.py`). `authorize` is an application-wide dependency that refuses missing permissions with 403, and `tests/openapi_semantic.py` checks that the router's `x-permission` matches the contract. Nav links in `AppShell.tsx` use the same keys. The role matrix lets a user tick permissions they do not hold, but the API refuses the grant (`_require_held` on the symmetric difference), refuses changes to the admin role, and refuses deleting system or assigned roles.
- **CSRF:** `client.ts` is unchanged (same-origin credentials, relative base). All new writes are POST, PUT, PATCH or DELETE, which browsers send with `Origin`, and the API checks it before the session. Export is a safe GET whose response is a download (`Content-Disposition: attachment`); no CORS is enabled. Path parameters are `encodeURIComponent`-encoded by openapi-fetch.
- **Destructive actions:** role delete, term merge, term delete and import are confirmed, and their buttons or inputs are disabled while pending, so none fires twice. A cancelled confirmation sends nothing. Role delete is not offered for system roles. Merge targets exclude the term, its descendants and inactive terms. The file input is reset after each choice. Finding 4 covers the one cross-action gap.
- **Cache across sign-out:** every new query and mutation lives in the shared QueryClient, so `forgetEverything` (`getMutationCache().clear()` plus `client.clear()`) removes the audit pages, settings, import documents, sample texts and export blob on sign-out and on the next sign-in. `regionsQuery` uses `staleTime: Infinity` but is still cleared.
- **Resource exhaustion:**
  - File size is checked before the file is read.
  - The 2 MiB pre-check equals `MAX_BODY_BYTES`.
  - The sample `maxLength` of 50 000 equals the contract's limit.
  - Evidence is capped at 5 snippets by the API.
  - The term tree draw stays capped at 16 levels, and `flatten` (used for the parent and merge pickers and the editor lookup) is iterative.
  - Import caps on the API side are 200 facets, 5 000 terms per facet and 10 000 in total; the merge picker at 5 000 options is acceptable.
  - Audit is paged at 50 rows.
  - RE2 patterns are never compiled in the browser (no `RegExp` in `src/`), so the browser has no ReDoS exposure.
- **File input:** `accept` is advisory only, and the API parses with a no-alias `SafeLoader`. The confirmation shows the file name as text. Oversized files are refused with a clear message.
- **Error text:** `problemText` shows only the API's `detail` and field messages. API 500s carry no detail, and import errors name the exception type only. Non-problem bodies (proxy HTML, network errors) fall back to fixed text.
- **Test helper (`web/src/test/api.ts`):** it now parses a body as JSON only when the `Content-Type` contains `json`, and otherwise records the raw text. This lets the import test see the YAML body and does not loosen any existing assertion. The recorded `origin` is always `null` under jsdom, which is unchanged and expected: no test can prove the browser sends `Origin`, and `client.test.ts` instead checks `credentials: "same-origin"`.
- **No new dependencies;** `CHANGELOG.md` is the only file outside `web/` in the range.

**Sign-off at review:** **signed off.** No critical, high or medium findings. Two low (1, 2) and eight info (3 to 10) are open, recommended for a follow-up `sec/` branch before the external audience is admitted; none blocks merging the stack. · Web UI independent review · 2026-11-15

## Evidence (reviewer)
- **Findings 1, 2 and 4:** proof-of-concept component tests (`/tmp/rwpoc3/web/src/poc.test.tsx`, a copy of `web/` with the repository's `node_modules` linked), 3 passed:
  - P1: `TAG INPUT shown: "# LegalLine twoLine three"` and `SENT {"value":"# LegalLine twoLine three!"}`.
  - P2: `STILL SHOWN after 401: true`.
  - P3: `DELETE disabled during merge: false`; calls `DELETE /taxonomy/terms/t-a | … | POST /taxonomy/terms/t-a/merge`.
- **Finding 5:** Node 22, `new Blob([latin1 bytes]).text()` gave `"…label: Caf�\n"`.
- **Findings 3, 6 to 10:** code reading, with the API files cited.
- **Repository suites:** `make lint-web test-web` on `1ae3c4e`: ESLint and Prettier clean, typecheck clean, 16 test files and 81 tests passed.

## Author follow-up (`sec/web-admin-followups`, pending re-verification)
- **Finding 1 (low):** string settings are edited in a `<textarea>` (`web/src/features/settings/SettingsPage.tsx`), so line breaks survive. Test: "keeps the line breaks of a multi-line text setting".
- **Finding 2 (low):** the audit table renders only while the query is not in error (`web/src/features/audit/AuditPage.tsx`), so a 401 or 403 on a later page hides the earlier rows. Test: "hides earlier rows once a later page fails". A global 401 handler is not added here; every other screen already shows only the error when its own query fails.
- **Finding 4:** merge and delete share one busy state (`web/src/features/taxonomy/TermActions.tsx`).
- **Finding 5:** import decodes with `TextDecoder("utf-8", { fatal: true })` and refuses other encodings (`web/src/features/taxonomy/TaxonomyTransfer.tsx`). Test: "refuses a file that is not UTF-8".
- **Finding 6:** the blob URL is revoked after 10 seconds. The export test checks it is not revoked at once and is revoked when the timer fires.
- **Finding 7:** each audit value shows at most 10,000 characters and how many more there are. Test: "shortens a very large value".
- **Findings 3, 8, 9 and 10:** deferred to BL-77.
- **Checks:** `make lint-web` clean; `make test-web` 85 tests passed, 98.71% lines.


## Re-verification (Web UI independent review, 2026-11-15)
Against `sec/web-admin-followups` at `f0a51be` (diff `1ae3c4e..f0a51be`).
- **Repository suites:** `make lint-web test-web`: lint, Prettier and typecheck clean; 16 test files and 85 tests passed; 98.71% lines.
- **Proofs of concept:** P1 to P3 re-run unchanged from a fresh copy of `web/` in `/tmp/rwpoc4`.

| # | Verdict | Evidence |
| --- | --- | --- |
| 1 | fixed | P1: the field is now a `TEXTAREA` showing `"# Legal\n\nLine two\nLine three"`. After one typed character it sends `{"value":"# Legal\n\nLine two\nLine three!"}`. |
| 2 | fixed | P2: after the 401 refetch, the row is no longer shown (`STILL SHOWN after 401: false`) and the alert is. The table renders only when `!audit.isError` (`AuditPage.tsx:104`). There is still no global 401 handler; this is accepted, because every screen now shows only the error when its own query fails. |
| 3 | deferred, covered | BL-77 (a): confirm flags and settings that send data out or widen fetching. |
| 4 | fixed | P3: Delete is disabled while the merge is in flight (`DELETE disabled during merge: true`). Only the merge request was sent; the PoC's own assertion of two calls now fails, as intended. One `busy` state is shared by both buttons (`TermActions.tsx:30`). |
| 5 | fixed | `TextDecoder("utf-8", { fatal: true })` on the file's bytes (`TaxonomyTransfer.tsx:50-62`). Node check: Latin-1 `Caf\xe9` and a UTF-16LE file are refused; UTF-8 `Café` is accepted; a UTF-8 BOM is stripped, which is what the API's `decode("utf-8")` would otherwise leave as U+FEFF, so this is no worse. |
| 6 | fixed | Revoked after 10 s (`TaxonomyTransfer.tsx:17-19`); covered by the author's fake-timer test. The URL is local and same-origin, so a blob that outlives a sign-out by up to 10 s exposes nothing. |
| 7 | fixed | Each value is cut at `VALUE_MAX` = 10 000 characters, with a count of what was cut (`AuditPage.tsx:180-194`). This bounds one page to about 1 MB of text. |
| 8 | deferred, covered | BL-77 (b): the API marks read-only settings. |
| 9 | deferred, covered | BL-77 (c): refresh the user's permissions after saving their own role. |
| 10 | deferred, covered | BL-77 (d): a version or `If-Match` check, flagged as a CP. |

The BL-77 row cites findings 3, 8, 9 and 10, its decision is `open`, and its modules are M1 and M2. That matches how BL-75 and BL-76 were recorded.

Checked for regressions:
- **Textarea for every `string` setting:** single-line keys (`general.site_title`, `capture.user_agent`, `branding.primary_color`, `general.contact_email`) can now take a typed newline. The API refuses it: `has_control` without `allow_newlines` (`core/schemas.py:36`, `admin/services.py:128`), and the error is shown as text. Enter no longer submits those rows; that is a usability point only. The `inputMode` branch now covers only `integer` and `number`, because every other type has its own control.
- **TextDecoder path:** the 2 MiB size check still runs before the file is read. A refused file sends nothing, and the error replaces the old size-only message without hiding upload or download errors.
- **Audit gating:** an error on a later page hides the rows and the page buttons together. Applying the filters again returns to page 1, which is cached, so the user is not stuck. Cutting a value in the middle of a surrogate pair can show one replacement character; this is cosmetic.
- **TermActions:** no change to the confirmations; a cancelled dialog still sends nothing.
- **Other files:** none in `web/` changed beyond the five above; the CHANGELOG and BACKLOG entries match the code.

New at re-verification: none.

**Sign-off:** signed off. Findings 1, 2 and 4 to 7 are verified fixed; 3 and 8 to 10 are carried in BL-77. No critical, high, medium or low findings are open. · Web UI independent review · 2026-11-15
