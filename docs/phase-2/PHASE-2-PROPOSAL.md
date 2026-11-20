# Phase II proposal: from aggregator to a focused knowledge resource

**Status:** proposal for the owner's conceptual review · **Date:** 2026-11-20 · **Author:** lead session, at the owner's request · **Branch:** `docs/phase-2-proposal`
**Builds on:** Phase I (P0 to P6: M0 to M11), especially M11 interests, the feed catalogue and groups (ADR-0012) · **Decision record to follow:** ADR-0013 (agent architecture), after the research in section 9

---

## 1. Summary

Phase I builds a reliable monitor: it captures official sources, tags and deduplicates items, and lets people search, map, report and receive outputs. Users still have to know what to ask for, and the settings say little about what they will change.

Phase II turns regwatch into a **focused source of knowledge for each user and team**. Five capabilities define it:

1. **An onboarding conversation.** It runs at first installation and for every new user or team. It asks about industry, focus areas, impact areas, regulatory targets, known risks and content expectations, and shows what each answer will change before it is saved.
2. **A persistent profile and memory.** It holds what the onboarding learned, what the user has already seen, and what they found useful, for each user and each team, so later sessions build on earlier ones.
3. **Relevance and delta-aware delivery.** Each user or team gets what matters to them and **what is new or changed since they last looked**, never the same item presented for the hundredth time. Sources are never altered; only selection, ranking and framing are shaped, and every statement cites the item it comes from.
4. **A feed steward.** It watches the sources, notices when a feed breaks, moves or changes shape, proposes a fix, and suggests sources that fill a profile's gaps.
5. **An operations steward.** It runs the routine work an IT person would otherwise do: data pulls, database maintenance, verified backups, email delivery, security watch and update proposals. Users stay consumers, never system administrators.

**Recommended architecture: a hybrid.**
- Build the **per-user intelligence inside regwatch**: onboarding, profiles, relevance, briefings and grounded answers. They must be multi-user, permissioned and audited, and must keep Phase I's guarantees.
- Run the **operations agent as a separate, tightly scoped service**. Hermes Agent is the leading candidate, subject to a research spike. It reaches regwatch only through a narrow tool interface, never a shell or the database.
- Every privileged action goes through an approval queue, and every agent action is logged.

**Path:** finish Phase I (M7, M8, M10 and gates G4 to G6) first. Phase II opens with three research spikes and a decision gate (G7), then builds in four phases (P7 to P10). A rough estimate is 6 to 9 weeks of build after G7 at Phase I's pace, longer if the owner adds integrations.

---

## 2. Where Phase I leaves us

| Already built (Phase I) | What it gives Phase II |
| --- | --- |
| Capture with SafeFetcher, robots.txt, health, runs (M3) | The feeds the steward supervises; health and run history to learn from |
| Processing, versions, diffs, change events, severity (M4) | "What changed" is already computed and stored: the basis of delta delivery |
| Search on PostgreSQL and OpenSearch, map activity (M5) | Retrieval for relevance and grounded answers |
| Interests as default filters, a curated catalogue, follows, feed requests, groups with roles and shared interests (M11) | The first, simple profile; Phase II enriches it rather than replacing it |
| Report layouts and server rendering (M7, in progress), outputs, email and schedules (M8, to come) | The delivery channels briefings use |
| Audit log, roles and permissions, sessions, idle timeout (M1, M9) | The authority model that every agent action must respect |
| Two-layer help tips on every setting | The place to show "what this choice will change" |

Gaps this proposal addresses: no understanding of a user's purpose beyond tick boxes; no memory of what a user has seen; no "since you last looked"; no explanation of the effect of settings; feed failures noticed only by an admin; operations that need an IT person.

---

## 3. The two examples, worked through

**A. Consumer electronics, supply-chain and product security.**
- **Onboarding learns:**
  - the industry (consumer electronics);
  - the focus (product cybersecurity, supply-chain security and resilience, labelling);
  - the named targets: the EU's supply-chain resilience proposals and the Cyber Resilience Act, and the US Cyber Trust Mark;
  - manufacturing and materials in Asia-Pacific;
  - sales in South America and Africa: present or not.
- **The profile becomes rules with conditions, not flat filters:**
  - Asia-Pacific counts for every topic in scope.
  - South America and Africa count only for items that are about consumer electronics, and only while the user says they do business there.
  - Proposals and consultations count as well as adopted law, because the user asked for anticipated changes.
