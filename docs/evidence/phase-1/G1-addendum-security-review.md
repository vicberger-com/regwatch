# Security review record: G1 addendum (CP-08 public branding and legal page, audit CSV export, LRU eviction in the login limiter)

**Scope (PRs, routes, tasks):** three changes that peer review found no security record covers. Part A: commit `7393cc1` (`feat/M1-public-branding`, CP-08): public `GET /branding/public`, public `GET /legal` with its required markings, `/legal` outside the signed-in web shell, and the sign-in page using the public summary. Part B: commit `120b321` (`feat/M1-web-audit-actor`): client-side audit CSV export over `GET /admin/audit` pages and the actor filter (`web/src/features/audit/csv.ts`, `AuditPage.tsx`, `web/src/app/router.tsx`). Part C: commit `03231e9` (`sec/M1-login-rate-fix2`): least-recently-used eviction in `SlidingWindow` and `evict_live=False` for `unknown_failures`, the fix for N4 and N5 of `M1-login-rate-review.md` re-verification 2. Code was read at the commits and at `dd2662b` (`fix/G1-review-findings`); no later commit changes the code in scope; `dd2662b` only adds 30 lines to `AuditPage.test.tsx`. · **Reviewer session label:** G1 addendum independent review · **Date:** 2026-11-16 · **Author sessions excluded from review:** yes

## Method (all parts)
- Read `git show` of each commit in full, and the unchanged code it relies on: `identity/permissions.py` (`authorize`), `core/routing.py` (`spec`), `admin/services.py` (`values`, `branding`, `legal`, `list_audit`), `admin/legal.py` (render cache and pools), `core/services.py` (`audit`), `api/middleware.py` (request id), `identity/services.py` (`login`, `_count_failure`, `LockTable`), `deploy/Caddyfile`, `docs/contracts/screens.md`, `registries.yaml`, and the earlier records `BL-68-security-review.md` and `M1-login-rate-review.md`.
- Proofs of concept are in `/tmp/g1addendum/`, outside the repository: `csv_probe.mjs` (a verbatim copy of `csvField`, run with Node 20), `lru_probe.py` and `mutant.py` (run with `cd api && uv run python -I`). The previous reviewer's `/tmp/rlpoc/v2.py`, `alt2.py` and `v3.py` were still present and were re-run unchanged.
- Tests run: `uv run pytest -q tests/unit/test_auth_gate.py` 30 passed; `tests/unit/test_contract_routes.py` 9 passed; `uv run pytest -q tests/unit` 537 passed.
- Not done: the web Vitest suite could not run on the host (Node 20; the web toolchain needs Node 22, which is only in the Docker images, and the Docker stacks were out of bounds). Database integration tests were not run for the same reason. No browser, no spreadsheet application, no external network. No repository file other than this record was changed.

---

## Part A: CP-08, public branding summary and public legal page (`7393cc1`)

### Scope
`api/src/regwatch/admin/router.py:83-96` (`GET /branding/public`, `GET /legal` now `public=True`), `admin/schemas.py` (`BrandingPublic`), `admin/services.py:255-261` (`branding_public`) and `:313-317` (`legal`, unchanged), `openapi/regwatch.v1.yaml` (`security: []` on both), `web/src/app/PublicFrame.tsx`, `web/src/app/router.tsx` (`legalRoute` under `rootRoute`), `web/src/features/auth/LoginPage.tsx`, `web/src/features/branding/LegalPage.tsx` and `api.ts` (`publicBrandingQuery`), tests in `api/tests/integration/test_admin.py` and `web/src/app/BrandingShell.test.tsx`.

### What anonymous visitors now see
- `GET /branding/public`: `site_title`, `logo_url` (`/api/v1/branding/logo?v=<first 12 hex of the logo's SHA-256>`), `primary_color`, `has_legal_page`. The handler builds `BrandingPublic` field by field, and `spec` sets it as `response_model`, so `company_name`, `company_short_name`, `company_address` and `required_markings`, which `branding()` also loads, cannot reach the response.
- `GET /legal`: the full sanitised HTML of `legal.page_markdown` (up to 200,000 characters of Markdown) and `legal.required_markings` verbatim.
- Unchanged: `/health`, `/version`, `/branding/logo`, `/auth/login`. Those six operations are the only `security: []` ones in the contract and the only `public=True` routes in `api/src`.

