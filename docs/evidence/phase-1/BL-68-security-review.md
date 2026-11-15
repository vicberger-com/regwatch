# Security review record: BL-68 logo upload, public logo route, rendered legal page and branding UI (M1)

**Scope (PRs, routes, tasks):** `feat/M1-legal` (`5f523bc`), `feat/M1-logo` (`87f56fd`), `feat/M1-logo-upload` (`51e3517`), `feat/M1-web-branding` (`1d2a372`), `feat/M1-web-legal-editor` (`c1afa75`), `feat/M1-web-shell-branding` (`75fd9c3`). Commit range `d400ea6..feat/M1-web-shell-branding` = `d400ea6..75fd9c3` (6 commits, 31 files, +1617/-31). API: `GET /legal`, `POST /admin/branding/logo`, the new public `GET /branding/logo` (CP-07), `GET /branding` (`logo_url`); `api/src/regwatch/admin/legal.py`, `admin/logo.py`, `admin/router.py`, `admin/services.py`, `core/objectstore.py`; `openapi/regwatch.v1.yaml`. Web: `/admin/branding`, `/legal`, header, footer and sign-in logo (`web/src/features/branding/`, `web/src/app/BrandingShell.tsx`, `AppShell.tsx`, `router.tsx`, `features/auth/LoginPage.tsx`, `styles/tokens.css`). New dependencies: nh3 0.3.7, markdown-it-py 4.3.0 with mdurl 0.1.2, defusedxml 0.7.1, python-multipart 0.0.33. · **Reviewer session label:** BL-68 independent review · **Date:** 2026-11-15 · **Author sessions excluded from review:** yes

## Method
- Read the full diff and every new or changed source file at `75fd9c3`. Also read the unchanged code they rely on: `api/middleware.py` (`BodySizeLimitMiddleware`), `identity/permissions.py` (`authorize`), `core/security.py` (`origin_allowed`), `core/errors.py`, `core/settings.py`, `deploy/Caddyfile` and `deploy/compose.yaml`.
- **Legal renderer.** Ran `regwatch.admin.legal.render` (`cd api && uv run python -I`) on 35 hostile inputs:
  - raw HTML, SVG, MathML, `<form>` and `<style>`;
  - `javascript:` in upper case, entity-encoded, percent-encoded and with tab, newline or NUL inside;
  - `data:` and `vbscript:` links, and `file:` autolinks;
  - link reference definitions, including entity-encoded ones;
  - title-attribute breakout, protocol-relative and relative links;
  - image syntax, table alignment and `ol start`.
  It was also timed on 24 pathological 200 000-character inputs (the `LegalWrite` cap).
- **Logo check.** Ran `regwatch.admin.logo.check` on 50 crafted files:
  - namespace and prefix tricks and case variants;
  - `href` and `xlink:href` under other prefixes;
  - `url()` with CSS escapes and comments, `image-set()` and `@import`;
  - DOCTYPE, entities, XInclude and processing instructions;
  - UTF-16, ISO-8859-1 and EBCDIC encodings;
  - a PNG/HTML polyglot;
  - a 1 MB attribute, nesting 140 000 deep, and 40 000 namespace declarations;
  - a `<use>` amplification file.
  Peak memory was measured with `tracemalloc`.
- **Multipart parsing.** Exercised Starlette 1.10.0 with python-multipart 0.0.33 through a minimal FastAPI app. The app used the route's exact `request.form(max_files=1, max_fields=1)` code behind the real `BodySizeLimitMiddleware`, and was sent:
  - extra fields and extra files, a missing or misnamed part;
  - urlencoded and JSON bodies, and no boundary;
  - 1.5 MB and 3 MB bodies, with `Content-Length` and chunked;
  - 1.9 MB of part headers and 1.8 MB of preamble.
- **Object store.** Called `objectstore.put` on traversal, dot-segment, upper-case, backslash and NUL keys, and with a `branding` directory that is a symlink out of the store root.
- **Proxy headers.** Started a throwaway Caddy container from the image `deploy/compose.yaml` pins (`caddy:2@sha256:36c24ad9…`, v2.11.7), with `--network none`. It used the repository's `header` block in front of an upstream that sends the logo route's CSP. Then the same with a candidate fix. The dev stack was not used or contacted.
- **Licenses.** Read the nh3 wheel's `dist-info` (`licenses/`, `sboms/nh3.cyclonedx.json`), `api/THIRD_PARTY_NOTICES.md`, `docs/03-architecture.md` 3.5 and 3.6, and R-01 B1 to B7. No advisory database was queried, because there was no network.
- **Repository suites:** `make lint test-web` and `make test-api`, the latter on its own throwaway database. Results are under Evidence.
- **Not done:** no real browser was available on the host, so browser rendering claims (findings 2 and 3) come from the CSS and SVG specifications and are marked as such.

## Data flows touched
- **Owner Markdown to every signed-in user:** `PUT /admin/legal` or `PUT /admin/settings/legal.page_markdown` (settings.manage, at most 200 000 characters) is stored as a setting. `GET /legal` renders it with markdown-it-py and nh3 on each cache miss. The web client inserts the HTML with `dangerouslySetInnerHTML` on `/legal` and in the editor preview.
- **Uploaded file to the public:** `POST /admin/branding/logo` (settings.manage, Origin checked, 2 MiB body cap) goes through `logo.check` and is stored in the local object store under `branding/logo-<sha256>.<ext>`. `branding.logo_ref` points at it.
- **Store to anonymous visitors:** `GET /branding/logo` is unauthenticated. It reads `branding.logo_ref` from the database (never from the request) and returns the bytes through Caddy. It is shown by `<img>` on the sign-in page, in the header, and in the branding screen.
- **Setting to CSS:** `branding.primary_color` (hex pattern on the server, re-checked in the client) is set as `--brand-accent` on `<html>`. `general.site_title` becomes `document.title`.

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | Upload, legal and branding writes | Session gate, `settings.manage`, Origin required on POST and PUT | none found | none |
| Tampering | Logo file, legal HTML, accent colour | Allowlist SVG check that rejects rather than rewrites; markdown-it with raw HTML off, then nh3; hex pattern on both sides; object keys made by the server | The SVG `url()` filter is bypassable; a `<use>` amplification passes | 2, 3 |
| Repudiation | Logo and legal changes | Audit row (`branding.logo`, `setting.update`) with before and after values | Re-uploading the current logo writes no row, which is correct | none |
| Information disclosure | Public logo route | Serves only the selected logo; key from the database; problem 404 | none beyond the logo, which is public by design | none |
| Denial of service | Legal render, SVG parse, public route | 200 000-character cap; 1 MB and 5 000-element cap; 2 MiB body cap; `lru_cache` | Quadratic Markdown input blocks a worker for about 12 s; parse memory is about 40 times the input | 4, 5 |
| Elevation of privilege | Logo shown to every visitor | Logo shown only through `<img>`; the route's own CSP with `sandbox`; nosniff | The proxy replaces the route's CSP, so an SVG opened directly runs as a document under the site CSP | 1 |

