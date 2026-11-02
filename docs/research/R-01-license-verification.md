# R-01: Component register license verification

**Issue:** #3 · **Module:** M0 · **Requirements:** REQ-19, REQ-20 · **Date:** 2026-11-01
**Policy:** `docs/03-architecture.md` 3.5 · **Register:** `docs/03-architecture.md` 3.6 · **Protocol:** 3.8

## Question

For every row in the component register, open the project's own LICENSE file at a tagged release, record the commit and the SPDX identifier, upgrade the row to V, and flag any mismatch with the register.

## Method

1. Resolve each upstream repository and follow any renames (`gh api repos/<owner>/<repo>`).
2. Pick the release with GraphQL `latestRelease`. When a repository has no GitHub releases, or its "latest" release is a pre-release or a sibling package, use the newest final tag instead. When a repository has no tags at all, read it at default-branch HEAD and record the date (see the notes below).
3. Resolve the tag to its commit SHA (`gh api repos/<o>/<r>/commits/<tag>`).
4. Fetch the license file at that SHA (`gh api repos/<o>/<r>/license?ref=<sha>`). This returns the file path, GitHub's licensee classification and the full text.
5. Read the head of every file. Read the whole file wherever the classifier returned `NOASSERTION`, the file held more than one license, or the register expected an edge case.

"Commit" below is the full SHA of the commit at which the license file was read: the tagged commit, or default-branch HEAD on the stated date for a repository with no tags (SearXNG, N4; `ipp`, E1). The register in 3.6 shows the first seven characters.

## Results

Result codes: **match** means the file agrees with the register. **note** means it agrees, with a detail worth knowing. **mismatch** means the register text needs correcting. **unverified** means no license file exists.

