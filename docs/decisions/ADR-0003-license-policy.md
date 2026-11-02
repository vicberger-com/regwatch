# ADR-0003: License policy, the service-boundary exception for unmodified AGPL services, and data terms

**Status:** proposed · **Date:** 2026-11-02 · **Requirements:** REQ-19, REQ-20 (also REQ-02, REQ-27)
**Research:** R-01 (#3), R-03 (#5), R-04 (#6), R-07 (#9), R-08 (#11); `docs/03-architecture.md` 3.5 and 3.6; `docs/08-security-compliance.md` 8.3 and 8.6; BL-20

## Context

- **The policy.** REQ-20 requires all reused code to come from licenses that permit the use. 3.5 lists licenses as allowed, review-required or prohibited in bundled code. It permits AGPL and GPL applications "as unmodified separate services or developer tooling, never vendored", and says every exception needs an ADR approved by the owner.
- **R-01: the register.** R-01 read 70 license files across 71 repositories for 51 register rows. 50 rows moved to status V, and no row moved from allowed to prohibited.
  - `ipp` (npm) has no license file at all (E1).
  - Three register texts were corrected: the Puck package name, structlog's dual license and ScanCode's data license.
  - AGPL-3.0 was confirmed for SearXNG (untagged HEAD `9ded3be`), Grafana and k6, and LGPL-2.1 for Semgrep.
  - trafilatura is GPL-3.0 before 1.8.0 (E2), and Celery's documentation is CC-BY-SA-4.0, though the documentation is not bundled (N1).
- **AGPL services the research now relies on.** Both run from the official image, unmodified, configured only by mounted files and environment variables:
  - SearXNG, the only zero-cost search option at the needed volume (R-07, image digest recorded);
  - LibreTranslate 1.9.6 (`497f6c6`), the only local translation provider left after Argos was blocked (R-08).
  - R-08 also notes that LibreTranslate's TRADEMARK.md treats container orchestration as "modified" for trademark purposes, so the admin UI should name it descriptively.
- **R-08: in-process Argos is blocked.**
  - argostranslate 1.11.0 imports AGPL `minisbd` at module level (F1).
  - 1.10.0 downloads the CC BY-SA 3.0 spaCy model `xx_sent_ud_sm` at import, outside SafeFetcher (F2).
  - The de 1.3 and ja 1.1 model packages state no license (F3), and the Stanza tokenizer model license is not stated (F4).
  - The zh, fr, es and pt models are CC-BY-4.0 with attribution.
- **R-04: provenance.** R-04 rejected the Node `ipp` package: it has no license text and no commits since 2019. `@sealsystems/ipp` has an MIT file in its npm tarball, but its repository is unreachable and it derives from the unlicensed `ipp`. R-04 records that a tarball is not equivalent to a LICENSE file at a recorded commit.
- **R-03: data terms that 3.5 does not name.**
  - OGL v3.0 (legislation.gov.uk); Open Government Licence - Canada, version not stated in the file (C7); Japan's PDL1.0 (C9).
  - CC BY 4.0 with prescribed attribution wording (Australia, C8); CDLA-Permissive-1.0 (OpenSSF data, C1).
  - Commission Decision 2011/833/EU; US government works (C4); CC0 (NIST OSCAL, C5).
  - Restrictive terms: CC BY-ND 3.0 (Brazil ANPD on gov.br, C13); all rights reserved (Singapore CSA, C10; China CAC, C14); a `robots.txt` that forbids all automated collection (flk.npc.gov.cn, C15); no license at all (Asenion tracker, C6).
  - BL-20 asks for an ADR to cover these.

## Decision

1. **Bundled code** follows the lists in 3.5 unchanged. A row is **V** only when an agent read the LICENSE file in the project's own repository at a recorded commit (R-01 method; R-04). A package-index field, a README heading or a file found only in a tarball does not qualify. A component with no license text is not usable, whatever license it claims.
2. **Service-boundary exception.** An AGPL-3.0 or GPL *application* may run as a separate service only if all of these hold:
   - (a) it runs from the official image or release, unmodified, configured only by mounted files and environment variables, and pulled by digest;
   - (b) it runs in its own container and is reached only over its network API; none of its code, libraries or models is imported, vendored or linked into project processes;
   - (c) a research record shows that no permissively licensed option meets the need;
   - (d) it has a register row with reuse mode `service (unmodified)` and status V;
   - (e) its name and logo are used only descriptively.

   Modifying such a service needs a new ADR and publication of the modified source (8.6 item 4). Once this ADR is accepted, the exception covers **SearXNG** (R-07) and **LibreTranslate** (R-08). Grafana, k6 (AGPL) and Semgrep (LGPL-2.1) remain tooling and never ship.
3. **Outside the exception.** SSPL, BUSL/BSL, the Elastic License, RSAL, Commons Clause and the Sustainable Use License are prohibited even as services. An AGPL or GPL library pulled into project processes as a dependency is prohibited, as with Argos 1.11+ through `minisbd`: the exception applies to applications, not dependencies.
4. **Runtime downloads are assessed on what they fetch.** A component that downloads code or models at run time is judged on the downloaded artifact (R-08 F2). Models and datasets that a service loads on the project's behalf (for example LibreTranslate's `LT_LOAD_ONLY` packages) are assessed as data under decision 5.
5. **Data terms (proposed answer to BL-20).**
   - **Allowed for data, with attribution where the terms require it:** OGL-UK-3.0, Open Government Licence - Canada, PDL1.0, CDLA-Permissive-1.0, Commission Decision 2011/833/EU, US government works and CC0, alongside CC-BY-4.0 already in 3.5.
   - **Captured sources fall into three use classes:**
     - (i) *Open:* capture, store and derive seed terms, with attribution.
     - (ii) *Internal monitoring only:* CC BY-ND, all rights reserved, or terms not found. Capture and display inside the organisation only. No seed derivation, and no text in outputs to outside recipients (8.3 recipient allow-list).
     - (iii) *Do not capture:* sources whose terms or `robots.txt` forbid automated access. No robots override is acceptable for them (C15).
   - **Model data:** CC-BY-4.0 models are allowed with attribution. A model with no stated license fails the gate (BL-42). CC BY-SA data needs review, not automatic approval.