## Checklist
- [x] Input validation on every field: hex colour (`BrandingWrite.primary_color`, also on the generic settings route through `_DEDICATED`); legal caps; `branding.logo_ref` is refused on the settings API; the logo type comes from the content; one file part. Findings 2 and 3 are gaps in the SVG check.
- [x] Output encoding: the only markup sink is `LegalHtml`, fed by server-sanitized HTML; logo URLs are built on the server; everything else renders as React text.
- [x] Authentication and authorization: `POST /admin/branding/logo` has `x-permission: settings.manage`; `GET /branding/logo` is `security: []` in the contract and `public=True` in the route; `/legal` needs a session.
- [x] Session handling: unchanged.
- [x] Secrets not logged or committed: none in range.
- [x] Outbound requests: none added; the API fetches nothing.
- [ ] File and body size limits; content-type checks: limits hold (see Checked and fine); the route's CSP does not survive the proxy (finding 1).
- [x] Audit rows written: the logo change is audited with the old and new keys.
- [ ] Dependency, image and license scans: lint and tests clean; bundled-crate notices incomplete (finding 7); no advisory database was queried (no network).

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | medium | **The reverse proxy replaces the logo route's CSP** (`deploy/Caddyfile:9-19`; route headers at `api/src/regwatch/admin/router.py:53-59`). The `header` block deletes `Server` (`-Server`), and that makes Caddy defer every operation in the block to write time. Its `Content-Security-Policy` is a plain set, so it overwrites the upstream value. Through the proxy, `/api/v1/branding/logo` is served with the site CSP: no `sandbox`, `style-src 'unsafe-inline'`, `img-src 'self' data:`. The route's `default-src 'none'; style-src 'unsafe-inline'; sandbox` is lost. The design (`logo.py` docstring, CHANGELOG, CP-07) counts that CSP as one of two layers. The integration test checks it only on the ASGI app, never through the proxy. **Scenario:** someone (an anonymous visitor following a link, or an admin) opens the logo URL directly. The SVG is then a same-origin document with no sandbox. The SVG allowlist becomes the only control against script and markup on the application's origin. A bypass of the allowlist (now, or after a later widening such as adding `<a>` or `<image>`) runs with the user's session. Finding 2 already lets the file make same-origin requests in this mode. Production headers (M10) will start from this block. **Fix:** in the Caddyfile, set the site CSP only when the upstream has not set one (`?Content-Security-Policy "…"`). Alternatively, give `/api/v1/branding/logo` a matcher with its own header block. Carry the same rule into `compose.prod.yaml` (BL-76), and add a check that requests the logo through the proxy and asserts `sandbox`. | open | reviewer PoC C1 (Caddy v2.11.7, pinned digest) |
| 2 | low | **The SVG `url()` filter can be bypassed** (`api/src/regwatch/admin/logo.py:53-55`, `:121-124`). The check is a plain regex for `url(`. CSS decodes escapes in function names, so `\75 rl(` and `\75rl(` are `url(` to a browser (CSS Syntax 3, "consume an ident-like token"). Image functions that take a bare string, such as `image-set('…' 1x)` and `cross-fade()`, need no `url(` at all. All of these are accepted, in `style` and in presentation attributes (`fill`, `mask`, `clip-path`). Examples: `style="fill:\75 rl(https://tracker.example/p)"` and `style="mask-image:image-set('https://evil/a.png' 1x)"`. `@\69mport` also passes `_STYLE_DENY`, though `@import` has no effect in a `style` attribute. **Scenario:** inside `<img>` nothing loads, because SVG used as an image loads no external resources, so today's screens are safe. Opened directly (finding 1), the file can request any same-origin URL with the user's cookies, which the site CSP `img-src 'self'` allows. Once the route's CSP is restored, it can request nothing. The bigger exposure is later reuse. M7 reports and M8 emails are to use the same logo (BL-68 remaining), and an inline SVG in a report rendered by Gotenberg, or in an HTML email, would load external URLs. That gives a tracking beacon on every report or email, or a request from the renderer. The code comment says "`url(...)` in a value may only be `url(#id)`", and that is not true. **Fix:** drop `style` from `ATTRIBUTES`; presentation attributes cover what a logo needs. Refuse any value containing `\` or `/*`. Allow `(` only in `transform`, `d` and `points`, in colour functions (`rgb`, `rgba`, `hsl`, `hsla`), and in `url(#id)` with an id-only grammar. Add tests for the escaped and `image-set` forms. | open | reviewer PoC S1 (both forms accepted); browser behaviour from the CSS specification, not run in a browser |
| 3 | low | **A `<use>` amplification SVG passes the check** (`api/src/regwatch/admin/logo.py:35`, `:101-104`). `MAX_ELEMENTS` counts elements in the source, not the instances `<use>` creates. A 2 180-byte file with 12 nested groups of 10 `<use href="#previous">` (120 elements) references 10^11 path instances, and `check` returns `image/svg+xml`. **Scenario:** a `settings.manage` holder, or anyone holding that session, uploads it. The logo is rendered on the public sign-in page and in the header of every screen, so every visitor's browser has to expand the tree. Browsers' own limits on `use` instances differ by engine and version, and where they are weak, the tab hangs on sign-in. That locks everyone out of the UI, including the admin who would replace the logo; recovery needs the API. **Fix:** refuse a `<use>` (or a `pattern` or `mask` reference) that points to an element containing a `<use>`. Alternatively, compute the expanded instance count on the server and refuse above a small bound (for example 5 000 in total). Refuse `href` targets that do not exist. Add a test with the nested file. | open | reviewer PoC S2 (accepted by `check`); browser behaviour not tested (no browser on the host) |
| 4 | low | **Pathological Markdown blocks an API worker for about 12 seconds** (`api/src/regwatch/admin/services.py:286-290`, `api/src/regwatch/admin/legal.py:33-42`). markdown-it-py 4.3.0 is quadratic on unclosed link and image openers. `render` is synchronous and runs on the event loop inside `async def legal`. Inputs within the 200 000-character cap: `"![" * 100000` took 11.9 s, `"[" * 200000` 9.1 s, `"[a" * 100000` 8.3 s, `"*_" * 100000` 1.2 s. nh3 took at most 0.08 s. **Scenario:** a `settings.manage` holder (or a compromised admin session) saves such a page. The next `GET /legal` on each API worker, from any signed-in user or from the editor preview, freezes that worker for about 12 s. Every request it holds stalls, including sign-ins and health checks. Saving the page again repeats the stall. **Fix:** render once when the page is saved, in `asyncio.to_thread`, with a time budget, and refuse the save if the budget is exceeded. Store or cache the HTML keyed by the setting's `updated_at`. Optionally lower the page cap (a legal page rarely needs 200 000 characters). Add a test with the `![` input. | open | reviewer PoC L2 |
| 5 | info | **SVG parsing builds the whole tree before the element cap and runs on the event loop** (`api/src/regwatch/admin/logo.py:92-104`; called from `services.py:265`). A 1 MB file nested 140 000 deep peaked at 41 MB and took 0.6 s before being refused for exceeding 5 000 elements; 40 000 namespace declarations were accepted (12 MB peak). This is bounded, needs `settings.manage`, and expat's recursion is not a problem. **Fix:** parse incrementally (`XMLPullParser` with `forbid_*` through defusedxml's expat parser), stop at element 5 001, cap the depth (for example 64), and run the check in `asyncio.to_thread`. | open (proposal) | reviewer PoC S1 timings |
| 6 | info | **The legal renderer drops table alignment and `tel:` links** (`api/src/regwatch/admin/legal.py:26-27`). markdown-it emits `style="text-align:…"` on `th` and `td`, not `align`, so the `align` allowlist never matches and alignment is lost. `tel:` hrefs are removed and leave a bare `<a>`. This is functional, not a security issue. **Fix:** either drop `align` from the list, or allow `style` with nh3's `filter_style_properties={"text-align"}` for `th` and `td`. Add `tel` to `URL_SCHEMES` if the owner wants phone links. | open (proposal) | reviewer PoC L1 |
| 7 | info | **Bundled-crate notices are incomplete, and the pyproject comments are mangled** (`api/THIRD_PARTY_NOTICES.md`; `docs/research/R-01-license-verification.md:162`; `api/pyproject.toml:22-23`). The nh3 wheel ships only nh3's own MIT `LICENSE`. The notices file carries Unicode-3.0 only. It does not carry the MIT or Apache-2.0 notices of the statically linked ammonia, html5ever, url and other crates (52 MIT OR Apache-2.0, 9 MIT). For cssparser 0.37.0 and dtoa-short 0.3.5, MPL-2.0 3.2(a) requires telling recipients of the executable form where the source can be obtained, even when the files are unmodified. R-01 says the MPL duty "does not arise", which is true only of publishing modifications. This matters once the API image is given to anyone outside the owner. Separately, the nh3 line lost its register comment, and the python-multipart line carries two. **Fix:** add a generated section to `THIRD_PARTY_NOTICES.md` from the wheel's `sboms/nh3.cyclonedx.json`, with each crate's license text and copyright and the MPL source URLs. Correct the R-01 sentence. Move the comment back to the nh3 line. | open (proposal) | reading the wheel's `dist-info` |
| 8 | info | **Test gaps on the new routes** (`api/tests/integration/test_logo.py:94-101`; `api/src/regwatch/core/objectstore.py:34`). `test_upload_needs_a_file_part_and_settings_manage` checks only 401 when signed out. No test shows that a signed-in user without `settings.manage` gets 403, or that a cross-origin multipart POST gets 403 (the app-wide gate does both today). The `is_relative_to` branch is marked `pragma: no cover` because "the key pattern already rules it out". In fact that branch is what stops a symlinked directory inside the store: PoC O1 shows `branding` as a symlink out of the root is refused only there. **Fix:** add the 403 and Origin tests for `POST /admin/branding/logo`, and a symlink test for the object store. Then drop the pragma and correct its comment. | open (proposal) | reviewer PoC O1; reading the tests |
| 9 | info | **Logo caching and lifecycle** (`web/src/features/auth/LoginPage.tsx:94`; `api/src/regwatch/admin/router.py:58`, `:77`; `services.py:270`). The sign-in page requests `/branding/logo` without the `?v=` hash, and the route sends `Cache-Control: public, max-age=300`. A replaced logo, for example one removed because it was wrong or offensive, can stay in browsers and shared caches for up to five minutes. There is no way to remove a logo, only to replace it. Old files are kept forever, by design, for the audit trail. `If-None-Match` is compared exactly, so `W/` or a list just yields a 200. **Fix:** have the sign-in page use a `logo_url` from a public endpoint, or accept the five minutes. Consider a delete route (CP), and a retention note for old logo files. | open (proposal) | reading the code |
| 10 | info | **Multipart errors answer 400, which the contract does not list for the upload** (`api/src/regwatch/admin/router.py:146`; `openapi/regwatch.v1.yaml:142-147`). Starlette raises `HTTPException(400)` for too many files or fields, a missing boundary and malformed parts. The problem handler formats it correctly, but the operation documents only 200 and 415 (and 413 from the live document). **Fix:** map these to the documented 415 in the route, or add 400 through a CP. | open (proposal) | reviewer PoC M1 |

