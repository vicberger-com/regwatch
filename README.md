# regwatch

Working codename (placeholder; rename is an owner decision). An application that monitors global legal and regulatory status and changes for information technology and cybersecurity topics, stores them in a taxonomy-driven database, shows them on a world map, and produces reports and outputs to email, printers and PDF.

**Status:** design package and Phase 0 answers approved by the owner on 2026-11-01 (baseline commit `6636de1`; the owner may tag it `design-approved`). Phase 0 (discovery and open-source review) is open: claim issues #3 to #11. No application code yet.

Start here: [`docs/00-README.md`](docs/00-README.md), then [`docs/01-how-to-use.md`](docs/01-how-to-use.md) if you are an AI session or agent working on this repository.

| Where | What |
| --- | --- |
| `docs/` | Design package: requirements, architecture, data model, module specs, process, testing, security, backlog |
| `docs/contracts/`, `openapi/` | Contracts parallel sessions build against: tooling, OpenAPI, DDL, registries, environment, connectors, screens, fixtures |
| `docs/decisions/` | Architecture decision records and the assumptions log |
| `docs/research/` | Phase 0 open-source component evaluations |
| `docs/evidence/phase-n/` | Test, review and gate evidence per phase |
| `CHANGELOG.md` | Change report (Keep a Changelog) |
| `BACKLOG.md` | Feature and change backlog awaiting owner decisions |
| `.github/workflows/claude.yml`, `claude-code-review.yml` | Claude Code GitHub Actions: `@claude` or the `claude` label assigns an issue; pull requests get an automatic review (setup in `docs/06-process.md` 6.7) |
| `CLAUDE.md` | Rules every Claude Code session or Action run reads first |
| `scripts/bootstrap-github.sh` | Creates labels and the Phase 0 issues with the GitHub CLI |

License for this repository's own code is an owner decision (D13 in `docs/10-open-questions-risks-glossary.md`); third-party components follow the policy in `docs/03-architecture.md` section 3.5.
