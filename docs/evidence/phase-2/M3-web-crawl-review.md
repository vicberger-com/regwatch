# Security review record: M3 Capture framework, bounded web crawl connector

**Scope (PRs, routes, tasks):** branch `feat/M3-web-crawl`, commit `c209055` (the branch tip; the brief first named `1da0d2c`, which does not exist in the repository, and the coordinator corrected it), on top of `15f6871`:
- `capture/connectors/web_crawl.py` (new: `check`, `_allowed`, `WebCrawlConnector`);
- the `web_page.py` refactor: `document()` and `finish_state()` as module functions, shared with the crawl;
- `capture/services.py` (`check_urls`: the crawl check after the address checks);
- `capture/execution.py` (the connector registered);
- the tests: `tests/unit/test_connector_web_crawl.py` and `tests/integration/test_sources.py::test_crawl_seeds_and_domains_are_checked`.

No routes change. `capture.run_job` now runs `web_crawl` sources, and `capture.dry_run` now crawls in `discover`. · **Reviewer session label:** M3 web crawl independent review · **Date:** 2026-11-18 · **Author sessions excluded from review:** yes

## Method
- **Reading:** I read the diff and the code it relies on:
  - `web_page.py` (`_origin`, `_extract`, `_url_filter`, `_previous_listing`, `document`, `finish_state`, listing `discover` and `fetch` for comparison);
  - `rss.entry_link`, `safe_fetch/policy.py` (`parse_target`), `safe_fetch/capture.py` (`before_hop`, how `robots_override` and `allow_hop` reach each hop), `safe_fetch/fetch.py` (the redirect loop, `FetchLimits`), `safe_fetch/rate.py`;
  - `extract/isolate.py` and `extract/text.py` (`MAX_LINKS`, `MAX_HREF`, `WALL_SECONDS`);
  - `capture/execution.py` (`run_connector`, `_retrying`, `_verdict`, the truncation message, `cursor_on_failure`), `capture/runs.py` (`_close`), `capture/dryrun.py` (`preview`), `capture/services.py` (`check_urls`, `check_job`);
  - `connectors/config.py` (`WebCrawlConfig`).

  Against: `docs/contracts/connectors.yaml` `web_crawl`, `docs/modules/M3-capture-framework.md` (crawl design note, acceptance 5), ADR-0009 amendment 2, 8.3 (robots.txt overrides), and the earlier records `M3-html-extract-review.md`, `M3-web-page-review.md` and `M3-web-listing-review.md`. I read none of the secret files in `deploy/`.
- **Tests:**
  - `uv run pytest -q tests/unit/test_connector_web_crawl.py tests/unit/test_connector_web_page.py` gave 49 passed.
  - `uv run pytest -q -m "integration and not stack" tests/integration/test_sources.py -k crawl` gave 2 passed. The fixture's throwaway PostgreSQL container was removed afterwards; the dev and QA stacks were not touched.
  - I did not rerun `make test-api` or `make lint`.