## Checked and fine
- **Legal page XSS (markdown-it plus nh3):** no markup, handler or dangerous URL got through. Escaped and treated as text:
  - raw `<script>`, `<img onerror>`, `<svg><script>`, `<math … xlink:href=javascript:>`, `<form><input>`, `<style>` and HTML comments.
  - `javascript:` in mixed case, entity-encoded (`&#106;avascript:`), or behind a backslash; `data:` links and `data:` images; `vbscript:` and `file:` autolinks. markdown-it refused to make these into links, and nh3 would have removed them anyway.
  - link reference definitions with `javascript:`, plain or entity-encoded (left as text).
  Other inputs:
  - `jav&#x09;ascript:`, `javascript%3A` and NUL-split schemes became percent-encoded relative URLs, which browsers cannot treat as a scheme.
  - A title-attribute breakout came out as an escaped `title` value.
  - Links get only `href`, `title` and `rel="noopener noreferrer nofollow"`; images are removed.
  - No SVG or MathML namespace is allowed, so the known ammonia namespace-confusion class does not apply.
  - `linkify` is off, so bare URLs stay text.
- **`dangerouslySetInnerHTML` justification** (`web/src/features/branding/BrandingPage.tsx:310-317`): accepted. The input is only `GET /legal`'s `html`, which the server sanitizes on every render, so stored data cannot skip the sanitizer. It is inserted in a `div` context and none of the allowed elements are parsing-context sensitive. The comment matches the code (allowlist, schemes; the dev CSP has `script-src 'self'`). The preview sits inside the editor `<form>`, but no form-associated element can pass the allowlist.
- **SVG check:**
  - Refused, each with a clear reason: the root in another namespace or with a prefix; `<script>` in any namespace; XHTML children; `on*` handlers, including namespaced ones; `foreignObject`, `a`, `image`, `set` and animation; XInclude.
  - `xlink:href` under any prefix maps to the same Clark name and must start with `#`.
  - DOCTYPE (internal or external) and entities are refused by defusedxml. `<?xml-stylesheet` is refused anywhere, whatever its case. Other PIs, comments and CDATA are dropped by ElementTree and do nothing in a browser.
  - UTF-16 and EBCDIC files are refused before or during parsing. ISO-8859-1 cannot hide ASCII-only markers.
  - A 1 MB attribute value parses in milliseconds.
  - The file is stored unchanged, exactly as checked.