6. **Approving a future exception** takes, in order: a research record with evidence; an ADR naming the component, version or digest, boundary and alternatives; a register row; and owner approval at the next gate (an `approved` comment on the gate issue, 6.1). Until approval, the service stays behind its feature flag or Compose profile and is off by default.

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **3.5 lists, a conditional service exception and data use classes (chosen)** | n/a | Keeps the only zero-cost search and local translation options (R-07, R-08); the conditions can be checked at review | AGPL services cannot be patched locally; data classes limit what can leave the organisation |
| Strict permissive-only, no exceptions | n/a | Simplest to audit | Loses SearXNG and LibreTranslate. The paid-API budget is zero (2.4 answer 12), so search and translation would drop to free tiers or nothing |
| Exceptions case by case, no fixed conditions | n/a | Flexible | Nothing to check at review; drift is likely across parallel sessions |
| AGPL libraries allowed in process | AGPL-3.0 | In-process Argos would work | Brings the product's own code under AGPL obligations; prohibited in 3.5 |
| Accept licenses found in package tarballs | varies | Would admit `@sealsystems/ipp` | No recorded commit; incomplete provenance (R-04) |

## Consequences

- **Positive:** every reuse decision in R-01 to R-08 maps to one rule; BL-20 gets a concrete proposal; the register's V standard is defined by method, not by trust.
- **Negative:**
  - SearXNG engine fixes must wait for upstream images, which ship almost daily (R-07).
  - Analysts cannot send class (ii) text outside the organisation, which affects Singapore, China and Brazil ANPD sources (R-03).
  - The version of the Canadian licence is not stated in the source file (C7).
  - R-01 read top-level LICENSE files only, not what is inside service images (BL-52).
- **Register:** no row changes. Data rows for seed sources are added when `seed/` takes derived data (R-03). BL-20 is answered by decision 5, pending the owner.
- **Follow-up backlog rows:** BL-20, BL-40, BL-42, BL-52.

## Open questions for the owner

1. Do you approve the service-boundary exception for SearXNG and LibreTranslate under conditions (a) to (e)?
2. Do you accept the data-terms list and the three use classes (BL-20)?
3. May class (ii) sources (CC BY-ND, all rights reserved) be machine-translated for internal display? A translation is an adaptation, and its legal effect under those terms is not established (R-03 C10, C13, C14).
4. Between gates, may anyone other than you approve an exception? This ADR assumes no: you approve at the next gate, and the service stays off until then.
