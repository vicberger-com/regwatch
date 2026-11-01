# 6. Development process for multiple AI sessions

Six phases, each opened by a questioning period and closed by an owner gate. Up to five sessions work in parallel inside a phase; the lead session owns issues, gates and the change report.

## 6.1 Phases and gates

| Phase | Modules | Entry | Questioning period | Exit gate (owner decision) | Evidence folder |
| --- | --- | --- | --- | --- | --- |
| P0 Discovery and open-source review | research for all modules, ADR-0001 to 0008 | this design accepted | section 2.4 global questions | G0: answers or assumptions recorded; component register rows at status V; ADRs approved | `docs/evidence/phase-0/` |
| P1 Foundation | M0, M1, M2 | G0 | M0, M1, M2 question banks | G1: fresh clone to running stack; admin logs in, creates users and taxonomy; CI gates proven | `phase-1/` |
| P2 Capture and processing | M3, M4, M5 | G1 | M3, M4, M5 banks | G2: starter sources produce tagged, deduplicated items; search and map activity endpoints meet latency targets | `phase-2/` |
| P3 Interface | M6, M9 | G2 (API contracts frozen for v1) | M6, M9 banks | G3: map shows live changes; keyboard and screen-reader journeys pass; three themes; use testing round 1 | `phase-3/` |
| P4 Reports and outputs | M7, M8 | G3 | M7, M8 banks | G4: stock reports render to PDF and email; custom layout saved and printed; use testing round 2 | `phase-4/` |
| P5 Hardening and operations | M10, M1b (SSO optional) | G4 | M10 bank | G5: application-level security review, adversarial analysis and peer review signed; restore drill passed; release candidate tagged | `phase-5/` |
| P6 User phased evaluation | all | G5 | pilot briefing | G6: pilot group feedback triaged into backlog; owner accepts v1.0 | `phase-6/` |

Phase gates are GitHub issues titled `Gate Gn` holding the checklist from section 7.8 and links to evidence. A gate closes only with an owner comment `approved`.

## 6.2 Parallelization plan

| Phase | Concurrent sessions (recommended) | Coordination rule |
| --- | --- | --- |
| P0 | 3 research agents (backend, frontend and map, capture and connectors) plus 1 lead | Research files per module; lead merges register |
| P1 | 1 on M0 until merged; then 1 on M1 API, 1 on M1 admin UI, 1 on M2 API, 1 on M2 UI | Schema PRs merge before UI starts; OpenAPI edits announced in the issue |
| P2 | 1 on M3 core; then 1 per connector (RSS and API feeds, page and crawl, search); 1 on M4; 1 on M5 | Connector protocol frozen after core PR; M4 fixtures shared in `tests/fixtures/corpus/` |
| P3 | 1 shell and design system; then 1 map, 1 items and detail, 1 M9 | Command registry and routes defined in shell PR first |
| P4 | 1 builder, 1 components and stock reports, 1 M8 PDF and email, 1 print bridge (flagged) | Report HTML contract agreed in an issue before parallel work |
| P5 | 1 observability, 1 hardening, 1 backup and runbooks, 1 SSO | Security reviewers must not be the module authors |
| P6 | 1 lead for triage, 1 for fixes | Fixes follow the normal PR flow |

## 6.3 Work item lifecycle

1. Lead creates issues from module specs using `docs/templates/TASK_CARD.md`, one per acceptance criterion group, labelled `module`, `phase`, `type`, `status:ready`.
2. Agent claims (`status:claimed`), creates branch `feat/Mx-short-name`, posts the question bank issue if not yet posted for the module.
3. Agent implements with tests, runs `make lint test`, opens a PR with `docs/templates/PULL_REQUEST_TEMPLATE.md` filled, including REQ IDs and the handoff note.
4. CI must be green. A peer reviewer session (not the author) reviews using the checklist in section 7.4 and approves or requests changes.
5. PRs touching auth, outbound HTTP, file handling, templates, email, printing or admin routes also need a security review record (section 7.5).
6. Lead merges with squash, appends to `CHANGELOG.md`, closes the issue with the evidence link.
7. At module completion the lead runs use testing (7.6) and adversarial analysis (7.7) and records them before marking the module done.

## 6.4 Repository layout