- **PNG and sniffing:** the IHDR is checked (4 096 by 4 096 at most, so a decode stays at about 64 MB); the server never decodes the image. A PNG/HTML polyglot is accepted as `image/png`, but it is served as `image/png` with `nosniff` (and `Content-Disposition: inline`), so browsers will not render it as HTML. The type comes from the content, not the declared type (integration test).
- **Public route:** `GET /branding/logo` takes no user input to the store. The key is read from `branding.logo_ref` and must match `branding/logo-<64 hex>.(png|svg)` before use, and the settings API refuses writes to that key. A missing logo or file gives a problem 404; nothing else is disclosed, and the ETag is the content's SHA-256, which is public anyway. The CSP the route sets is correct (`default-src 'none'` with `sandbox` and no `allow-*` tokens), apart from being overwritten (finding 1). The 304 response carries the same headers. There is no rate limit, but each request costs one indexed query and a read of at most 1 MB, which is acceptable behind the proxy.
- **Object-store keys:** refused keys include `..`, `.`, empty segments, upper case, backslash, NUL and a leading `.`, so no key can collide with the `.tmp-` temporary files. Keys are generated by the server from the content hash. The temporary file is made with `mkstemp` (mode 0600, unique name) in the target directory, is fsynced, and replaces the target atomically; it is deleted on any exception. A crash can leave a `.tmp-*` file behind, which is harmless.
- **Multipart limits:** results of the PoC with the real middleware:
  - `Content-Length` or chunked bodies over 2 MiB get a 413 before parsing.
  - The route runs only after `authorize`, so nothing is parsed for anonymous or cross-origin callers.
  - One extra plain field is tolerated and ignored. Two extra fields, or a second file, get a 400.
  - A missing or misnamed part, a plain `file` field, urlencoded, JSON and empty bodies get a 415.
  - Header floods give a 400; a 1.8 MB CRLF preamble parses quickly.
  - The file is spooled (at most 1 MB in memory), read up to `MAX_BYTES + 1`, and closed by `async with`.
  - python-multipart has no runtime dependencies.