| # | Register row | Repository | Tag | Commit | File | SPDX (read) | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | FastAPI | fastapi/fastapi | 0.162.0 | 7a0a3f0b286c6c865cf4398ea0e957a87b8bffa4 | LICENSE | MIT | match |
| 2 | Pydantic | pydantic/pydantic | v2.14.2 | aa540acc29960fb394312cf97d888c99f9686814 | LICENSE | MIT | match |
| 3 | SQLAlchemy | sqlalchemy/sqlalchemy | rel_2_1_6 | 2f6968cc126d4da2d2eabc5a51285472bb9bfc9e | LICENSE | MIT | match |
| 4 | Alembic | sqlalchemy/alembic | rel_1_20_1 | 47da01c856027876f4022b2da721a4edd6b4a0db | LICENSE | MIT | match |
| 5 | PostgreSQL 16 | postgres/postgres (official mirror) | REL_16_15 | 7d3e000c5961a544302072058a1184e9a588837b | COPYRIGHT | PostgreSQL | match |
| 6 | pgvector | pgvector/pgvector | v0.8.7 (tag) | f37c13f68b57d2c3472b2214fbcff699d6d34876 | LICENSE | PostgreSQL | match |
| 7 | Celery | celery/celery | v5.6.3 | 3f4d8d795ad128bd7430cc5dc174a802cded425c | LICENSE | BSD-3-Clause | note (N1) |
| 8 | Valkey | valkey-io/valkey | 9.1.3 | 29173b67508b2de4c0f0ed551f3b47cf19fc3ca8 | COPYING | BSD-3-Clause | note (N2) |
| 9 | feedparser | kurtmckee/feedparser | v6.0.14 | 14425f6851790184fbf7bbd8076de237d5f444f9 | LICENSE | BSD-2-Clause | note (N3) |
| 10 | Scrapy | scrapy/scrapy | 2.19.0 | 8026deeaac371a5d9a3edbe4886d58f61139d464 | LICENSE | BSD-3-Clause | match |
| 11 | trafilatura 1.8+ | adbar/trafilatura | v2.3.1 | e2f85c965662c7df26b73290ef175b2c2a5fdca6 | LICENSE | Apache-2.0 | match (E2) |
| 12 | readability-lxml | buriy/python-readability | 0.9 | 7159b09ad688378779294cbb5d9f3cfa3274368f | LICENSE | Apache-2.0 | match |
| 13 | Playwright (Python) | microsoft/playwright-python | v1.64.1 | bcb9debb4f3a9bb22f954e0f71e4c5b512ad7142 | LICENSE | Apache-2.0 | match |
| 14 | changedetection.io | dgtlmoon/changedetection.io | 0.60.10 | 16974bf351cd68b1978af9494082b75efadaa8e0 | LICENSE | Apache-2.0 | match |
| 15 | SearXNG | searxng/searxng | none; `master` HEAD on 2026-11-01 | 9ded3bec1ae0b92e6abe40d27e1ca38d1906abbe | LICENSE | AGPL-3.0 | note (N4) |
| 16 | httpx | encode/httpx | 0.28.1 | 26d48e0634e6ee9cdc0533996db289ce4b430177 | LICENSE.md | BSD-3-Clause | match |
| 17 | langdetect | Mimino666/langdetect | 1.0.8 | d0c8e85622abe3d67e763d9377f707e51c4a7217 | LICENSE | Apache-2.0 | note (N5) |
| 18 | lingua-py | pemistahl/lingua-py | v2.2.0 | 754ce21122c083a7200763015fdaf7cda8d85453 | LICENSE.txt | Apache-2.0 | match |
| 19 | spaCy | explosion/spaCy | release-v3.8.18 | 43311999028032fd81bef77a75fdb4fa96803c98 | LICENSE | MIT | match |
| 20 | rapidfuzz | rapidfuzz/RapidFuzz | v3.14.6-1 | 377d0c0ace35bbb4683180ebf110414dfff11abb | LICENSE | MIT | match |
| 21 | React, React DOM | react/react (was facebook/react) | v19.3.1 | 61aa00df822d0eb76d0362eb8b6fdd3527693efe | LICENSE | MIT | match |
| 22 | Vite | vitejs/vite | v8.3.5 | 981f07fa4580fb88b333c4450431e4715d2a0b82 | LICENSE | MIT | match |
| 23 | TanStack Query | TanStack/query | release-2026-11-01-1008 | a6be1cede9b69b56ee0bd6c84641dd3899c86ed2 | LICENSE | MIT | match |
| 24 | TanStack Table | TanStack/table | @tanstack/vue-table-devtools@9.3.1 | 95c4768496c07b45b1e65d8e33c3291ac66eae9b | LICENSE | MIT | match |
| 25 | TanStack Router | TanStack/router | release-2026-10-22-2011 | 6b9fe6d29552270836c511bc9b343d73541f4424 | LICENSE | MIT | match |
| 26 | Tailwind CSS | tailwindlabs/tailwindcss | v4.3.3 | c2b24dd15fed1c59dd521bd86082f520c9f5ad0d | LICENSE | MIT | match |
| 27 | shadcn/ui | shadcn-ui/ui | shadcn@4.23.0 | 96da9cc7f1aa10580a3741664e2a77c721206c00 | LICENSE.md | MIT | match |
| 28 | Radix UI | radix-ui/primitives | 1.6.7 (tag) | 9aebdd45abd447b84092ecf20f8bcd27f2398c36 | LICENSE | MIT | match |
| 29 | MapLibre GL JS | maplibre/maplibre-gl-js | v6.16.0 | 538a7680ab16d5cf5a6564ee0ce72a11be14d142 | LICENSE.txt | BSD-3-Clause | note (N6) |
| 30 | Natural Earth | nvkelso/natural-earth-vector | v5.1.2 | f1890d9f152c896d250a77557a5751a93d494776 | LICENSE.md | public domain (no SPDX ID) | match |
| 31 | world-atlas | topojson/world-atlas | v2.0.2 | a912c0a22c3fbd1979cb6defdd6389d8c35e7c2a | LICENSE | ISC | note (N7) |
| 32 | topojson-client | topojson/topojson-client | v3.1.0 | 71e5bd6428fd8b7a40fa980d2ef7862140851f03 | LICENSE | ISC | match |
| 33 | i18n-iso-countries | michaelwittig/node-i18n-iso-countries | v7.14.0 (tag) | 55c3a72603faf0185661e80841074e1c2fcf8db5 | LICENSE | MIT | match |
| 34 | Apache ECharts | apache/echarts | 6.1.0 | c5a48f5f97d23e5379720870b8444cd05b50ffb4 | LICENSE | Apache-2.0 | match |
| 35 | Puck | puckeditor/puck | v0.24.0 | d14401c3a47947543e9de733ef1a20fb85140d52 | LICENSE | MIT | mismatch (E3) |
| 36 | dnd-kit | clauderic/dnd-kit | @dnd-kit/geometry@0.5.3 | 3910e2773d57482f58ba135623523fe97b588245 | LICENSE | MIT | match |
| 37 | Gotenberg | gotenberg/gotenberg | v8.39.0 | 3d4f655272f8b96ac9271270ee1d1ec94f9880b6 | LICENSE | MIT | match |
| 38 | WeasyPrint | Kozea/WeasyPrint | v70.0 | 4d3b7b6449e3494f59c7c2f36b512d129225679c | LICENSE | BSD-3-Clause | match |
| 39 | aiosmtplib | cole/aiosmtplib | v5.1.3 | 9cc425460026ee54392507f0593ecd4052cd6aa4 | LICENSE.txt | MIT | match |
| 40 | Mailpit | axllent/mailpit | v1.33.0 | 364916b15e80a8bac1e7b0ab66a4f2b3d7d745c2 | LICENSE | MIT | match |
| 41 | ipp (npm) | williamkapke/ipp | none; `master` HEAD from 2019-08-17 | 5d806b7dda5191826672346d3927c2f8670b42a4 | **none** | MIT claimed only | **unverified (E1)** |
| 42 | argon2-cffi | hynek/argon2-cffi | 25.1.0 | 1fcae4fc1b7ff192b5ade54f6616771e5cf5f391 | LICENSE | MIT | match |
| 43 | Authlib | authlib/authlib | v1.9.1 | 46b94870d915ee77430da8fa2a358378d90b3a45 | LICENSE | BSD-3-Clause | match |
| 44 | Keycloak | keycloak/keycloak | 26.8.1 | 24ed1dadf3f246a555adb6d3d4a99e9b3003fb3b | LICENSE.txt | Apache-2.0 | match |
| 45 | pycasbin | apache/casbin-pycasbin (was casbin/pycasbin) | v2.8.0 | f858158e85eb9abdf308fd356d0246b89922b11b | LICENSE | Apache-2.0 | note (N8) |
| 46 | Caddy | caddyserver/caddy | v2.11.7 | 72dd0fb067f6d7826c7f79907670ba4a713bfe37 | LICENSE | Apache-2.0 | match |
| 47 | structlog | hynek/structlog | 26.1.0 | 8174a86a2f14b5bd295eded733ff5fffc12aa173 | LICENSE-MIT, LICENSE-APACHE | MIT OR Apache-2.0 | mismatch (E4) |
| 48 | OpenTelemetry | open-telemetry/opentelemetry-python | v1.45.2 | ad755945ad69008219e661c33ff1d72ff1bbcb51 | LICENSE | Apache-2.0 | match |
| 49 | prometheus-client | prometheus/client_python | v0.26.0 | 9b6b971f903e7a08f88da5a95048b7a2a28f55a5 | LICENSE | Apache-2.0 | match |
| 50 | Grafana | grafana/grafana | v13.3.0 | 752e3462ff71a43a5c1fb62d00a482fa2dc0ee6a | LICENSE | AGPL-3.0 | match (tooling only) |
| 51 | Prometheus | prometheus/prometheus | v3.15.1 | bae3eced0a5369e050e83ea73bc381d7c4b1a719 | LICENSE | Apache-2.0 | match |
| 52 | pytest | pytest-dev/pytest | 9.2.0 | ae1d0ff57b8bd4252da9ade7353523ac0ac73281 | LICENSE | MIT | match |
| 53 | pytest-cov | pytest-dev/pytest-cov | v7.1.0 (tag) | 66c8a526b1246b5eb8fb1bc218878131bc628622 | LICENSE | MIT | match |
| 54 | Hypothesis | HypothesisWorks/hypothesis | v6.170.14 | 255a880b2f626852a139934e7893479039db7d1e | LICENSE.txt | MPL-2.0 | note (N9) |
| 55 | Vitest | vitest-dev/vitest | v5.0.5 | 7a825db43e2beca0b219d2eadaec334cb81af0c7 | LICENSE | MIT | match |
| 56 | Testing Library (React) | testing-library/react-testing-library | v16.3.3 | 20ce75f2907ca0e5c5a8ae595c0e9a4e368c7800 | LICENSE | MIT | match |
| 57 | Testing Library (DOM) | testing-library/dom-testing-library | v10.4.2 | 6049cc0bc7cf2201625c476c95fa6299d0e2fa8b | LICENSE | MIT | match |
| 58 | axe-core | dequelabs/axe-core | v4.14.0 | e797173108eadfa4355fe06af331791734e1757f | LICENSE | MPL-2.0 | match |
| 59 | @axe-core/playwright | dequelabs/axe-core-npm | v4.14.0 | 2375f7f5523a2accaeef91a3cb12e30a46e7fbea | LICENSE | MPL-2.0 | match |
| 60 | k6 | grafana/k6 | v2.3.0 | e0887846143ab176d4b5483c9d52cf3b3e009f1a | LICENSE.md | AGPL-3.0 | match (tooling only) |
| 61 | OWASP ZAP | zaproxy/zaproxy | v2.17.0 | 8a1bff313f4d183dba5aa154ecbe89ad751c9153 | LICENSE | Apache-2.0 | match |
| 62 | Semgrep CLI | semgrep/semgrep | v1.183.0 | 4fe07d805dd2a4b64fed486e95136923f08648d0 | LICENSE | LGPL-2.1 | match (tooling only) |
| 63 | Bandit | PyCQA/bandit | 1.9.4 | 92ae8b82fb422a639f0ed8d99e96cea769594e08 | LICENSE | Apache-2.0 | match |
| 64 | ESLint | eslint/eslint | v10.14.0 | 12cbff4125db3f6446f72fa0c48c46b92b120427 | LICENSE | MIT | match |
| 65 | Trivy | aquasecurity/trivy | v0.76.1 | e713f67f7d54decdcd9b3132c9751833dcced698 | LICENSE | Apache-2.0 | match |
| 66 | gitleaks | gitleaks/gitleaks | v8.30.1 | 83d9cd684c87d95d656c1458ef04895a7f1cbd8e | LICENSE | MIT | match |
| 67 | pip-audit | pypa/pip-audit | v2.10.1 | 8894eb8cee033531a1fbd9f2fb160892531c14e3 | LICENSE | Apache-2.0 | match |
| 68 | ScanCode toolkit | aboutcode-org/scancode-toolkit | v32.5.0 | abd87fb81609ea4a29ab4cdda755c188b8be3601 | NOTICE, apache-2.0.LICENSE, cc-by-4.0.LICENSE | Apache-2.0 AND CC-BY-4.0 | mismatch (E5) |
| 69 | license-checker | davglass/license-checker | v25.0.1 (tag) | 05f5e14322ccadc9836b9b68404030fba508e854 | LICENSE | BSD-3-Clause | note (N10) |
| 70 | pip-licenses | raimon49/pip-licenses | v-5.5.5 | a870ce40eebf6d11c7cdfd513ff547d10fe0af2b | LICENSE | MIT | match |
| 71 | Ollama | ollama/ollama | v0.40.13 | 04088e7c9d41cba5d33bafbf788d87a465c79d5b | LICENSE | MIT | match |