- **What they receive:** a daily brief of new and changed items in scope, proposed measures flagged as "proposed", and a watch list for each named target that tracks its stage from consultation to adoption to effect.

**B. A leader running a new AI service with corporate privacy and security concerns.**
- **Onboarding learns:** AI governance, privacy and data protection, and security, with global reach, because the service is reachable from anywhere.
- **The profile:** jurisdictions are weighted by where users of the service are and by "extraterritorial reach" signals, not by geography alone. Topics combine: an AI law that changes privacy duties ranks above one that does not.
- **What they receive:** a weekly brief with a "what this means for an AI service" framing, which cites the items behind it, and alerts for major changes in the jurisdictions marked critical.

**Teams.** Team A (legal environment) and Team B (supply-chain availability and security of the product) share an industry but differ in focus.
- Each team has a team profile.
- A member's effective profile is the team's plus their own refinements, as M11 interests already work.
- The two teams receive different briefs from the same corpus.

---

## 4. Capabilities

### 4.1 Onboarding conversation (installation and users)
- **First installation:** a guided setup replaces the admin's checklist. It covers:
  - the organisation and its industry;
  - the contact email that some sources require;
  - email delivery, backups, the first teams, and which catalogue feeds to follow.

  Each answer is checked before it is saved: an SMTP test, a backup test and a feed test.
- **A new user or team:** a short conversation, of about 8 to 12 questions with follow-ups. It covers:
  - industry and role;
  - focus areas and impact areas;
  - regulatory targets and known risks;
  - where they manufacture, sell and operate;
  - content expectations: depth, frequency, channel, "proposed as well as adopted", and language.
- **Impact preview before saving:** "With these answers you would have seen 37 items last month from 9 feeds. 4 of them were major. Here are three examples." Every setting gains the same preview, through the existing help tips.
- **The structured result:**
  - The profile is stored as structured data: M11 interests plus the new fields in 4.2. It is never only a chat transcript.
  - The user can edit it as a form at any time, and the conversation can be re-run.
- **Fallback:** without a language-model provider configured, onboarding falls back to a questionnaire with the same questions and the same structured result.

### 4.2 Profiles and memory (three tiers)

| Tier | Holds | Lives in | Lifetime | Who can see it |
| --- | --- | --- | --- | --- |
| 1. Working memory | The current conversation or task: the onboarding dialog, a question being answered, a brief being assembled | Process memory, plus a short-lived session row | Minutes to a day | The user, and the agent for that task |
| 2. Profile memory | Structured, versioned facts: industry, focus, regions with conditions, targets, risks, expectations, delivery choices; team profiles and inheritance | PostgreSQL tables, every change audited and versioned | Until changed | The user, their team's managers, admins |
| 3. Knowledge memory | What each profile has been shown and when (the delivery ledger), relevance judgments with reasons, feedback ("useful", "not for me"), item embeddings, summaries the agent wrote with their citations | PostgreSQL (with pgvector for embeddings) and the search index | Retention set by admins (default 1 year; the ledger as long as briefs need it) | The user's own; team-level aggregates for the team |

Design points:
- **Tier 2 is the source of truth.** Tier 3 can always be rebuilt from Tier 2 and the corpus.
- **A team profile is inherited, not copied.** A member's refinements are stored as differences, so a team change reaches everyone.
- **The agent never keeps private notes about a user** outside these tiers. Every memory the user is affected by is visible to them and deletable (GDPR-style access and erasure).

### 4.3 Relevance and delta-aware delivery
- **Two stages:**
  1. Deterministic rules from the profile: jurisdictions with conditions, topics, terms, stages.
  2. Then, optionally, a model judgment that scores each candidate against the profile and writes a one-line reason that names the matched clause.

  Rules alone must already be useful.
- **The delivery ledger** records, for each profile, every item and version it was shown and through which channel. A brief contains:
  - new items;
  - new versions of items already shown, with the diff;
  - stage changes (proposed, adopted, in force);
  - nothing else, unless the user asks for "everything in scope".
- **Never alter sources:**
  - Item text, titles and links are shown as captured.
  - Agent text (summaries, "why this matters") is visibly marked, cites its items, and is stored apart from them.
  - A brief can always be opened to show the items that support it.
- **Feedback:** "useful", "not relevant" and "more like this" adjust that profile's weights (Tier 3). They never delete or hide content for anyone else.