- **Authorization, CSRF and audit:** `x-permission: settings.manage` is on the route and in the contract. `authorize` refuses a POST without an `Origin` equal to `REGWATCH_BASE_URL` (`core/security.py:88-93`), so a cross-site `<form enctype=multipart/form-data>` fails. The web client sends `FormData` same-origin with credentials. Each change writes an audit row with the old and new keys and the client IP. The web route `/admin/branding` is gated on the same permission, and the API enforces it regardless.
- **`primary_color` CSS injection:** the server pattern is `^#[0-9A-Fa-f]{6}$` (Pydantic's Rust regex, so `$` does not accept a trailing newline). It is also applied when the key is written through `PUT /admin/settings` (`_DEDICATED`). The client re-tests it before `setProperty("--brand-accent", …)`, and `setProperty` takes a single value. A stored value that fails the test removes the property. Values such as `red;}` or `url(…)` cannot reach the style. `document.title` is a text property.
- **Web upload code:** the 1 MB pre-check matches the API, and the input is reset after each choice. The API's reason is shown as text. The logo renders through `<img>` only, with `logo_url` built by the server. The sign-in page hides the image when it fails to load.
- **Dependencies:** versions are pinned in `uv.lock` (nh3 0.3.7, markdown-it-py 4.3.0, defusedxml 0.7.1, python-multipart 0.0.33). The licenses (MIT, MIT, PSF-2.0, Apache-2.0) are on the 3.5 allow-list. The register rows and R-01 B1 to B7 exist, and Unicode-3.0 has its owner decision (BL-78). markdown-it-py 4.3.0 is past the 2.2.0 fixes for its published quadratic-input advisories; finding 4 is a different pattern.

**Sign-off at review:** **signed off with conditions.** No critical or high findings. Medium finding 1 should be fixed before the external audience is admitted, and before M7 or M8 reuse the logo. It is a proxy-configuration change with no API change. Low findings 2 to 4 are recommended for the same follow-up `sec/` branch. Info findings 5 to 10 can go to BACKLOG. None of them blocks merging the stack into a development environment. · BL-68 independent review · 2026-11-15

## Evidence (reviewer)
All proof-of-concept scripts are in `/tmp/bl68poc/`, outside the repository.
- **C1 (finding 1), `caddy/Caddyfile`:** run in `caddy@sha256:36c24ad9…` (v2.11.7) with `--network none`. Results:
  - The upstream sends `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`.
  - Through the repository's `header` block, the client receives `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; … img-src 'self' data: …`.
  - With `?Content-Security-Policy`, the logo keeps the route's CSP, and a response without a CSP still gets the site CSP.
- **S1 (findings 2 and 5), `svg_poc.py`:**
  - Accepted: `fill url escaped`, `style url escaped`, `style image-set` and `style @\69mport`.
  - Refused: `script`, `onload`, `xlink ext`, `xlink other prefix`, `doctype`, `xinclude`, `pi stylesheet`, `foreignObject`, `a element`, `image`, `set/animate`, `utf16` and `cp037`.
  - The PNG/HTML polyglot gives `image/png`.
  - `deep 140000 (980046B)` was refused for exceeding 5 000 elements, after `time=0.60s peak=41.4MB`. `40k ns decls` was accepted with a peak of 11.6 MB.
- **S2 (finding 3), `use_bomb.py`:** `use bomb 2180 bytes, 120 elements, instances 10^11: image/svg+xml`. A `\75 rl(https://tracker.example/p)` fill is accepted as `image/svg+xml`.
- **L1 (legal XSS and finding 6), `legal_poc.py`:** 35 cases, output quoted above. Examples: `raw_html` gives `<p>&lt;script&gt;…`; `js_entity` gives `<p>[a](javascript:alert(1))</p>`; `js_entity2` gives `href="jav%09ascript:alert(1)"`; `table_align` gives `<th>a</th>` with no alignment; `tel` gives `<a rel=…>t</a>`.
- **L2 (finding 4), `legal_dos.py` and `legal_poc.py`:** `img_br md=11.88s`, `open_br md=9.13s`, `br_a md=8.31s`, `brackets` (`[`×100 000 plus `]`×100 000) `4.10s`, `star_under 1.24s`; nh3 at most 0.08 s.
- **M1 (finding 10 and multipart), `multipart_poc.py`:** Starlette 1.10.0 with python-multipart 0.0.33.
  - `file + 2 extra fields`: 400 `Too many fields`. `two files`: 400 `Too many files`.
  - `file under other name`, `file as plain field`, `urlencoded`, `json` and `no content-type`: 415.
  - `multipart no boundary`: 400.
  - `3MB file (content-length)` and `3MB chunked`: 413.
  - `part with 1.9MB of headers`: 400.
- **O1 (finding 8 and the object store), `symlink_poc.py`:**
  - `'branding/logo-a.png' refused: object key leaves the store` when `branding` is a symlink out of the root.
  - `../x`, `a/../b`, `A`, `.tmp-x`, `a//b`, `a/./b`, `a\b` and `a\x00b` refused as malformed.
- **Repository suites:**
  - `make lint test-web` on `75fd9c3`: Ruff check and format clean (153 files), mypy clean (92 source files), ESLint and Prettier clean, `tsc -b` clean; Vitest 18 files and 96 tests passed; 98.3% lines.
  - `make test-api` on `75fd9c3` (throwaway PostgreSQL on 127.0.0.1): unit tests 504 passed, with every security-critical module at its 100% floor; integration tests 97 passed; combined coverage 96.67% (floor 85%).

## Author follow-up (`sec/M1-bl68-followups`, pending re-verification)
- **Finding 1 (medium):** `deploy/Caddyfile` sets `?Content-Security-Policy`, so the proxy adds the site policy only when the upstream sent none and the logo keeps `default-src 'none'; style-src 'unsafe-inline'; sandbox`. `scripts/tests/test_caddyfile.py` checks that the site CSP is conditional and keeps its core directives. It reads the file only; no Caddy runs in the test suites. The production header set (M10, BL-76 a) must keep the same rule.
- **Finding 2 (low):** `regwatch.admin.logo` drops the `style` attribute and refuses `\`, `/*` and `@` in any value. After removing exact `url(#id)`, numeric `rgb`/`rgba`/`hsl`/`hsla`, and (in transform attributes only) numeric transform functions, any remaining `(` or `)` is refused. `href` and `xlink:href` must be an exact `#id`. The module docstring now describes this. Tests: `test_css_tricks_in_values_are_refused`, covering 11 cases including `\75 rl(`, `image-set(` and `url( https:… )`.
- **Finding 3 (low):** a `<use>` may not point at an element that is, or contains, a `<use>`; one linear pass uses a parent map. Single references (50 `<use>` of one shape) still pass. The reviewer's `use_bomb.py` is now refused, and a 4,990-level nested worst case checks in 7 ms. Test: `test_use_chains_are_refused_but_single_references_pass`.
- **Finding 4 (low):** rendering runs in a worker thread (`render_async`). `PUT /admin/legal` renders the new page within `SAVE_BUDGET` (2 s) or refuses it with a 400, and the cached result serves `GET /legal`. A refused render finishes once in its thread and cannot be stored. Test: `test_render_runs_off_the_event_loop_and_enforces_a_budget`.
- **Finding 5:** `logo.check` runs in a worker thread.
- **Finding 7:** the `pyproject.toml` comments are corrected. `api/THIRD_PARTY_NOTICES.md` gains the MPL-2.0 3.2(a) source statement for cssparser and dtoa-short, and R-01's reasoning is corrected. The MIT and Apache-2.0 notices for the other bundled crates are BL-81 (a), due before the first distribution of the API image.
- **Finding 8:** new tests cover a signed-in user without `settings.manage` (403) and a foreign `Origin` (403, nothing stored). The object-store root check is no longer marked `pragma: no cover`; `test_a_symlink_out_of_the_store_is_refused` covers it.
- **Findings 6, 9 and 10:** BL-81 (b) to (d).


## Re-verification (BL-68 independent review, 2026-11-15)
Against `sec/M1-bl68-followups` at `c5e0a84` (diff `75fd9c3..c5e0a84`, 16 files).

**Method.**
- Read the whole diff.
- Re-ran PoCs S1, S2 and L2 unchanged from `/tmp/bl68poc/`. Added three new ones:
  - `reverify_svg.py`: 20 legitimate exports and colour forms, 13 remaining `(` forms, and 2 paint-server chains;
  - `reverify_legal.py`: the settings-route path, the event-loop lag, and the default executor under refused saves;
  - `caddy2/Caddyfile`: the repository's `:80` block verbatim, with only the upstream addresses and the admin line changed (checked by `diff`), run in the pinned Caddy image with `--network none`.
- Ran `make lint test-web`, `make test-api`, and `scripts/tests` the way CI does.
- No repository file other than this record was changed. The dev stack was not used.

| # | Verdict | Evidence |
| --- | --- | --- |
| 1 | fixed | C1 again, against the new `deploy/Caddyfile`. Through the proxy, `/api/v1/branding/logo` keeps `default-src 'none'; style-src 'unsafe-inline'; sandbox`. A response with no CSP (`/`, the SPA stub) still gets the site CSP. `nosniff` and `X-Frame-Options: DENY` are still set on both. No other upstream sets a CSP (`grep` over `api/src`, `web/vite.config.*` and `web/index.html`), so the `?` cannot keep a weaker policy. `scripts/tests/test_caddyfile.py` is a static check of the file, and it runs in CI (`ci.yml:77`); 32 passed locally. Production (M10) must keep the rule, and the author's note says so. |
| 2 | fixed | S1: every bypass from the review is refused: `\75 rl(`, all `style` forms, `image-set`, `@\69mport`, and `url(#a) url(https://…)`. No remaining `(` form can fetch. After the exact `url(#id)`, numeric colour functions and (in transform attributes only) numeric transform functions are removed, any `(` or `)` left is refused. That covers a rebuilt `uurl(#a)rl(https://…)` and an entity-encoded `url&#40;…&#41;`, which the XML parser decodes before the check. What still passes cannot fetch: `url(#a)` in `transform`, `rgb()` in `transform`, a full-width `（`, a bare word `image-set`, and `url( #a )`. CSS does not treat these as functions, or treats them as invalid. |
| 3 | fixed for `<use>`; see N2 | S2 (`use_bomb.py`) is now refused: "A `<use>` in an SVG logo may not point at another `<use>`." 50 `<use>` of one shape still pass. Two elements sharing an id are handled, because any marked id refuses. |
| 4 | partly fixed; see N1 | The event loop is no longer blocked. One `"![" * 100000` render in a thread gave a maximum loop lag of 26 ms, against 12 s before. `PUT /admin/legal` refuses a page that takes over 2 s. The budget can still be bypassed, and refused renders keep running (N1). |
| 5 | fixed | `logo.check` runs in `asyncio.to_thread` (`services.py:266`). Parse memory is unchanged (41 MB peak for 1 MB), which the finding accepted. |
| 6 | deferred, covered | BL-81 (d): keep table alignment and allow `tel:`. |
| 7 | partly fixed, rest covered | The MPL-2.0 3.2(a) statement for cssparser 0.37.0 and dtoa-short 0.3.5 is in `api/THIRD_PARTY_NOTICES.md`, with crates.io and repository URLs. R-01 now states the 3.2(a) duty correctly, and the `pyproject.toml` comments are on the right lines. The MIT and Apache-2.0 notices are BL-81 (a), "before the first distribution of the API image", which is the point at which they are owed. |
| 8 | fixed | The new tests cover 403 without `settings.manage`, 403 for a foreign `Origin` (and that nothing was stored), and the symlink case. The pragma is gone and the comment is correct. The 100% floors held (`make test-api`). |
| 9 | deferred, covered | BL-81 (b): logo removal, and `?v=` on the sign-in page. |
| 10 | deferred, covered | BL-81 (c): a CP listing 400 for malformed multipart. |

The BL-81 row cites findings 6, 7, 9 and 10, its decision is `open`, and its modules are M1 and M10. That matches how BL-77 was recorded.

### New at re-verification
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| N1 | low | **The legal save budget can be bypassed, and refused renders still occupy the shared thread pool** (`api/src/regwatch/admin/services.py:185-201` and `:294-306`; `api/src/regwatch/admin/legal.py:56-64`). There are two parts. (a) `PUT /admin/settings/legal.page_markdown` is still accepted. It runs `_check_owned_by_dedicated_route`, which validates `LegalWrite` (length only) and never renders. So a page that takes 12 s is stored without the budget, and every worker renders it on its next `GET /legal` with no budget. The settings screen edits this key in a text area since the admin web follow-ups. (b) `asyncio.wait_for` cancels only the await; the thread keeps running until the render ends. Every `asyncio.to_thread` call shares the loop's default executor (8 workers on this 4-CPU host), including `objectstore.get` for the public `GET /branding/logo` and the logo check. The renders are pure Python and hold the GIL. **Scenario:** a `settings.manage` holder, or a stolen admin session, submits ten different slow pages to `PUT /admin/legal`. Each one is refused at 2 s, but together they fill the pool. A `to_thread` call made 0.3 s later waited 96 s, so for about 1.5 minutes per burst the public logo and uploads hang on every worker the requests reach, and the loop lag rose to 357 ms. The module docstring says a refused render "cannot recur", but the same request can be repeated. **Fix:** check `legal.page_markdown` on the settings route with the same budget, or refuse that key there, since it has a dedicated route. Render in a dedicated executor with one or two workers, or in a subprocess that is killed at the budget. Refuse a save while a render for it is still running. Keep object-store I/O off that executor. Add a test that saves a slow page through `PUT /admin/settings/{key}`. | open | reviewer PoC R1 (`reverify_legal.py`) |
| N2 | low | **Reference amplification through paint servers still passes** (`api/src/regwatch/admin/logo.py:120-134`). `_check_use_chains` follows only `href` on `<use>`. It does not follow `url(#id)` references from `fill`, `stroke`, `mask` and `clip-path`. Two files are accepted: a 10-level chain of `<use>` → `<g>` (a rect filled with a `<pattern>` that holds 10 `<use>` of the next `<g>`), and a 10-level `<mask>` chain with 10 masked rects per level. Each references 10^10 drawn copies if the engine does not cache the paint server. **Scenario:** the same as finding 3, on the sign-in page and every header, in any engine that draws pattern or mask content again for each reference. This was not run in a browser (none on the host), and engines that cache pattern or mask content per element are not affected. **Fix:** build one reference graph from `href` and `url(#id)`, and refuse when a referenced element is, or contains, an element that makes a reference. Alternatively, bound the expanded count over that graph. Add both chains as tests. | open | reviewer PoC R2 (`reverify_svg.py`, both accepted) |
| N3 | info | **More legitimate exports are refused, and the reasons mislead** (`api/src/regwatch/admin/logo.py:56-66`, `:153-161`). Inkscape's default output (`style="fill:…;stroke:none"`) is now refused. Illustrator's `<style>` and `data-name`, and Inkscape's own namespaced attributes, were refused before; the message names `inkscape:version` as "the version attribute". Also refused: `rgb(31 90 166 / 50%)`, `hsl(210deg, …)`, upper-case `RGB(`, an `@` in an `id`, and a `#id` that starts with a digit. Colours are refused with "may not load anything from elsewhere". Figma-style files pass (`fill="none"`, `clip-path="url(#clip0_1_2)"`, `url('#g')`), as do legacy `rgb` and `hsl`, and `rotate(45 10 10)`. This is not a security issue: users will see refusals they cannot understand. **Fix:** say in the upload hint and the refusal that SVGs must use presentation attributes, and suggest the tool's "optimized" or "presentation attributes" export. Name namespaced attributes with their prefix. Accept function names case-insensitively, angle units and the `/` alpha form. Give colour refusals their own message. | open (proposal) | reviewer PoC R2 |

**Regression checks:**
- **`asyncio.to_thread` for the logo check:** each call takes at most about 0.6 s and needs `settings.manage`, so this adds no exposure of its own. The shared-pool issue is N1.
- **Thread safety:** markdown-it builds a fresh state on each `render`, and `lru_cache` is thread-safe, so sharing `_markdown` across threads is fine.
- **`href` grammar:** `href` must now be an exact `#[A-Za-z_][\w.-]*`, so a `#a'` or `#a https://…` value is refused, and a whitespace-padded `#a` still passes after `strip()`.

**Repository suites at `c5e0a84`:**
- `make lint test-web`: Ruff check and format clean (153 files), mypy clean (92 files), ESLint, Prettier and `tsc -b` clean; Vitest 18 files and 96 tests passed; 98.3% lines.
- `make test-api`: unit tests 518 passed, with every security-critical module at its 100% floor; integration tests 98 passed; 96.67% combined coverage.
- `scripts/tests` (as `ci.yml:77`): 32 passed.

**Sign-off:** **signed off.** Findings 1, 2, 5 and 8 are verified fixed. Finding 3 is fixed for `<use>`. Finding 4 is fixed for the event loop. Findings 6, 9 and 10 and the rest of 7 are carried in BL-81. No critical, high or medium findings are open, and the condition from the first sign-off (finding 1 before the external audience) is met.
- Low N1 and N2 are open. N1 is recommended before the external audience is admitted, because it lets one admin session stall the public logo route on every API worker.
- N2 is recommended before M7 or M8 reuse the logo. Both can go to a follow-up `sec/` branch or a BACKLOG row.
- N3 is a usability proposal.

· BL-68 independent review · 2026-11-15

## Author follow-up 2 (re-verification N1 to N3, pending re-verification)
- **N1 (low):** `PUT /admin/settings/legal.page_markdown` now applies the same check as `PUT /admin/legal`. The check (`legal.check_budget`) renders in a separate spawned process, waits until the child reports that its imports are done, and then gives it `SAVE_BUDGET` (2 s). It kills the child when the result arrives or when the budget runs out, so a refused render no longer keeps running. Both the checks and `GET /legal` renders use a dedicated two-thread pool, not the shared default pool, so the logo route and the upload check cannot be starved. Pages under 1,000 characters skip the check.
  - Tests: `test_slow_pages_are_refused_and_their_render_is_killed` (unit; it returns in under a second for a page that takes about 12 s to render) and `test_slow_legal_pages_are_refused_on_both_routes` (integration, both routes).
- **N2 (low):** the chain check now treats `url(#id)` like `href`. No reference may point at an element that is, or contains, a referencing element, except a gradient (gradients only inherit stops). The reviewer's pattern and mask chains in `reverify_svg.py` are refused. Tests: `test_chains_through_patterns_and_masks_are_refused` and `test_gradients_may_inherit_and_one_level_patterns_pass`.
- **N3 (info), in part:** colour functions are accepted in any case and in the modern space-and-slash syntax with angle units (`RGB(1 2 3 / 50%)`, `hsl(120deg 50% 50%)`). Inkscape-style `style=` exports, ids starting with a digit, and `@` in ids are still refused, which is the conservative choice. They are recorded under BL-81 (e).
- **Test change:** `test_gated_api_conforms` now also accepts 413. A fuzzed body over the 2 MB cap is refused before the session gate, which is correct, and one random run had produced one.
- **Checks:** `make lint` clean; `make test-api` 521 unit and 99 database tests passed, 96.70% coverage; `make test-web` 96 passed; `scripts/tests` 32 passed; license scan 0 failing.


## Re-verification 2 (BL-68 independent review, 2026-11-15)
Against `sec/M1-bl68-followups` at `8539557` (diff `c5e0a84..8539557`, 10 files).

**Method.**
- Read the whole diff.
- Re-ran `reverify_legal.py`, `reverify_svg.py` and `use_bomb.py` from `/tmp/bl68poc/`.
- Added three new PoCs:
  - `reverify_legal2.py`: the child's lifetime and leftover processes, inputs under 1,000 characters, and ten concurrent refused saves (with the legal pool, the default pool and the event loop measured during them);
  - `reverify_crash.py`: inputs that make the renderer raise;
  - `reverify_svg2.py`: the gradient exemption, `href` between paint servers, duplicate ids, and `href` together with `xlink:href`.
- Searched `api/src` for every writer of `legal.page_markdown`.
- Ran `make lint test-web`, `make test-api` and `scripts/tests`.
- Only this record was changed, and the dev stack was not used.

| Item | Verdict | Evidence |
| --- | --- | --- |
| N1: no route stores an unchecked page | fixed | Only `put_legal` (`services.py:303-312`) and `put_setting` (`:200-201`) write `legal.page_markdown`, and both now call `_check_legal_budget`. `put_branding` writes branding keys only, and `seed.py` inserts the registry default (`""`) only when the row is missing. The new integration test refuses the slow page on both routes. |
| N1: the child is killed at the budget | fixed | A refused check returns after 2.11 s, where the full render takes 12 s. `proc.kill()` and `join()` run in `finally`. Child processes alive after a check, after ten concurrent checks, and after the full `make test-api` run: none, apart from multiprocessing's single `resource_tracker` for the parent, which exits with the parent. The `resource_tracker` with PID 131466 seen on the host runs from `/opt/venv` and started hours earlier; it is not part of this test. |
| N1: the startup wait and the under-1,000 shortcut | fine | Spawning plus rendering a 2,400-character page took 0.23 s. Page content cannot lengthen the import phase: the argument is only an unpickled string of at most 200,000 characters. A start slower than 20 s raises `RuntimeError`, so the save fails with a 500 and nothing is stored; that fails closed. The slowest inputs under 1,000 characters take 0.8 to 56 ms (`"![" * 499` 56 ms, `"[" * 999` 39 ms), far below the budget, so the shortcut cannot be abused. |
| N1: process and pool exhaustion | fixed; see N4 | Ten concurrent slow saves were all refused. At most two checks ran at once (3 children at peak, counting the tracker), the maximum event-loop lag was 12 ms, and a default-pool `to_thread` call waited 0.004 s, against 96 s at re-verification 1. So the public logo route and the upload check are no longer starved. `GET /legal` is the exception: N4. |
| N1: `GET /legal` and checks sharing a pool | open; see N4 | The `GET /legal`-style `render_async` call, made 0.3 s after the ten saves began, waited 10.3 s. |
| N2: paint-server chains | partly fixed; see N5 | The pattern and mask chains from re-verification 1 are refused, and `use_bomb.py` still is. The gradient exemption cannot be used directly:<br>• a gradient holding a `<use>` passes, but gradient content is not drawn (only `stop`, `animate`, `set` and descriptive elements are);<br>• a gradient whose `href` points at a pattern is refused;<br>• a pattern whose `href` points at another pattern is refused (conservative).<br>Duplicate ids defeat the check, which also reopens finding 3 (N5). |
| N3: colour forms | fixed | `RGB(1,2,3)`, `rgb(31 90 166 / 50%)` and `hsl(210deg, 60%, 40%)` now pass. No new `(` form can fetch: the same 13 bypass cases give the same verdicts. |
| N3: the rest | deferred, partly covered | BL-81 (e) covers Inkscape `style=` and ids that start with a digit. It does not mention `@` in ids or the misleading refusal for namespaced attributes (`inkscape:version` is still named "the version attribute"). Both are cosmetic, and BL-81 can take them. |
| Test change: Schemathesis 413 | accepted | `BodySizeLimitMiddleware` sits in front of the app and answers 413 only for bodies over 2 MiB, before any handler or gate runs. So a 413 means nothing was processed, and it cannot hide a gate that let a request through. The live document lists 413 on every operation with a body (CHANGELOG, BL-64), so the response conforms. The set still excludes every 2xx and 5xx. |

### New at re-verification 2
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| N4 | info | **Saves can delay `GET /legal`** (`api/src/regwatch/admin/legal.py:63-70`, `:94-101`). Checks and `GET /legal` renders share the two-thread `_POOL`, and its queue has no bound. Each check holds a thread for the spawn time plus at most 2 s. Ten slow saves sent at once kept a `GET /legal` render waiting 10.3 s. A `settings.manage` session that keeps sending them can keep `GET /legal` waiting on that worker for as long as it continues, but nothing else is affected (the default pool and the event loop were fine). **Fix:** give `GET /legal` its own executor, separate from checks, or refuse a save with 429 or 409 while a check is already running. | open (proposal) | reviewer PoC R3 (`reverify_legal2.py`) |
| N5 | low | **Duplicate ids bypass the chain check** (`api/src/regwatch/admin/logo.py:142-150`). `by_id = {el.get("id"): el …}` keeps the last element with each id. Browsers resolve `href` and `url(#id)` to the first element in document order. Each level of the chain is a `<g id="gK">` holding 10 `<use href="#g(K-1)">`, followed by a decoy with the same id: an empty `<linearGradient id="gK"/>`, which is exempt, or a plain `<rect id="gK"/>`, which holds no reference. The check then looks at the decoy and accepts a 10^10 chain. Both variants passed. This is a regression from `c5e0a84`, which marked ids through a set and refused this file, so finding 3 is open again. **Scenario:** the same as finding 3 and N2 (sign-in page and every header). It was not run in a browser; that first-in-tree-order resolution is standard DOM behaviour. **Fix:** refuse any SVG in which an id appears twice; legitimate exports do not repeat ids. If duplicates must be allowed, mark an id as holding a reference when any element with that id does. Add the duplicate-id chain as a test. A related point: a file that has both `href` and `xlink:href` passes, with only `href` checked. Current engines prefer `href` too, so this is consistent today, but refusing both together is simpler. | open | reviewer PoC R4 (`reverify_svg2.py`: "duplicate-id gradient decoys, use chain 10^10" and "plain-rect decoy last" both give `image/svg+xml`) |
| N6 | info | **The budget check fails open if the child dies** (`api/src/regwatch/admin/legal.py:87-88`). `parent.poll(budget)` is also true at end of file. A child that raises or is killed (for example by the out-of-memory killer) therefore counts as "within budget", and the page is stored. No input found today does this. The one input that makes `render` raise, a lone surrogate (`UnicodeEncodeError` in nh3), is refused earlier by `LegalWrite` and `has_control` on both routes, and could not be encoded for PostgreSQL anyway. **Fix:** `recv()` the result, or check `proc.exitcode` before killing, and count EOF or an error as a refusal. | open (proposal) | reviewer PoC R5 (`reverify_crash.py`) |

**Repository suites at `8539557`:**
- `make lint test-web`: Ruff check and format clean (153 files), mypy clean (92 files), ESLint, Prettier and `tsc -b` clean; Vitest 18 files and 96 tests passed; 98.3% lines.
- `make test-api`: unit tests 521 passed, with every security-critical module at its 100% floor; integration tests 99 passed; 96.70% combined coverage.
- `scripts/tests`: 32 passed.

**Sign-off:** **signed off.**
- **Verified fixed:** N1 for storage, killing the child, process limits and the shared pool; N3 for colour forms; the Schemathesis change is accepted.
- **Open, low:** N5, which reopens finding 3. It should be fixed before the external audience is admitted, because one `settings.manage` session could make the public sign-in page unusable. The fix is small: refuse duplicate ids.
- **Open, info:** N4 and N6 are proposals for BACKLOG.
- **Carried in BL-81:** the rest of N3.
- No critical, high or medium findings are open.

· BL-68 independent review · 2026-11-15

## Author follow-up 3 (re-verification 2: N4 to N6)
- **N5 (low):** an SVG that repeats an id is refused before references are followed, so the check and the browser always resolve a reference to the same element. Test: `test_repeated_ids_are_refused`. The reviewer's three duplicate-id files in `reverify_svg2.py` are refused.
- **N6 (info):** `_within_budget` now reads the child's answer. A child that ends without one raises, so the save fails closed with a 500 and nothing is stored. Test: `test_a_child_that_dies_without_an_answer_fails_closed`.
- **N4 (info):** budget checks run in their own two-thread pool (`legal-check`), so `GET /legal` renders in `legal-render` never wait behind them. Checks and child processes stay bounded at two at a time.
- **N3 leftovers:** `@` in ids and the "version attribute" message for `inkscape:version` are cosmetic. They are recorded with BL-81 (e).