**Totals:** 71 repositories across 51 register rows. 70 license files read; 70 consistent with the policy result already recorded in 3.6. 1 unverified (ipp). 3 register texts corrected (Puck, structlog, ScanCode). No row moves from allowed to prohibited.

### Tag selection notes
- Celery: GitHub marks `v5.7.0rc1` as latest without flagging it a pre-release, so the last final release, `v5.6.3`, was used.
- Vite: the repository's "latest" release is `create-vite@9.3.3`, so the core package release `v8.3.5` was used.
- i18n-iso-countries: the last GitHub release is v7.0.0 (2021), but tags continue to `v7.14.0`, which was used.
- PostgreSQL: the register pins major version 16, so the newest `REL_16_*` tag was used rather than `REL_19_RC1`.
- Monorepos (TanStack, dnd-kit, shadcn/ui, Radix) tag per package or per release train. The license file is at the repository root and applies to every package.

### Notes (agree with register)
- **N1 Celery:** the code is BSD-3-Clause. The same LICENSE file puts the documentation under CC-BY-SA-4.0. Documentation is not bundled, so there is no impact.
- **N2 Valkey:** COPYING holds two BSD-3-Clause grants: "Valkey contributors 2024-present" and "Redis Ltd. 2006-2020". The Redis-derived code predates Redis's 2024 relicensing, which confirms the reasoning in 3.2.
- **N3 feedparser:** the code is BSD-2-Clause. The docs use a separate BSD-2-style documentation license.
- **N4 SearXNG:** has no tags or releases; it ships as rolling container images. It was read at `master` HEAD. It stays AGPL-3.0, service boundary only (ADR-0003).
- **N5 langdetect:** a short Apache-2.0 notice. The last release (1.0.8) was in 2021. lingua-py is active. Both are allowed; the choice belongs to M4 research.
- **N6 MapLibre GL JS:** LICENSE.txt carries MapLibre BSD-3-Clause plus inherited notices: Mapbox GL JS (BSD-3-Clause, 2020), Evan Wallace (MIT) and Mike Bostock (BSD-3-Clause). All are permissive, and all must be reproduced in `THIRD_PARTY_NOTICES.md` when the bundle ships.
- **N7 world-atlas:** ISC, but **the repository is archived** (last release 2019). This has no license impact. It is an ADR-0004 maintenance input, proposed as BL-12.
- **N8 pycasbin:** the repository moved to `apache/casbin-pycasbin`. The license is unchanged (Apache-2.0).
- **N9 Hypothesis:** MPL-2.0, with some files keeping their original upstream licenses. It is tooling only.
- **N10 license-checker:** BSD-3-Clause; no push since 2024-01. It is tooling only.