### 4.4 Grounded questions and answers
- Users ask, for example, "what does the Cyber Resilience Act require of a router maker, and by when?"
- The answer:
  - is built only from items in regwatch, retrieved through search and embeddings;
  - quotes and links them;
  - says plainly when the corpus does not hold the answer.
- No answer without citations. Answers can be saved into a report or a brief.

### 4.5 Feed steward
- **Watches** run history, health, item counts, structure fingerprints, and redirects or moved pages.
- **Detects:**
  - a feed that stopped;
  - a page whose layout changed, so its selectors now find nothing;
  - a URL that moved;
  - a source that started returning errors or blocks;
  - content drift, such as a feed that now carries a different publication.
- **Proposes a fix:**
  - new selectors, tested by a dry run on the worker;
  - a new URL, checked by SafeFetcher;
  - a pause.

  An editor approves the fix, or the admin's policy allows low-risk fixes automatically, such as following a permanent redirect on the same host.
- **Finds gaps:** for each profile it notes targets with no source (for example "no Japanese AI guidance source") and drafts a feed request from the catalogue research for an editor to approve (M11.3).
- **Never** changes robots.txt handling, overrides, terms or credibility on its own.

### 4.6 Operations steward
- **Data pulls:** schedules, catch-up after outages, back-pressure.
- **Database maintenance:** vacuum, reindex, partition and retention jobs, index rebuilds.
- **Backups:** scheduled, encrypted, *verified* by a restore into a scratch database, and reported. The restore drill (G5) becomes routine.
- **Email and reporting:** delivery monitoring, bounce handling, retries, and the digest schedule.
- **Security watch:** failed sign-ins, unusual exports, permission changes, expiring certificates, new dependency advisories.
- **Updates:** it proposes dependency and image updates as pull requests with test results. It **does not deploy on its own** unless the owner opts in for patch-level updates with automatic rollback.
- **Status:** a plain-language report for admins and owners ("all 14 sources healthy; backup verified at 02:10; 2 updates waiting for approval"). Problems go to an inbox with a recommended action and one button to approve it.

### 4.7 Explaining settings
- Every setting, filter and interest shows its effect before it is saved: counts, examples, and what would be lost or gained.
- Every setting carries a short "why you might change this".
- This uses the M6 help tips and the relevance engine's dry run.

---

## 5. Architecture

```
                  ┌────────────────────────── regwatch (Phase I services) ───────────────────────────┐
 users  ──web──►  │ web ─► api (FastAPI) ─► PostgreSQL (+ pgvector) ◄── worker (Celery) ─► SafeFetcher │
 email  ◄──────── │          │   ▲  audit, RBAC, approvals         ▲                                  │
                  │          ▼   │                                 │                                  │
                  │   intelligence service (new, Python, same repo): onboarding, profiles, relevance, │
                  │   briefings, grounded answers, feed-steward analysis ── LLM client (provider-agnostic)│
                  │          ▲                                                                         │
                  │   tool gateway (new): MCP server exposing named, permissioned regwatch actions     │
                  └──────────┼──────────────────────────────────────────────────────────────────────────┘
                             │ scoped token, no shell, no database access
                  ┌──────────┴──────────┐
                  │ operations agent     │  candidate: Hermes Agent (MIT), in its own container:
                  │ (separate service)   │  cron, skills, memory; email channel only; no terminal backend
                  └──────────────────────┘
```

**Why a hybrid:**
- **Per-user work needs Phase I's guarantees.** Onboarding, relevance, briefings and answers are multi-user, permissioned and audited. They touch every user's data and must respect roles, groups, sharing and the "default filter, never a limit" rule of ADR-0012. Building them in-process keeps one authority model, one audit log and one test suite.
- **Hermes Agent fits operations better than per-user work.** What we learned about it on 2026-11-20 is in the table below. Its strengths are a personal, autonomous assistant: scheduling, memory, self-improving skills and many channels. Those suit operations work for the owner or admin.
- **Hermes's risks are contained by giving it only the tool gateway:**
  - it runs shell commands through terminal backends;
  - skills modify themselves;
  - it is built around one user;
  - it targets a newer Python than ours.

  Through the gateway it has no shell, no database credentials, no file system of ours, and the same permission checks and audit as a person.

