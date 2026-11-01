# Changelog

All notable changes to this project are recorded here. Format: Keep a Changelog; every line ends with issue and requirement IDs. A release section is cut at every phase gate.

## [Unreleased]

### Changed
- Owner approved the design package and the recorded Phase 0 answers; commit `6636de1` marks the baseline (#2, REQ-21, REQ-23)
- Owner answers to the Phase 0 questions recorded: China added to day-one jurisdictions, supply chain security added to topics, translation with a selectable provider added to M4, branding configuration and legal page added to M1, M6 and M7 (#1, REQ-02, REQ-03, REQ-16, REQ-17)

### Added
- Claude Code GitHub Actions: interactive `@claude` and `claude`-label workflow, automatic pull request review workflow, root `CLAUDE.md` with the session rules (REQ-26)
- Contracts set for parallel sessions: M0 tooling decisions, OpenAPI 3.1 contract (68 paths, 58 schemas, validated), canonical DDL, registries (permissions, roles, settings, flags, tasks, events), environment variable contract, connector configuration schemas, screen inventory with design brief, fixtures inventory (REQ-01, REQ-25)
- Research item R-08 translation providers (#1, REQ-02)
- Design package `docs/` with requirements, architecture, data model, eleven module specifications, process, testing, security and backlog (REQ-01, REQ-19 to REQ-27)
- Agent templates for task cards, handoffs, ADRs, questioning issues, pull requests, component evaluations, security reviews, adversarial records and use-testing scripts (REQ-23, REQ-25)
- GitHub bootstrap script for labels and Phase 0 issues (REQ-26)