## Addendum: M0 scaffold additions (#27, 2026-11-02)

Same method as above, except that the license file was read from a shallow `git clone --branch <tag>` of the project's own repository (the session's GitHub API access is limited to this repository). Tags match the versions locked in `api/uv.lock`.

| # | Component | Repository | Tag | Commit | File | SPDX | Policy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | Uvicorn | encode/uvicorn | 0.54.0 | 3eb9a9ab9af69005c687728097461c1fd2a95db9 | LICENSE.md | BSD-3-Clause | allowed |
| A2 | pydantic-settings | pydantic/pydantic-settings | v2.16.2 | 94150a0d24967026724031a08e6949b9849df3c5 | LICENSE | MIT | allowed |
| A3 | pytest-asyncio | pytest-dev/pytest-asyncio | v1.4.1.post1 | e4203495fecbe370d971eaf90ac5ac7d97e67b9a | LICENSE | Apache-2.0 | allowed (tooling) |
| A4 | uv | astral-sh/uv | 0.11.32 | 3010295ae7ff572de459987ad70db315a62ecd61 | LICENSE-MIT, LICENSE-APACHE | MIT OR Apache-2.0 | allowed (tooling) |
| A5 | Ruff | astral-sh/ruff | 0.17.3 | ba65abf8ba7bfbcc059f7fb9712be5ba9cab6abc | LICENSE | MIT | allowed (tooling) |
| A6 | mypy | python/mypy | v2.4.1 | ad02a35e623d105ab7340f75558716bc09f8242e | LICENSE | MIT; mypyc `lib-rt` files PSF-2.0 | allowed (tooling) |
| A7 | CPython | python/cpython | v3.12.3 | f6650f9ad73359051f3e558c2431a109bc016664 | LICENSE | PSF-2.0 | not on the allow-list; see BL-53 |
| A8 | Docker official Python image | docker-library/python | untagged HEAD, 2026-11-02 | f4c67ece208dead594e43628d22e3c6027dd97ab | LICENSE | MIT | allowed |
| A9 | TypeScript | microsoft/TypeScript | v5.9.3 | c63de15a992d37f0d6cec03ac7631872838602cb | LICENSE.txt | Apache-2.0 | allowed (tooling) |
| A10 | typescript-eslint | typescript-eslint/typescript-eslint | v8.72.1 | 4ad6b7553781fa3c93fc26642d7219d2e6624504 | LICENSE | MIT | allowed (tooling) |
| A11 | eslint-plugin-react-hooks | facebook/react | eslint-plugin-react-hooks@7.1.1 | d1727fbf987392749b374f3afe62227d2c70fc41 | LICENSE | MIT | allowed (tooling) |
| A12 | eslint-plugin-jsx-a11y | jsx-eslint/eslint-plugin-jsx-a11y | v6.10.2 | 7f3d698f40d697471555e1dae74bfc7ee94d0b86 | LICENSE.md | MIT | allowed (tooling) |
| A13 | Prettier | prettier/prettier | 3.9.10 | 1172b82c295c4f889fd787dc6c78c3e194ebf353 | LICENSE | MIT | allowed (tooling) |
| A14 | pnpm | pnpm/pnpm | v9.15.9 | d22a3f65ee047ecee7c89dd6f1971ecea4ecd4d4 | LICENSE | MIT | allowed (tooling) |
| A15 | jsdom | jsdom/jsdom | v30.1.3 | 058c0f55f369a70bcb113d660ae562b9066f2d44 | LICENSE.txt | MIT | allowed (tooling) |
| A16 | jest-dom | testing-library/jest-dom | v7.0.1 | 3782c78b3dc9824675afe0cb8f1722f8c96f494d | LICENSE | MIT | allowed (tooling) |
| A17 | user-event | testing-library/user-event | v14.6.8 | 1951eb77cc190a68eb6dac6bd40b53648b18805f | LICENSE | MIT | allowed (tooling) |
| A18 | DefinitelyTyped | DefinitelyTyped/DefinitelyTyped | untagged HEAD, 2026-11-02 | 8239b0b905a41a5dead2beb0cfa05893a09dc087 | LICENSE | MIT | allowed (tooling) |
| A19 | Node.js | nodejs/node | v22.23.4 | 27f213124280b4db4cd1e3dd42f6f8afd01ceff7 | LICENSE | MIT, with bundled third-party notices | allowed (development image only) |
| A20 | Docker official Node image | nodejs/docker-node | untagged HEAD, 2026-11-02 | 14b1d124e21d312c46b30db98985ab7e58a89594 | LICENSE | MIT | allowed (development image only) |

