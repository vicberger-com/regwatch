# R-04: IPP client for the print bridge

**Issue:** #6 · **Module:** M8 · **Requirements:** REQ-15, REQ-20 · **Backlog:** BL-13 · **Date:** 2026-11-01
**Policy:** `docs/03-architecture.md` 3.5 · **Register:** 3.6 · **Protocol:** 3.8 · **Prior record:** R-01 E1

## Question

Confirm an MIT or Apache-2.0 licensed IPP client that can send a PDF from the print bridge to a network printer, or conclude that the first release ships browser printing only and the server-side print bridge is deferred.

## Recommendation

**The first release ships browser printing only. The server-side print bridge is deferred (BL-13).**

1. No Node client passes the license gate, and the tooling contract (`docs/contracts/M0-tooling.md`) fixes `print-bridge/` as a Node package. `ipp` has no license text. `@sealsystems/ipp` ships an MIT file, but its source repository is not publicly reachable, so no commit can be recorded. It also derives from the unlicensed `ipp` code without carrying that author's notice.
2. Python clients pass the license gate and printed in the live test. `ippx` (MIT, its only runtime dependency is httpx, which is already in the register) fits the project best. It is young (v0.1.1, one maintainer). `aioipp` (MIT) is better maintained, but from 0.19.0 it requires Python 3.14, while the contract fixes Python 3.12.
3. Server printing is therefore possible, but only with a contract change: a Python print bridge, or `outputs.print_ipp` sending IPP from the worker. This is proposed as BL-15. When the bridge is scheduled, re-score `ippx` and `aioipp` and open a `CP-nn` issue. Until then the `outputs.server_print` flag stays off. This matches the M8 question-bank default (question 3).

## Method

- Candidates came from the npm and PyPI registries and from the hints in the earlier issue #6 attempts. `ipp-encoder`, `ipp-printer` and `unix-print` were screened out because they encode only, act as a printer server, or shell out to `lp`.
- **Licenses:** each repository was cloned with `git clone --filter=blob:none`, and the license file was read with `git show <tag>:<file>` at the tag recorded below. In this session, the GitHub REST API is scoped to this repository only, so tags and commits come from git itself. Two repositories (`sealsystems/node-ipp`, `filiptypjeu/npm-easyprint`) were not publicly cloneable, because git asked for credentials. For those, the published npm tarball was read and its SHA-256 recorded. That is not equivalent to a repository LICENSE file at a commit.
- **Activity:** `git rev-list --count --since=2025-11-01 HEAD` and tag dates. **Advisories:** PyPI JSON `vulnerabilities` per release and `pnpm audit`. OSV (`api.osv.dev`) and the GitHub advisory API were not reachable from this environment.

## Candidates

| # | Candidate | Lang | Version | Repository | Tag / commit read | License file | SPDX | Last commit | Live test | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `ipp` | Node | 2.0.1 (npm) | williamkapke/ipp | untagged HEAD 5d806b7dda5191826672346d3927c2f8670b42a4 | **none** (README and package.json claim MIT) | none | 2019-08-17 | printed | reject |
| 2 | `@sealsystems/ipp` | Node | 2.11.0 | sealsystems/node-ipp (**not reachable**) | npm tarball sha256 fc36f240…1181d39 | LICENSE (tarball only) | MIT | unknown; release 2025-12-03 | printed | reject (review) |
| 3 | `ipp-easyprint` | Node | 3.0.5 | filiptypjeu/npm-easyprint (**not reachable**) | npm tarball sha256 7f0eea7d…77528f166 | **none** (package.json says ISC) | none | unknown; release 2021-09-01 | not run | reject |
| 4 | `@thiagoelg/node-printer` | Node (native) | 0.6.2 | thiagoelg/node-printer | v0.6.2 85f6202f5f16bf29e172425c716257978a9ace67 | **none** (package.json BSD, README MIT) | none | 2023-10-04 | not run | reject |
| 5 | `pyipp` | Python | 0.17.2 | ctalkington/python-ipp | 0.17.2 d49d5aa2c1ee50b804e280515db5591c66196264 | LICENSE | MIT | 2025-07-05 | not run (code identical in path to 6) | reject |
| 6 | `aioipp` (fork of pyipp) | Python | 0.18.1 (0.21.0 latest) | brianegge/aioipp | 0.18.1 f9c23a73e5e44ae0350079586dbd167c6bd2bb45; 0.21.0 fb0f82e93010ff4785ee67dc28e46a4b82fbd3af | LICENSE | MIT | 2026-10-31 | printed (0.18.1) | fallback |
| 7 | `ippx` | Python | 0.1.1 | smck83/ippx | v0.1.1 4ea06b47fcc2e9dcc0135f23a6695afb55f03323 | LICENSE | MIT | 2026-08-23 | printed | preferred if bridge moves to Python |
| 8 | `pyipptool` | Python | 0.4.9 | ezeep/pyipptool | v0.4.9 fddfc13893b5c16083d454ca49d374a59f10fe4e | LICENSE.txt | Apache-2.0 | 2014-06-09 | not run | reject |