- **Proofs of concept:** in `/tmp/web-crawl-review/`. Unless noted, they run the real connector through `run_connector`, using the unit test's own `Site` and `crawl` helpers (SafeFetcher on a `MockTransport` routed by `Host`, a stub resolver, the real extraction child, an in-memory store, a limiter that does not sleep):
  - `p1_domains.py`: `_allowed`, `parse_target` and `entry_link` on suffix, case, trailing dot, port, scheme, userinfo, IDNA, fullwidth and ideographic dots, IP literals, backslash and percent hosts; `check` on public suffixes and malformed domains;
  - `p2_override_redirect.py`: a seed-origin URL redirecting onto another allowed host whose robots.txt disallows all;
  - `p3_seed_failure_state.py`: a seed answering 503 once, over four runs;
  - `p4_truncation.py`: six pages with `max_pages_per_run` 3, over three runs; then a full run, a truncated run and a full run;
  - `p5_not_html.py`: a seed linking 300 PDFs, with `max_pages_per_run` and `max_items` 2;
  - `p6_bodies_held.py`: the candidates' bodies still referenced when the manifest is written;
  - `p7_frontier.py`: discovery alone, with the child's answer replaced by one at its limits (2,000 links of about 1,900 characters per page);
  - `p8_stored_retry.py`: three pages that time out in discovery;
  - `p9_dryrun.py`: `dryrun.preview` on a crawl source (seed disallowed, seed 404, a PDF-heavy seed);
  - `p10_politeness.py`: the rate derived from `politeness_delay_seconds`, and other config bounds;
  - `p11_rate.py`: acceptance 5 with a simulated clock (the limiter's clock and sleep replaced): every request the host sees, robots.txt included, timed over a 200-page crawl.
- **Limits:** no external network. Slow hosts, timeouts and the clock were simulated. I did not check how the system resolver treats a backslash in a host name (finding 8). M4 is not built, so nothing reads the manifest yet. Python 3.12.

## Data flows touched
- **Worker to seed and crawled hosts:** one `GET` per frontier URL through `ctx.fetcher` (SafeFetcher, robots.txt, the per-host rate), at `min(job rate, 60 / politeness)` a minute; `allow_hop` keeps every hop on `allowed_domains`; `robots_override` is passed when the requested URL's origin is a seed's origin.
- **Worker to the extraction child:** each HTML body, with `links_selector` `a` while the depth is under `max_depth`. The answer: the text, and at most 2,000 hrefs of at most 2,048 characters.
- **Links to the frontier:** resolved by `entry_link` against the final URL, query stripped (default), deduplicated in `seen`, kept on `allowed_domains`, filtered by the URL patterns. **No bound on the frontier's size.**
- **Discovery to fetch:** each candidate carries the `FetchResult` (body up to 10 MB) and the extraction (text up to 1,000,000 characters), or the error discovery met.
- **Object store:** as listing mode: `raw/{sid}/{sha256}` and `text/{sid}/{hash}.txt` for new or changed pages, the state in `state/{sid}/listing-{a,b}.json`, the manifest.
- **Cursor (CP-16):** `{"listing_ref": key}`, written for `success`, `partial`, and `failed` (`cursor_on_failure`).
- **Dry run:** the same discovery, no store, 25 s, at most 5 candidates.
- **Trust boundary:** every crawled page, its links and redirects are hostile (8.1). The admin's `allowed_domains`, seeds and override reason are trusted, but only for what they name.

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | crawled hosts | `_allowed` on links and every hop; SafeFetcher's address checks | hop host check on the raw `urlsplit` name, not the fetcher's parsed one; public suffixes accepted as domains | 8, 10 |
| Tampering | robots.txt policy (8.3) | override only for URLs on a seed origin | the override is applied to every redirect hop of such a URL, onto other hosts | 1 |
| Tampering | change detection | listing state per URL | pages not reached this run lose their baseline, and are handed to M4 as `new` again | 2 |
| Repudiation | run messages | `truncated` note | "continues where this one stopped" while the same BFS prefix is crawled every run; dry run shows refused seeds as candidates with `allowed` | 3, 6 |
| Information disclosure | error text | fixed refusal texts | none found | none |
| Denial of service | run budget | `min(max_pages_per_run, max_items)`, 3 unreadable pages, the 45-minute deadline | non-HTML fetches are not counted; stored errors retried with sleeps | 4, 7 |
| Denial of service | worker memory | none for the frontier; none for held bodies | unbounded frontier on link-heavy pages; every new page's body held to the run's end | 5 |
| Elevation of privilege | in-process parsing | pages only through `extract_isolated` | none found | none |

## Checklist
- [ ] Input validation on every field (types, sizes, enumerations): domains must match a host-name pattern and every seed must be on one (at save and at run). However, `politeness_delay_seconds` above 60 s is not honoured (finding 9), `allowed_domains` accepts public suffixes and has no size limit (finding 10), and `max_depth` has no lower bound (info).
- [x] Output encoding in UI, templates, emails, CSV: links reach M4 only as URLs rebuilt by `entry_link`.
- [x] Authentication and authorization on every route and task: no routes change; the save check runs inside the existing source routes.
- [x] Session handling: not touched.
- [x] Secrets not logged or committed: none in the diff.
- [ ] Outbound requests only through SafeFetcher or registered services: every request goes through `ctx.fetcher`. However, the source's robots.txt override reaches hosts other than the seeds' origins through redirects (finding 1).
- [ ] File and body size limits; content-type checks: each body is capped at 10 MB and only HTML is read. However, non-HTML answers are not counted against the page budget (finding 4), and the frontier and the held bodies are unbounded in total (finding 5).
- [x] Logging excludes sensitive data; audit rows written: the connector does not log.
- [x] Dependency, image and license scans: no new dependency (ADR-0009 amendment 2 drops Scrapy).

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | medium | **The robots.txt override reaches other hosts through redirects.** `discover` passes `job.robots_override` when the requested URL is on a seed's origin (`web_crawl.py:107`), and `CaptureFetcher` applies it to every hop of that fetch (`safe_fetch/capture.py:69-70`). `allow_hop` only keeps hops on `allowed_domains`, so a seed-origin URL may redirect to any allowed host, and that host's robots.txt is never read. The listing slice closed the same gap by keeping every hop on the page's origin (web listing finding 1, R3); the crawl reopens it. **Failure case** (`p2_override_redirect.py`): seed `https://reg.example/` with an override; both `reg.example` and `docs.reg.example` have `Disallow: /`. `/go` answers 302 to `https://docs.reg.example/private`, which is fetched and stored (document `reg.example/go`, final URL on `docs.reg.example`); `docs.reg.example/robots.txt` is not even asked for that fetch. A direct link to `docs.reg.example/direct` is refused, as intended. **Fix:** when the override is passed, make `allow_hop` also require each hop to stay on the requested URL's origin (a cross-origin redirect then ends as `refused-host`); optionally queue the redirect target as a frontier link so it is fetched later under its own robots.txt. Test this case. | | |
| 2 | medium | **Pages the run does not reach lose their baseline, so the next run hands them all to M4 as `new` again.** `finish_state` writes entries only for `listing["listed"]` (`web_page.py`, `finish_state`). In listing mode that is every link on the listing page; in the crawl it is only the pages this run fetched (`web_crawl.py:106`). A page not reached because a seed or an intermediate page failed, the run was truncated, or the deadline cut it, drops out of the state. Because `cursor_on_failure` writes the state even for a `failed` run, one failed seed is enough. **Failure cases:** `p3_seed_failure_state.py`: a seed with 20 pages, run 2 `unchanged` 21; on run 3 the seed answers 503 once (`failed`, `fetch-failed`), the cursor moves to a state of 1 entry; on run 4, with nothing changed, `new` 20 and 20 documents go to M4. `p4_truncation.py`: after a full run of 7 pages, one run with `max_pages_per_run` 3 leaves 3 entries, and the next full run reports `new` 4 for unchanged pages. This is what CP-16 and web listing finding 2 set out to prevent. **Fix:** in the crawl, keep the previous entry of every URL in the previous state that this run did not reach (bounded, for example by `max_pages_per_run` entries or by dropping entries not seen for some number of runs or days). Drop an entry only when a run that finished its whole frontier without failures no longer found the page. Test p3 and p4 over the following run. | | |
| 3 | low | **A truncated crawl fetches the same breadth-first prefix every run, never reaches the rest, and says the opposite.** The frontier starts from the seeds in the same order each run; nothing rotates by `checked_at` as listing mode does (web listing finding 4). The message uses `moved = cursor is not None`, and the crawl's cursor changes slot every run. **Failure case** (`p4_truncation.py`): six pages with `max_pages_per_run` 3: all three runs fetch the seed, `p0` and `p1`, and each says "the next run continues where this one stopped"; `p2` to `p5` are never fetched. With the default 200 pages, any larger regulator site is monitored on a fixed subset. The same holds for runs cut at the deadline. **Fix:** either rotate (for example keep the breadth-first order for discovery but, at the page budget, prefer pages never checked or longest unchecked, or persist the remaining frontier in the state), or give the crawl its own message: "raise max_pages_per_run or narrow the URL patterns". Test the message and coverage over runs. | | |
| 4 | medium | **Pages that are not HTML are fetched without counting against `max_pages_per_run` or the item limit.** A non-HTML answer is popped from `listed` (`web_crawl.py:119-121`), so the budget check (`len(listed) >= limit`) never sees it. Every such link in the frontier is fetched, up to 10 MB each, bounded only by the rate and the 45-minute deadline. Regulator sites link PDFs heavily (BL-101 (c)). **Failure case** (`p5_not_html.py`): a seed linking 300 PDFs and one page, `max_pages_per_run` 2 and `max_items` 2: 240 requests before the test's non-sleeping limiter refused the host as `rate-limited`; with real waits, all 301. The run is `partial` / `truncated` with one document. Over 45 minutes at 30 a minute that is about 1,350 bodies, up to about 13 GB, for a run that may store 2 pages. **Fix:** count every fetch (HTML or not, failed or not) against the run's page budget, or add a separate fetch budget of the same size; optionally skip links whose path ends in a known non-HTML extension. Test p5. | | |
| 5 | medium | **Worker memory is unbounded: the frontier on link-heavy pages, and every new page's body held to the end of the run.** (a) Each page may add 2,000 links of up to 2,048 characters to `frontier` and `seen`, with no cap (`web_crawl.py:127-135`), while only `limit` pages are ever fetched. `p7_frontier.py` (the child's answer at its limits): after 20 pages, 40,000 queued URLs, peak RSS 140 MiB, and about 0.6 s of event-loop time per page in `entry_link`. That extrapolates to about 0.8 GB at the default 200 pages and about 8 GB at 2,000; the deadline and rate only slow it. (b) The candidate's hints keep the `FetchResult` and the extraction, and `run_connector` keeps `(candidate, document)` for every new or changed page until the manifest is written. `p6_bodies_held.py`: 8 pages of 1.5 MB leave 12,000,521 bytes of bodies referenced at manifest time. With 10 MB bodies that is up to 2 GB at 200 pages and 20 GB at 2,000. Listing mode does not hold bodies. A worker container runs two processes (`--concurrency 2`), so one hostile or simply large site can kill both runs by memory. **Fix:** (a) stop adding to the frontier once `len(seen)` reaches a cap tied to the budget (for example `limit` plus a margin), and stop extracting links once the frontier alone can fill the budget; (b) in `fetch`, pop `got` and `found` from the hints after `document()` has used them. Test both caps. | | |
| 6 | low | **The dry run shows a seed refused by robots.txt, or one that failed, as a normal candidate with `robots_decision` `allowed`.** The crawl yields an error candidate instead of raising (`web_crawl.py:112-118`), and `preview` lists every candidate without looking at its hints. **Failure case** (`p9_dryrun.py`): a seed whose robots.txt is `Disallow: /` gives `{"candidates": [{"url": "https://reg.example/"}], "robots_decision": "allowed", "warnings": []}`; a 404 seed gives the same. The admin's test says the source works. Also, a PDF-heavy seed took 56 requests for a 5-candidate preview; with real waits the 25 s deadline bounds this, which is acceptable. **Fix:** in `preview`, report candidates whose hints carry an error as warnings (the refusal reason, not the detail), setting the decision for `robots`, and do not count them as candidates; or let the crawl raise when the first seed is refused before anything is yielded. Test the dry run in crawl mode. | | |
| 7 | low | **A page that timed out or could not connect in discovery is "retried" by the run three times with real sleeps and no new request.** `fetch` re-raises the stored `FetchRefusedError`; `_retrying` treats `timeout` and `connect` as transient and waits 1 s and 2 s. **Failure case** (`p8_stored_retry.py`): three such pages cost 9.4 s of sleeps, 10 `fetch` calls, and 3 requests. 200 such pages cost about 600 s of a 45-minute run, so a slow site is cut short sooner. The page is also never really retried, unlike listing mode. BL-101 (b) calls this harmless; it is not quite. **Fix:** either fetch again in `fetch` for a stored transient error (what the retry is for), or raise it in a form `_transient` does not retry. | | |
| 8 | low | **Redirect hops are checked on the raw host name, not the host the fetcher will use.** `_allowed` uses `urlsplit(hop).hostname`; `parse_target` encodes IDNA and strips a trailing dot; links go through `entry_link`, which refuses backslashes and `%` in hosts, but hops do not. **Cases** (`p1_domains.py`): `https://evil.example\.reg.example/` and `https://evil.example%2e.reg.example/` pass `_allowed`, and `parse_target` keeps the backslash or percent in the host it resolves. A DNS resolver that reads `\.` as an escaped dot would look up a name outside `reg.example` (label `example.reg` under `example`); I did not verify the system resolver's behaviour, and in practice such a label is not registrable, so I found no way to reach another site. Trailing-dot and fullwidth-dot hops are refused (fail closed). **Fix:** check hops on `parse_target(hop).host`, refusing hosts outside letters, digits, hyphens and dots, as `entry_link` does. | | |
| 9 | low | **`politeness_delay_seconds` above 60 s is not honoured.** The rate is `max(1, int(60 / delay))` a minute (`web_crawl.py:90`), and the schema has no upper bound. **Cases** (`p10_politeness.py`): 61 s, 300 s, 3,600 s and `inf` all give one request every 60 s. Below 60 s the floor always errs slower, which is correct. **Fix:** pass the interval in seconds to the fetcher (or a rate as a float), or bound the delay at 60 in the contract (a CP). | | |
| 10 | low | **`allowed_domains` accepts public suffixes and has no size limit.** `gov.uk`, `co.uk` and `github.io` pass `_DOMAIN`, so a seed on one of them lets the crawl wander over every site under it (each with its own robots.txt, but none chosen by the admin). The list has no `maxItems` (10,000 entries accepted). **Fix:** refuse well-known multi-party suffixes (a short built-in list, or a public suffix list if one passes the license gate), or warn in the UI; add `maxItems` (for example 20, as for seeds) through a CP. | | |
| 11 | low | **Test gaps.** Acceptance 5 asks for "10 requests per minute per host under a crawl of 200 pages (verified by a local test server)". The test only checks that `rate_per_minute=10` is passed for one 404 seed (`test_the_politeness_delay_sets_the_rate`); no test times requests under a crawl. Not tested: the override and a redirect (finding 1); a failed seed or a truncated run, then the next run's counts (finding 2); the truncation message and coverage over runs (3); non-HTML pages against the budget (4); frontier and memory caps (5); the dry run with a crawl source (6); stored transient errors (7); hop host forms and IDNA links (8); a seed with a query, and `http` on 443. | | |
| 12 | info | (a) Any broken link on a site makes every run `partial` / `some-failed`; real sites have some, so a crawl source may never show `success`. (b) `_allowed` accepts `http` on 443 and `https` on 80. (c) `max_depth` has no lower bound; a negative value crawls only the seeds. (d) Seeds are not query-stripped like links, so `https://reg.example/?a=1` and `/` are two pages. (e) The save-time budget (`check_job`) uses the job's rate only, not the politeness delay or the extraction time; a delay of 10 s with 400 items always ends at the deadline. Pages that each take just under the child's 20 s are not counted as unreadable (as in listing mode). (f) The rate is per host name, as the spec says; a site with many subdomains under one allowed domain is crawled at that rate per subdomain. | | |