Re-read at the versions pinned in `web/pnpm-lock.yaml`, because rows 21, 22, 26, 55 and 64 above were read at newer majors; all unchanged (MIT): React v18.3.1 `f1338f8080abd1386454a10bbf93d67bfe37ce85`, Vite v6.4.5 `83ab40b53969349d5c4ed259313fff367bb86827`, Tailwind CSS v3.4.19 `f38be227df384504a170409c2131ca5ca8bfe025`, Vitest v3.2.7 `c0c203db7ae2948536ad54f93e3a2b168334e245`, ESLint v9.39.5 `4a24e8c09d374d773a034e36b1d7a7fbe1216478`.

Transitive packages in `api/uv.lock` (Starlette, AnyIO, python-dotenv, typing-extensions and others) and `web/pnpm-lock.yaml` are not listed here; the license scan in #29 (pip-licenses, license-checker and the allow-list) covers them.

## Exceptions (component evaluation records)

Only the license criteria are in scope for R-01. Activity, tests, documentation, API fit and size are scored by each module's candidate research (3.8 step 1).

### E1. ipp (npm)

**Capability needed:** IPP printing bridge · **Module:** M8 · **Repository URL:** https://github.com/williamkapke/ipp · **Version evaluated:** 2.0.0 (`package.json`; no git tags)
**License (from LICENSE file at commit 5d806b7dda5191826672346d3927c2f8670b42a4):** no LICENSE, COPYING or NOTICE file exists. `README.md` has a "License: MIT" heading. `package.json` uses the deprecated `licenses: [{type: "MIT"}]` field. · **Policy result:** cannot be determined from a license file

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 2 | MIT is claimed but no license text or copyright notice exists, so the MIT notice condition cannot be met as written |
| Activity last 12 months | 1 | last commit 2019-08-17; last push 2022-08-17; `engines.node` is `<4.0.0` |

