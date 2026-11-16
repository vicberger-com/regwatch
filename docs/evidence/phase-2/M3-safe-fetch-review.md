# Security review record: M3 Capture framework, SafeFetcher (part 1 and 2)

**Scope (PRs, routes, tasks):** branch `feat/M3-safe-fetch` (`docs/G1-approved...feat/M3-safe-fetch`, commits `ff54b22` policy and `30aa2c8` fetch). Files: `api/src/regwatch/capture/safe_fetch/__init__.py`, `policy.py`, `fetch.py`; tests `api/tests/unit/test_safe_fetch_policy.py`, `api/tests/unit/test_safe_fetch_fetch.py`; the `httpx` dependency in `api/pyproject.toml` and `api/uv.lock`. No routes or tasks yet: nothing outside the package and its tests imports it. Out of scope, not built yet: robots.txt (M3 acceptance 4) and per-host rate limits (acceptance 5), which wait on the owner's approval of new libraries. · **Reviewer session label:** M3 SafeFetcher independent review · **Date:** 2026-11-16 · **Author sessions excluded from review:** yes

## Method
- Read the diff against M3 "Design notes" and acceptance criterion 3, `docs/08-security-compliance.md` 8.1 and 8.2, and `docs/contracts/fixtures.md` (`private_redirect.json`, fixture server routes).
- Checked the security-relevant behaviour of the libraries in the lockfile (httpx 0.28.1, httpcore 1.0.9, Python 3.12.16) by reading their source: TLS server name, pool keep-alive, environment proxies, content decoders.
- Ran the two test files (77 passed) and line plus branch coverage for `regwatch.capture.safe_fetch` (191 statements, 44 branches, 100 percent).
- Ran scratch proof-of-concept scripts outside the repository (`/tmp/m3review/`): an address-policy probe, a slow-resolver and redirect-boundary probe, and gzip-bomb fetches against a separately started fixture server on 127.0.0.1, which was stopped afterwards. No repository file other than this record was changed. No external network was used, and the Docker stacks were not touched.

## Data flows touched
- **Admin to API (future M3 routes):** a source URL, checked by `validate_source_url` when it is saved (acceptance 3, configuration time).
- **Worker to DNS:** the system resolver (`getaddrinfo` in the default executor), or a resolver injected by tests.
- **Worker to external hosts:** HTTP/1.1 or TLS to one checked address per hop. The name goes in `Host` and in the TLS server name. Redirects are followed by hand.
- **External host to worker:** hostile status, headers, `Location`, `Content-Encoding` and body. The body is returned to callers (future connectors, then M4).
- **Trust boundary:** everything after the URL string is hostile: DNS answers, redirect targets, encodings, body sizes and timing.

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | TLS to a pinned IP | `sni_hostname` extension; httpcore uses it as `server_hostname` with the default verifying context | Not tested end to end with a real TLS listener | 5 |
| Tampering | URL parsing, Host header, redirects | Control and space characters refused; scheme allow-list; userinfo refused; every hop re-parsed and re-resolved | 301 and 302 keep the method | 7 |
| Repudiation | n/a (no audit in this layer) | Stable `reason` codes for callers to record | Logging and audit come with the connectors | none |
| Information disclosure (SSRF) | `policy.check_address`, `resolve`, pinning | All answers checked and any private answer refuses the host; IPv4-mapped, 6to4, Teredo and NAT64 embeddings checked; connection goes to a checked address; no env proxies | IPv4-compatible and IPv4-translated IPv6 forms pass; test-only bypass sits on the public constructor | 2, 4 |
| Denial of service | Body reading, deadlines | Content-Length pre-check; cap on decoded stream; connect, read and per-hop deadlines | Decompression happens before the cap, so a stacked encoding expands without bound in one chunk; DNS time sits outside the deadline | 1, 3 |
| Elevation of privilege | `pinned_hosts` | Not reachable from configuration today | One keyword argument away from an unchecked address | 4 |

## Checklist
- [ ] Input validation on every field (types, sizes, enumerations): URL validation is thorough. Two IPv6 forms are not refused (finding 2).
- [x] Output encoding in UI, templates, emails, CSV: no output in scope.
- [ ] Authentication and authorization on every route and task: no routes or tasks yet. This needs checking when connectors and the source API use the package.
- [x] Session handling (cookie flags, rotation, revocation): not touched.
- [x] Secrets not logged or committed: the diff has no secrets and no logging. The User-Agent comes from the caller.
- [x] Outbound requests only through SafeFetcher or registered services: this is SafeFetcher. No other outbound client was added.
- [ ] File and body size limits; content-type checks: the 10 MB cap exists, but memory is not bounded by it (finding 1). Content-type is exposed (`FetchResult.mime`) and is left to callers.
- [x] Logging excludes sensitive data; audit rows written: no logging in this layer.
- [ ] Dependency, image and license scans attached and clean: none attached. The `httpx` register row exists (3.6, BSD-3). The pin has no upper bound (finding 6).

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | high | **The body cap applies after decompression, but decompression is unbounded, so a stacked `Content-Encoding` exhausts memory.** `fetch.py:102` counts the chunks from `response.aiter_bytes()`. httpx produces each chunk with `zlib.decompressobj().decompress(data)` and no `max_length`, and applies every coding in `Content-Encoding` in turn (`gzip, gzip`, and also `br` or `zstd` if those packages ever arrive transitively), whatever `Accept-Encoding` asked for (`fetch.py:90`). The whole output of one network read is held in memory before the size check runs. **Failure case:** `/bomb/gzip?mib=400&nested=1` from the fixture server, with `max_bytes` at 1 MiB, was refused as `too-large`, but only after one decoded chunk of 400.0 MiB, with a peak RSS of 837 MiB (a plain page peaked at 36 MiB). The fixture's maximum `mib=4096` would need about 4 GiB in one allocation, so a hostile source can OOM-kill a worker each time it is fetched. A single gzip layer is bounded but still about 1000 times the raw read, roughly 64 MiB per 64 KiB read, regardless of the cap. The existing bomb test passes only because uvicorn streams small single-layer chunks. **Fix:** read `response.aiter_raw()` and decode it in the fetcher. Accept exactly one of `identity`, `gzip` or `deflate`, and refuse anything else (stacked, `br`, `zstd`, unknown) with `reason="encoding"`. Decompress in a loop with `decompress(buf, max_length=limit - size + 1)` and `unconsumed_tail`, so no single step yields more than the bytes still allowed. Add fixture tests for `nested=1` and `mib=4096` that assert the refusal and bound the largest decoded piece (or peak RSS) by the cap. | open | reviewer PoC, Evidence 1 |
| 2 | medium | **IPv4-compatible and IPv4-translated IPv6 addresses pass the policy.** `policy.py:90-102` (`_embedded`) extracts IPv4-mapped (`::ffff:0:0/96`), 6to4, Teredo and NAT64 `64:ff9b::/96`. It does not handle the deprecated IPv4-compatible `::/96` (RFC 4291) or IPv4-translated `::ffff:0:0:0/96` (RFC 2765), and Python's `is_global` is True for both. **Failure case:** `check_address("::169.254.169.254")`, `"::127.0.0.1"` and `"::ffff:0:a9fe:a9fe"` all return the address as public. A DNS AAAA answer or a redirect to `http://[::a9fe:a9fe]/` passes every check. Whether it then reaches 169.254.169.254 depends on the host's stack: automatic SIT tunnelling, SIIT or NAT46 translators, and some container or cloud overlays route these. This could not be confirmed here because IPv6 is unavailable in the review sandbox. Even so, it breaks the 8.1 control "no IPv6 to IPv4 mapped bypass" and the module docstring's claim. Also allowed: deprecated site-local `fec0::/10` (`fec0::1` passes). **Fix:** refuse `::/96`, `::ffff:0:0:0/96` and `fec0::/10` outright, and simplest of all, any IPv6 address whose upper 80 bits are zero. Add these to `test_private_and_special_addresses_are_refused`. | open | reviewer PoC, Evidence 2 |
| 3 | low | **DNS resolution sits outside the per-hop deadline.** `fetch.py:113` awaits `resolve` before `asyncio.timeout` opens on line 115, and the system resolver has no timeout of its own. **Failure case:** a resolver that takes 2 s, with `total_s=0.05`, still returned 200 after 2.0 s. A source whose authoritative name server (which the attacker controls) answers slowly holds a worker for the resolver's full retry schedule (glibc default 5 s per try, times attempts, times servers, for A and AAAA), and does so on each of up to 6 hops. `getaddrinfo` also occupies a default-executor thread that cancellation cannot free, so many such sources can exhaust the executor. The module docstring says each hop has a total deadline. **Fix:** move `resolve` inside the `asyncio.timeout` block, or give it its own short `asyncio.wait_for` (for example 5 s) that maps to `reason="dns"`. Consider an overall fetch budget as well (see 7c). Add a test with a slow fake resolver. | open | reviewer PoC, Evidence 3 |
| 4 | low | **The test-only `pinned_hosts` bypass sits on the public production constructor and on public `resolve`.** `fetch.py:70,76` and `policy.py:138-139`: a pinned name gets its address with no DNS and no `check_address`. Today it cannot be reached from configuration: no settings key exists, and nothing outside the package and its tests constructs `SafeFetcher`. But nothing enforces that. A future factory such as `SafeFetcher(**settings.capture)`, or one careless call, would turn any name into a route to any internal address. A non-IP value raises a bare `ValueError` instead of `FetchRefusedError`. **Fix:** remove `pinned_hosts` from `SafeFetcher` and `resolve`. Give tests a subclass in `tests/support/` that overrides a private resolve hook, or keep the argument but refuse non-loopback targets and require a module-level flag that only `tests/conftest.py` sets. Add a test that `SafeFetcher`'s signature and the settings schema expose no such key. | open | code reading and grep |
| 5 | low | **The TLS host-name check is asserted only as a request attribute, not as behaviour.** `test_the_connection_is_pinned_to_the_checked_address` uses `MockTransport` and checks that `extensions["sni_hostname"] == "example.org"`. Verification actually happens in httpcore (`_async/connection.py:151`, `server_hostname = sni_hostname or origin host`, with the default verifying context). By code reading this is correct today, and it fails closed if the extension is dropped (the check would then run against the IP). Even so, the central TLS property and any regression in it are untested. **Fix:** add a fixture test with a local TLS listener whose certificate is issued for `fixtures.example` by a test CA, passed in through a test-only SSL context. Assert that the right name succeeds, a certificate for another name is refused (`connect`), and that a redirect to another name on the same address does a second handshake. | open | code reading |
| 6 | low | **Test coverage is 100 percent by line and branch, but several tests check configuration rather than behaviour.** (a) `test_hops_do_not_share_connections` checks the `AsyncClient` keyword arguments while passing a `MockTransport`, and httpx ignores `limits` when a transport is given, so the test would still pass if pooling reused connections. Count TCP connections at the fixture server across `/redirect/chain/3` instead. (b) There is no behavioural proxy test: set `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` to an unused port and show that the fetch still reaches the fixture server. (c) There is no boundary test for the redirect cap (exactly 5 succeed and the 6th is refused; the reviewer confirmed 5 succeed). (d) The raw-listener routes `/lie/long`, `/lie/short`, `/raw/slow-headers`, `/raw/hang` and `/raw/garbage` are not exercised. (e) The nested bomb is not exercised (finding 1). (f) There is no test for finding 2's forms or finding 3's slow DNS. (g) Also, `httpx>=0.27` has no upper bound, unlike its neighbours in `pyproject.toml:20`. The design depends on httpx and httpcore internals (`sni_hostname`, decoder behaviour), and httpcore is only a transitive dependency. Bound it (`<0.29`) and consider listing httpcore. | open | code reading and PoC |
| 7 | info | (a) A 301 or 302 after a POST or other method keeps the method (`fetch.py:163` changes only 303). No body is ever sent, so there is no security impact, but the `method` parameter could be restricted to GET and HEAD. (b) Only the first checked address is tried, with no fallback, which affects availability only. (c) No overall budget across hops: up to 6 times 60 s plus DNS, which is within the per-hop wording of the spec. (d) Any port on a public host is allowed, and https to http downgrades on redirect are followed. Decide whether policy should restrict either. (e) NAT64 or DNS64 with an operator-specific prefix cannot be detected. Deployments must not use one, or must add the prefix to the deny list. Record this in the deployment notes. (f) On Python 3.12.16, `2002::/16` and `2001::/32` are already non-global, so all 6to4 and Teredo addresses are refused even with a public embedded address (`2002:808:808::1` refused). This is conservative and acceptable, and the embedded checks for those two forms are defence in depth. (g) Acceptance criteria 4 and 5 (robots.txt, per-host rate limits) are not built yet. | n/a | n/a |