Excluded by policy without evaluation: pycups (GPL-2.0, see 3.2).

## Live test evidence

**Server:** `ippeveprinter` from CUPS 2.4.7 (Ubuntu package `cups-ipp-utils` 2.4.7-1.2ubuntu7.14; `/usr/share/doc/cups-ipp-utils/copyright` says Apache-2.0 with GPL2/LGPL2 exception). It is the PWG reference IPP Everywhere printer and was used as test tooling only. Command: `ippeveprinter -v -k -d <spool> -f application/pdf,application/octet-stream -p 8631 -n localhost "regwatch-test"`.

**Environment workarounds (not part of any candidate):** `ippeveprinter` needs DNS-SD, so `dbus-daemon` and `avahi-daemon` were started. It also stops when it cannot open an IPv6 listener, and this container has no IPv6 (`/proc/sys/net/ipv6` is absent). A 20-line `LD_PRELOAD` shim moved only that IPv6 listener to an ephemeral IPv4 loopback port. All requests went to the unmodified IPv4 listener on port 8631. These steps used `apt-get`, `gcc` and daemons, none of which are in the GitHub Action's allowed command list, so the test cannot be repeated in the Action runner as configured.

**Document:** a hand-built one-page PDF 1.4, 602 bytes, sha256 `93cb2b592cc01d5a8067485a060b19f48356bda16caf2772b987e8bac84beaa2`.

**Clients:** Python 3.12.3 venv via `uv` (aioipp 0.18.1 with aiohttp 3.14.5; ippx 0.1.1 with httpx 0.28.1). Node v22.23.4 via `pnpm` (`@sealsystems/ipp` 2.11.0, `ipp` 2.0.1). Each client sent one `Print-Job` with `document-format=application/pdf` to `ipp://localhost:8631/ipp/print`.

| Job | Client | Print-Job response | Final job-state (independent `ipptool` Get-Jobs) | Spool file sha256 = input |
| --- | --- | --- | --- | --- |
| 1 | aioipp 0.18.1 | status-code 0 (successful-ok), job-id 1 | completed | yes |
| 2 | ippx 0.1.1 | job-id 2; `wait_for_job` → 9, `job-completed-successfully` | completed | yes |
| 3 | @sealsystems/ipp 2.11.0 | successful-ok, job-id 3 | completed | yes |
| 4 | ipp 2.0.1 (despite `engines.node <4.0.0`) | successful-ok, job-id 4 | completed | yes |

The ippx and `@sealsystems/ipp` first attempts got `server-error-busy` because the single-job test printer was still processing job 1. Both were rerun after `printer-state` returned to `idle`. The server log shows six `Print-Job` requests: four `successful-ok` (one per job) and the two `server-error-busy` responses.

**Exercised:** IPP/1.1 `Print-Job` over plain HTTP to a local IPP Everywhere reference server, delivery of PDF bytes, job completion state. **Not exercised:** a physical printer or paper output, `ipps://` (TLS), authentication, `copies` and `media` attributes, `Get-Job-Attributes` polling from aioipp or the Node clients, large documents, the regwatch bridge or worker code (none exists yet), candidates 3, 4, 5 and 8.

## Evaluation records

### 1. ipp (npm)

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/williamkapke/ipp · **Version evaluated:** 2.0.1 (npm); repository HEAD declares 2.0.0
**License (from LICENSE file at commit 5d806b7dda5191826672346d3927c2f8670b42a4):** no LICENSE file in the repository or in the 2.0.1 tarball · **Policy result:** cannot be determined (R-01 E1)

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 1 | MIT claimed only; no license text or copyright line to reproduce |
| Activity last 12 months | 1 | 0 commits; last 2019-08-17 |
| Tests and CI | 2 | one parser test file; no CI |
| Documentation | 3 | README with examples |
| Open security advisories | 5 | `pnpm audit`: none; no runtime dependencies |
| API fit | 3 | `Printer.execute('Print-Job')` worked on Node 22; `engines` still says `<4.0.0` |
| Size or footprint | 4 | 752 KB unpacked (includes JSON fixtures), 0 dependencies |

