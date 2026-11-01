# 1. How AI sessions and agents use this design package

This package is the single source of truth for building and testing the regulatory monitor application (working codename `regwatch`, a placeholder the owner may rename). Every AI session or agent that touches the project reads this section first, then only the sections its task needs.

## 1.1 Reading order by role

| Role | Read first | Then | Produces |
| --- | --- | --- | --- |
| Orchestrator / lead session | 01, 06 (process), 02 (requirements) | Module list in 05 | Issues, task cards, phase gates, change report entries |
| Module developer agent | 01, the one module spec in 05, 03 (architecture), 04 (data model) | 07 (testing), 08 (security) | Code, tests, ADRs, PR with checklist |
| Test / QA agent | 01, 07, the module spec under test | 02 (requirement IDs) | Test plans, test code, defect issues |
| Security / adversarial agent | 01, 08, 07 section on adversarial analysis | Module spec | Threat findings, fixes, sign-off record |
| Peer reviewer agent | 01, 06 review protocol, module spec | 07 definition of done | Review comments, approval or block |
| Research agent (open-source review) | 01, 03 component register and license policy | Module spec | Component evaluation records |
| Documentation agent | 01, 06 change report and backlog format | Everything changed | Changelog, user docs, ADR index |

## 1.2 Non-negotiable conventions

1. **Requirement traceability.** Every issue, PR, test and ADR cites at least one requirement ID from section 02 (`REQ-xx`) or a backlog item ID (`BL-xx`). Work with no ID is rejected at review.
2. **License gate before code reuse.** No third-party code, snippet, model, dataset or map asset enters the repository until it has a row in the component register (`docs/03-architecture.md`, section 3.6) with its license verified against the allow-list in section 08. "Verified" means an agent opened the project's own LICENSE file, not a package index summary.
3. **Questioning period opens every module and phase.** Before writing code for a module, the agent posts the module's question bank (from its spec) as a GitHub issue titled `Questions: Mx <name>`, records the owner's answers or, if the owner is unavailable, records explicit assumptions in the issue and in `docs/decisions/ASSUMPTIONS.md`. Assumed answers are tagged `assumed` and surface in the next change report.
4. **Tests before or with code.** Unit tests are written in the same PR as the code. A PR that lowers coverage below the module's floor (section 07) fails CI.
5. **One module, one branch, one PR stream.** Branch names: `feat/Mx-short-name`, `fix/Mx-issue-number`, `docs/topic`, `test/Mx-topic`, `sec/Mx-topic`. Keep PRs under roughly 400 changed lines where possible.
6. **Change report is append-only.** Every merged PR appends a line to `CHANGELOG.md` under `Unreleased`, and every scope change, new idea or deferred item appends to `BACKLOG.md`. Formats are in section 06.
7. **Decisions are ADRs.** Any choice between alternatives with lasting effect (library, schema shape, API style) is written as `docs/decisions/ADR-nnnn-title.md` using the template in `docs/templates/`.
8. **No secrets in the repository.** Secrets come from environment variables or the secrets manager named in section 08. CI runs a secret scanner on every push.
9. **Model identity is never written into repository artifacts.** Commit messages, PR bodies and code comments do not name the AI model used.
10. **Agents never widen scope silently.** Anything outside the module spec goes to `BACKLOG.md` with a proposal, not into the PR.

## 1.3 Claiming and handing off work

- Work items live as GitHub Issues with labels `module:Mx`, `phase:Pn`, `type:{feature,bug,test,security,docs,question,research}`, `status:{ready,claimed,in-review,blocked,done}`.
- An agent claims an issue by assigning itself (or commenting `claimed by <session label>`) and moving the label to `status:claimed`. A claim older than 24 hours with no linked branch may be reclaimed.
- Every session ends with a handoff note in the issue: what was done, what was verified (with commands run and results), what remains, and any assumptions made. The handoff template is in `docs/templates/HANDOFF.md`.
- Parallel sessions must not edit the same module's migration files or the shared OpenAPI spec without coordinating through an issue comment first.

## 1.4 Definition of done (applies to every module)

A module is done only when all of the following are true and linked from its tracking issue:

- [ ] Questioning period closed: all questions answered or recorded as assumptions.
- [ ] All `REQ` IDs mapped to the module have passing automated tests.
- [ ] Unit coverage at or above the module floor; integration and end-to-end tests for every user-visible flow.
- [ ] OpenAPI spec updated and contract tests passing.
- [ ] Accessibility checks pass (axe-core zero serious or critical violations; keyboard-only walkthrough recorded).
- [ ] Security review record completed (section 07.5) with no open high or critical findings.
- [ ] Peer review approval from a session that did not write the code.
- [ ] Adversarial analysis record completed (section 07.6).
- [ ] Use testing script executed against a deployed preview and results recorded.
- [ ] Component register updated for any new dependency; license scan green.
- [ ] `CHANGELOG.md`, `BACKLOG.md`, ADRs and user documentation updated.
- [ ] Owner has accepted the module in the phase gate review.

## 1.5 Where things live

| Artifact | Location |
| --- | --- |
| This design package | `docs/` (numbered files) |
| Module specs | `docs/modules/Mx-name.md` |
| Decisions and assumptions | `docs/decisions/` |
| Templates (issue, PR, ADR, handoff, review records) | `docs/templates/` |
| Component register | `docs/03-architecture.md` section 3.6 and `THIRD_PARTY_NOTICES.md` |
| Change report | `CHANGELOG.md` |
| Feature backlog and change proposals | `BACKLOG.md` |
| Test evidence per phase | `docs/evidence/phase-n/` |