**Sign-off at review:** not signed off; one high (1) and one medium (2) open · M3 SafeFetcher independent review · 2026-11-16

## Checked and found fine
- **Scheme and URL:** only `http` and `https` are accepted. `file`, `gopher`, `ftp` and `javascript` are refused. Userinfo is refused. Control characters, spaces, DEL and CR LF are refused before parsing, so Host-header and request-line injection fail. There is a 2048-character limit. Bad ports and bad IPv6 brackets give `url`. IDNA encoding is done, and bad labels give `url`. Fragments are dropped.
- **Numeric spellings:** every host goes through the resolver, so `2130706433`, `0x7f000001`, `017700000001`, `127.1` and `localhost` are refused at the address (tests use the real system resolver).
- **Address policy:** relies on Python 3.12.16 `is_global` plus an explicit multicast check. Loopback, RFC 1918, 100.64/10, 169.254/16, 0/8, 240/4, broadcast, 198.18/15, documentation ranges, `::`, `::1`, `fe80::/10` with or without a zone, `fc00::/7` (including `fd00:ec2::254`), `ff00::/8`, `2001:db8::/32`, `100::/64`, `64:ff9b:1::/48`, IPv4-mapped, NAT64 with a private address, 6to4 and Teredo are all refused. Public IPv4, IPv6 and NAT64 with a public address pass.
- **DNS:** every answer is checked, a mixed public and private answer refuses the host, an empty answer and resolver errors give `dns`, and duplicate answers are removed.
- **Pinning:** the request URL carries the checked IP literal (IPv6 bracketed), and `Host` carries the name and any non-default port. For https the TLS server name and certificate check use the name (httpcore 1.0.9 `connection.py:151`, default `verify=True` context). Plain http sends no `sni_hostname`.
- **Redirects:** handled by hand (`follow_redirects=False`). Each hop is re-parsed, re-resolved and re-checked. Relative `Location` values are resolved against the logical URL, not the IP. The cap is 5 (5 succeed and the 6th is refused, reviewer probe). A 303 becomes GET. A 3xx without `Location` is returned as the answer. All 15 targets in `private_redirect.json` are refused, and the default fetcher refuses the fixture server itself (acceptance 3 at fetch time). `validate_source_url` covers configuration time.
- **Body:** a `Content-Length` over the cap is refused before reading, the decoded stream is capped, and the response is closed in `finally`.
- **Timeouts:** connect 10 s, read and write 30 s, pool 10 s. `asyncio.timeout(total_s)` covers the send, the headers and the body, which the trickling-body fixture test shows. `TimeoutError`, `httpx.TimeoutException` and other `httpx.HTTPError` become stable reasons, and no raw exception leaks.
- **Proxies:** with `trust_env=False` and no transport, httpx builds no environment proxy mounts (`_client.py:685`, `allow_env_proxies = trust_env and transport is None`). That also leaves `SSL_CERT_FILE` and netrc unused.
- **Connection reuse:** `max_keepalive_connections=0` makes the pool close idle connections, each response is closed before the next hop, and every `fetch` creates and closes its own client. No pooled TLS session crosses hops or fetches. HTTP/2 is off.
- **Dependency:** the `httpx` register row exists (BSD-3), and the lockfile pins httpx 0.28.1 and httpcore 1.0.9. `brotli` and `zstandard` are not installed today.
- **Tests:** 77 pass in about 4 s. Coverage is 100 percent by line and branch. The fixture-server tests run on 127.0.0.1 only, reached through a made-up name, while every real spelling of that address stays refused, as the fixture contract requires.

## Evidence (reviewer)
1. **Finding 1:** `/tmp/m3review/bomb.py` against `python -m tests.support.fixture_server --port 18431`, `FetchLimits(max_bytes=1 MiB)`, with a spy on `Response.aiter_bytes`:
   - `/pages/page_v1.html`: ok, peak RSS 36 MiB.
   - `/bomb/gzip?mib=1024`: `too-large`, largest decoded chunk 1.0 MiB, RSS 39 MiB.
   - `/bomb/gzip?mib=400&nested=1`: `too-large`, **largest decoded chunk 400.0 MiB, peak RSS 837 MiB**.
2. **Finding 2:** `/tmp/m3review/addr.py`:
   - Pass: `::127.0.0.1`, `::a9fe:a9fe`, `::ffff:0:7f00:1`, `::ffff:0:a9fe:a9fe` and `fec0::1`.
   - Refused: `64:ff9b:1::a9fe:a9fe`, `100::1`, `2002:a00:1::1`, `fd00:ec2::254`, `198.51.100.1` and `0.1.2.3`.
3. **Finding 3 and the redirect boundary:** `/tmp/m3review/misc.py`:
   - Slow resolver, 2 s, with `total_s=0.05`: status 200 after 2.0 s.
   - Five redirects: 200 with 5 recorded.
   - A 302 after POST: methods `['POST', 'POST']`.
4. **Tests:** `uv run pytest -q tests/unit/test_safe_fetch_policy.py tests/unit/test_safe_fetch_fetch.py`: 77 passed. With `--cov=regwatch.capture.safe_fetch --cov-branch`: 191 statements, 44 branches, 100 percent.

## Author follow-up (`sec/M3-safe-fetch-followups`, pending re-verification)
- **Finding 1 (high):** the body is read with `aiter_raw` and decompressed by SafeFetcher, never by httpx. Each `decompress` call is limited to the room left plus one byte (`max_length`), with `unconsumed_tail` fed back, so output never exceeds the cap whatever the input. Only identity, gzip and deflate are accepted, one at a time; stacked encodings (`gzip, gzip`), unknown ones (`br`) and damaged streams are refused with reason `encoding`. Test: `test_a_nested_gzip_bomb_never_grows_past_the_cap` fetches `/bomb/gzip?mib=400&nested=1` with a 1 MB cap and asserts a tracemalloc peak under 32 MiB. Also `test_stacked_and_unknown_encodings_are_refused`.
- **Finding 2 (medium):** every IPv6 address in `::/64` is refused: IPv4-compatible, IPv4-mapped and IPv4-translated forms, plus `::` and `::1`. So is site-local `fec0::/10`. The IPv4-mapped unwrapping became unreachable and is removed. Tests: the policy cases `::169.254.169.254`, `::10.0.0.1`, `::ffff:0:a9fe:a9fe`, `::ffff:0:7f00:1`, `::8.8.8.8`, `fec0::1` and `fedc::1`.
- **Finding 3 (low):** DNS resolution runs inside the per-hop deadline. Test: `test_dns_counts_against_the_deadline`.
- **Finding 4 (low):** `pinned_hosts` is gone from `SafeFetcher` and `policy.resolve`. Tests reach the fixture server through a test-only subclass that overrides `_resolve`, so the production class has no way to skip the address check.
- **Finding 5 (low):** `test_a_certificate_for_another_name_is_refused` runs a local TLS listener with a certificate for `good.example`, signed by a throwaway authority made with openssl. A fetch of `good.example` succeeds, `bad.example` on the same address is refused, and the system trust store refuses the throwaway authority. The new `_tls` hook lets the test trust that authority. Writing this test showed the hook had not been passed to the client; it is now.
- **Finding 6 (low):**
  - `test_hops_do_not_share_connections` uses the real transport; the fixture server now records each request's client port, and two hops show two ports.
  - `test_environment_proxies_are_ignored` sets every proxy variable.
  - `test_the_redirect_cap_is_exactly_five`: 5 redirects pass and 6 are refused.
  - `test_misbehaving_servers_are_refusals` covers the raw listener's hang, slow-headers, garbage and short-body routes.
  - `/lie/long` reads exactly the 10 declared bytes and ignores the rest (`test_a_body_longer_than_declared_is_cut_at_the_declared_length`).
  - httpx is bounded `<1`.
- **Info (7):** no change.

