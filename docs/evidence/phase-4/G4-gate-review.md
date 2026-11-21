# Gate G4 review: Phase 4 Reports and outputs (M7, M8)

**Prepared by:** lead session · **Build under review:** `feat/M7-reports` (top of the Phase 4 stack, on `feat/M11-interests`) at the commit that adds this record · **Date:** 2026-11-21 · **Decision:** **approved by the owner on 2026-11-21** on the `Gate G4` issue, with the open items on their recommended defaults (the owner's standing instruction): the adversarial session is deferred to G5, as at G1 and G3; the manual screen-reader run moves to G5 with it; the M7 and M8 decisions, CP-32 and CP-33 are confirmed; the BL-144 minors follow in Phase 5.

**Exit criterion (6.1):**
- stock reports render to PDF and email;
- a custom layout is saved and printed;
- use testing round 2.

## Exit criterion

| Part | Status | Evidence |
| --- | --- | --- |
| Stock reports render to PDF and email | **Met** | M8 acceptance 1 and 2 (`M8-module-summary.md`): on the QA stack, a stock report becomes a PDF through Gotenberg, and the PDF has the preview's page count (`e2e/reports.spec.ts`); a stock report emailed to two allowed addresses arrives in Mailpit with its PDF, audited (`e2e/reports.spec.ts`). The jurisdiction profile for Germany is made from a screen since U-M7-1 was fixed (re-test, `use-testing/M7.md`). |
| Custom layout saved and printed | **Met** | M7 acceptance 1 and 2 (the Puck builder: save, share, preview; `e2e/reports.spec.ts`, keyboard and axe). Printed three ways: browser printing with markings and page numbers on every page (`e2e/print.spec.ts`); a PDF; and network printing to an IPP printer (M8 acceptance 3, `e2e/printing.spec.ts` with CUPS's ippeveprinter on QA). |
| Use testing round 2 | **Done, with findings fixed** | `docs/evidence/phase-4/use-testing/M7.md` and `M8.md`, an independent tester session, 73 screenshots. Round 2: M7 4 of 7, M8 7 of 11 journeys passed, one blocker and six majors. All seven were fixed and re-tested: the blocker and every major fixed. U-M7-2 is partly fixed (no thumbnails, the preview pane below the list); U-M8-3 was not reproducible in a UI session and is covered by a test. All three realistic-day scenarios pass in the re-test. A new major found then (U-M8-11, faint links on paper) is fixed. Eleven minors and three new minors stay in BL-144. |
| Screen-reader journey (moved here from G3) | **Deferred to G5** at approval | The structure is in place, and axe passes on every e2e journey. The manual run with a screen reader needs a person. |

## Checklist (docs/07-testing-quality.md 7.8)

| Item | Status | Evidence |
| --- | --- | --- |
| Module definitions of done complete and linked | **Yes** | `M7-module-summary.md`: acceptance 1 to 4 met (4 by the page-count journey). `M8-module-summary.md`: acceptance 1 to 5 met. |
| CI green on the release branch; coverage report attached | **Pending the owner:** local only, until the stack is pushed and the PRs opened | `make lint` clean. `make test-api`: 1,567 unit (95.28%) and 474 of 476 database tests at `40caa15`; the two failures explained at the end of this file. `make test-web`: 226 tests. `make e2e`: 14 of 14 on the QA stack (the canary skipped by design). |
| Contract tests pass against the committed OpenAPI | **Yes** | Contract changes in P4: CP-30, CP-31 (M7), CP-32 (signed artifact links), CP-33 (network printing: `GET /printers`, `printer.tls_sha256`, two settings). Every route is now implemented, so the fuzz's stub pass is retired (`test_no_stub_routes_remain`). |
| End-to-end suite green in three themes; accessibility report | **Yes** | The accessibility journey covers the three themes; the reports, outputs and print journeys run axe. |
| Performance results within budgets | **Partly** | A PDF renders in seconds (5.2 s for three pages in use testing; acceptance 1 asks for under two minutes). The M6 first-paint timings still need a production build (U-M6-12). |
| Security scans attached; no high or critical open | **Yes** | `make security` passes, after fixing two `assert`s, an unexplained `Markup` and a semgrep false positive found at this gate (`bc0ead9`). pnpm audit: six moderate advisories, all in development test tooling (BL-143 o). Every M7 and M8 slice, the use-testing fixes and the printing work are signed off by the independent reviewer, with fixes re-verified. |
| Peer, security, use and adversarial records for every module | **Security and use: yes. Peer and adversarial: not yet.** | The adversarial session is the owner's; G1 and G3 deferred it to G5. Peer review is due on each PR. |
| License scan clean; register and notices updated | **Yes** | 702 allowed, 0 failing. New in P4: Puck, Jinja2, 0BSD (ADR-0003 amendment 4), ippx 0.1.1 (MIT, wheel checked against its tag), CUPS ippeveprinter (Apache-2.0, a QA-only separate service). |
| CHANGELOG release section cut; BACKLOG decisions recorded; CP issues summarised | **At the gate** | BL-140 (M7), BL-143 (M8), BL-144 (use testing), BL-145 (network printing); CP-30 to CP-33. |
| Questioning-period issues closed or assumptions recorded | **Recorded** | The M7 and M8 bank defaults on the owner's standing instruction, except M8 question 3, which the owner decided (BL-15). |
| Owner comment `approved` | **Approved 2026-11-21** on the `Gate G4` issue | |

## Owner actions before approval

1. **Push the branch:** `git push origin feat/M7-reports`. Then open the PRs so CI runs.
2. **Migrate the dev stack:** migration 0011 adds `printer.tls_sha256` (`make migrate`). Seed: no change.
3. **Run the screen-reader journey** (NVDA or VoiceOver), including the reports and outputs pages:
   - sign in;
   - the map list and table;
   - an item's tabs;
   - Reports: a stock report's "PDF or email";
   - New output: the report settings, the recipients, and the status message;
   - the Outputs history;
   - the idle warning.
4. **The adversarial session:** run it, or defer it to G5 as at G1 and G3.
5. **Confirm or override:**
   - the decisions recorded in `M7-module-summary.md` and `M8-module-summary.md`;
   - CP-32 and CP-33;
   - the BL-144 minors left open.
6. **Before network printing is turned on for real printers:** set `outputs.printer_networks` to the printers' subnets (empty means none). Prefer `ipps://`, with a certificate fingerprint for self-signed printers.

## Test run at the gate

`make test-api` at `40caa15`:
- **Unit:** 1,567 passed; coverage 95.28%, over the 85% floor, and the security-critical floor met.
- **Database:** 474 of 476 passed, 1 skipped, 2 failed.
  - `test_seed_twice_changes_nothing` still counted 40 settings; CP-33 adds two, so it was corrected (`test_seed.py`) and passes.
  - `test_valkey_rate.py` acceptance 5 is an M3 timing test: it failed while the e2e browsers loaded the machine, as it did once before, and passes alone, 4 of 4 three times. It is recorded as a flake to make robust (BL-144).

`make test-web`: 226 passed. `make e2e` on QA: 14 passed (the canary skipped by design), acceptance 3 against the test printer included. `make security` and `make licenses` pass.