**Sign-off at review:** commit `c209055` is **not signed off**.

What is sound:
- domain matching: suffix tricks (`evilreg.example`, `reg.example.evil.example`), userinfo, IP literals, other ports and schemes are refused, and IDNA links are compared in punycode;
- every redirect hop is checked against the domains before it is contacted, and links are resolved against the final URL, which was itself checked;
- the override is withheld from non-seed hosts that are requested directly, and their robots.txt is obeyed;
- three unreadable pages stop the run; the deadline holds; pages are read only in the child;
- the refactor of `document()` and `finish_state()` is a move, with no change in behaviour (the web page tests pass);
- the save check runs after the address checks and reports the right field.

Four medium findings remain:
- Finding 1: the robots.txt override reaches other hosts through a redirect, against 8.3 and the crawl's own claim.
- Finding 2: one failed seed, or a truncated run, makes the next run resend every page under it to M4 as `new`.
- Finding 4: non-HTML answers are fetched without limit within a run.
- Finding 5: the frontier and held bodies can take gigabytes of worker memory.

They should be fixed, with their tests, before sign-off. Findings 3 and 6 to 11 are low and can follow, though 3 and 6 are cheap to do with 2. · M3 web crawl independent review · 2026-11-18

## Acceptance 5 (per-host rate under a 200-page crawl)
**Holds for a single host** (`p11_rate.py`, simulated clock, real connector, real child, `MemoryRateLimiter`; every request the host saw, robots.txt included, was timed):
- job 10 a minute, politeness 2 s: 200 documents, 201 requests over 20.0 simulated minutes, at most 10 in any 60 s window, smallest gap 6.00 s;
- job 30 a minute, politeness 6 s: the same (the politeness delay governs);
- job 30 a minute, politeness 2 s (40 pages): at most 30 a minute, smallest gap 2.00 s, as configured.