## Re-verification (`sec/M3-safe-fetch-followups` at `db1e1b4`)
**Method:** I read `git diff feat/M3-safe-fetch sec/M3-safe-fetch-followups` and re-ran the two test files: 95 passed, and coverage of `regwatch.capture.safe_fetch` is 100 percent (218 statements, 56 branches). I re-ran the proof-of-concept scripts in `/tmp/m3review/`, adapted from the removed `pinned_hosts` to a subclass that overrides `_resolve`. Against a separately started fixture server on 127.0.0.1 I ran `bomb2.py`. With `MockTransport` I ran `addr.py`, `misc.py`, `mem.py`, `regress.py` and `trail.py`. The fixture server was stopped afterwards. No external network was used, the Docker stacks were not touched, and no file other than this record was changed.

### Verdict per finding
| # | Verdict | Evidence |
| --- | --- | --- |
| 1 | **closed for the reported case; a new high regression in the same code (finding 8)** | `/bomb/gzip?mib=400&nested=1` is now refused as `encoding` before any decompression, with peak RSS 36 MiB (837 MiB before). Single-layer bombs are bounded: `mib=1024` and `mib=4096` from the fixture server peaked at 38 MiB RSS. With the 10 MiB cap, a 1 GiB and a 4 GiB bomb, each delivered as one raw chunk, were refused at 21 MiB and 24 MiB peak traced memory. The cap edge is exact: 1 MiB decoded passes, and 1 MiB plus 1 byte is refused. |
| 2 | closed | `::127.0.0.1`, `::a9fe:a9fe`, `::ffff:0:7f00:1`, `::ffff:0:a9fe:a9fe`, `::1:0:0:1` and `fec0::1` (also `febf::1`) are refused (`policy.py:114`). Public `2001:4860:4860::8888`, `2606:4700:4700::1111`, `2a00:1450:4001:80b::200e`, `2620:4f:8000::1` and NAT64 `64:ff9b::808:808` still pass. |
| 3 | closed | A 2 s resolver with `total_s=0.2` is refused as `timeout` after 0.2 s (`fetch.py:150`). |
| 4 | closed | `pinned_hosts` is gone from `SafeFetcher` and `resolve`. Nothing under `api/src` subclasses `SafeFetcher` or overrides `_resolve` or `_tls`. The only override is `PinnedFetcher` in the test module. |
| 5 | closed | `test_a_certificate_for_another_name_is_refused` uses a real TLS listener and a throwaway authority. The right name passes, another name on the same address is refused (`connect`), and the default trust refuses the throwaway authority. |
| 6 | closed | Reading the tests, they now exercise behaviour. The connection test runs on the real transport and compares client ports, so it would fail if a connection were reused. The proxy test sets the variables to an unroutable proxy. The cap test checks the boundary (chain/4 passes, chain/5 is refused). The raw-listener routes are covered. `httpx>=0.27,<1` is accepted; httpcore is still only pinned by the lockfile. New gaps are in finding 10. |

### Regression checks requested
- **Gzip with trailing data, or several members:** this is a regression, see findings 8 and 9.
- **Does refusing `::/64` block anything legitimate?** No. `::/64` lies inside `::/8`, which IANA reserves; no global unicast address is allocated there. The only behaviour change is that an AAAA answer in IPv4-mapped form with a public address (`::ffff:8.8.8.8`) is now refused, where before it passed. The system resolver does not return mapped addresses (no `AI_V4MAPPED`), and refusing them is safe. `0:0:0:1::1` is still in reserved `::/8` but outside `::/64`, and it passes. It is not routable; see 11(c).
- **Does DNS inside the deadline change the error a user sees?** Only for slow DNS. NXDOMAIN is still `dns` ("could not be resolved"), and a private answer is still `private-address`. `FetchRefusedError` passes through the handlers in `_hop` unchanged. A slow name server now gives `timeout` with "`<host>` took longer than N s", where before the hop simply waited. The message does not say that DNS was the slow part; see 11(b).
- **Could the `_tls` hook weaken certificate checking in production?** No, as built. `_tls()` returns `True`, which is httpx's own default: the bundled CA file, `CERT_REQUIRED`, and `check_hostname` on. Because of `trust_env=False`, `SSL_CERT_FILE` and `SSL_CERT_DIR` cannot change it. Only a subclass can change the hook, and none exists outside tests. The residual risk is a future subclass, or a test-style context copied into production code; see 11(a).

### New findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 8 | high | **Raw bytes after the end of a gzip stream pile up in memory without limit (a regression from the finding 1 fix).** In `fetch.py:132-142`, once the gzip member ends (`decoder.eof`), each later raw chunk passed to `decoder.decompress` produces no output. zlib appends it to `decoder.unused_data`, and the loop still reads every chunk (`unconsumed_tail` is empty, so the inner loop ends at once). Neither `take` nor the Content-Length pre-check counts these bytes; a chunked response has no Content-Length. **Failure case** (`/tmp/m3review/trail.py`): a 5-byte gzip member followed by 200 MiB of raw bytes, with a 1 MiB cap. The fetch *succeeds* with a 5-byte body, and peak traced memory is 399 MiB. Over a real connection only the 60 s hop deadline limits this, which is several GB on a fast link, so a hostile source can OOM-kill a worker, as in finding 1. **Fix:** after each `decompress`, if `decoder.eof`, stop reading. Either refuse (`encoding`) when `decoder.unused_data` or later chunks hold anything other than whitespace, or start a fresh bounded decompressor for the next member (see 9). As a backstop, count raw bytes against a cap (for example `max_bytes`) whatever the encoding. Add tests for trailing data and for a member followed by a large raw tail, with a memory assertion. | open | reviewer PoC |
| 9 | low | **Correctness of the new decoder.** (a) A body with several gzip members (valid under RFC 1952) is silently cut to the first member, and trailing garbage is silently ignored. (b) A truncated gzip stream is accepted as complete, because `flush()` runs without checking `decoder.eof`. So a capture can be silently partial, which M3 change detection would report as "changed". (c) Raw deflate without the zlib header, which some servers send and httpx used to accept, is now refused as `encoding`. (d) `FetchResult.headers` still carries `content-encoding` (and any `content-length`) for a body that is already decoded, so a caller that trusts the headers could decode twice or mislabel the content. **Fix:** support members with a fresh bounded decompressor that shares the cap (or refuse them); refuse with `encoding` when `decoder.eof` is false at the end of the stream; decide whether to allow a raw-deflate fallback (`wbits=-15`); drop `content-encoding` and `content-length` from the returned headers, or mark the body as decoded. | open | reviewer PoC (`regress.py`) |
| 10 | low | **The bounded-decompression path has no memory test.** `test_a_nested_gzip_bomb_never_grows_past_the_cap` accepts `reason in {"too-large", "encoding"}`, and the fixture sends `Content-Encoding: gzip, gzip`. It therefore passes on the stacked-encoding refusal alone, and would still pass if the `max_length` argument were removed. The single-layer bomb test (`mib=50`) has no memory assertion. **Fix:** assert `reason == "encoding"` for the nested case. Add a single-layer bomb test, ideally one large raw chunk through `MockTransport`, that asserts a tracemalloc peak of a small multiple of the cap. Add trailing-data, multi-member and truncated-stream tests (findings 8 and 9). | open | code reading and PoC (`mem.py`) |
| 11 | info | (a) Make the `_tls` hook fail closed: in `fetch`, refuse an `SSLContext` whose `verify_mode` is not `CERT_REQUIRED` or whose `check_hostname` is false, and accept no other `bool` than `True`. Also correct its docstring, which says "the system's trusted authorities", whereas httpx's `True` uses its bundled CA file. (b) Let the timeout detail say whether DNS or the server was slow, for operators. (c) Consider refusing all of reserved `::/8` (for example `0:0:0:1::1`), not only `::/64`. (d) The production constructor still takes `transport`, which, when given, bypasses `trust_env`, `limits` and `verify`. It is not reachable from configuration; keep it so, or move it to the test subclass as was done for pinning. (e) Peak memory is about twice the cap, because `bytes(out)` copies the bytearray. Return `bytes` from a single buffer, or accept and document the figure. | n/a | n/a |

**Sign-off at re-verification:** not signed off; one high open (8, a regression from the finding 1 fix). Findings 1 to 6 are closed. Findings 9 and 10 are low, and 11 is info. Sign-off can follow once 8 is fixed and tested as described, with 10 at least covering finding 8. · M3 SafeFetcher independent review · 2026-11-16

### Evidence (re-verification)
1. `bomb2.py` against the fixture server, 1 MiB cap:
   - `page_v1.html`: ok, RSS 36 MiB.
   - `/bomb/gzip?mib=1024`: `too-large`, 38 MiB.
   - `/bomb/gzip?mib=4096`: `too-large`, 38 MiB.
   - `/bomb/gzip?mib=400&nested=1`: `encoding`, 36 MiB.
   - `/pages/zip_bomb.html.gz?mib=4096`: `too-large`, 38 MiB.
2. `mem.py`, 10 MiB cap, single-layer gzip in one raw chunk:
   - 1 GiB in 1019 KiB: `too-large`, peak traced 21.2 MiB.
   - 4 GiB in 4076 KiB: `too-large`, peak traced 24.0 MiB.
3. `trail.py`: a gzip member plus 200 MiB of trailing raw bytes, 1 MiB cap: ok with a 5-byte body, peak traced 399 MiB. As a direct zlib check, `decompress(b"tail")` after EOF adds to `unused_data`.
4. `regress.py`, decoder cases:
   - Two members, in one chunk or split into chunks: 13 bytes (the first member only).
   - First member followed by trailing garbage: 13 bytes (the garbage is ignored).
   - Second member a 1 GiB bomb: 13 bytes (not decoded).
   - Truncated gzip: ok with 100,000 bytes and no error.
   - Raw deflate: `encoding`.
   - `x-gzip`, `GZIP` and `identity, gzip`: decoded.
   - In every decoded result, the `content-encoding` header is still present.
5. `regress.py`, DNS cases with a 0.2 s deadline:
   - Slow resolver: `timeout` after 0.2 s.
   - NXDOMAIN: `dns`.
   - Private answer: `private-address`.
6. `addr.py` and `regress.py`, addresses: see the verdict for finding 2 above. Also refused: `::ffff:8.8.8.8`, `100::1`, `fe80::1`, `ff0e::1` and `2002:808:808::1`. Passes: `0:0:0:1::1`.
7. `misc.py`: the slow-DNS probe now raises `FetchRefusedError("timeout")`, where before it returned 200 after 2.0 s.

