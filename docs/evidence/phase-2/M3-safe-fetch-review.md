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