**Decision:** reject · **Reasoning:** there is no license text to comply with, and it is unmaintained for seven years. · **Notices required:** no

### 2. @sealsystems/ipp

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/sealsystems/node-ipp (not publicly reachable on 2026-11-01) · **Version evaluated:** 2.11.0
**License (from LICENSE file at commit ...):** no commit available. The npm tarball (sha256 fc36f2409b9b050f538fd06f45d60b9cd3d42e308739e945e5b62b6db1181d39) holds an MIT LICENSE: "Copyright (c) 2017-2025 SEAL Systems AG" · **Policy result:** review

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 2 | MIT text, but it is a fork of `ipp` (package.json author William Kapke, README links to williamkapke/ipp), and the upstream code never carried a license text or notice |
| Activity last 12 months | 3 | release 2.11.0 on 2025-12-03; commit history not visible |
| Tests and CI | 1 | not verifiable: no tests in tarball, repository unreachable |
| Documentation | 3 | README inherited from `ipp` |
| Open security advisories | 3 | pins `moment` exactly at 2.30.1: GHSA-4p3w-j4w9-5jqw (moderate, fixed in 2.31.0) |
| API fit | 4 | same API as `ipp`; printed in the live test |
| Size or footprint | 4 | 157 KB unpacked, 1 dependency |

**Decision:** reject (reconsider if the source repository becomes public and upstream provenance is resolved) · **Reasoning:** the register's V status needs a LICENSE at a recorded commit, and the copyright chain from the unlicensed upstream is incomplete. · **Notices required:** not applicable

### 3. ipp-easyprint

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/filiptypjeu/npm-easyprint (not publicly reachable) · **Version evaluated:** 3.0.5
**License (from LICENSE file at commit ...):** none; the tarball (sha256 7f0eea7da086f8c6cd770abd3c30c3b47f3e48fe9254a74ec15c14d77528f166) has no license file, and package.json says ISC · **Policy result:** cannot be determined

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 1 | no license text |
| Activity last 12 months | 1 | last release 2021-09-01 |
| Tests and CI | 1 | not verifiable |
| Documentation | 2 | short README |
| Open security advisories | 3 | inherits `@sealsystems/ipp` and `moment` |
| API fit | 3 | convenience wrapper over `@sealsystems/ipp` |
| Size or footprint | 4 | 161 KB unpacked |

**Decision:** reject · **Reasoning:** no license text, unmaintained, and it only wraps candidate 2. · **Notices required:** not applicable

### 4. @thiagoelg/node-printer

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/thiagoelg/node-printer · **Version evaluated:** 0.6.2
**License (from LICENSE file at commit 85f6202f5f16bf29e172425c716257978a9ace67):** no license file; package.json says BSD, README says MIT · **Policy result:** cannot be determined

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 1 | no text, and the two declarations conflict |
| Activity last 12 months | 1 | 0 commits; last 2023-10-04 |
| Tests and CI | 2 | test directory; CI only builds prebuilt binaries |
| Documentation | 3 | README and examples |
| Open security advisories | n/a | not audited (rejected on license) |
| API fit | 1 | native binding to the host's libcups and CUPS queues, not a direct IPP client |
| Size or footprint | 2 | `node-gyp` build or prebuilt binary; needs CUPS in the container |

**Decision:** reject · **Reasoning:** no license text, and a native CUPS dependency the bridge does not need. · **Notices required:** not applicable

### 5. pyipp

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/ctalkington/python-ipp · **Version evaluated:** 0.17.2
**License (from LICENSE file at commit d49d5aa2c1ee50b804e280515db5591c66196264):** MIT, "Copyright (c) 2020 Chris Talkington" · **Policy result:** allowed

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | MIT |
| Activity last 12 months | 1 | 0 commits; last 2025-07-05 |
| Tests and CI | 4 | pytest, typing and lint workflows |
| Documentation | 3 | README; printing only in `examples/print_example.py` |
| Open security advisories | 5 | PyPI: none for 0.17.2 |
| API fit | 3 | generic `execute(PRINT_JOB, {..., "data": bytes})`; built for monitoring |
| Size or footprint | 3 | 16 KB wheel; aiohttp, yarl, deepmerge, awesomeversion, backoff |

**Decision:** reject · **Reasoning:** inactive; its maintained successor is candidate 6. · **Notices required:** not applicable