| Hermes Agent, as read from its repository README (verify in R-09) | Fit |
| --- | --- |
| MIT license | Allowed by the license policy (3.5) |
| Agent-curated memory, session search, user modelling | Useful for the operator; per-user memory stays in regwatch (4.2) |
| Skills created and improved during use; the agentskills.io standard; subagents; MCP servers | MCP lets it call our gateway. Skill self-modification needs review before use in production. |
| Built-in cron with delivery to channels (daily reports, nightly backups) | A close match to the operations steward |
| Gateway for Telegram, Discord, Slack, WhatsApp, Signal, email and the CLI | Email first; others only by owner choice |
| Terminal backends: local, Docker, SSH and hosted sandboxes; command approval; container isolation | Must be turned off or confined; regwatch actions only through the gateway |
| Any model provider, or your own endpoint | Matches a provider-agnostic design, including a self-hosted model |
| Installer provisions a newer Python plus Node | A separate container, not inside our API image |
| Multi-user: "allowed users" and DM pairing, no multi-tenant design stated | It must not hold or serve per-user regwatch data |

**The LLM client:**
- one provider-agnostic interface, with a hosted provider or a self-hosted model chosen by the admin;
- a budget per day and per user;
- timeouts, retries and caching;
- every prompt and response logged with a retention period;
- a "no model" mode in which every feature degrades to rules and forms.

**The tool gateway (MCP server):**
- **What it exposes:** named actions such as `sources.health`, `sources.propose_fix`, `runs.retry`, `backup.run`, `backup.verify`, `digest.send` and `updates.propose`. Each has a JSON schema, a required permission, a risk level and a rate.
- **What it never exposes:** "run SQL", "run a shell command", "fetch any URL" or "send email to anyone".
- **Risky actions** create approval requests rather than acting.

---

## 6. Safety, security and trust

Captured content is hostile (8.1). For an agent, that adds **prompt injection**: a page could contain text written to steer the model. The design treats it as follows.

- **Content is data, never instructions.**
  - Item text reaches a model only inside a delimited, labelled data block.
  - Tool use is not available in the same step as reading item text: relevance and summarising steps have **no tools**.
  - Any step that can act gets only the profile and the item ids.
- **Least privilege and approval:**
  - Every agent action runs as a service principal with its own role, permissions and audit actor.
  - Actions have risk levels. Read-only runs freely; low-risk runs within policy (retry a run, pause a failing source); everything else needs an approval: changing a source, sending outside a profile's recipients, restoring data, updating software.
- **Never alter or invent:**
  - Agent text is stored apart from items, marked as generated, and must cite.
  - A check refuses any brief whose claims carry no citation.
- **Data leaving the stack:**
  - Prompts may contain item text and profile facts.
  - The admin chooses the provider, region and retention, and can pick a self-hosted model so nothing leaves.
  - Users are told what is sent.
  - Personal data in profiles is kept minimal.
- **Cost and abuse:** budgets per user and per day, rate limits, a kill switch, and alerts at 80% of the budget.
- **Evaluation:** a fixed test corpus with expected relevance and briefs, run in CI with a stub model and nightly with the real one. It measures:
  - precision and recall for each example profile;
  - repeat rate (items shown again without change), with a target of 0;
  - citation coverage (100%);
  - injection fixtures (0 tool calls caused).
- **Owner kill switch:** one flag turns all agent features off. The application keeps working as in Phase I.

---

## 7. Alterations to Phase I

| Area | Change |
| --- | --- |
| Data model | New tables: `profile` (versioned, with conditions), `profile_member`, `delivery_ledger`, `relevance` (item × profile × version, score, reason), `feedback`, `agent_action`, `approval_request`, `agent_memory` (tier 3), `llm_call` (log); a pgvector column on items. Each is a CP with a migration. |
| M11 interests | Become the simplest form of a profile. Existing interests migrate into profiles, and the map and items keep working through the same default-filter path. |
| M8 outputs | Briefs become an output kind that uses the ledger. Schedules gain "only when something changed". |
| M3 capture | Structure fingerprints and drift signals for each run; a dry run of proposed fixes; a redirect-follow policy. |
| M10 operations | The steward runs M10's runbooks; backups gain automatic verification. |
| Settings and help | An impact preview on every setting; agent and provider settings; budgets; data-egress notice. |
| Roles | New permissions: `agent.approve`, `agent.configure`, `profile.manage_team`. A service principal for the agent. |
| Security docs | Threat model additions (prompt injection, tool abuse, exfiltration by email), an LLM data-handling section, an ADR for agent authority. |
| Process | Evaluation reports become gate evidence. Use testing includes onboarding for each example persona. |

