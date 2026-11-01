# Security review record: Mx Module name

**Scope (PRs, routes, tasks):** · **Reviewer session label:** · **Date:** · **Author sessions excluded from review:** yes

## Data flows touched
Inputs, outputs, trust boundaries crossed (browser, API, workers, external sources, email, printers, model provider).

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | | | | |
| Tampering | | | | |
| Repudiation | | | | |
| Information disclosure | | | | |
| Denial of service | | | | |
| Elevation of privilege | | | | |

## Checklist
- [ ] Input validation on every field (types, sizes, enumerations)
- [ ] Output encoding in UI, templates, emails, CSV
- [ ] Authentication and authorization on every route and task
- [ ] Session handling (cookie flags, rotation, revocation)
- [ ] Secrets not logged or committed
- [ ] Outbound requests only through SafeFetcher or registered services
- [ ] File and body size limits; content-type checks
- [ ] Logging excludes sensitive data; audit rows written
- [ ] Dependency, image and license scans attached and clean

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |

**Sign-off:** no high or critical open · reviewer label · date
