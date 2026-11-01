# Regulatory monitor design package

Working codename `regwatch` (placeholder; the owner may rename). This package is the design document for an application that monitors global legal and regulatory changes in information technology and cybersecurity, stores them in a taxonomy-driven database, shows them on a world map, and produces reports and outputs. It is written so that multiple AI sessions and agents can develop and test the application in parallel.

Start with `01-how-to-use.md`. Sections:

| File | Section |
| --- | --- |
| `01-how-to-use.md` | How AI sessions and agents use this package; conventions; definition of done |
| `02-requirements.md` | 27 numbered requirements, gaps, defaults and the Phase 0 question record |
| `03-architecture.md` | Architecture, stack decisions, license policy, component register, ADR list, open-source review protocol |
| `04-data-model.md` | Entities, dynamic attributes, map aggregation, seed data, migration rules |
| `05-modules.md` and `modules/` | Module index and eleven module specifications M0 to M10 |
| `06-process.md` | Phases and gates, parallelization plan, work item lifecycle, repository layout, change report and backlog |
| `07-testing-quality.md` | Test pyramid, fixtures, peer review, security review, use testing, adversarial analysis, gate checklist, pilot waves |
| `08-security-compliance.md` | Threat model, controls, scraping etiquette, privacy, secrets, license compliance |
| `09-enhancements-backlog.md` | 25 suggested enhancements, backlog seed, Phase 0 research items |
| `10-open-questions-risks-glossary.md` | Owner decisions for G0, risks, glossary |
| `contracts/` and `../openapi/regwatch.v1.yaml` | Shared contracts for parallel sessions: tooling decisions, OpenAPI, DDL, registries, environment variables, connector schemas, screen inventory, fixtures |
| `templates/` | Task card, handoff, ADR, questions issue, PR template, component evaluation, security review, adversarial record, use-testing script |

Source: the owner's requirements document (regulatory_application.docx), reviewed on 2026-11-01. A formatted copy of this package is published as a Claude document for review and comments.
