# M8 Output and delivery: module status record

**Branch:** `feat/M7-reports` (M7 and M8, stacked on `feat/M11-interests`) · **Date:** 2026-11-20 · **Status:**
- **Acceptance:** criteria 1, 2, 4 and 5 are met. Criterion 3 (server printing to an IPP printer) is deferred: browser printing ships, the print bridge stays behind its flag, and BL-15 is for the owner at G4.
- **Security:** each slice (8.1 to 8.7) is signed off by the independent reviewer, with every fix re-verified (the last, `eff7e6f`, included).
- **Tests:**
  - `make test-api`: the full run at `9dfb93f` passed 1,529 unit tests (95.41% coverage) and 459 database tests. The later slices were run on their own suites (outputs: 24 integration, 5 CSV, 3 schedule unit; objectstore 17) and on the full unit suite (1,532). A full run at the branch head was in progress at the time of writing; its result goes in the pull request.
  - `make test-web`: 215 pass; `make lint` is clean.
  - `make e2e` on the QA stack (real Gotenberg, Mailpit and worker): a PDF of a stock report, the preview and the PDF with the same page count, an email arriving in Mailpit with its PDF, a CSV requested from the Outputs page and downloaded, the print layout, and the reports and keyboard journeys with zero axe violations.

## Acceptance criteria (`docs/modules/M8-output-delivery.md`)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A PDF of a saved layout downloads, its page count matching the preview, within 2 minutes | **Met** | `e2e/reports.spec.ts`: "a report becomes a PDF through Gotenberg within two minutes" and "the PDF has the preview's pages" (a 150-row layout; the preview printed by Chromium and Gotenberg's PDF have equal page counts). `test_outputs.py` (rights, retries, caps, cancel during a render). |
| 2 | Emailing a stock report to two allowed addresses delivers with the PDF (Mailpit) and is audited; an outside address is refused clearly | **Met** | `e2e/reports.spec.ts` (Mailpit); `test_outputs.py` email tests and `test_outputs_mail.py` (28: strict single addresses, IDNA, bypasses refused, the explicit envelope). |
| 3 | With the print flag on and a test IPP server, a job reaches the printer and shows `sent` | **Deferred** | R-04: no Node IPP client passes the license gate; the Python route (`ippx`) needs BL-15 and a tooling contract change. M8 question 3's default (browser print at launch, bridge behind the flag) is taken: `outputs.server_print` stays off, `/admin/printers` stays a stub. Browser printing (8.5): `Print.test.tsx`, `printMarkings.test.ts`, `e2e/print.spec.ts`. |
| 4 | A weekly schedule creates a job each Monday 07:00 in the user's time zone (frozen clock) | **Met** | `test_outputs.py::test_a_weekly_schedule_runs_each_monday_at_seven_local` (Europe/Berlin), with the cap, permission, pause, resume and one-tick limit tests; `test_outputs_schedules.py` (the hour between runs over a year, clock changes included). |
| 5 | A failed SMTP delivery retries 3 times with backoff and ends `failed` with the error class shown | **Met** | `test_outputs.py` (30 s and 120 s backoff, three attempts, `smtp-unavailable` shown; a partial send never resends). The Outputs page shows the error text. |

M7 criterion 4 (preview and PDF paginate the same) is met by the same page-count journey.

## Built

| Slice | What | Commits |
| --- | --- | --- |
| 8.1 | PDF through Gotenberg (JavaScript off, file-only allow list), signed artifact links (CP-32), current rights each run, rate and attempt caps, sweep of interrupted renders | `0455fa6`, `a02ed0f`, `602a4c1`, `644cfdd` |
| 8.2 | Email with the PDF: allowed domains, strict single addresses as the envelope, safe headers, one send per recipient, retries with backoff, no clear-text login off the stack | `ebd1ed3`, `8b2e90f`, `0a132fe`, `239aac2` |
| 8.3 | Schedules: cron in the owner's zone, an hour between runs, 10 a user, current rights each run, pause and resume | `9dfb93f`, `c432fb6` |
| 8.4 | CSV of a query or saved view, through the search export's checks and escaping | `24666b1`; source deletion `5dec58d`, `300029d` |
| 8.5 | Browser printing: Print button, print stylesheet, markings and page numbers on every page | `43a31e0`, `eff7e6f` |
| 8.6 | The Outputs page: history, schedules, download, retry, cancel, resume, New output | `84e7ead`, `cfac90f`, `cf748df`, `7bd88b1`, `157ebe1` |
| 8.7 | Retention of output files (`outputs.artifact_retention_days`), isolated tick steps | `bfb30cc`, `84e7ead` |

## Decisions (accepted on recommendation; listed for the owner at G4)
- **Browser printing at launch**, the IPP bridge behind `outputs.server_print` (M8 question 3 default; R-04; BL-13). BL-15 (a Python IPP client) is the owner's choice at G4.
- **CP-32:** the artifact route answers the file itself once the link is signed.
- **Email through the standard library** (`smtplib`), not aiosmtplib; addresses parsed by our own strict rule instead of email-validator: no new dependencies in M8.
- **Schedules in the output_job table** (`scheduled_cron`, child runs with `parent_job_id`), with cron parsing shared with capture schedules instead of croniter.
- **One size cap for outputs:** `outputs.attachment_max_bytes` (20 MB) bounds PDFs, CSVs and attachments.

## Open (BACKLOG BL-143)
- (i) Email with a CSV attachment; (m) a free cron field, report parameters in the form.
- (k) A pass that removes files no job refers to (rare: a commit failing after the file is stored).
- (j) Users whose schedules stop because a shared source was deleted see `source-deleted` in their history; no notice is sent.
- (n) Acceptance 3 with BL-15.
- BL-140 (g), the preview's styles under the production CSP, from M7. BL-140 (d), deleting a layout outputs refer to, is resolved by `5dec58d`.
