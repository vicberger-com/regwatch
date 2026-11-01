# regwatch: instructions for Claude Code sessions and GitHub Action runs

This repository holds the design package for a regulatory monitor application and, from Phase 1, its code. Read `docs/01-how-to-use.md` before any task; it is the authoritative version of these rules.

## Before you change anything
- Find the issue you are working on. Every change cites an issue and at least one requirement ID (`REQ-xx` in `docs/02-requirements.md`) or backlog ID (`BL-xx`).
- Read the module spec in `docs/modules/` and the contracts in `docs/contracts/` and `openapi/regwatch.v1.yaml`. Contracts win over specs; specs win over the numbered sections. If a contract is wrong, open a `CP-nn` issue and keep building to the current contract.
- Post the module's question bank as an issue titled `Questions: Mx <name>` if it does not exist; record assumptions in `docs/decisions/ASSUMPTIONS.md`.

## While working
- Tooling is fixed in `docs/contracts/M0-tooling.md` (Python 3.12 with uv, Node 22 with pnpm, Ruff, mypy, ESLint, pytest, Vitest, Playwright). Do not introduce alternatives.
- Tests ship in the same change. Never delete or skip a failing test to make CI pass.
- Third-party code enters only after a row in the component register (`docs/03-architecture.md` 3.6) with its license checked against the policy in 3.5. GPL, AGPL, SSPL, BUSL and similar are prohibited in bundled code.
- All outbound HTTP in workers goes through SafeFetcher; captured content is hostile; follow `docs/08-security-compliance.md`.
- No secrets in the repository. No AI model names in commits, pull request text or code comments.
- Branches: `feat/Mx-name`, `fix/Mx-issue`, `test/Mx-topic`, `sec/Mx-topic`, `docs/topic`; branches created by the GitHub Action use the `claude/` prefix. Conventional Commits with a `Refs: #issue REQ-xx` line. Keep pull requests under about 400 changed lines.

## Before you finish
- Run `make lint test` (and `make e2e` for UI changes) and paste the results in the pull request.
- Update `CHANGELOG.md` under Unreleased, `BACKLOG.md` for anything deferred or proposed, the component register for new dependencies, and ADRs for lasting decisions.
- Fill the pull request template and end with a handoff note (`docs/templates/HANDOFF.md`).
- Do not widen scope. Anything beyond the issue goes to `BACKLOG.md` as a proposal.
