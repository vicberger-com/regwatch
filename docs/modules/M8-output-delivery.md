# M8 Output and delivery

**Phase:** P4 · **Size:** M · **Parallelism:** PDF and email (one session), print bridge (one session, flagged), scheduling (one session).
**Requirements:** REQ-10, REQ-15

## Purpose
Send configured reports, query outputs and predefined data to email, printers, PDF download or CSV, on demand or on a schedule, with history and retry.

## Scope
In: PDF rendering through Gotenberg from M7 HTML, email with PDF or CSV attachments and an HTML body, browser print stylesheet, server-side printing to admin-registered IPP printers (feature flag), CSV export of queries, scheduled outputs (cron), output history with download of artifacts, retention of artifacts (default 90 days).
Out: fax, SharePoint or cloud drive push (backlog), webhooks (E19).

## Interfaces
- `POST /outputs` body `{kind: pdf|email|print|csv, source: {layout_id | view_id | query}, destination: {emails[], printer_id, copies}, schedule?: cron}` returns `output_job`.
- `GET /outputs?mine|all`, `GET /outputs/{id}`, `GET /outputs/{id}/artifact` (signed, time-limited), `POST /outputs/{id}/retry`, `DELETE /outputs/{id}` (cancel schedule).
- `GET|POST|PATCH /admin/printers`, `POST /admin/printers/{id}/test-page`.
- Celery tasks: `outputs.render_pdf`, `outputs.send_email`, `outputs.print_ipp`, `outputs.export_csv`, `outputs.schedule_tick`.
- Event `output.sent`.

## Data
`output_job`, `printer`, object store `outputs/{job_id}.pdf|csv`.

## Open-source components
Gotenberg (MIT, service), aiosmtplib (MIT), email-validator (CC0), Mailpit (MIT, dev), Node `ipp` (MIT) in `print-bridge/`, WeasyPrint (BSD-3) fallback, croniter (MIT) for schedules.

## Design notes
- Email: HTML body is the report's first page summary plus a link to the application; attachments capped at 20 MB; recipients restricted to allowed domains list (admin setting) to prevent data exfiltration by a compromised account; all sends audited.
- PDF: Gotenberg Chromium route with the report HTML and inlined CSS and fonts; PDF/A-2b option for archival; metadata title and creator set.
- Printing: the bridge accepts `{printer_url, pdf_ref, copies, media}` on an internal-only port, streams the PDF to the IPP printer, and reports job state; browser print uses `@media print` CSS from M7.
- Schedules run under the requesting user's permissions snapshot and are disabled automatically if the user is disabled.
- Retention job deletes artifacts older than the setting and keeps the job record.

## Acceptance criteria
1. Requesting a PDF of a saved layout produces a downloadable file whose page count matches preview within 2 minutes.
2. Emailing a stock report to two allowed addresses delivers with the PDF attached (verified in Mailpit) and is audited; an address outside the allowed domains is rejected with a clear message.
3. With the print flag on and a test IPP server (ippserver from CUPS project tools or `ipp-usb`-free mock), a print job reaches the printer queue and the job shows `sent`.
4. A weekly schedule creates a job each Monday 07:00 in the user's time zone (tested with a frozen clock).
5. A failed SMTP delivery retries 3 times with backoff and ends `failed` with the error class visible to the user.

## Test plan
- Unit: destination validation, cron parsing, retention policy.
- Integration: Gotenberg container render, Mailpit delivery, IPP mock.
- E2E: print stock report from toolbar to download.
- Security: SSRF on printer URL (bridge accepts only registered printers), attachment size limits, header injection in email fields, signed artifact URLs expire.

## Question bank
1. SMTP relay details and whether authentication is required? Default: admin-configured host, port, STARTTLS, credentials in secrets.
2. Allowed recipient domains? Default: the organisation's domain.
3. Is server-side printing required at launch or is browser print enough? Default: browser print at launch, bridge behind flag.
4. Artifact retention period? Default: 90 days.

## Enhancements to propose
E19 webhooks and chat notifications (Apprise, BSD-2); E1 daily or weekly digest emails; E18 Excel export (openpyxl, MIT).
