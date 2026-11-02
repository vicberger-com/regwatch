# ADR-0006: Celery and Valkey for scheduling, with per-host politeness enforced in SafeFetcher

**Status:** accepted at Gate G0 on 2026-11-02 · **Date:** 2026-11-02 · **Requirements:** REQ-04, REQ-05 (also REQ-02, REQ-20)
**Research:** R-01 rows 7 and 8 (#3), R-03 (#5), R-06 (#8), R-07 (#9); `docs/03-architecture.md` 3.2; `docs/08-security-compliance.md` 8.3; `docs/modules/M3-capture-framework.md`; `docs/contracts/registries.yaml`

## Context

- **Contract.** `registries.yaml` names the Celery tasks and their queues (`capture`, `process`, `outputs`, `default`) and the periodic tasks run by beat:
  - `capture.schedule_tick` and `outputs.schedule_tick`, every minute;
  - `capture.health_check`, hourly;
  - retention, audit and backup tasks, daily.

  `capture_job` holds `cron` or `interval_seconds` (at least 900), `rate_limit_per_minute` (default 30) and `next_run_at` (`schema.sql`). The owner asked for feeds every 15 minutes to 24 hours, configurable per source (2.4 answer 4).
- **Politeness rules.**
  - The default is 1 request per 2 seconds per host, a crawl depth of 3 and 200 pages per run (8.3).
  - M3 enforces per-host limits in Valkey, runs at most one run per source at a time, allows at most 3 retries per run, and flags a source `unhealthy` after 5 failed runs.
  - M3 acceptance criterion 5: 10 requests per minute per host under a 200-page crawl. The M3 load test: 100 due jobs finish within 10 minutes on 2 workers.
- **Host limits found by research:**

  | Host | Published limit | `robots.txt` | Source |
  | --- | --- | --- | --- |
  | legislation.gov.uk | 1,500 requests per 5 minutes per user (live page; R-03's 3,000 came from GitHub docs, BL-29) | `Crawl-delay: 5` | R-06 3 |
  | legislation.gov.au | not stated | `Crawl-delay: 10` | R-03 C8 |
  | lexml.gov.br | not stated | `Crawl-delay: 5` | R-03 C12 |
  | EUR-Lex Cellar, Federal Register API | not stated; R-06 proposes 10 requests per minute and one SPARQL query per run | not limiting for the API paths | R-06 1, 2 |
  | cac.gov.cn | not stated; one request was reset by the peer | no crawl delay | R-03 C14 |
  | SearXNG upstream engines | not stated; DuckDuckGo served a CAPTCHA after 7 queries | n/a | R-07 2.3, 4 |

  WAF challenges and CAPTCHA redirects must be treated as `blocked_by_provider` failures and never retried around (R-06 adapter note 2; 8.3).
- **Licenses:**
  - Celery: BSD-3-Clause, verified at v5.6.3 (`3f4d8d7`). GitHub labels 5.7.0rc1 as "latest", so it is not flagged as a pre-release (R-01 row 7).
  - Valkey: BSD-3-Clause, verified at 9.1.3 (`29173b6`). Both copyright blocks are BSD-3, including the Redis code from before 2024 (R-01 N2). The Compose contract pins `valkey/valkey:8`.
  - Redis: moved to RSAL, SSPL or AGPL in 2024 (3.2).
- **No measurement.** No research item measured Celery or Valkey throughput.

## Decision

1. **Celery 5.x** workers consume the contract queues, with exactly one `beat`. **Valkey** is the broker and holds transient coordination state only: per-host tokens, per-source run locks and per-provider pacing. Records live in PostgreSQL (`capture_run`, `output_job`, `change_event`), so a Valkey restart loses queued messages but no records.
2. **Schedules live in PostgreSQL, not in beat.** Beat fires only the fixed periodic tasks in `registries.yaml`. `capture.schedule_tick` enqueues jobs whose `next_run_at` has passed, with jitter. It takes a per-source lock in Valkey so a source never runs twice at once. Messages lost from Valkey are re-enqueued on the next tick, because `next_run_at` and `output_job.status` are still in PostgreSQL. Tasks are written to be idempotent, as M4 already requires.
3. **Politeness is per host, shared by all jobs and workers.** SafeFetcher takes a Valkey-backed token for the target host before every request. The interval for a host is the largest of:
   - its `robots.txt` `Crawl-delay`;
   - its published limit, converted to an interval;
   - the job's `rate_limit_per_minute`;
   - the 8.3 default of 2 seconds.

   Celery's own `rate_limit` applies per worker and per task type, so it is not used for politeness. A request that cannot get a token soon is re-queued with a countdown, and the wait does not count as a failure. Applied to the hosts above:
   - legislation.gov.uk: 5 s (12 per minute; the 1,500 per 5 minutes limit is looser);
   - legislation.gov.au: 10 s;
   - LexML: 5 s;
   - Cellar and the Federal Register: 6 s, from R-06's proposed per-job limit of 10 per minute;
   - every other host: 2 s.
4. **Failures.** At most 3 retries per run with backoff. `Retry-After` on 429 or 503 is honoured when a host sends it (R-06 saw none from the Federal Register). `blocked_by_provider` ends the run as failed with no retry.
5. **Search pacing is per provider.** SearXNG gets one query at a time, at least 60 s apart with random spacing, through a Valkey token. Search jobs default to daily or weekly (R-07 4, BL-33).
6. **Images and versions.** Valkey and Celery are pinned to final releases, and the Valkey image is pulled by digest (8.6 item 4). Whether to stay on the contract's Valkey 8 line or move to 9 is BL-51.

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **Celery 5 with Valkey; schedules in PostgreSQL; per-host tokens in SafeFetcher (chosen)** | BSD-3 (both V) | Mature retries, routing and periodic tasks (3.2); records survive a broker loss; politeness shared across jobs and workers | Another container; the per-host limiter is project code to write and test |
| Procrastinate (PostgreSQL queue) | MIT per 3.2 (not verified; no register row) | No broker container; enqueue in the same transaction | Per-host tokens would need PostgreSQL row locks or another store; not evaluated in research; 3.2 notes it only for smaller deployments |
| APScheduler in-process | not verified | Simplest scheduler | Runs inside the API process, which must not fetch (3.1); duplicate schedules when more than one process runs; no work distribution |
| Temporal | not verified | Durable workflows with history | A workflow server and its own database to operate on one host for 50 users; no workflow in M3 to M8 needs it |
| Redis as the broker | RSAL, SSPL or AGPL since 2024 (3.2) | Celery's reference broker | RSAL and SSPL prohibited (3.5); the AGPL option fails ADR-0003 decision 2c because Valkey exists |

## Consequences

- **Positive:** published host limits are met by construction, even when several jobs target one host. Schedules are visible and editable as rows. A broker loss costs at most one tick.
- **Negative:**
  - Slow hosts set long run times. A 200-page crawl at 10 s per request takes at least 33 minutes (200 × 10 s), so the per-source lock, not the 15-minute minimum interval, prevents overlapping runs.
  - Jobs on the same host run one request at a time, so the M3 target of 100 jobs in 10 minutes on 2 workers assumes jobs spread over many hosts.
  - Throughput and memory are not measured.
  - SearXNG's own upstream requests are not covered by SafeFetcher tokens (ADR-0001). Only the query rate into SearXNG is paced.
- **Follow-up backlog rows:** BL-29 (block contact-required sources while `general.contact_email` is empty); BL-32 and BL-33 (search pacing and soak test); BL-51 (Valkey and Celery versions).

## Open questions for the owner

1. For hosts that publish no limit (EUR-Lex Cellar, the Federal Register), should the default stay at 8.3's 1 request per 2 seconds, with R-06's 10 per minute set only in those starter sources, or should 10 per minute become the default for official APIs?
2. Is a broker with no persistence acceptable, given decision 2 (records and schedules in PostgreSQL; lost messages re-enqueued on the next tick)?
3. BL-51: keep the contract's Valkey 8 line and re-verify its license, or move the contract to 9, the line R-01 verified?


## Owner decisions at Gate G0 (2026-11-02)

The owner accepted the recommended default for every open question above:

- Q1: keep the 1 request per 2 s default; set 10 per minute only in the Cellar and Federal Register starter sources.
- Q2 accepted: a broker with no persistence.
- Q3 (BL-51): the contract moves to Valkey 9, the line R-01 verified.