**Decision:** keep at S; do not adopt until R-04 decides.
**Reasoning:** without a license text, the register cannot claim V. Combined with no activity since 2019 and an engines field pinned below Node 4, R-04 should prefer a maintained, properly licensed alternative or fall back to browser print only.
**Notices required:** not applicable until a replacement is chosen.

### E2. trafilatura (version boundary)

**Capability needed:** main-text extraction · **Module:** M3 · **Repository URL:** https://github.com/adbar/trafilatura · **Version evaluated:** v2.3.1, plus the v1.7.0 and v1.8.0 boundary
**License (from LICENSE file at commit e2f85c965662c7df26b73290ef175b2c2a5fdca6):** Apache-2.0 · **Policy result:** allowed (from 1.8.0)

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | v1.7.0 (97dc088190506f46651fca86c50c333832c82a03) LICENSE is GPL-3.0; v1.8.0 (ff38644e41341c20f8f13e970b0e94f83fa4a0ef) and v2.3.1 are Apache-2.0 |

**Decision:** dependency, pinned `>=1.8.0` (the register already says "1.8+").
**Reasoning:** the boundary stated in 3.2 is confirmed against the files on both sides, so the lower pin is mandatory.
**Notices required:** no (dependency, not vendored; M3 checks for an upstream NOTICE file when it pins).