### 6. aioipp

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/brianegge/aioipp · **Version evaluated:** 0.18.1 (also read 0.21.0)
**License (from LICENSE file at commit f9c23a73e5e44ae0350079586dbd167c6bd2bb45):** MIT, "Copyright (c) 2020 Chris Talkington". The file is byte-identical at 0.21.0 (fb0f82e) and in pyipp 0.17.2 · **Policy result:** allowed

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | MIT; the original copyright is kept in the fork |
| Activity last 12 months | 5 | 97 commits (36 by the maintainer, the rest dependency bots); 9 releases since 2026-09-10 |
| Tests and CI | 4 | 49 test functions; CI on Python 3.11 to 3.13 at 0.18.1 |
| Documentation | 3 | README; printing only by example |
| Open security advisories | 5 | PyPI: none for 0.18.1 or aiohttp 3.14.5 |
| API fit | 3 | printed in the live test; raw dictionary API with no job polling helper; **0.19.0 and later require Python >=3.14**, but the contract fixes 3.12 |
| Size or footprint | 3 | 17 KB wheel; aiohttp, yarl, deepmerge, awesomeversion (none in the register) |

**Decision:** pattern or fallback only; not adopted · **Reasoning:** maintained and licensed, but adopting it now means pinning a version that upstream has already left behind. · **Notices required:** not applicable until adopted

### 7. ippx

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/smck83/ippx · **Version evaluated:** 0.1.1
**License (from LICENSE file at commit 4ea06b47fcc2e9dcc0135f23a6695afb55f03323):** MIT, "Copyright(c) 2026 smck83" · **Policy result:** allowed

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | MIT |
| Activity last 12 months | 2 | 6 commits and 2 releases since 2026-06-13; one maintainer |
| Tests and CI | 4 | 46 test functions; CI runs ruff, mypy and pytest on Python 3.11 to 3.13 |
| Documentation | 4 | README covers print, polling, TLS pinning, auth |
| Open security advisories | 5 | PyPI: none for 0.1.1 |
| API fit | 5 | `print_job`, `wait_for_job`, `get_job_attributes`, `cancel_job`, sync and async; printed in the live test |
| Size or footprint | 5 | 21 KB wheel; only runtime dependency is httpx (already V in 3.6) |

**Decision:** not adopted now; preferred candidate for BL-15 · **Reasoning:** best technical fit for the Python stack, but too new to depend on until it shows sustained maintenance. · **Notices required:** not applicable until adopted

### 8. pyipptool

**Capability needed:** IPP client for print bridge · **Module:** M8 · **Repository URL:** https://github.com/ezeep/pyipptool · **Version evaluated:** 0.4.9
**License (from LICENSE file at commit fddfc13893b5c16083d454ca49d374a59f10fe4e):** Apache-2.0, "Copyright 2013 ezeep GmbH" · **Policy result:** allowed

| Criterion (1 to 5) | Score | Evidence |
| --- | --- | --- |
| License fit | 5 | Apache-2.0 |
| Activity last 12 months | 1 | last commit 2014-06-09 |
| Tests and CI | 2 | tests present; no CI |
| Documentation | 2 | short README |
| Open security advisories | 5 | PyPI: none |
| API fit | 1 | runs the CUPS `ipptool` binary through `subprocess`; Python 2.7 classifiers |
| Size or footprint | 2 | needs CUPS tools in the image |

**Decision:** reject · **Reasoning:** abandoned for twelve years, and it is a subprocess wrapper. · **Notices required:** not applicable

## Inputs for a future print-bridge ADR

No client is adopted, so no ADR is written now. When BL-15 is taken up, the ADR should record:
- **Decision:** a Python print path (a `print-bridge` Python service or `outputs.print_ipp` in the worker) using ippx, or aioipp if ippx has stalled. This needs a `CP-nn` change to `M0-tooling.md` (Node `print-bridge/`), `03-architecture.md` 3.2 and 3.6, and the M8 spec's component list.
- **Alternatives:** Node `ipp` and `@sealsystems/ipp` (license and provenance), native CUPS bindings (pycups is GPL-2.0; node-printer has no license), and browser print only.
- **Constraints carried over from M8:** printers are only those registered by an admin (SSRF), the bridge is internal-only, `ipps://` is preferred with optional certificate pinning, and job state comes from `Get-Job-Attributes`.
- **Test:** repeat this record's live test in CI with `ippeveprinter` (an Apache-2.0 tooling row would be needed) on a runner with IPv6, or use the shim.