## Author follow-up 2 (findings 8 to 11, pending re-verification)
- **Finding 8 (high):** decoding moved into `_BodyDecoder`. Anything left after the end of a compressed stream is handled in the same call, so it never accumulates in zlib's `unused_data`: another gzip member (it must start with the gzip magic) is decoded, and any other trailing data is refused with reason `encoding`. Raw bytes from the network also count against `max_bytes`, whatever the encoding.
  - Tests: `test_data_after_a_gzip_body_is_refused_without_piling_up` (50 MiB of junk in 1 KiB chunks after a tiny gzip body; refused, tracemalloc peak under 16 MiB) and `test_raw_bytes_count_against_the_cap_too`.
- **Finding 9 (low):**
  - several gzip members are decoded in full;
  - a stream that ends early is refused ("ends early");
  - trailing data after gzip or deflate is refused;
  - raw deflate without a zlib header is accepted again;
  - a damaged gzip body is refused;
  - a decoded body no longer carries `content-encoding` or `content-length` in the returned headers.
  - Test: `test_gzip_members_truncation_and_deflate_forms`.
- **Finding 10 (low):** the nested-bomb test now asserts `encoding` only. A new `test_a_single_layer_gzip_bomb_stays_within_the_cap` fetches `/bomb/gzip?mib=400` with a 1 MiB cap and asserts `too-large` with a peak under 32 MiB.
- **Finding 11 (info):**
  - `_checked_tls` refuses any context without `CERT_REQUIRED` and `check_hostname` (`test_a_tls_context_that_checks_less_is_refused`), and the docstring now names httpx's default authorities.
  - Timeouts say whether DNS or the server was slow (`test_a_slow_name_server_is_named_in_the_timeout`).
  - `::/8` was **not** adopted: the NAT64 prefix `64:ff9b::/96` lies inside it, so it would block every NAT64 answer. `::/64` stays, and NAT64 addresses are judged by their embedded IPv4 address (`64:ff9b::808:808` passes).
  - The `transport` constructor argument and the roughly twice-the-cap peak are left as they are.

## Re-verification 2 (`sec/M3-safe-fetch-followups` at `cea315f`)
**Method:** I read `git diff HEAD~1 HEAD` and re-ran the two test files: 102 passed, and coverage of `regwatch.capture.safe_fetch` is 100 percent (265 statements, 78 branches). I re-ran `trail.py`, `mem.py` and `regress.py` with `MockTransport`, and `bomb2.py` against a separately started fixture server on 127.0.0.1, which was stopped afterwards. A new script, `/tmp/m3review/edges.py`, probes the `_BodyDecoder` edge cases requested. No external network was used, the Docker stacks were not touched, and no file other than this record was changed.

### Verdict per finding
| # | Verdict | Evidence |
| --- | --- | --- |
| 8 | closed | `trail.py`: a gzip member followed by 200 MiB of raw bytes with a 1 MiB cap is now refused (`too-large`, from the raw-byte cap at `fetch.py:200`). Peak traced memory is under 1 MiB, where it was 399 MiB. After a stream ends, leftover input is taken from `unused_data` within the same call (`fetch.py:85`) and is either decoded as the next gzip member or refused. The author's test uses 50 MiB in 1 KiB chunks and asserts a peak under 16 MiB. |
| 9 | closed, with two new low issues in deflate handling (finding 12) | `regress.py`: two members, in one chunk or split, decode to all 26 bytes. Trailing garbage after gzip is `encoding`. A second member holding a 1 GiB bomb is `too-large`. Raw deflate decodes. The decoded result no longer carries `content-encoding` or `content-length`. `edges.py`: a gzip stream genuinely cut short (random data cut at 3,000 bytes) is refused with "ends early". My first-round truncation probe had cut a stream that was already complete, so its "accepted" result was not evidence. |
| 10 | closed | The nested test now asserts `encoding` only. `test_a_single_layer_gzip_bomb_stays_within_the_cap` asserts `too-large` and a peak under 32 MiB, so it now exercises the `max_length` path. `mem.py`: 1 GiB and 4 GiB single-layer bombs in one raw chunk with a 10 MiB cap peak at 21.2 MiB and 24.0 MiB. `bomb2.py`: every fixture bomb peaks at 36 to 38 MiB RSS. |
| 11 | closed; `::/8` decision accepted | (a) `_checked_tls` (`fetch.py:180`) accepts only `True`, or an `SSLContext` with `CERT_REQUIRED` and `check_hostname`. `False` or a weaker context raises before any connection, and the docstring is corrected. (b) The timeout detail now reads "DNS for `<host>`…" or "the server at `<host>`…" (`regress.py`: "DNS for example.org took longer than 0.2 s"). NXDOMAIN is still `dns`, and a private answer is still `private-address`. (c) **The author is right, and my suggestion in 11(c) was wrong.** `64:ff9b::/96` (first 16 bits `0x0064`) lies inside `::/8`, so refusing all of `::/8` would block every NAT64 answer, including `64:ff9b::808:808`. Keeping `::/64` plus the NAT64 embedded-address check is correct. What is left is unallocated reserved space such as `0:0:0:1::1`, which is not routable. If wanted, refuse `::/8` minus `64:ff9b::/96` and `64:ff9b:1::/48`; this is optional. (d), (e): left as they are, accepted as info. |

### `_BodyDecoder` regression checks requested
- **A gzip member boundary split across chunks:** correct. I tried every 2-way split of a two-member body: all 47 split points decode to the full 26 bytes. These also decode correctly:
  - one byte per chunk;
  - a split leaving a one-byte remainder (`\x1f` | `\x8b…`);
  - a three-way split of member 1 | `\x1f` | rest.

  A lone trailing `\x1f` at the end of the body is refused through `_pending` in `finish`. An empty body with `Content-Encoding: gzip` returns `b""`.
- **Deflate detection on a first chunk of one byte:** a defect, see 12(a). With only one byte, the zlib-header test (`fetch.py:65`, `len(data) >= 2`) fails, so a zlib-wrapped body is decoded as raw deflate and refused as damaged. This happens both when the first chunk is one byte and when every chunk is one byte. Raw deflate in one-byte chunks decodes correctly.
- **Could the raw-byte cap refuse legitimate bodies?** Only within about 0.03 percent of the cap. A 1,048,476-byte incompressible body (100 bytes under a 1 MiB cap) gzips to 1,048,814 bytes and is refused as `too-large`, while the same body sent uncompressed passes. Compressible content is always smaller raw than decoded. At the 10 MB default this affects only incompressible bodies within about 3 KB of the cap. I accept this; see 13(a).
- **The `max(1, …)` room argument:** correct. The caller passes `limit - len(out) ≥ 0`, and `feed` stops as soon as its output exceeds `room`, so `room - len(out) + 1` is always at least 1. The `max` is a guard against passing `0`, which zlib treats as "no limit". `feed(…, room=0)` returns exactly 1 byte, which the caller then refuses.

### New findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 12 | low | **Two defects in deflate handling in `_BodyDecoder`; neither affects memory or address safety.**<br>(a) A zlib-wrapped `deflate` body whose first raw chunk is one byte is misdetected as raw deflate and refused (`encoding`, "Error -3"), so a legitimate body is lost. Over chunked transfer, a 1-byte first chunk is unusual but legal. **Fix:** for `deflate`, hold back a first chunk shorter than 2 bytes in `_pending`, as gzip already does, and decide only when 2 bytes are available.<br>(b) After a deflate stream ends exactly at a chunk boundary, `_d` is reset to `None` (`fetch.py:88`), so the next chunk starts a *new* deflate stream. A second zlib stream in the next chunk is decoded and appended (the `SMUGGLED` probe), and junk in the next chunk is reported as "ends early" rather than as trailing data. That is inconsistent with the stated rule that trailing data after deflate is refused. It is bounded by both caps. **Fix:** record that a deflate stream has ended, and refuse any later byte with "data after the end of the deflate body". Add tests for both cases. | open | reviewer PoC (`edges.py`) |
| 13 | info | (a) The raw-byte cap equals `max_bytes`, so incompressible gzip bodies within gzip's overhead of the cap (about 0.03 percent, plus 18 bytes) are refused. A raw cap of `max_bytes + max_bytes // 512 + 64` would remove this without weakening finding 8. (b) Trailing NUL padding after a gzip body, which gzip(1) and Python's `gzip` module tolerate, is refused. This is rare on HTTP and acceptable. (c) Decoding many back-to-back empty gzip members copies `unused_data` once per member, so cost grows with the square of the chunk size. It is negligible at httpcore's 64 KiB reads: 10 MiB of empty members in 64 KiB chunks took 0.9 s in total, about 0.01 s per chunk. A 1 MiB chunk, which only a custom transport can deliver, blocks the loop for 0.81 s. No change needed while production uses the default transport (see 11(d)). | n/a | n/a |

**Sign-off at re-verification 2:** signed off; no high or critical open. Findings 1 to 11 are closed. Finding 12 (low) is open and tracked for a follow-up, and finding 13 is info. Acceptance criteria 4 and 5 (robots.txt, per-host rate limits) remain outside this review. · M3 SafeFetcher independent review · 2026-11-16

### Evidence (re-verification 2)
1. `trail.py`: a gzip member plus 200 MiB of trailing raw bytes, 1 MiB cap: refused `too-large`, peak traced under 1 MiB.
2. `mem.py`, 10 MiB cap, single-layer bomb in one raw chunk:
   - 1 GiB: `too-large`, 21.2 MiB.
   - 4 GiB: `too-large`, 24.0 MiB.
3. `bomb2.py` against the fixture server, 1 MiB cap:
   - `page_v1.html`: ok, RSS 36 MiB.
   - `/bomb/gzip?mib=1024`: `too-large`, 38 MiB.
   - `/bomb/gzip?mib=4096`: `too-large`, 38 MiB.
   - `/bomb/gzip?mib=400&nested=1`: `encoding`, 36 MiB.
   - `/pages/zip_bomb.html.gz?mib=4096`: `too-large`, 38 MiB.
   - `/redirect/chain/3`: ok, 36 MiB.