The limiter is the same per-host slot logic as the Valkey script, but the Valkey limiter was not exercised here. The repository's own test does not show this (finding 11); `p11_rate.py` could be adopted as that test with a local server. Two limits apply: the rate is per host name (12 (f)), and a delay above 60 s is not honoured (finding 9).

## Checked and found fine
- **Suffix matching:** `host == d or host.endswith("." + d)` on a lower-cased host; `evilreg.example`, `reg.example.evil.example`, `reg.example@evil.example` (refused as userinfo) and `evil.example#.reg.example` are all refused (`p1_domains.py`). Domains are lower-case LDH names with a dot, so neither `*.example` nor an IP can be a domain.
- **IDNA:** links are rebuilt by `entry_link` from `parse_target`, so `rég.reg.example` becomes `xn--rg-bja.reg.example` and matches a punycode domain; Unicode domains are refused at save. A fullwidth or ideographic dot in a hop's host makes it fail the check (fail closed).
- **Ports and schemes:** only `http` and `https` on ports 80 and 443; `https://docs.reg.example:8443/` is refused, as are `ftp:` seeds (tested).
- **Seeds:** checked at save after the address checks, and again at run time in `discover`, so a stale row is `bad-config`.
- **Override scope for direct requests:** the seed origin is scheme, host and port; a link to another host, port or scheme of an allowed domain is fetched without the override (tested; `p2_override_redirect.py`, `/direct`).
- **Links from redirected pages:** resolved against `got.url`, which every hop check passed.
- **Unreadable stop:** counted in `fetch` for `too-slow`, `too-large`, `too-deep` and `parse-failed`; the third stops the run as `unreadable-pages` (tested), so at most about 60 s of children.
- **Deadline:** `discover` runs inside `asyncio.timeout(RUN_DEADLINE_S)`; a cancelled child is killed (`isolate.py`), and `finish_state` still runs.
- **State keys:** the same two slots and exact-key checks as listing mode; failed pages keep their previous hash with the attempt's time (`tried`).
- **Rate formula:** `int(60 / delay)` floors, so the interval is never shorter than the delay for delays up to 60 s (`p10_politeness.py`), and robots.txt fetches take their own slot.