### E3. Puck (package renamed)

**Capability needed:** drag-and-drop layout editor · **Module:** M7 · **Repository URL:** https://github.com/puckeditor/puck · **Version evaluated:** v0.24.0
**License (from LICENSE file at commit d14401c3a47947543e9de733ef1a20fb85140d52):** MIT ("Copyright (c) The Puck Contributors") · **Policy result:** allowed

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | MIT; `packages/core/package.json` is named `@puckeditor/core` with `license: MIT` |

**Decision:** dependency. Register text corrected from `@measured/puck` to `@puckeditor/core`.
**Reasoning:** the old package name in the register would point M7 at a stale npm package, so the name must change before ADR-0005 is written.
**Notices required:** no.

### E4. structlog (dual license)

**Capability needed:** structured logging · **Module:** M10 · **Repository URL:** https://github.com/hynek/structlog · **Version evaluated:** 26.1.0
**License (from LICENSE file at commit 8174a86a2f14b5bd295eded733ff5fffc12aa173):** `LICENSE-MIT` and `LICENSE-APACHE`; `pyproject.toml` declares `MIT OR Apache-2.0` · **Policy result:** allowed

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | both options are on the allowed list |

**Decision:** dependency. Register text corrected from "MIT" to "MIT OR Apache-2.0"; either option satisfies 3.5.
**Reasoning:** the register should state the SPDX expression the project declares.
**Notices required:** no.

### E5. ScanCode toolkit (data license)

**Capability needed:** license inventory · **Module:** compliance · **Repository URL:** https://github.com/aboutcode-org/scancode-toolkit · **Version evaluated:** v32.5.0
**License (from LICENSE file at commit abd87fb81609ea4a29ab4cdda755c188b8be3601):** NOTICE declares `Apache-2.0 AND CC-BY-4.0` (software Apache-2.0, license-detection data CC-BY-4.0) · **Policy result:** allowed (tooling)

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | both allowed; it is used only as a development tool, so CC-BY attribution does not reach the product |

**Decision:** tooling. Register text corrected to "Apache-2.0 AND CC-BY-4.0".
**Reasoning:** the register should not hide the data license, even for tooling.
**Notices required:** no (not bundled).

## ADRs affected

No ADR files exist yet (`docs/decisions/` holds only README and ASSUMPTIONS). The planned ADRs in 3.7 should cite this record:
- **ADR-0003** (license policy and service-boundary exception): the AGPL-3.0 licenses of SearXNG, Grafana and k6 and the LGPL-2.1 license of Semgrep are confirmed from their files.
- **ADR-0004** (MapLibre with Natural Earth): MapLibre's notice obligations (N6), Natural Earth public domain confirmed, and world-atlas archived (N7).
- **ADR-0005** (Puck): the package name is `@puckeditor/core` (E3).
- **ADR-0006** (Celery and Valkey): Valkey's BSD-3-Clause license is confirmed for both copyright blocks (N2).

## Follow-ups

- BL-12: replace or vendor world-atlas, since the repository is archived (ADR-0004 input).
- BL-13: ipp has no license file; feeds R-04, which should prefer a maintained alternative.
- BL-14: email-validator and croniter appear in `docs/modules/M8-output-delivery.md` but have no register row.