4. `regress.py`:
   - Two members: 26 bytes.
   - Trailing garbage: `encoding`.
   - Bomb as the second member: `too-large`.
   - Raw deflate: ok.
   - `content-encoding` is absent from every decoded result.
   - Exactly at the cap: ok. One byte over: `too-large`.
   - Slow DNS: "DNS for example.org took longer than 0.2 s". NXDOMAIN: `dns`. Private answer: `private-address`.
   - `::ffff:8.8.8.8` and `::1:0:0:1` are refused. `0:0:0:1::1` and `64:ff9b::808:808` pass.
5. `edges.py`, gzip:
   - All 2-way splits: ok.
   - One-byte remainder: ok. One byte per chunk: ok. Three-way split: ok.
   - A lone trailing `\x1f`: refused. NUL padding: refused.
   - Empty body: `b""`.
   - Truncated stream: refused, "ends early".
6. `edges.py`, deflate:
   - zlib-wrapped, one chunk: ok.
   - zlib-wrapped, first chunk one byte: **refused** (12a).
   - zlib-wrapped, one byte per chunk: **refused** (12a).
   - Raw, one byte per chunk: ok.
   - zlib plus junk in the same chunk: refused.
   - zlib plus a second zlib stream in the next chunk: **decoded and appended** (12b).
   - zlib plus junk in the next chunk: refused as "ends early" (12b).
7. `edges.py`, caps and cost:
   - Incompressible body 100 bytes under a 1 MiB cap, gzipped: `too-large`. The same body uncompressed: ok.
   - Empty-member decoding: 0.01 s per 64 KiB chunk, 0.81 s for a 1 MiB chunk, and 0.9 s for 10 MiB in 64 KiB chunks.
   - `feed(room=0)` returns 1 byte.

## Author follow-up 3 (finding 12)
- **12 (a):** a first chunk shorter than 2 bytes is held back for deflate as well as gzip, so the zlib-header check always sees two bytes. A one-byte first chunk of a zlib-wrapped body decodes.
- **12 (b):** once the deflate stream has ended, any later byte is refused ("data after the end of the deflate body"), including when the stream ended exactly at a chunk boundary.
- A lone held-back byte at the end of a deflate body is refused as "ends early".
- Test: `test_deflate_split_at_awkward_places`.
- **13 (info):** no change.

## Slices 3 and 4: robots.txt and per-host rate limits
**Scope:**
- **Slice 3**, `feat/M3-robots` (`git diff docs/M3-components...feat/M3-robots`, commit `c719f36`):
  - `safe_fetch/robots.py` (`RobotsPolicy`);
  - `SafeFetcher.with_limits`;
  - `tests/unit/test_safe_fetch_robots.py`.
- **Slice 4**, `feat/M3-rate-limit` (`git diff feat/M3-robots...feat/M3-rate-limit`, commit `0c7a749`):
  - `safe_fetch/rate.py` (Lua slot script, `ValkeyRateLimiter`, `MemoryRateLimiter`, `wait_turn`);
  - `safe_fetch/capture.py` (`CaptureFetcher`);
  - the `before_hop` argument of `SafeFetcher.fetch`;
  - `tests/unit/test_safe_fetch_rate.py`, `tests/integration/test_valkey_rate.py`.

Also checked: the M3 acceptance criteria 4 and 5, RFC 9309, 8.3 (politeness), and the follow-up 3 note for finding 12, whose deflate fixes are in the base and covered by the passing tests. · **Reviewer session label:** M3 SafeFetcher independent review · **Date:** 2026-11-16 · **Author sessions excluded from review:** yes

**Method:**
- **Code and tests:** I read both diffs and protego 0.7.0's matching. I ran all four SafeFetcher unit files: 122 passed, and coverage of `regwatch.capture.safe_fetch` is 100 percent (397 statements, 110 branches). I ran `tests/integration/test_valkey_rate.py` (2 passed; its throwaway container was removed).
- **Probes:** scratch scripts in `/tmp/m3review/`:
  - `robots_probe.py`: protego and RFC 9309 behaviour, and hostile Crawl-delay values;
  - `capture_probe.py`: CaptureFetcher with `MockTransport` and a fake clock;
  - `valkey_probe.py`: the Lua script against a throwaway Valkey of my own (`regwatch-review-valkey-*`). It ran from the locally present pinned image `valkey/valkey:9@sha256:3add1a33…`, bound to 127.0.0.1 only, and was removed afterwards.
- **Not touched:** the `regwatch-qa-*` stacks, including their Valkey. No external network was used, and no image was pulled. Only this record was changed.

### Data flows touched
- **Worker to external hosts:** `GET /robots.txt` per origin through SafeFetcher (512 KiB cap, 30 s), then the page hops.
- **Worker to Valkey:** one `EVALSHA` per hop on key `regwatch:rate:<host>`, run on Valkey's clock.
- **Hostile inputs:**
  - robots.txt content: groups, rules, Crawl-delay and size;
  - the status code of the robots.txt answer;
  - redirect targets, which choose which origins and hosts get robots fetches, cache entries and Valkey keys.
- **Admin input (future routes):** the per-source robots override reason, and the job's rate.

### STRIDE (slices 3 and 4)
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Tampering | robots.txt parsing | protego; RFC 9309 status rules; group merging, longest match and percent-encoding are correct | Substring matching of group names; files over 512 KiB are treated as unreadable | 20 |
| Repudiation | robots override | A reason is required (an empty or blank reason gives `ValueError`) | Permission and audit are not in this layer | 22 |
| Information disclosure (SSRF) | `before_hop` on redirect targets | SafeFetcher still refuses private addresses (robots fetch and hop) | The refusal is reported as `robots`; with an override, a rate slot is used up on the private host | 19 |
| Denial of service | Lua slot script, robots cache, Crawl-delay | Atomic script; `max_wait_s`; a 10,000-origin cache limit | Refused takes still reserve slots; the key expires before its reservations, so limits are exceeded; the cache can grow to about 122 GiB; a huge Crawl-delay raises a raw `ResponseError` and creates keys that live for decades | 14, 15, 16, 17 |
| Elevation of privilege | override | Only a non-empty reason string | Who may set it is enforced elsewhere (8.3 `sources.override_robots`) | 22 |

### Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 14 | medium | **A refused take still reserves a slot, so contention locks a host out for longer and longer.** `rate.py:26-34` always runs `SET … free + interval`. `wait_turn` (`rate.py:72-83`) only refuses afterwards. **Failure case** (`valkey_probe.py`, interval 6 s, `max_wait_s` 120): with 21 slots already reserved, 50 more attempts are all refused, yet they move next-free by 300 s, so the next caller must wait 426 s. Every job that tries that host is refused until the key expires (finding 15). Several sources on one regulator's site at one scheduler tick (the M3 load test: 100 jobs due at once) starve each other, and the "tried again on the next run" retries add more reservations. **Fix:** pass `max_wait_ms` to the script. When `free - now > max_wait_ms`, return the wait (or -1) **without** `SET`. `wait_turn` then refuses without consuming a slot. Test it against Valkey: refused attempts leave the key unchanged. | open | reviewer PoC on Valkey |
| 15 | medium | **The key's lifetime is shorter than the reservations it holds, so the limit resets and is exceeded (acceptance 5).** `rate.py:32` sets `PX interval + 60000`, counted from *now*. The stored value `free + interval` can be up to `max_wait_s + interval` in the future (or further, finding 14). **Failure case** (`valkey_probe.py`):<br>- Five takes at 30 s leave next-free 150 s ahead with a TTL of 90 s.<br>- With interval 1 s and 70 queued takes (horizon 70 s, TTL 61 s), a new caller at t=62 s waits **0 s**, while slots up to t=70 s are still held by sleeping workers. Two requests then go to the host in the same second.<br>At 10 a minute (interval 6 s, horizon up to 126 s, TTL 66 s), a lull of 66 s with no take after a burst of queued single-page jobs lets new jobs start a fresh schedule alongside the 9 still-queued slots. The host then gets up to about 20 requests in a minute, against a limit of 10. **Fix:** expire relative to the reservation, `PX (free + interval - now) + 60000` (or `PXAT`), so the key outlives every slot it hands out. Add an integration test that queues past the TTL and asserts no wait is shorter than the queue. | open | reviewer PoC on Valkey |
| 16 | medium | **The robots cache is bounded by entry count, not by memory: about 12.5 MiB per large file and up to about 122 GiB in total.** `robots.py:62-64` clears the cache above 10,000 origins, but each entry is a parsed `Protego` object. A 500 KiB robots.txt (24,000 rules) takes about 12.5 MiB once parsed. **Failure case** (`capture_probe.py`): 100 origins under a wildcard domain, each serving a 500 KiB file, hold 1,245 MiB. A hostile page that redirects to fresh subdomains adds up to 5 origins per fetch (the redirect cap), and they stay cached for 24 h. A 200-page crawl of such a site can exhaust a worker's memory long before the 10,000-entry limit is reached. **Fix:** bound the cache by size, for example an LRU with a byte budget estimated from body length (say 64 MiB per process). Alternatively cap rules per origin, or keep only the matching group's rules for `regwatch` and `*`. Add a test with many large files that asserts the budget. | open | reviewer PoC |
| 17 | low | **A huge Crawl-delay breaks the fetch with a raw Valkey error, or creates a key that lives for decades.** protego accepts any finite float (`Crawl-delay: 1e20` gives 1e20), and `interval` passes it through (`rate.py:43-47`). **Failure case** (`valkey_probe.py`): `1e20` makes the script fail with `redis.exceptions.ResponseError: value is not an integer or out of range`, which escapes `CaptureFetcher.fetch` as a non-`FetchRefusedError`, so the job errors rather than recording a refusal. `Crawl-delay: 1e9` gives the key a TTL of 32 years. Every hostile host reached through redirects can leave such a key, so the key count grows without expiry. `inf`, `nan`, negative and non-numeric values are dropped by protego, which is fine. **Fix:** clamp Crawl-delay. If it is above `max_wait_s` (or a ceiling such as 1 day), refuse with `robots` or `rate-limited` without calling Valkey, and also cap the interval passed to the script. Add a test with hostile values. | open | reviewer PoC on Valkey |
| 18 | low | **robots.txt requests bypass the rate limit, so acceptance 5 is exceeded by one.** `RobotsPolicy._rules` fetches through a plain `SafeFetcher` (`robots.py:51`), with no slot. **Failure case** (`capture_probe.py`): 30 pages at 10 a minute with a real robots.txt made 31 requests, and the worst minute had **11** requests to the host. It is 10 only because `test_a_200_page_crawl_keeps_to_10_per_minute` stubs robots out. The robots fetch also comes back every 15 minutes after a failure. **Fix:** take the host's slot before a robots fetch (pass the limiter to `RobotsPolicy`, or fetch robots inside `before_hop` after `wait_turn`). Let the acceptance test count robots.txt. | open | reviewer PoC |
| 19 | low | **A redirect to a private address is reported as `robots`, and with an override it first uses up a rate slot.** `before_hop` (`capture.py:45-49`) runs before SafeFetcher's own checks on the hop (`fetch.py:288`). The robots fetch for `http://evil.example/` is refused at the address, and that is cached as "disallow everything". **Failure case** (`capture_probe.py`): the refusal reads `robots` ("robots.txt could not be read"), not `private-address`, so SSRF attempts disappear from any monitoring keyed on the reason, and a disallow entry is cached for the internal host. With `robots_override`, the reason is right, but `wait_turn` has already reserved a slot on `evil.example`, and could have slept up to 120 s first. **Fix:** in `before_hop`, run `parse_target` and `resolve` (the policy check) before robots and the rate limit. Alternatively let `RobotsPolicy` re-raise address and scheme refusals unchanged rather than caching them. Test it with the private-redirect fixtures through `CaptureFetcher`. | open | reviewer PoC |
| 20 | low | **Deviations from RFC 9309.**<br>(a) A robots.txt larger than 512 KiB is refused as too large and treated as **disallow everything**, retried every 15 minutes, so such a site is never captured. RFC 9309 2.5 says crawlers SHOULD parse at least 500 KiB and may ignore the rest. Confirmed with a valid 600 KB `Allow: /` file, which is refused. **Fix:** read the first 512 KiB and parse that; this needs a "truncate" mode in SafeFetcher's body cap for this caller.<br>(b) protego matches group names by substring: `User-agent: reg` applies to `regwatch`. RFC 9309 2.2.1 matches the product token. Low impact; note it in the tests or match exactly.<br>(c) A 429 answer for robots.txt is a 4xx, so everything is allowed. That is RFC-compliant, but a site that is throttling us is then crawled unrestricted. Consider treating 429 like 5xx. | open | reviewer PoC |
| 21 | low | **The tests do not prove acceptance 5 or the Valkey behaviour.**<br>- The 200-page test runs `MemoryRateLimiter` in one sequential loop, with robots stubbed out and `MockTransport` rather than the local test server the criterion names. One worker in a loop cannot exceed the limit whatever the limiter does.<br>- `MemoryRateLimiter` has no expiry and works in float seconds, so it cannot show findings 14 or 15.<br>- The Valkey tests check spacing and atomicity only. They do not cover refusals, the TTL against the horizon, workers taking again over time, or hostile Crawl-delay. The TTL assertion is loose (up to 72 s). The "two clients" share one connection pool, which is fine for atomicity but is not two workers.<br>- The robots tests do not cover group merging, percent-encoding, the size limit, a private redirect target, or the cache's memory. The fixture Crawl-delay test asserts only `is not None`.<br>**Fix:** run the acceptance test through `CaptureFetcher` against the fixture server's robots and pages, with `ValkeyRateLimiter`, several concurrent workers, and robots.txt counted. Add the tests named in findings 14 to 20. | open | code reading |
| 22 | info | (a) **Override:** a reason that is empty or only whitespace raises `ValueError`, so the override cannot be used without one. But any one-character reason passes, its length is unbounded, and the permission check (`sources.override_robots`) and the audit row are not in this layer. Re-check them when the source routes and run records land. The override also drops the site's Crawl-delay, leaving only the job's rate; decide whether that is intended. (b) **Rounding:** `round(interval_s * 1000)` can shorten the interval by up to 0.5 ms (60/7 s gives 8,571 ms against 8,571.43); use `math.ceil`. A rate over 120,000 a minute rounds to 0 ms, which means no limit; bound `rate_per_minute` when it is configured. `rate_per_minute=0` falls back to the default silently (`capture.py:43`, `or`). (c) **The clock and atomicity are fine:** one script, with `TIME` read inside it, is atomic and safe under Valkey 9's effect replication. The milliseconds come from seconds × 1000 plus `floor(µs/1000)`, and Lua's number formatting is exact for 13-digit millisecond values. (d) If Valkey is unreachable, `redis.ConnectionError` escapes. This fails closed, but it is not a refusal. (e) The robots cache belongs to each `CaptureFetcher`, so connectors should share one per worker. Concurrent checks of one origin each fetch robots.txt. (f) `with_limits` makes a shallow copy, which is correct; resolver, transport and subclass hooks are kept. | n/a | n/a |

### Checked and found fine
- **RFC 9309 status rules:** 2xx is parsed. Any 4xx, including 401, 403, 404 and 410, allows everything. 5xx, an unreachable server, a refusal by SafeFetcher, or a 3xx without `Location` disallows everything and is retried after 15 minutes. Up to 5 redirects of robots.txt itself are followed.
- **Cache:** keyed by origin (scheme, host and port), held for at most 24 h on the monotonic clock.
- **protego (`robots_probe.py`):** the `regwatch` group wins over `*`. Group names match case-insensitively. Two `regwatch` groups are merged. Several `User-agent` lines may share one group. The longest match wins, and equal-length Allow and Disallow ties resolve to Allow. Percent-encoded and UTF-8 paths match each other. `$` anchors and `*` wildcards work. A rule with 14 wildcards against a 1,900-character path takes under 10 ms, so there is no regex blow-up.
- **Crawl-delay:** returned as a float, then used as `max(60/rate, delay)`. protego drops `inf`, `nan`, negative and non-numeric values.
- **Every hop:** `before_hop` runs before every hop, the first one and each redirect target (`fetch.py:288`). Robots and the rate limit both apply to the target host. `test_robots_and_rates_apply_to_every_redirect_hop` shows a redirect target's robots.txt refusing.
- **Override:** `robots_override` skips only robots. The rate limit still applies (`test_an_override_skips_robots_but_not_the_rate`).
- **Lua script:** atomic. It uses Valkey's clock, so workers on different machines share one limit. Twenty concurrent takes got twenty distinct slots (integration test). A missing key starts at now, and a stale next-free value is raised to now.
- **`max_wait_s`:** a wait above it is refused with `rate-limited` without sleeping. A wait at or under it is slept through the injectable `sleep`.
- **Host keys:** `regwatch:rate:` plus the normalised IDNA host (no port). Every key carries a TTL of at least 60 s, so a flood of ordinary hosts expires on its own (except finding 17).

**Sign-off for slices 3 and 4:** not signed off; three medium findings open:
- 14 and 15: acceptance 5 can be exceeded, and hosts starved, under concurrent load;
- 16: hostile robots files can exhaust a worker's memory.

Findings 17 to 21 are low and 22 is info. Sign-off can follow when 14 to 16 are fixed with Valkey-backed tests and 21's acceptance test covers them. · M3 SafeFetcher independent review · 2026-11-16

### Evidence (slices 3 and 4)
1. **Tests:** the four SafeFetcher unit files: 122 passed, 100 percent (397 statements, 110 branches). `-m integration tests/integration/test_valkey_rate.py`: 2 passed, and no test container was left behind.
2. **`valkey_probe.py`** (throwaway Valkey on 127.0.0.1, removed afterwards):
   - 50 refused attempts move next-free by 300 s, and the next caller waits 426 s (finding 14).
   - Five 30 s takes leave next-free 150 s ahead with a TTL of 90 s.
   - With interval 1 s and 70 takes (horizon 69.99 s, TTL 61 s), a caller at t=62 s waits 0.0 s (finding 15).
   - An interval of `1e20` raises `ResponseError: value is not an integer or out of range`.
   - An interval of `1e9` gives a TTL of 32 years (finding 17).
   - 60/7 s is sent as 8,571 ms.
3. **`capture_probe.py`:**
   - A private redirect target gives `robots` without an override and `private-address` with one, and a slot is reserved for `evil.example` (finding 19).
   - 30 pages at 10 a minute with a real robots.txt make 31 requests, with a worst minute of 11 (finding 18).
   - robots.txt answered with 429 or 401 allows everything. A 600 KB valid file is refused (finding 20).
   - 100 origins with 500 KiB files hold 1,245 MiB in the cache (finding 16).
4. **`robots_probe.py`:**
   - Group `reg` applies to `regwatch`, and `regwatch-bot` does not. `RegWatch` matches. Merged groups, longest match, the Allow tie, percent-encoding, UTF-8 and `$` behave as RFC 9309 describes.
   - Crawl-delay: `inf`, `nan`, `-5`, `abc` and `1e400` give None; `1e20` gives 1e20.
   - Wildcard matching takes 0.00 s.
   - A 500 KiB file (24,336 lines) parses to 12.9 MiB.