---

## 8. Questions for the owner

1. **Model provider and data residency.** Hosted (which region?), self-hosted, or both with a choice per feature? May item text and profile facts leave the stack?
2. **Autonomy.** Which operations may the agent do without approval: retry runs, pause failing sources, follow same-host redirects, apply patch updates?
3. **Approvers.** Who approves agent proposals: admins only, editors for sources, team managers for team profiles?
4. **Channels.** Email only, or also Teams, Slack or others? (Each is an integration and a data path.)
5. **Tenancy.** One organisation per installation (as now), or several organisations in one installation?
6. **Memory retention.** How long to keep the delivery ledger, feedback, generated summaries and model logs? May users erase their memory?
7. **Framing.** May briefs paraphrase and summarise with citations, or only select and quote?
8. **Success measures.** For example: onboarding under 10 minutes; at least 80% of brief items rated useful; zero repeats; feed outages fixed within a day.
9. **Order.** Must Phase I reach G6 (v1.0) before Phase II starts, or may the research spikes run alongside P4 and P5? The recommendation is spikes alongside, build after G6.
10. **Hermes Agent.** Do you want it specifically, or the capability? If R-09 finds a better fit, or that building the operations steward in-house is safer, may we choose that?

---

## 9. Path forward

| Step | What | Output | Gate |
| --- | --- | --- | --- |
| 0 | Finish Phase I: M7, M8, M10, G4 to G6. Apply patches, backlog items and fixes. | v1.0 | G6 |
| R-09 | Agent harness evaluation: Hermes Agent against an in-house loop, and against one or two other MIT or Apache-2.0 frameworks. Covers license, multi-user fit, MCP support, sandboxing, memory, cron, update cadence, a security review of the skill system, and a proof of concept of the tool gateway with three actions. | Research record, ADR-0013 draft | G7 |
| R-10 | LLM provider and data handling: hosted and self-hosted options, cost per user per month, latency, region, retention, contract terms; the stub provider for CI. | Research record, ADR-0014 draft | G7 |
| R-11 | Memory and retrieval: pgvector against the search index for embeddings, the ledger design, profile-with-conditions design, evaluation corpus and metrics. | Research record, data-model proposal | G7 |
| P7 | Profiles and onboarding (M12): the profile model with conditions and inheritance, migration from M11 interests, the onboarding conversation and questionnaire, impact previews, first-installation setup. | M12 | G8 |
| P8 | Relevance and briefings (M13): rules engine, optional model scoring with reasons, delivery ledger, delta briefs through M8, feedback, the evaluation suite. Grounded answers (M14). | M13, M14 | G9 |
| P9 | Agent platform and stewards (M15, M16): tool gateway (MCP), approvals queue, service principal, LLM client with budgets; feed steward; operations steward on M10's runbooks; the operations agent container if ADR-0013 chooses it. | M15, M16 | G10 |
| P10 | Pilot with the two example personas and two teams; tuning; acceptance. | Phase II release | G11 |

**Rough effort after G7, at Phase I's pace:**
- P7: 1 to 1.5 weeks;
- P8: 2 to 3 weeks;
- P9: 2 to 3 weeks;
- P10: 1 to 2 weeks (a pilot of the owner's chosen length).

**Risks:**
- **Model quality and cost:** mitigated by rules-first, budgets and evaluation.
- **Prompt injection:** mitigated by the separation in section 6 and fixtures.
- **Harness churn:** Hermes is fast-moving (very many commits, no tagged releases shown). Mitigated by pinning, a narrow gateway and a fallback to the in-house loop.
- **Scope growth from channels and tenancy:** decided at G7.

---

## 10. What this branch starts

- **This branch, `docs/phase-2-proposal`:** this document, for review.
- **After the owner's review, the next commits on this branch:**
  - the Phase II question bank, recorded in ASSUMPTIONS;
  - the R-09 to R-11 research briefs;
  - ADR-0013 and ADR-0014 drafts;
  - the M12 to M16 module specs in `docs/modules/`;
  - the BACKLOG rows.
- **Code** starts only after G7, on `feat/M12-…` branches stacked as in Phase I.