```
regwatch/
  README.md  CHANGELOG.md  BACKLOG.md  SECURITY.md  LICENSE  THIRD_PARTY_NOTICES.md
  docs/            # this package, decisions/, research/, evidence/, templates/, runbooks/
  openapi/         # committed generated spec per version
  api/             # Python: regwatch/ package, alembic/, seed/, tests/
  worker/          # entrypoints for celery worker and beat (same Python package)
  web/             # React app: src/app, src/features, src/components/ui, src/lib, e2e/
  print-bridge/    # optional Node IPP bridge
  deploy/          # compose.yaml, compose.prod.yaml, caddy/Caddyfile, env.example
  scripts/         # make targets, backup.sh, restore.sh, license-scan.sh
  .github/         # workflows (ci.yml, release.yml, security.yml), ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md
```

## 6.5 Change report and backlog

`CHANGELOG.md` follows Keep a Changelog with sections Added, Changed, Fixed, Security, Removed, and every line ends with the issue and requirement IDs, for example `- Capture: SafeFetcher blocks private ranges (#42, REQ-05, SEC-03)`. A release section is cut at every gate.

`BACKLOG.md` is a table: `BL-id | Title | Origin (owner, agent, review, test, pilot) | Type (feature, change, deferral, risk) | Module | Proposed by | Decision (open, accepted, rejected, deferred) | Decided by | Date | Notes`. Agents add a row with status `open` and a one-paragraph proposal; the owner decides at the next gate. Accepted items become issues.

Change proposals that alter an accepted design (schema, API, scope) are issues titled `CP-nn: title` referencing the ADR they would amend; they are summarised in the gate review under "Proposed changes" so the owner sees every change developed through the process (REQ-24).

## 6.6 Handoff and session hygiene

- Every session's final comment uses `docs/templates/HANDOFF.md`: done, verified (commands and results), remaining, assumptions, risks.
- No session leaves a branch without a pushed commit and a PR in draft.
- Sessions do not rebase or force-push shared branches; the lead resolves conflicts.
- Any secret or credential discovered in history triggers rotation and a `SEC-` backlog row.

## 6.7 Claude Code GitHub Actions

Two workflows in `.github/workflows/` let the owner assign work from GitHub without starting a session by hand:

| Workflow | Trigger | What happens |
| --- | --- | --- |
| `claude.yml` (interactive) | Comment `@claude <request>` on an issue or pull request, mention `@claude` in a new issue, or add the `claude` label to an issue | The action reads `CLAUDE.md` and the docs, works on a `claude/<name>` branch from `main`, keeps a tracking comment with checkboxes updated, and opens a pull request; on a PR it can answer questions or push fixes |
| `claude-code-review.yml` (automation) | Every non-draft pull request opened, updated, reopened or marked ready | Reviews the diff and posts inline comments, or one summary comment when it finds nothing |

Setup (owner, once): add the repository secret `ANTHROPIC_API_KEY`, an API key created in the Claude Console (platform.claude.com) inside a workspace dedicated to this project so its spend is visible and capped; runs bill that Console account per token. To bill a Claude subscription instead, store a token from `claude setup-token` as `CLAUDE_CODE_OAUTH_TOKEN` and change the `anthropic_api_key` line in both workflows to `claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`. The Claude GitHub App is already installed on the repository. Only users with write access can trigger runs; bots cannot.

Using it with this plan: comment `@claude claim this issue and implement it per docs/01-how-to-use.md` on a `status:ready` issue, or add the `claude` label. The run counts as a session: it must post the questions issue, cite requirement IDs, update the changelog and backlog, and leave a handoff note, exactly as a hand-started session would. Review the resulting pull request like any other (section 7.4); the review workflow gives a first pass automatically.

Cost controls: `--max-turns 80` and a 90-minute job timeout in `claude.yml`, 30 minutes for reviews, one run per issue or PR at a time through concurrency groups. GitHub Actions minutes and API tokens are both consumed; an OAuth token bills the subscription instead of the API.

## 6.8 Commit and PR conventions

Conventional Commits (`feat(M3): ...`, `fix(M6): ...`, `test(M4): ...`, `docs: ...`, `sec(M1): ...`) with a body line `Refs: #issue REQ-xx`. PR title mirrors the commit. Squash merge. Model identity never appears in commits or PRs. Branches opened by the GitHub Action carry the `claude/` prefix instead of the module prefixes above; the PR title still names the module.