### Findings
| # | Severity | Location | Description and failure scenario | Fix |
| --- | --- | --- | --- | --- |
| A1 | low | `api/src/regwatch/admin/services.py:313-317`, `router.py:91-96`; `api/tests/integration/test_admin.py:390`; `web/src/features/branding/BrandingPage.tsx:276` | **The required markings and the legal text are now public, but the commit, the test and the editor say otherwise.** The commit message and CHANGELOG say "Company details stay private", and `test_public_branding_summary` is described as "without company details or markings". `GET /legal`, however, returns `required_markings` to anyone. Per `registries.yaml` these markings are "short text inserted in report and email footers", i.e. classification text written for internal readers. In round 2 of use testing the markings were "ACME INTERNAL", which publishes the short company name that `GET /branding` keeps private. The editor labels the field "Required markings (report and email footers)" and the page text field gives no hint that either is public. Legal text and markings saved before CP-08 were written when only signed-in users could read them, and they were published by this change without the owner seeing them again. **Scenario:** an owner who enters "CONFIDENTIAL: Acme Compliance Ltd, internal distribution only" for report footers, as the label suggests, publishes it on the external site. Similarly, a compromised `settings.manage` session can place links (http, https, mailto, with any link text) on a page that is now public and carries the site's branding. That was visible only to signed-in users before. `screens.md` does list the markings on the public `/legal`, so the contract is consistent; the gap is that nobody decided that the markings, rather than the legal page alone, should be public. | Owner decision, then one of these. (a) Drop `required_markings` from the anonymous `GET /legal` response: return it only when a session is present, or split it into the authenticated `GET /branding`, which already carries it. (b) Keep it public, and say so: label both fields "shown publicly on /legal" in the editor, correct the commit's claim in the CHANGELOG and the test docstring, and add a test asserting what the anonymous `GET /legal` returns. In either case, ask the owner to re-read the stored page and markings before the external audience is admitted. |
| A2 | info | `api/src/regwatch/admin/router.py:83-96`, `services.py:255-261`; `deploy/Caddyfile` | **Public reads have no cache headers and no rate limit.** Neither route sets `Cache-Control` or an `ETag`. Each anonymous `GET /branding/public` runs two settings queries (`branding()` and a second `values()` for the legal page) only to compute a boolean. Each `GET /legal` runs one query and returns the whole page, which at the 200,000-character cap is up to about 1.7 MB of HTML (BL-68 PoC R6 measured that size). The render is cached by content (`lru_cache(maxsize=8)`), so the CPU cost is small. The proxy has no request limit (M1 login-rate review N1). **Scenario:** an anonymous client looping on `GET /legal` turns each small request into up to 1.7 MB of response and one database round trip. That holds pool connections that sign-ins also need. `/health` and `/branding/logo` already had this property, so the change adds to an existing gap; it does not open a new one. | Send `Cache-Control: public, max-age=60` (or `no-cache` with an `ETag` from the setting's `updated_at` or a content hash) on both routes. Read the legal key in the same `values()` call in `branding_public`. Add a per-address request limit for unauthenticated `/api/*` paths to the production proxy work (M10, BL-76). |

### Checked and fine
1. **No other branding or setting field leaks.** `BrandingPublic` has exactly four fields; the integration test asserts the full dictionary with a company name and markings stored, and that `GET /branding` stays 401 anonymously. No other route changed its `security`. `has_legal_page` reveals only whether the stored Markdown is blank.
2. **Enumeration.** Neither route takes input. There is nothing to enumerate except the logo version, and the logo itself is public by CP-07. Nothing about users or accounts is exposed.
3. **Session and cookies.** `authorize` returns before reading the cookie on `security: []` routes, so public responses never depend on the session, never set a cookie, and are the same for every viewer. A shared cache that stores them could not mix up users' data. `Origin` is still checked on mutating methods; both routes are GET only.
4. **Caching in the web client.** `publicBrandingQuery` (stale after 5 minutes) and `legalQuery` hold only public data, so they need no clearing at sign-out. The sign-in page now loads the logo with its `?v=` hash, so the logo route's `max-age=300` no longer keeps a replaced logo on the sign-in page (BL-68 finding 9, first half).
5. **BL-68's sanitisation assumptions still hold for anonymous viewers.** The HTML that reaches `dangerouslySetInnerHTML` (`LegalHtml`) still comes only from the server's markdown-it (raw HTML off) and nh3 allowlist (`legal.py`). The stored Markdown can only be written through the two budget-checked routes (BL-68 re-verification 2). BL-68's XSS cases do not depend on who is viewing. An anonymous visitor has no session to steal, and a signed-in user who opens `/legal` sees the same document as before. So making the page public does not widen what a sanitiser bypass could do, beyond the larger audience in A1.
6. **CSP and headers.** `/legal` is an SPA route served through the same Caddy `handle`, so it gets the site CSP (`script-src 'self'`, `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff` and `Referrer-Policy: no-referrer`. Links carry `rel="noopener noreferrer nofollow"`. The production CSP (BL-76) must cover this public route as it does every other SPA route; nothing route-specific is needed.
7. **Render load from anonymous callers.** The Markdown comes from the database, never from the request, so anonymous callers cannot fill or flush the render cache. A cache miss after a save renders at most two pages at a time in the dedicated `legal-render` pool, within the 2 s save budget; concurrent misses queue and then hit the cache. The default thread pool and the event loop are not involved (BL-68 N1 and N4).
8. **Web shell.** `legalRoute` moved from `authedRoute` to `rootRoute`. It runs no session query and passes no signed-in data to `PublicFrame`. The accent colour is checked against `COLOR` before `setProperty`, as in the shell. `logo_url` is built by the server from the `LOGO_KEY` pattern. If `/branding/public` fails, the sign-in page still works without branding (web test).
9. **Contract and fuzzing.** `security: []` is in the contract for both operations, the route-count test was updated, and the Schemathesis exclusion of the two database-reading public routes matches the existing `/branding/logo` precedent. Their integration tests cover them instead.

### Sign-off (Part A)
**Given, with one condition.** No critical, high or medium findings. A1 (low) needs an owner decision recorded (markings public or not), and either the code or the wording changed to match, before the external audience is admitted (M10). A2 is a proposal for M10 and BL-76.

---

## Part B: audit log actor filter and CSV export (`120b321`)

### Scope
`web/src/features/audit/csv.ts` (`csvField`, `toCsv`, `fetchForExport`, `MAX_EXPORT_ROWS = 10_000`), `web/src/features/audit/AuditPage.tsx` (`saveCsv`, export button, actor `<select>`), `web/src/app/router.tsx` (`canListUsers={hasPermission(me, "users.manage")}`), tests `csv.test.ts` and `AuditPage.test.tsx`. Server code relied on, unchanged: `GET /admin/audit` (`x-permission: audit.read`, `page_size` at most 200, `admin/services.py:333-385`) and `GET /admin/users` (`users.manage`).

### What leaves the system
The export can save up to 10,000 rows to the user's disk, in columns `occurred_at`, `actor_email`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `ip`, `request_id`, `before` and `after`. These include:
- client IP addresses of every sign-in, failure, lock and admin action;
- actor emails;
- `email_sha256` of every failed sign-in for an unknown or disabled account (`identity/services.py:475`), an unsalted SHA-256 that a list of candidate emails reverses; when someone types their password into the email field, it becomes an unsalted SHA-256 of that password;
- role, permission and user changes;
- the full before and after text of every legal page and setting change.

This is the same data `audit.read` holders can already page through on screen. The export makes the extraction one click, and the copy leaves 8.4's controls: when a user is deleted, the audit rows are anonymised, but exported files are not.

### Findings
| # | Severity | Location | Description and failure scenario | Fix |
| --- | --- | --- | --- | --- |
| B1 | low | `web/src/features/audit/csv.ts:45-60`, `AuditPage.tsx:58-63`; 8.2 | **The export writes no audit row, and the server cannot tell an export apart from paging.** 8.2 requires "audit rows for every admin and output action", and an export of the audit log is an output of personal data. Since the CSV is assembled in the browser from ordinary `GET /admin/audit` calls, nothing records who exported which filters, how many rows, or when. **Scenario:** a user with `audit.read`, or a stolen session of one, exports the newest 10,000 rows (IPs, emails, email digests, permission changes) and leaves no trace beyond access-log lines that look like paging. Viewing is not audited either, so the gain over a script that pages through is small. But 8.2 is a stated control that this record is meant to enforce, and peer review asked about it. | Answering peer review: **yes, the export should write its own audit row.** Recommended: a server-side `GET /admin/audit/export` (needs a CP) that takes the same filters and streams `text/csv` built with the same defusal on the server. Commit an `audit.export` row (actor, IP, filters, row count, truncated or not) before the body is sent. Gate it on `audit.read`, or on a separate `audit.export` if the owner wants to split them. This also fixes B2 and B3. Minimum alternative: record the deviation from 8.2 with the owner's acceptance in BACKLOG until M6's export framework lands. A client-reported "I exported" call is not a substitute, because the client can skip it. |
| B2 | info | `csv.ts:45-60`, `:37-42`; `AuditPage.tsx:41-52` | **Memory is bounded by row count, not size.** `before` and `after` are unbounded JSON. A `legal.update` or `setting.update` of the legal page carries up to 200,000 characters in each (the viewer already cuts values at `VALUE_MAX` for this reason). The export holds every entry, then an array of CSV lines, then the joined string, then the `Blob`: about four copies. Worst case, 10,000 such rows are about 4 GB of text, and the tab runs out of memory. On the server, each 200-row page is built in memory as one response (up to about 80 MB for such rows), 50 times in sequence. That is no more than a user can request by hand, but it is now one click. Typical rows are under 1 KB, so a normal export is about 10 MB. Requests are sequential and the button is disabled while one is running, so one tab sends one request at a time. | Build the `Blob` from per-page CSV chunks and drop each page's entries as you go. Optionally cap each value at `VALUE_MAX` with an explicit "… N more characters" marker, and say so in the file header. The server-side export in B1 removes the issue. |
| B3 | info | `csv.ts:16-19`, `:50-58`; `admin/services.py:358-365` | **The export is not a consistent snapshot, and the file does not say what it holds.** Offset pages are taken over a table that keeps growing, newest first. Rows written during the export push earlier rows onto the next page, so the file repeats some rows, and near the cap it holds fewer than 10,000 distinct ones. The `id` column is not exported, so duplicates cannot be removed reliably. Every export itself adds `auth.login` and other rows. The truncation warning appears only on screen; the file carries no record of the filters, the export time or the cut. For an audit trail used as evidence, this is an integrity weakness, not a confidentiality one. | At the start, fix `to` to the current time (the API supports `to`, which is exclusive), so new rows cannot shift the pages. Export `id`. Put the export time, the filters and "truncated at 10,000 of N" in the file name or a first comment row. The server-side export in B1 can use a single query. |
| B4 | info | `web/src/features/audit/csv.ts:33` | **The formula defusal covers OWASP's characters but not some variants.** `^[=+\-@\t\r]` gets an apostrophe; leading LF, leading spaces before `=`, and the full-width `＝`, `＋`, `－`, `＠` do not (`csv_probe.mjs`). Whether a spreadsheet evaluates these variants depends on the application and locale; none was available to test. Today no top-level column can start with one: `request_id` is the only value a client controls (`api/middleware.py:20`, `[A-Za-z0-9._-]{1,128}`, and a leading `-` is already defused); emails pass `check_email`; `action` and `entity_type` are constants; `entity_id` is a UUID, a setting key, or a key matching `^[a-z][a-z0-9_]{1,40}$`; `before` and `after` are JSON objects that start with `{`. So this is hardening against future columns. | Test `^[\s　]*[=+\-@＝＋－＠]` and `^[\t\r\n]`, and add these cases to `csv.test.ts`. When the CSV is moved to the server (B1), keep one shared function for all CSV exports (M6). |
| B5 | info | `web/src/app/router.tsx:207`, `AuditPage.tsx:56-57`, `:115-139` | **The actor filter depends on `users.manage`, a permission unrelated to auditing.** The API accepts `actor` from any `audit.read` holder. Only the web picker needs `GET /admin/users`. An auditor role with `audit.read` alone gets the note "Filtering by actor needs the users.manage permission", and could be granted `users.manage`, which lets them create users and reset passwords, just to filter. This is not a hole: the server enforces both permissions, and an `audit.read` holder already sees every actor's email in the rows. The risk is that someone grants too much to get the filter. | Do not grant `users.manage` for this. Either offer a filter by actor email or id that needs no user list (the id is in every row, so a "filter by this actor" link on a row works with `audit.read` alone), or add, through a CP, a small `GET /admin/audit/actors` under `audit.read` that returns id and email for actors who appear in the log. |

### Checked and fine
1. **Quoting.** Every field is quoted and embedded quotes are doubled. Records end in CRLF. Embedded CR and LF stay inside quotes (`"a""b\r\nc"`), so a value cannot start a new row or column. The header row is a fixed list of names. `null` becomes an empty quoted field, and objects become JSON text.
2. **Defusal on the characters OWASP lists.** `=`, `+`, `-`, `@`, tab and CR at the start get a leading apostrophe inside the quotes. The apostrophe stays visible in some applications, which is the usual trade-off. Tests cover each of these and an `actor_email` of `=evil()`.
3. **Authorization.** The export calls the same `GET /admin/audit` with the same session and the filters currently applied (not the unsaved draft), so it can return nothing the viewer could not show. It is reached only from the `/admin/audit` route, which checks `audit.read`, and the API enforces `audit.read` on every page. The actor list is enabled only with `users.manage`, and if `GET /admin/users` fails, the picker just shows "Anyone".
4. **Cap and request count.** 10,000 rows is under 8.2's export cap of 50,000. That is 50 requests of 200 rows, sent one after another, and the loop stops on a short page or at the reported total. A failed page throws, and no partial file is saved.
5. **Download handling.** The file is a same-origin `blob:` URL with a fixed name, revoked after 10 s. Nothing is sent to a third party, and the CSP is unaffected.
6. **The table view.** Before and after values are still rendered as React text in `<pre>`, not as markup.

### Sign-off (Part B)
**Given, with one condition.** No critical, high or medium findings. B1 (low) is the 8.2 gap peer review raised. Either a server-side export that writes an `audit.export` row (preferred) or an owner-accepted, recorded deviation is needed before the external audience is admitted. B2 to B5 are proposals for BACKLOG; B3's fixed `to` is a one-line change that is worth making now.

---

## Part C: re-verification of N4 and N5 in the login limiter (`03231e9`)

### Scope
`api/src/regwatch/identity/services.py:85-163` (`SlidingWindow`: `evict_live`, `hit()` moves its key to the end, `_sweep` evicts live keys only when `evict_live`), `:193-198` (`unknown_failures = SlidingWindow(..., evict_live=False)`), tests `test_recently_hit_keys_survive_the_sweep` and `test_unknown_account_failures_are_never_evicted_while_live` in `api/tests/unit/test_auth_gate.py`, the CHANGELOG sentence (N5). The identity code at `dd2662b` is identical to `03231e9`. The author's follow-up 3 in `M1-login-rate-review.md` describes the change; this is its re-verification.

### Method
- Re-ran the earlier reviewer's `/tmp/rlpoc/v2.py`, `alt2.py` and `v3.py` unchanged.
- Added `/tmp/g1addendum/lru_probe.py`:
  - A: LRU order;
  - A2: an attacker held at a target's limit while a flood runs;
  - B: the real `unknown_failures` object past a scaled-down cap;
  - B2: expiry still sweeps;
  - C: memory per entry and sweep cost with 200,000 live keys;
  - D: dummy Argon2 verify throughput on this host;
  - E: exact refunds after reordering.
- Added `/tmp/g1addendum/mutant.py`, which runs the new LRU test's steps against a `hit()` without the move to the end.

### Verdicts
| # | Verdict | Evidence |
| --- | --- | --- |
| N4 | fixed | `hit()` re-inserts its key (`self._hits[key] = self._hits.pop(key)`), so dictionary order is the order of the last hit, and `_sweep` evicts from the front. `v3.py` part 1: the address that signed in just before the flood keeps `addr 4` (it was 0 at `b020647`). `lru_probe.py` A: an account last hit before the flood is evicted, and an account hit during the flood keeps its recent hits, as LRU should behave. For `unknown_failures`, `evict_live=False` is set on the module object, and `lru_probe.py` B uses that real object with `MAX_KEYS` scaled to 100: after 500 other keys, the target keeps 9 failures, and the 10th reaches the lock threshold. So under a flood, unknown emails lock at the same count as real ones (M1 acceptance 3). `v3.py` part 2 uses its own default window, so it still prints 0; the author said so, and that is expected. B2: expired entries are still dropped at the sweep (501 keys down to 1). |
| N4 test | meaningful | `mutant.py`: without the move to the end, the steps of `test_recently_hit_keys_survive_the_sweep` leave the victim at 0, so the test would fail on the `b020647` code. `test_unknown_account_failures_are_never_evicted_while_live` asserts the flag on the real object and the behaviour on a standalone window. Nothing drives `unknown_failures` through `login()`, but the call site (`services.py:480`) uses only `hit` and `reset`, which `lru_probe.py` B covers. |
| N5 | fixed | The CHANGELOG now says "at most once per counter window, least recently used first (the unknown-account lockout counter never drops live entries)", which matches `_sweep` and the constructor argument. |

### Regression checks
- **N1 and N2 stay fixed.** `count`, `retry_after` and `refund` neither create nor reorder entries; only `hit` reorders, and only admitted requests call it (`_check`, `services.py:237-247`). `v2.py`: 60,000 refused requests from one address leave 30 `all_attempts` keys; a client retrying correct sign-ins twice a second is refused 140 of 180, as at re-verification 2. `v3.py`: 60,000 admitted requests from 2,000 addresses cost 0.012 ms each with 57,000 keys, 0.011 ms after.
- **Bursts.** `v3.py`: of 50 concurrent coroutines on one account, 5 are admitted. The move adds no `await`.
- **Exact refunds.** `v2.py` 1a and 1b are unchanged (29 to 29; 5 s age). `lru_probe.py` E: after reordering, `forgive` removes exactly its own entry (count 1), and the key stays at the end.
- **Cost of `pop` and re-insert.** Amortised O(1). With `evict_live=False` and 200,000 live keys, the once-per-window sweep took 12.3 ms, and 1,000 hits after it took 0.17 ms in total (`lru_probe.py` C). A sweep that cannot evict reruns only after another full window, so it cannot become the per-request scan of N1.
- **`alt2.py`:** "failures admitted 20 blocked at request 40 ip count 20" and "own-account failures admitted 5", unchanged.

### New findings
| # | Severity | Location | Description and failure scenario | Fix |
| --- | --- | --- | --- | --- |
| C1 | info | `api/src/regwatch/identity/services.py:240-243`, `:129-136` | **A refused attempt does not refresh its key, so the key an attacker is being held at is the least recently used one.** Since N1 and N2, a refused request touches no counter, so it also does not move the key. `lru_probe.py` A2 (`MAX_KEYS` 100): an attacker at the 5-a-minute limit on a target account, refused while a flood of other keys runs, was admitted 5 more times when the sweep evicted the target's counter (295 of 300 refused, not 300). At the real cap this needs more than 45,000 live keys in one 60 s window, i.e. about 750 admitted sign-ins a second, each with an Argon2 verify. This host manages 11 dummy verifies a second (`lru_probe.py` D). The gain is at most 5 extra guesses per window, and the database lockout (10 in 15 minutes) still caps guesses per real account. Unknown emails are not affected (`evict_live=False`). | Optional: when `_check` refuses on a key that exists, move that key to the end (`window._hits[key] = window._hits.pop(key)` after the `count`). This creates no entry, so N1 stays fixed. Add a unit test that a refused key survives a sweep. Or accept this, and record in BL-84 that LRU eviction resets counters that are only being refused. |
| C2 | info | `api/src/regwatch/identity/services.py:197`, `:117-127`, `:174-178` | **`unknown_failures` memory is now bounded only by the admitted rate, and `LockTable` has the per-call rebuild N1 removed from `SlidingWindow`.** With `evict_live=False`, live entries are kept above `MAX_KEYS`. An entry costs about 930 bytes (`lru_probe.py` C: 177.8 MiB for 200,000). Expired entries wait for the next sweep, at most 900 s, so the bound is about 1,800 s times the rate of admitted unknown-email failures. Each such failure costs a dummy Argon2 verify and an audit-row commit. At this host's 11 a second, that is about 20,000 entries, or 18 MiB; on a large host doing 200 a second, about 335 MiB per API process. Separately, and unchanged by this commit, `LockTable.lock` rebuilds its whole dictionary on every call once more than 50,000 locks are live. That needs about 280 unknown-email failures a second sustained for 30 minutes, so it cannot be reached at Argon2 rates on the current hardware. | Record the bound with BL-65 and BL-84: the counters are sized by Argon2 throughput, not by `MAX_KEYS`. If larger hosts are planned, add a hard ceiling, for example 4 × `MAX_KEYS`, above which new unknown-email counters are refused with the same 429 as the address limit; this keeps unknown and real emails alike, since both are refused. Make `LockTable` prune at most once per interval, as `SlidingWindow` does. |

### Sign-off (Part C)
**Given.** N4 and N5 are verified fixed, and the new tests detect the original bug. N1 to N3 and findings 1 to 6 of `M1-login-rate-review.md` are unaffected. C1 and C2 are info-level and can go to BL-84. The condition the earlier sign-off set for N4 ("fixed, or recorded in BL-84 with the owner's decision, before the API is exposed externally") is met. No critical, high, medium or low findings are open for the login limiter.

---

## Overall sign-off
**Given, with two conditions before the external audience is admitted (M10).** No critical, high or medium findings in any part.
- A1 (low): the owner decides whether `required_markings` and the existing legal text are public, and code or wording is brought in line.
- B1 (low): the audit export writes an `audit.export` row through a server-side export, or the deviation from 8.2 is recorded with the owner's acceptance.

Info findings A2, B2 to B5, C1 and C2 are proposals for BACKLOG (BL-76, BL-84, M6 exports). · G1 addendum independent review · 2026-11-16

## Evidence
- `/tmp/g1addendum/csv_probe.mjs` (Node 20.20.2), abridged:
  - `"=1+1" -> "'=1+1"`, `"-1-1" -> "'-1-1"`, `-5 -> "'-5"`;
  - `" =1+1"`, `"\n=1+1"`, `"＝1+1"`, `"＋1"` unchanged;
  - `"a\"b\r\nc" -> "a""b\r\nc"` inside quotes.
- `/tmp/g1addendum/lru_probe.py`:
  - `A idle account after flood 0 | busy account 2 | keys 395`
  - `A2 target count 5 target attempts refused during flood 295 of 300`
  - `B unknown target after flood 9 keys 501 10th failure locks: True`
  - `B2 after expiry sweep keys 1`
  - `C 200000 live entries: 177.8 MiB, 932 B/entry`
  - `C sweep over 200001 live keys: 12.3 ms once; next hit 0.172 ms per 1000 hits`
  - `D dummy verifies per second on this host: 11; entries live 900 s -> at most ~20245 (window plus one sweep interval), about 18 MiB`
  - `E address count after refund 1 order last True`
- `/tmp/g1addendum/mutant.py`: `without move-to-end: victim 0 (test expects 2)`.
- `/tmp/rlpoc/v2.py`:
  - `poc1a before/after 29 29`
  - `poc1b remaining ages [5.0]`
  - `user with 5 typos + 15 retries recovers after 61s`
  - `2/s successful-retry client: rejected 140 of 180`
  - `60000 req one address: rejected 59970, all_attempts live keys 30`
  - The `address_key` lines are unchanged.
- `/tmp/rlpoc/alt2.py`: `failures admitted 20 blocked at request 40 ip count 20`, `own-account failures admitted 5`.
- `/tmp/rlpoc/v3.py`:
  - `victim failures 4`, then `live keys 111 victim failures after flood 0`
  - `victim (recently hit address) after flood 0 addr 4`
  - `unknown target failures after flood 0` (standalone default window; see N4)
  - `60000 admitted from 2000 addresses: 0.012 ms/req avg, login_attempts keys 56999`
  - `after: 0.011 ms/req, keys 57999`
  - `burst admitted 5 of 50`
  - `lookups create keys: 0`
- Tests:
  - `uv run pytest -q tests/unit/test_auth_gate.py`: 30 passed.
  - `tests/unit/test_auth_gate.py` with `tests/unit/test_contract_routes.py`: 39 passed.
  - `uv run pytest -q tests/unit`: 537 passed.
  - Web Vitest and database integration tests: not run (Node 22 and the test database are only in Docker, which was out of bounds).
- Part A and the rest of Part B: from reading the code. The use-testing record `docs/evidence/phase-1/use-testing/M1.md` (R2-M1-11, R2-M1-S3) confirms that the markings ("ACME INTERNAL") are shown on the signed-out `/legal`.

## Re-verification (G1 addendum independent review, 2026-11-16)
Against two branches:
- `sec/G1-addendum-followups` at `7960723`, where `16c75b1` holds the code and `7960723` lists this record in the gate review;
- `feat/M1-audit-export` at `35c8d47` (CP-10), which is stacked on it.

**Method.**
- Read both diffs in full, and the code they touch at `35c8d47`: `admin/audit_export.py`, `admin/services.py:333-348` (`export_audit`) and `:350` (`list_audit`), `admin/router.py:183-211`, `web/src/features/audit/export.ts`, `AuditPage.tsx`, `features/branding/api.ts` and `BrandingPage.tsx`, and `openapi/regwatch.v1.yaml`. Also read code the change relies on but does not alter: `identity/permissions.py` (`authorize`), `core/security.py:88-93` (`origin_allowed`), `identity/services.py` (`set_session_cookie`), and the `audit_log` indexes in `alembic/versions/0001_baseline.sql`.
- Added these PoCs:
  - `/tmp/g1addendum/export_probe.py`: event-loop time and memory of `to_csv`, plus formula and encoding cases, run against the real module;
  - `/tmp/g1addendum/export_gate.py`: an anonymous call through the real app.
- Tests on `feat/M1-audit-export`:
  - `uv run pytest -q tests/unit/test_audit_export.py tests/unit/test_contract_routes.py`: 22 passed;
  - `uv run pytest -q tests/unit`: 551 passed.
  - The two new integration tests (`test_audit_export_is_csv_and_is_itself_audited`, `test_audit_export_needs_audit_read`) and the web tests were read but not run (they need the test database and Node 22, which run only in Docker).
- The working tree is `feat/M1-audit-export`. Only this record was changed, and it is not committed.

### Verdicts
| # | Verdict | Evidence |
| --- | --- | --- |
| A1 | fixed | The owner accepted public markings on 2026-11-16 (BL-86 (d)). The editor now labels the field "Required markings (report and email footers, and shown publicly on the legal page)" (`BrandingPage.tsx:276-279`). The test docstring and the CHANGELOG now say the markings are public with `/legal`. The CP-08 statement that company details stay private is still true: `GET /branding/public` is unchanged. Two small points remain, and neither blocks: the page-text field itself still gives no hint that the page is public, and no test asserts what the anonymous `GET /legal` returns for the markings. |
| A2 | fixed for caching; rate limit deferred | `GET /branding/public` and `GET /legal` send `Cache-Control: public, max-age=60` (`router.py`, `PUBLIC_CACHE`), and the integration test asserts it for `/branding/public`. `public` is correct: both answers are the same for every caller, and `authorize` never reads the cookie on these routes. Problem responses carry no cache header, so errors are not cached. The proxy rate limit is BL-86 (b), for M10, which I accept. There is a side effect; see R4. |
| B1 | fixed, as CP-10 | `GET /admin/audit/export` writes an `audit.export` row (actor, client IP, request id, the filters that were set, `rows`, `total`, `truncated`). It commits that row before the response is returned, so no CSV leaves the server unrecorded. A failed commit gives a 500 with no body, which fails closed. The web client now downloads from this route, and the browser-built CSV is gone. The new route raises R1 to R3 below. |
| B2 | partly; see R1 | The 20 MB cap bounds the file. It does not bound server memory, because all 10,000 rows are loaded first. |
| B3 | fixed | On `sec/G1-addendum-followups`, the client export pins `to` at the start and exports `id`. On `feat/M1-audit-export` that code is replaced. The server reads the rows in a single `SELECT`, so pages can no longer shift, and `id` is the first column. The file now ends with a truncation line. One small gap remains; see R5. |
| B4 | fixed | Server `_FORMULA` (`audit_export.py:24`) is `^\s*[=+\-@＝＋－＠]|^[\t\r\n]`. Python's `\s` is Unicode-aware here, so a leading NBSP or ideographic space before `=` is defused too (probe). The client regex on `sec/G1-addendum-followups` is equivalent. Not covered: U+FE66 `﹦`, and a BOM or zero-width space before `=`. No column can start with these today (Part B, B4), so this needs nothing now. |

### Review of `GET /admin/audit/export` (7.5 surface)
| # | Severity | Location | Description and failure scenario | Fix |
| --- | --- | --- | --- | --- |
| R1 | low | `api/src/regwatch/admin/services.py:339-340`, `:350-390`; `audit_export.py:41-54` | **All 10,000 rows, with full `before` and `after`, are loaded before the 20 MB cap applies.** `export_audit` calls `list_audit(db, 1, MAX_ROWS)`. This keeps 10,000 ORM rows and 10,000 `AuditEntry` copies of their JSON, and `to_csv` then makes a third copy per row (`model_dump`) before it checks the size. Measured with `export_probe.py`: 100 entries holding a 200,000-character `before` and `after` take 38 MiB as `AuditEntry` objects alone, and 97 MiB at peak in `to_csv`. Only 34 of them fit under the cap. At 10,000 such rows, the entries alone come to about 3.7 GiB, before the ORM objects and the asyncpg decode. Any `settings.manage` holder can create such rows quickly. `PUT /admin/settings/{key}` accepts up to 200,000 characters for every string setting, and only `legal.page_markdown` has a render budget, so each save writes one row with both values. **Scenario:** a malicious or compromised admin saves a few thousand large string settings, then runs one export (an admin holds `audit.read`). Alternatively, any `audit.read` user runs it later, or a third party triggers it through R2. The single API process runs out of memory, and every user loses the service. With typical rows (about 0.5 KB), 10,000 rows produce 6.3 MiB of CSV, and memory is not a concern. | Read in batches, for example 200 rows at a time with keyset pagination on (`occurred_at`, `id`), or `stream_scalars` with `yield_per`. Append each batch to the CSV and stop as soon as `MAX_BYTES` or `MAX_ROWS` is reached; then write the audit row and return. Buffering at most 20 MB plus one batch keeps the audit-before-body order. Add a unit test where the size cap stops the read, not only the formatting. |
| R2 | low | `api/src/regwatch/admin/router.py:190-211`; `core/security.py:88-93`; `identity/services.py:411-414` | **The export is a GET with a side effect, so another site can trigger it.** The session cookie is `SameSite=Lax`, which is sent on top-level cross-site GET navigations. The CSRF check (`origin_allowed`) applies only to unsafe methods. A link, redirect or `window.location` on any site therefore makes a signed-in auditor's browser run the export with filters the attacker chooses. That writes an `audit.export` row under the auditor's name, and the CSV is saved to their downloads (`Content-Disposition: attachment`). The attacker cannot read the file, so nothing leaks. But the audit trail now holds export records nobody intended, which matters for an evidence trail, and the attacker can make the auditor's session run exports repeatedly, including the expensive ones in R1 and R3. This is the first GET route in the API with a side effect, which is why the app-wide check does not cover it. | Refuse the export unless the request is same-origin: reject `Sec-Fetch-Site` other than `same-origin` (and `Sec-Fetch-Mode: navigate`), or require a custom header that the web client sends and a navigation cannot (for example `X-Regwatch-Export: 1`). Alternatively, make it `POST /admin/audit/exports`, which the gate already checks for `Origin`; that needs a CP update. Add an integration test that a cross-site navigation-style request gets 403 and writes no row. |
| R3 | info | `admin/services.py:339-340`; `audit_export.py:41-54` | **One `audit.read` caller can make exports expensive, and the work runs on the event loop.** For a typical 10,000-row export, `to_csv` alone held the loop for 125 ms, and building the 10,000 entries in `list_audit` adds more synchronous time. A filter on `action` or `actor` has no index (only `ix_audit_time` and `ix_audit_entity` exist), so each export also scans the table and counts it. There is no limit on exports per user, nor on concurrent exports. 8.2 sets "outputs 20 per hour per user". A client that loops on exports, from several tabs or through R2, adds latency for every user of the single API process. | Apply 8.2's output limit to this route: 20 an hour per user, and one at a time per user, refused with 429. Run `to_csv` (or the batched builder from R1) in `asyncio.to_thread`. Consider an index on `(action, occurred_at)` when M10 sizes the audit table. |
| R4 | info | `web/src/features/branding/api.ts:36-46`; `router.py` `PUBLIC_CACHE` | **The 60-second cache makes the legal editor's preview stale after a save.** After `PUT /admin/legal`, the web invalidates `["branding", …]`, but the refetch goes through `fetch` with the default cache mode, so the browser can answer `GET /legal` from its HTTP cache for up to 60 s. The editor then shows the new Markdown next to the old rendered preview. For the A1 workflow, this matters: an owner who removes text from the public page sees it still there and may save again or think the save failed. `/branding/public` behaves the same after a branding change. A replaced page also stays in browsers for up to 60 s, which was accepted with A2. | Fetch `GET /legal` and `GET /branding/public` with `cache: "no-cache"` from the signed-in screens, or invalidate with a cache-busting query. Alternatively, serve `no-cache` with an `ETag` (content hash), which is still cheap with a 304. |
| R5 | info | `admin/services.py:339-341`, `:368` | **`total` and the rows come from two statements.** `list_audit` counts, then selects, each in its own snapshot under READ COMMITTED. A row written in between makes `total` disagree with the rows by one or more. The export's own row is written after both, so it is not affected. `truncated` can then be reported as true for a complete file, or the audit row can record a `total` smaller than `rows`. This is cosmetic, but the row is evidence. | Pin `to` to the request time on the server when the caller gives none (the web no longer sends it on this branch), or run both statements in one `REPEATABLE READ` transaction. Derive `truncated` from fetching `MAX_ROWS + 1` rows. |

### Checked and fine
1. **Permission gate.** `spec(perm="audit.read")` puts `x-permission: audit.read` on the route, and the contract matches (`test_contract_routes` passes). The app-wide `authorize` denies by default: an anonymous call through the real app gets 401 (`export_gate.py`), a signed-in `viewer` gets 403 (integration test, read), and a temporary-password session gets 403. `CurrentPrincipal` supplies the actor for the audit row from the session, never from the request.
2. **Audit row content.** It records only the filters that were set, as strings, along with `rows`, `total`, `truncated`, the actor, the IP taken with the trusted-proxy rule, and the request id. That is enough to answer who exported what and when. Query strings are bounded by the server's header-size limit, so a filter value cannot make the row large. The row is written after the read, so it is not in its own export, and it is committed before the body is sent.
3. **CSV encoding.** Every field is quoted with `"` doubled, and records end in CRLF. Embedded CR and LF stay inside the quotes (`'a"b\r\nc'` gives `"a""b\r\nc"`). JSON is compact with `ensure_ascii=False`, and the body is encoded as UTF-8 under `text/csv; charset=utf-8`. Values that are neither strings nor JSON become `str()` (`5`; `-5` is defused). UUIDs and datetimes arrive as strings from `model_dump(mode="json")`. The size check counts UTF-8 bytes, and the unit test shows the file stays at or under the cap.
4. **Headers.** `X-Export-Rows` and `X-Export-Truncated` hold only a count and a boolean that the body already shows. `Content-Disposition` is a fixed name with no caller input, so header injection is not possible. `Cache-Control: no-store` keeps browsers and the proxy from storing the file, as the session-bearing auth routes already do. These are same-origin responses, so the custom headers need no CORS exposure.
5. **Web client.** `exportAudit` sends the applied filters through the typed client with same-origin credentials, takes the body as a `Blob`, and saves it from a `blob:` URL that is revoked after 10 s. Peak tab memory is about the file size (20 MB or less). The truncation notice now comes from the server's header.
6. **The client-side follow-ups on `sec/G1-addendum-followups`**, for the period before CP-10 merges: `to` is pinned (the web test asserts it on every page), `id` is exported, and the wider defusal is tested with `\nx`, `  =1` and `＝1`.

### Sign-off
**Given.** The two conditions of the first sign-off are met:
- A1: the owner decided the markings are public, and the editor, test and CHANGELOG say so.
- B1: the export is server-side and writes an `audit.export` row before the body is sent.

A2, B3 and B4 are fixed; B2 is covered by R1, and A2's proxy rate limit is BL-86 (b). No critical, high or medium findings are open.
- **Recommended before the external audience (M10):** the two low findings on the new route. R1: read in batches and stop at the size cap, so one export cannot exhaust the API's memory. R2: refuse cross-site requests to the export.
- **Proposals for BL-86:** R3 to R5 (info).

· G1 addendum independent review · 2026-11-16

### Evidence
- `/tmp/g1addendum/export_probe.py`, run against `35c8d47`:
  - `typical 10000 rows: to_csv 125 ms on the loop, 6.3 MiB, rows 10000, cut False`
  - `100 large rows: entries 38 MiB, peak with to_csv 97 MiB, 106 ms, rows written 34, cut True, csv 19.5 MiB`
  - `-> 10,000 such rows held before the cap: about 3.7 GiB of entries alone`
  - Defused: `'=1'`, `'  =1'`, `'　=1'`, `'\xa0=1'`, `'\n=1'`, `'＝1'`, `'-'`, and `-5` becomes `'-5`.
  - Not defused: `'﻿=1'`, `'​=1'`, `'﹦1'`.
  - `'a"b\r\nc' -> '"a""b\r\nc"'`; `True -> "True"`.
- `/tmp/g1addendum/export_gate.py`: `anonymous: 401 application/problem+json` for `GET /api/v1/admin/audit/export`.
- Tests: `tests/unit/test_audit_export.py` with `tests/unit/test_contract_routes.py`, 22 passed; `tests/unit`, 551 passed.
- R2 and R4: from reading the code (`samesite="lax"` at `identity/services.py:413`; `origin_allowed` returns `True` for GET; the default `fetch` cache mode in `lib/api/client.ts`). They were not run in a browser, since none is available on the host.

## Author follow-up (`sec/M1-audit-export-followups`, pending re-verification)
- **R1 (low):** the export reads in keyset-paged batches of `EXPORT_BATCH` (100) through `CsvBuilder` and stops at the row or size cap, so memory is bounded by one batch plus the 20 MB file. The event loop yields between batches. Test: `test_audit_export_reads_in_batches`, with a batch of 2, checks that every matching row is exported once.
- **R2 (low):** the route refuses a request whose `Sec-Fetch-Site` is anything but `same-origin` or `none` (a typed URL) with 403 `cross-site`. Clients that send no such header (curl, tests) are treated as same-origin. Test: `test_audit_export_refuses_cross_site_requests`.
- **R3 (info):** the per-user export limit and the indexes on `audit_log.action` and `actor_user_id` are BL-86 (e).
- **R4 (info):** the legal editor's query sends `cache: "no-cache"`, so its preview revalidates instead of using the 60-second public cache.
- **R5 (info):** the audit row no longer records `total`, which came from a second query. It records the rows written and whether a cap was reached.


## Re-verification 2 (G1 addendum independent review, 2026-11-16)
Against `sec/M1-audit-export-followups` at `1c1174b` (diff `f995584..1c1174b`, 8 files).

**Method.**
- Read the whole diff and the resulting code:
  - `admin/services.py:333-407` (`_audit_conds`, `_audit_entry`, `_audit_select`, `export_audit`, `list_audit`);
  - `admin/audit_export.py` (`CsvBuilder`);
  - `admin/router.py:190-216`;
  - `web/src/features/branding/api.ts:28-36`;
  - the `audit_log` table in `alembic/versions/0001_baseline.sql:318-328`.
- Re-ran `/tmp/g1addendum/export_probe.py` unchanged. It exercises `to_csv`, which is kept as a wrapper around `CsvBuilder`.
- Added these probes in `/tmp/g1addendum/`:
  - `export_probe2.py`: copies `export_audit`'s loop (batches of `services.EXPORT_BATCH` entries fed to `CsvBuilder`) and measures peak memory and time spent on the loop;
  - `keyset_probe.py`: the SQL the keyset step emits for PostgreSQL, and the paging logic on 1,000 rows with only 3 distinct timestamps;
  - `nocache_probe.mjs`: whether openapi-fetch 0.17.0, as the web client uses it, carries `cache: "no-cache"` into the `Request` that the app's custom `fetch` receives.
- Tests: `uv run pytest -q tests/unit` 551 passed, and `export_gate.py` still gives an anonymous 401. I read the two new integration tests but did not run them, since the test database runs only in Docker. There is no browser on the host.
- Only this record was changed, and it is not committed.

### Correction to re-verification 1
In the B3 verdict I wrote "The file now ends with a truncation line." That is wrong. The module docstring of `audit_export.py` says the export "says so in its last line", but neither `to_csv` nor `CsvBuilder` writes such a line. Truncation is carried only by `X-Export-Truncated`, the on-screen notice and the `audit.export` row, so a saved file still does not say it was cut. See S4.

### Verdicts
| # | Verdict | Evidence |
| --- | --- | --- |
| R1 | fixed | `export_audit` reads keyset batches of 100 (`services.py:393-404`), adds each row to `CsvBuilder`, and stops at the first row that does not fit. It holds one batch at a time; the `AuditLog` objects are not modified, so the session's identity map keeps them only weakly. `export_probe2.py`, rows with a 200,000-character `before` and `after`: peak 59 MiB at 34 rows and 19.5 MiB of CSV, where loading all 10,000 had come to about 3.7 GiB. Typical rows: peak 19 MiB for 10,000 rows and 6.3 MiB of CSV. tracemalloc does not count the driver's and ORM's copy of the current batch, which is up to about 100 × 2 × 0.4 MB of JSON text, so the real peak is about 100 to 200 MB. Concurrent exports each add that, and there is no per-user limit yet (R3). |
| R2 | fixed for browsers that send Fetch Metadata | The route refuses `Sec-Fetch-Site` values other than `same-origin` or `none` with 403 before `export_audit` runs (`router.py:204-205`). A refused request therefore writes no row and reads nothing. The anonymous gate still answers first (401). Current Chromium, Firefox and Safari 16.4 or later mark a cross-site link, redirect, form or `window.location` as `cross-site`. Sibling-subdomain sites are `same-site`, which is also refused. `none` means the user typed, pasted or bookmarked the URL, which a third-party page cannot produce. If the header is absent, the request is treated as same-origin; see S2. |
| R3 | properly deferred | BL-86 (e) holds the per-user export limit (8.2: 20 outputs an hour per user) and the indexes on `audit_log.action` and `actor_user_id`. In part, the loop now yields between batches (`asyncio.sleep(0)`, plus the awaits on each batch query). The longest synchronous stretch per batch was 21 ms for typical rows and 110 ms for the largest, against about 250 ms for one whole export before. Moving the work to `asyncio.to_thread` is not listed. With the yielding batches, that is no longer needed. |
| R4 | fixed | `legalQuery` passes `{ cache: "no-cache" }`. In openapi-fetch 0.17.0 this lands in `requestInit` and then in the `Request` handed to the app's `fetch(request)`: `nocache_probe.mjs` shows `no-cache` with the option and `default` without it. A `no-cache` request is never answered from the HTTP cache without revalidation. So after a save, the editor's preview shows the new page. See S3 for the side effect on the public page. |
| R5 | fixed | The export no longer calls `list_audit`, so there is no second statement, and the row records only `rows` and `truncated`. `truncated` is now exact. It is set only when a row exists beyond a cap. `export_probe2.py` confirms both cases: exactly 10,000 rows with a further batch empty gives `false`; 10,001 rows gives `true` (rows 10,000). The oversized case gives `true` at 34 rows. |

### Regression checks
- **Keyset with equal `occurred_at`:**
  - `occurred_at` is `now()`, the transaction start time, so all rows from one transaction share it (a taxonomy import, for example), and `id` (`uuidv7()`, the primary key) breaks the tie.
  - The emitted SQL is `(audit_log.occurred_at, audit_log.id) < (:ts, :id::UUID) ORDER BY occurred_at DESC, id DESC LIMIT 100`. Row comparison in PostgreSQL is lexicographic and matches the sort order, so no row is skipped or repeated at a tie.
  - `keyset_probe.py`: 1,000 rows over 3 timestamps, batches of 7, all 1,000 rows exported once in sort order.
  - `last` is the last row added, and the timestamps keep microseconds both ways through asyncpg, so equality holds exactly.
  - Rows committed during the export carry later timestamps and are excluded, apart from S1's edge case.
- **`Sec-Fetch-Site` and clients without it:**
  - Non-browser clients (curl, scripts, the tests) send no header and are allowed. That is correct, because CSRF needs a victim's browser, and such a client must hold a session and `audit.read` anyway.
  - The weak spot is browsers that do not send Fetch Metadata, such as Safari before 16.4. For them the R2 attack still works (S2).
  - Header case does not matter, since Starlette's lookup ignores it.
  - The check comes after the gate, so it reveals nothing to anonymous callers.
- **`cache: "no-cache"` honoured:** yes, as shown under R4. No other query got the option. `publicBrandingQuery` keeps the 60 s cache, which is fine, because the signed-in screens use `GET /branding`, which is not cached.
- **Still in place:** `Cache-Control: no-store` and the fixed `Content-Disposition` on the export; the audit row is still committed before the body is returned; `list_audit` behaves as before and now shares `_audit_conds` and `_audit_select` with the export.

### New findings
| # | Severity | Location | Description and failure scenario | Fix |
| --- | --- | --- | --- | --- |
| S1 | info | `api/src/regwatch/admin/services.py:394-397`; `alembic/versions/0001_baseline.sql:327` | **The keyset step may not use an index, so each batch can rescan the rows already exported.** The only time index is `ix_audit_time (occurred_at DESC)`. PostgreSQL can use a row comparison `(occurred_at, id) < (…)` as an index condition only on a composite B-tree with those columns. Otherwise it may walk `ix_audit_time` from the newest row and filter, re-reading every row of earlier batches for each new batch. For 100 batches that is about 500,000 row visits instead of 10,000. This comes from planner behaviour and was not measured: there is no PostgreSQL outside Docker here. A separate edge case: a row whose transaction began before the export and committed during it has an older `occurred_at`, so it can appear even though it was not visible when the export started. That is harmless. | Add the redundant `AuditLog.occurred_at <= last[0]` next to the row comparison, so `ix_audit_time` bounds each batch. Add `(occurred_at DESC, id DESC)` to BL-86 (e)'s index work. Check with `EXPLAIN` on the test database. |
| S2 | info | `api/src/regwatch/admin/router.py:204` | **Without `Sec-Fetch-Site`, a request counts as same-origin.** Browsers that do not send Fetch Metadata (Safari before 16.4, older embedded views) are still open to the cross-site export of R2, and so is any future fetch path that strips the header. Impact is as before: rows written under the victim's name and a forced download, no data to the attacker. | Optional, for every browser: the web client sends a custom header on this request only (for example `X-Regwatch-Export: 1`), and the route requires it. A navigation cannot set headers, and a cross-origin `fetch` with a custom header needs a CORS preflight, which the API does not grant. Then keep the `Sec-Fetch-Site` rule as a second layer. |
| S3 | info | `web/src/features/branding/api.ts:32`; `LegalPage.tsx:10` | **`no-cache` also applies to the public `/legal` page, so A2's browser cache no longer helps there.** `legalQuery` is shared by the editor and the public page. The responses carry no `ETag` or `Last-Modified`, so every revalidation is a full download of the page, up to about 1.7 MB. Anonymous load on `/legal` is now the same as before A2. A2 still helps `/branding/public`, and the real control on the public routes remains BL-86 (b). | Use `no-cache` only in the editor (a separate query or option), or add an `ETag` (hash of the rendered HTML) to `GET /legal` so revalidation is a cheap 304. |
| S4 | info | `api/src/regwatch/admin/audit_export.py:6-7`, `:41-66` | **The docstring promises a truncation line that the code does not write** (see the correction above). The saved file does not say it was cut or by which cap, which is the file-level half of B3. | Either append a final line such as `"# truncated at 10,000 rows or 20 MB; narrow the filters"`, with a test, or drop the sentence from the docstring. |
| S5 | info | `api/tests/integration/test_admin.py:458-482` | **The batch test does not exercise ties.** Its five rows come from five separate requests and so carry five different `now()` values. A tie-breaking bug would pass it. The cross-site test does not check that a refused export writes no row. | Write rows in one transaction (a taxonomy import with several terms) and export with `EXPORT_BATCH` 2. In the cross-site test, assert that the `audit.export` count is unchanged after the 403s. |

### Sign-off
**Given.** R1 and R2 are fixed. R2's protection covers browsers that send Fetch Metadata. R4 and R5 are fixed, and R3 is properly deferred as BL-86 (e). No critical, high, medium or low findings are open in this record. S1 to S5 are info-level proposals for BL-86. For S1, check with `EXPLAIN` before M10 sizes the audit table. S2's custom header is optional hardening for older browsers. The earlier conditions (A1, B1, R1, R2) are all met, so nothing in this record blocks admitting the external audience. · G1 addendum independent review · 2026-11-16

### Evidence
- `/tmp/g1addendum/export_probe2.py` (at `1c1174b`, `EXPORT_BATCH 100`, `MAX_BYTES 20971520`):
  - `typical 10000: rows 10000, full False, csv 6.3 MiB, peak 19 MiB, total 1.39 s, worst batch on loop 21 ms`
  - `large (2 x 200,000 chars): rows 34, full True, csv 19.5 MiB, peak 59 MiB, total 0.13 s, worst batch on loop 110 ms`
  - `10001 typical (cap by rows): rows 10000, full True, csv 6.3 MiB, peak 19 MiB, total 1.32 s, worst batch on loop 20 ms`
- `/tmp/g1addendum/export_probe.py`, re-run: the output is unchanged (`to_csv` 126 ms; 100 large rows, peak 97 MiB, all held at once). It shows the cost of the whole-list path that `to_csv` keeps for tests; the route no longer uses it.
- `/tmp/g1addendum/keyset_probe.py`:
  - SQL: `WHERE audit_log.entity_type = … AND (audit_log.occurred_at, audit_log.id) < (…, …::UUID) ORDER BY audit_log.occurred_at DESC, audit_log.id DESC LIMIT …`
  - Paging: `rows 1000 exported 1000 unique 1000 same order True`
- `/tmp/g1addendum/nocache_probe.mjs` (Node 20, openapi-fetch 0.17.0 from `web/node_modules`): `with option: no-cache same-origin`, `without option: default`.
- `/tmp/g1addendum/export_gate.py`: `anonymous: 401 application/problem+json`.
- Tests: `tests/unit`, 551 passed. The integration tests `test_audit_export_refuses_cross_site_requests` and `test_audit_export_reads_in_batches` were read, not run (the test database runs only in Docker).