### Author follow-up (`sec/M3-capture-followups`, pending re-verification)
- **14 (medium):** the Lua script takes the longest acceptable wait (`ARGV[2]`) and returns -1 without reserving anything when the wait is longer, so refusals never push slots back. `MemoryRateLimiter` does the same. Tests: `test_refused_attempts_reserve_nothing` (unit) and `test_refusals_reserve_nothing_and_keys_outlive_their_slots` (Valkey).
- **15 (medium):** the key's expiry is the last reserved slot plus a minute (`nxt - now + 60000`), so queued slots never expire early. The Valkey test asserts a TTL beyond 70 queued slots.
- **16 (medium):** the robots cache is an LRU bounded by `CACHE_BUDGET`, 4 MiB of parsed robots.txt text (about 100 MB once parsed, by the review's measurement), with the least recently used evicted first. Entries without rules hold no bytes, and the 10,000-entry cap stays. Test: `test_the_cache_is_bounded_by_bytes_least_recent_first`.
- **17 (low):** `interval` is clamped to between 1 ms and `MAX_INTERVAL_S` (an hour), so a hostile Crawl-delay can neither break the script nor leave keys that live for years. Intervals round up (`ceil`). Test: `test_huge_crawl_delays_and_rates_are_clamped`.
- **18 (low):** a robots.txt fetch takes a rate slot of its own when the origin is not cached. Test: `test_robots_fetches_take_a_rate_slot` (30 pages plus robots.txt at 10 a minute: at most 10 in any minute).
- **19 (low):** `before_hop` runs `SafeFetcher.check_url`, which parses the URL and checks its addresses, before robots and the rate slot. A private redirect is reported as `private-address` and takes no slot. Test: `test_a_private_redirect_is_reported_as_such`.
- **20 (low):**
  - robots.txt is read up to 2 MiB and the first 500 KiB are parsed (`test_large_robots_files_are_parsed_up_to_500_kib`);
  - a 429 means try later (`test_429_means_try_later`);
  - protego's substring matching of `User-agent` names stays as it is and is recorded in BL-87.
- **21 (low):** `test_acceptance_5_with_valkey_and_the_fixture_server` runs 30 concurrent fetches plus robots.txt through the real Valkey limiter and the fixture server at 600 a minute, and asserts the 31 requests took at least 3 s.
- **22 (info):** a rate of 0 is no longer read as "use the default"; it raises. The override's reason length, its permission and its audit row are checked when the source routes land (M3 routes slice).

### Re-verification (slices 3 and 4, `sec/M3-capture-followups` at `22ceaef`)
**Method:**
- **Code and tests:** I read `git show 22ceaef`. All four SafeFetcher unit files pass (129 tests), and coverage of `regwatch.capture.safe_fetch` is 100 percent (425 statements, 116 branches). `tests/integration/test_valkey_rate.py` passes (4 tests); its container was removed.
- **Probes rerun:** `robots_probe.py`. I also ran `capture_probe2.py` and `valkey_probe2.py`, copies adapted to the new `take(host, interval_s, max_wait_s)` signature.
- **New probes:** `concurrency.py`, plus the LRU, deadline and truncation checks in `capture_probe2.py`.
- **Isolation:** the Valkey probe ran against a throwaway container of my own, from the locally present pinned image, bound to 127.0.0.1 and removed afterwards. The `regwatch-qa-*` stacks were not touched. No external network was used, and no image was pulled. Only this record was changed.

| # | Verdict | Evidence |
| --- | --- | --- |
| 14 | closed | On Valkey, 50 refused attempts move next-free by **0 s** (it was 300 s). The boundary is right: a wait exactly equal to `max_wait` is accepted, and a wait over it returns -1 and leaves the stored value unchanged. `MemoryRateLimiter` does the same. |
| 15 | closed | Five takes at 30 s leave next-free 150.0 s ahead with a TTL of 210.0 s, which is the horizon plus 60 s (`nxt - now + 60000`). With interval 1 s, 70 queued takes and 62 s of sleep, a new caller waits **7.9 s**, correctly behind the queue; before, it waited 0 s. The key can never expire before the slots it hands out. |
| 16 | closed | `CACHE_BUDGET` bounds the text held, and the loop evicts the least recently used entries. 100 origins with 500 KiB files each leave 8 cached entries holding 3.91 MiB of text. Measured memory is 112 MiB at worst (wildcard rules), 45 MiB for `Allow:/` lines and 17 MiB for many groups, against 1,245 MiB before. The budget applies per `RobotsPolicy`, so connectors should share one per worker (22(e)). |
| 17 | closed | `interval` clamps to between 1 ms and 3,600 s. A Crawl-delay of 1e20 reaches the script as 3,600,000 ms, with a key TTL of 3,660 s, and the `ResponseError` no longer occurs through `CaptureFetcher`. `ValkeyRateLimiter.take` itself still passes whatever it is given: called directly with 1e20 it still raises `ResponseError`. That is defence in depth only; see 25(b). |
| 18 | closed, with a regression (25) | 30 pages at 10 a minute with a real robots.txt: 31 requests, with a worst minute of **10**. |
| 19 | closed, with a regression (23) | A private redirect target is now reported as `private-address`, with or without an override, and no slot is taken for `evil.example`. |
| 20 | (a) closed, with a regression (24); (b) deferred to BL-87, accepted; (c) closed | (a) A valid 600 KB `Allow: /` file is now honoured. Files over 2 MiB are still disallow-all, which is acceptable because the RFC requires parsing only 500 KiB. (c) A 429 answer gives `robots` ("could not be read"), and a 401 still allows everything. |
| 21 | partly closed | Added: Valkey tests for findings 14 and 15, a private-redirect test, a robots-slot test, a byte-budget LRU test, and a CaptureFetcher test with the fixture server and real Valkey. **What is left:** `test_acceptance_5_with_valkey_and_the_fixture_server` asserts only the request count (31) and a total of at least 2.9 s, not "at most N in any window". The test would still pass if requests bunched at the end. Record a timestamp per request (the fixture server's `RecordedRequest` has none), or time them in a transport wrapper, and assert the sliding-window maximum. |
| 22 | closed for (b) and the rate-0 fallback; (a) deferred to the M3 routes slice | A rate of 0 now raises, and intervals round up (`ceil`, 6.0004 s gives 6,001 ms). The override's permission, audit row and reason length are still to be checked when the source routes land. |

### Regression checks requested
- **`check_url`'s second DNS lookup:** it opens **no rebinding gap**. `check_url` (`fetch.py:184-188`) only decides whether to continue. `_hop` resolves again, checks every answer again, and connects to an address from its own lookup (`fetch.py:241`). A name that answers public to the first lookup and private to the second is refused at the hop. It is harmful in two smaller ways (finding 23). The lookup runs **outside any deadline**: with a 1 s resolver and a 0.2 s hop deadline, the fetch took 3.2 s before refusing. And the first hop to an uncached origin makes 3 lookups (check, robots fetch, hop).
- **LRU accounting after `_store` replaces an entry:** correct. `_store` pops the old entry and subtracts its size before adding the new one, and evicts the least recently used while over budget or over 10,000 entries. A fuzz of 20,000 random stores, including replacements, over 300 origins and sizes from 0 to 500 KiB, found `_held` always equal to the sum of the cached sizes, never negative and never over budget.
- **The rate slot taken for the robots.txt fetch:** it is right when fetches run one after another (the worst minute stays at 10). Under concurrency it wastes slots without exceeding the limit; see finding 25. Also, the gap between the robots fetch and the first page follows the job's rate, not the site's Crawl-delay, because the delay is not yet known when that slot is reserved. That is acceptable.
- **The Lua script's `-1` path and the expiry arithmetic:** correct. `-1` is returned before any write, so neither the value nor the TTL changes. A legitimate wait is never negative, because `free` is raised to `now` first. `nxt - now + 60000` is always at least 60,001 ms, and with the clamps it is at most `max_wait + 3600 s + 60 s`, so keys from a flood of hosts expire within about an hour.

### New findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 23 | low | **`check_url` puts a DNS lookup back outside the deadline (a regression of finding 3 on the CaptureFetcher path).** `before_hop` awaits `self.fetcher.check_url(hop_url)` (`capture.py:49`), which resolves with no timeout (`fetch.py:187`). **Failure case** (`capture_probe2.py` f): a 1 s resolver with a 0.2 s hop deadline took 3.2 s before refusing, with 3 lookups. A slow authoritative name server again holds a worker for the system resolver's full retry time on every hop. **Fix:** run `check_url`'s resolve under `asyncio.timeout(self.limits.total_s)`, mapped to `timeout` with "DNS for…". Optionally keep the checked target for the hop to cut the extra lookup. Add a slow-resolver test through `CaptureFetcher`. | open | reviewer PoC |
| 24 | low | **Truncating robots.txt at 500 KiB can cut the last rule short and widen an Allow.** `got.body[:PARSE_BYTES]` (`robots.py:82`) cuts mid-line. **Failure case** (`capture_probe2.py` c): a file of `Disallow: /`, padding, and then `Allow: /public-docs` across the 500 KiB boundary. The last rule is parsed as `Allow: /`, which ties with `Disallow: /`, so **the whole site is allowed**. A cut Disallow only gets stricter, but a cut Allow gets looser. This is a politeness and legal issue (8.3, G12), not a security one. **Fix:** when the body is longer than `PARSE_BYTES`, drop everything after the last newline before the cut. Add a test with an `Allow` line straddling the boundary. | open | reviewer PoC |
| 25 | low | (a) **Concurrent first requests to an uncached origin each reserve a robots slot, so the first wave runs at half speed.** `before_hop` checks `is_cached` and reserves a slot before any coroutine has fetched robots.txt (`capture.py:50`). Only the first one fetches; the others find the rules cached by the time their slot comes, so their slots go unused. **Failure case** (`concurrency.py`, with a resolver that yields as real DNS does): 30 concurrent pages at 600 a minute make 31 requests but reserve 60 slots, taking 5.9 s instead of about 3.0 s. With 40 jobs and a 20-interval `max_wait`, 20 jobs are refused, and half the reserved slots were never used. This is never over the limit, but it is wasted capacity, and more jobs are refused when many are due at once. **Fix:** fetch robots.txt once per origin (a per-origin `asyncio.Future`), and reserve the robots slot inside `RobotsPolicy` just before the fetch that actually happens, for example through a `before_fetch` callback. (b) Clamp the interval in `ValkeyRateLimiter.take` and `MemoryRateLimiter.take` as well, so the limiter does not rely on every caller using `interval()`. | open | reviewer PoC |

**Sign-off at re-verification (slices 3 and 4):** signed off; no high or critical open, and no medium open. Findings 14 to 20 are closed; 20(b) is deferred to BL-87. Finding 21 is partly closed (the window assertion), 22(a) is deferred to the routes slice, and 23 to 25 are low and tracked for a follow-up. · M3 SafeFetcher independent review · 2026-11-16

### Evidence (re-verification, slices 3 and 4)
1. **Tests:** the four unit files: 129 passed, 100 percent (425 statements, 116 branches). Valkey integration: 4 passed, and no container was left behind.
2. **`valkey_probe2.py`:**
   - 50 refused attempts move next-free by 0 s, and the next caller waits 125.987 s.
   - Five 30 s takes: next free in 150 s, TTL 210 s.
   - 70 takes at 1 s, then 62 s of sleep: TTL 129.988 s, and the new caller waits 7.9 s.
   - Boundary: waits 0.0 and 1.999 s are accepted with a 2.0 s maximum. With a 1.999 s maximum the take returns `None` and the value is unchanged.
   - The clamped 1e20 gives a TTL of 3,660 s.
   - Calling `take` directly with 1e20 still gives `ResponseError`, and 1e9 still gives 32 years (25(b)).
3. **`capture_probe2.py`:**
   - a: `private-address`, with no slot, with and without an override.
   - b: 31 requests, worst minute 10.
   - c: 429 refused as `robots`; 401 allows; 600 KB `Allow` allows; 2.5 MB refused. A boundary-straddling `Allow: /public-docs` is cut to `Allow: /` and allows the whole site (24).
   - d: 8 entries, 3.91 MiB of text, 112, 45 and 17 MiB of memory.
   - e: the LRU fuzz holds.
   - f: 3.2 s with 3 lookups, against a 0.2 s deadline (23).
   - g: 31 requests and 31 slots, but only because the stub resolver never yields.
4. **`concurrency.py`** (resolver that yields):
   - 30 jobs at 600 a minute: 31 requests, 60 slots, 5.9 s.
   - 40 jobs at 600 a minute with `max_wait` 2 s: 21 requests, 41 slots, 20 refused, 4.0 s (25).
5. **`robots_probe.py`:** RFC behaviour is unchanged. The Crawl-delay `1e20` now gives an interval of 3,600 s (3,600,000 ms).

### Re-verification of findings 23 to 25 and residual 21 (`sec/M3-fetch-followups` at `511079e`)
**Method:**
- **Code and tests:** I read `git diff 511079e~1 511079e`. The four SafeFetcher unit files pass (135 tests), and coverage of `regwatch.capture.safe_fetch` is 100 percent (462 statements, 126 branches). `tests/integration/test_valkey_rate.py` passes (4 tests); its container was removed.
- **Probes rerun:** `capture_probe2.py` (all parts, including c and f) and `concurrency.py`.
- **New probes:** `fix3.py` covers truncation edge cases, the lock handoff, cleanup and the clamps. `clamp_valkey.py` calls `ValkeyRateLimiter.take` directly on a throwaway Valkey from the locally present pinned image, bound to 127.0.0.1 and removed afterwards.
- **Isolation:** no dev-stack data was changed, no bind was widened, no external network was used, and no image was pulled. Only this record was changed, and it is not committed.

| # | Verdict | Evidence |
| --- | --- | --- |
| 23 | closed | `capture_probe2.py` f: a 1 s resolver with a 0.2 s deadline is refused as `timeout`, "DNS for example.org took longer than 0.2 s", **after 0.2 s** (it was 3.2 s). The fetch is now stopped at the first lookup (1 lookup made, against 3 before). `check_url` wraps `_resolve` in `asyncio.timeout(total_s)` (`fetch.py:184-195`). The extra lookup on hops that pass is not removed, as the author says; it now has a deadline, so I accept it. There is still no rebinding gap, because `_hop` re-resolves and connects to an address from its own checked lookup. |
| 24 | closed for LF and CRLF files; a new low issue for CR-only files (26) | `capture_probe2.py` c: the file whose `Allow: /public-docs` straddles the limit is now refused (`robots`), because `Disallow: /` applies. Before, it was allowed. `fix3.py`: a newline at `PARSE_BYTES - 1` cuts there (511,999 characters parsed), and a newline at exactly `PARSE_BYTES` is kept (512,001). A CRLF file over the limit keeps its rules. |
| 25(a) | closed | `concurrency.py` (resolver that yields):<br>- 30 concurrent pages at 600 a minute: 31 requests, **31 slots reserved, 3.0 s** (it was 60 slots and 5.9 s).<br>- 40 jobs with a 20-interval `max_wait`: 21 requests, 21 slots, 20 refused, 2.0 s (it was 41 slots and 4.0 s).<br><br>`fix3.py`:<br>- 20 concurrent checks of one origin: 1 robots.txt fetch, 1 `before_fetch` call, 0 locks left.<br>- When `before_fetch` refuses for the first two waiters: those two get `rate-limited`, the third waiter tries for itself and fetches once, the rest are served from the cache, and 0 locks are left.<br>- Three checks cancelled mid-fetch leave 0 locks and nothing cached.<br><br>The user count is decremented in `finally` and the entry is deleted at zero, which is correct under cancellation as well. |
| 25(b) | closed | `_clamp` (`rate.py:58`) is applied inside both limiters. Direct `ValkeyRateLimiter.take` calls with `1e20`, `1e9`, `inf` and `nan` now succeed: two takes give a TTL of 7,260 s, which is two clamped 3,600 s slots plus 60 s. `-5` gives a 1 ms interval (TTL 60 s). `MemoryRateLimiter` gives 3,600 s for `1e20`, `inf` and `nan`, and 0.001 s for `-5` and `0`. The `ResponseError` from finding 17 can no longer occur. |
| 21 | closed | `RecordedRequest.at` exists. The acceptance-5 test now asserts that any 11 consecutive arrivals span at least 0.95 s, which is the sliding-window check: at most 10 per second at 600 a minute. It also asserts the run takes 2.9 to 4.5 s, which would catch the 25(a) slot waste (5.9 s). This proves acceptance 5 at a sped-up rate against the real Valkey script and the fixture server. |

### New findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 26 | low | **A robots.txt over 500 KiB with CR-only line endings is parsed as empty, so everything is allowed.** RFC 9309 2.2 allows CR, LF and CRLF as line ends, and protego splits on a bare CR. `_parse_text` (`robots.py:50-55`) looks only for `\n`; with none found, it parses `b""`. **Failure case** (`fix3.py` 1): a 512,083-byte CR-only file whose first rule is `Disallow: /private` lets `/private/x` through, while the same file under the limit refuses it. This is a politeness and legal issue (8.3), not a security one, and such files are rare. A single line longer than 500 KiB is also parsed as empty, so everything is allowed (`fix3.py` 2). Ignoring content beyond the limit is RFC-consistent, so I note that case only. **Fix:** cut at the last of `\n` or `\r` at or before the limit, e.g. `max(body.rfind(b"\n", 0, L + 1), body.rfind(b"\r", 0, L + 1))`. Optionally treat a truncated file with no complete line as unreadable (disallow, retry after 15 minutes). Add a CR-only test. | open | reviewer PoC |
| 27 | info | `max_wait_s` is not validated. In `MemoryRateLimiter`, a NaN `max_wait_s` accepts every take, because comparisons with NaN are false. In `ValkeyRateLimiter`, `math.floor(nan)` raises `ValueError`. The value comes from code (`MAX_WAIT_S`), not configuration. Validate it if it ever becomes configurable. | n/a | n/a |

**Sign-off at this re-verification:** signed off; no high, critical or medium finding open. Findings 21, 23, 24, 25(a) and 25(b) are closed. Finding 26 is low and tracked for a follow-up, and 27 is info. 20(b) stays deferred to BL-87, and 22(a) to the routes slice. · M3 SafeFetcher independent review · 2026-11-16

### Evidence (this re-verification)
1. **Tests:** the four unit files: 135 passed, 100 percent (462 statements, 126 branches). Valkey integration: 4 passed.
2. **`capture_probe2.py`:**
   - a: `private-address`, with no slot, with and without an override.
   - b: 31 requests, worst minute 10.
   - c: 429 gives `robots`; 401 allows; 600 KB `Allow` allows; 2.5 MB gives `robots`. The boundary file is now **refused** (24).
   - d: 8 entries, 3.91 MiB; memory 112, 45 and 15 MiB.
   - e: the LRU fuzz holds.
   - f: `timeout` after 0.2 s, with 1 lookup (23).
   - g: 31 requests and 31 slots, 3.0 s.
3. **`concurrency.py`:**
   - 30 jobs: 31 requests, 31 slots, 0 refused, 3.0 s.
   - 40 jobs with `max_wait` 2 s: 21 requests, 21 slots, 20 refused, 2.0 s.
4. **`fix3.py`, truncation:**
   - Over the limit: CR-only allows (26); one long line allows; CRLF refuses.
   - A newline at `PARSE_BYTES - 1` gives a refusal with 511,999 characters parsed. A newline at exactly `PARSE_BYTES` gives a refusal with 512,001.
5. **`fix3.py`, the lock:**
   - 20 concurrent checks: 1 fetch, 1 `before_fetch` call, 0 locks left.
   - With a flaky `before_fetch`: `[rate-limited, rate-limited, allowed, allowed, allowed]`, 3 `before_fetch` calls, 1 fetch, 0 locks left.
   - Cancelled checks: 0 locks left, nothing cached.
6. **`fix3.py`, clamps:** `MemoryRateLimiter` intervals: 3,600 s for `1e20`, `inf` and `nan`; 0.001 s for `-5` and `0`. A NaN `max_wait_s` accepts the take (27).
7. **`clamp_valkey.py`:** `1e20`, `1e9`, `inf` and `nan` all succeed, each with a TTL of 7,260 s after two takes. `-5` gives a TTL of 60 s.

### Re-verification of findings 26 and 27 (`sec/M3-fetch-followups` at `7a02053`)
**Method:** I read `git show 7a02053`. The four SafeFetcher unit files pass (139 tests), and coverage of `regwatch.capture.safe_fetch` is 100 percent (467 statements, 128 branches). I ran a new probe, `/tmp/m3review/fix4.py`. No Valkey was needed: the script must not run when the input is refused, so a stub client that fails if it is called stood in for one. No dev-stack data was changed, no bind was widened, no external network was used, and only this record was changed (it is not committed).

| # | Verdict | Evidence |
| --- | --- | --- |
| 26 | closed | `_parse_text` (`robots.py:50-56`) cuts at the later of the last LF and the last CR at or before `PARSE_BYTES`. The `Disallow: /private` rule is enforced over the limit in all three line-end styles: CR-only (open before), LF and CRLF. A CRLF pair split by the limit keeps the CR and drops the LF, so 512,001 characters are parsed and the line still ends. A CR-only file with an `Allow: /private-docs` straddling the limit drops that partial line, and the request is still refused. A single line longer than the limit still parses as empty, so everything is allowed. That is RFC-consistent, as noted under 26, and not a defect. |
| 27 | closed | `_check_wait` (`rate.py:58-61`) refuses NaN, -1, +inf and -inf with `ValueError` in both `MemoryRateLimiter.take` and `ValkeyRateLimiter.take`. It runs before any state change: the in-memory table stays empty, and the stub Valkey script is never called. A `max_wait_s` of 0 or 120 is still accepted. |

**Sign-off:** signed off; no finding above info is open in slices 1 to 4. 20(b) is deferred to BL-87, and 22(a) to the routes slice. · M3 SafeFetcher independent review · 2026-11-16
