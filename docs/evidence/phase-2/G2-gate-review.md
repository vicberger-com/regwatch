# Gate G2 review: Phase 2 Capture and processing (M3, M4, M5)

**Prepared by:** lead session · **Build under review:** `feat/M5-map` (top of the Phase 2 stack) at the commit that adds this record · **Date:** 2026-11-19 · **Decision:** **pending the owner**. Mirror the decision as the comment `approved` on the `Gate G2` issue (docs/06-process.md 6.1).

**Exit criterion (6.1):**
- starter sources produce tagged, deduplicated items;
- the search and map activity endpoints meet their latency targets.

**Entry to P3:** API contracts frozen for v1.

## Checklist (docs/07-testing-quality.md 7.8)

| Item | Status | Evidence |
| --- | --- | --- |
| Module definitions of done complete and linked | **Yes.** M3 complete. M4 complete, acceptance 1 to 6. M5 complete, acceptance 1 to 4; the k6 run with 10 concurrent users is open (BL-118). | `M3-module-summary.md`, `M4-module-summary.md`, `M5-module-summary.md` |
| CI green on the release branch; coverage report attached | **Pending the owner:** every branch passes locally; CI runs on GitHub once the PRs are opened | Local run on this commit: `make lint` clean; `make test-api` 1,467 unit and 381 database tests (1 skipped), combined coverage 96.10% (floor 85%) |
| Contract tests pass against the committed OpenAPI | **Yes** | `python -m tests.openapi_semantic ../openapi/regwatch.v1.yaml`: 0 differences across 95 operations (CP-02's accepted stricter fields only); Schemathesis passes in `make test-api` |
| End-to-end suite green in three themes; accessibility report | **Not applicable at G2:** `make e2e` lands in Phase 3; Phase 2 adds only the sources admin screens, which have component tests | `make test-web` 123 tests, 96.7% lines |
| Performance results within budgets | **Sequentially yes; at 10 concurrent users no.** On 1M corpus-derived items on OpenSearch, after a warm-up pass: search p95 254 ms (budget 300); map p95 48 ms (budget 150); export of 50,000 rows at 17 MB peak (budget 300 MB). The cold pass, reported separately: search median 369 ms, worst 2.5 s. PostgreSQL alone measured p95 about 5 s, hence ADR-0011. **10 concurrent users (BL-118), not met:** search p95 814 ms and map p95 185 ms, with every user back to back with no think time, in one Python process on the same 4-CPU host as PostgreSQL and OpenSearch. Whether the bottleneck is the test process or the stores is not yet known. **Owner decision:** judge acceptance 3 sequentially (met), or hold G2 until the concurrent run meets it. | `M5-module-summary.md`; ADR-0011 Results; `tests/integration/test_perf_search.py` |
| Security scans attached; no high or critical open | **Yes, after a fix at this gate:** `make security` passes (bandit, semgrep, pip-audit, pnpm audit at the high threshold, gitleaks). On `f831214`, before that fix, bandit reported 12 low findings and semgrep 2 blocking ones (`SET LOCAL` through `text()`); the fix replaces the asserts with explicit errors, gives a reason for each `nosec`, and sets the timeout with `set_config` as a bound parameter. Six moderate advisories remain in test tooling (BL-82). | This commit |
| Peer, security, use and adversarial records for every module | **Security: yes. Peer, use and adversarial: not yet.** Every slice had an independent security review, and its fixes were re-verified. Peer review is due on each PR (7.4). There is no use-testing round for Phase 2: it has no user-facing screens beyond the sources admin. The adversarial session is still the owner's decision from G1. | M3: `M3-*-review.md` and `CP-13-14-review.md`. M4: `M4-item-routes-review.md`, `M4-pipeline-review.md` and the completion review in `M4-module-summary.md`. M5: `M5-search-review.md` (search and views, slice 2, and the OpenSearch slices, signed off at `f831214`). |
| License scan clean; register and notices updated | **Yes** | `scripts/license-scan.sh`: 574 allowed, 1 by reviewed exception, 0 failing. The register has rows for lingua, rapidfuzz, pypdf and the OpenSearch sidecar (ADR-0011). |
| CHANGELOG release section cut; BACKLOG decisions recorded; CP issues summarised | **At the gate:** the release section is cut when the owner approves; the CPs are below | `CHANGELOG.md` Unreleased |
| Questioning-period issues closed or assumptions recorded | **Recorded:** M3, M4 and M5 assumptions are confirmed by the owner or accepted under the standing instruction of 2026-11-19; the bank issues still need opening on GitHub | `docs/decisions/ASSUMPTIONS.md` |
| Owner comment `approved` | **Pending** | |

## Owner demonstration (exit criterion)

Run from `~/.workspace/regwatch-git` after pushing the stack:
1. `make migrate` (0004 to 0007), then `make seed`.
2. **Optional, for the latency path:**
   - `scripts/index-setup.sh`;
   - `docker compose -f deploy/compose.yaml --profile index up -d`;
   - restart api and worker;
   - rebuild the index with `docker compose -f deploy/compose.yaml exec worker python -m regwatch.search.tasks`.
   Without the index, search and the map run on PostgreSQL at about 5 s p95 at 1M items. The dev corpus is far smaller, so this is fine for a demonstration.
3. On `/admin/sources`:
   - enable two or three starter sources;
   - run each with "Run now";
   - check that items appear with jurisdiction and topic tags, and that a re-run makes no new items (deduplication).
4. `POST /api/v1/search` with `{"q": "NIS2 incident"}`, and `GET /api/v1/map/activity?view_by=region`.

The automated evidence for the same criterion:
- the M4 corpus: jurisdiction precision 0.974 and recall 0.925; rule precision 0.846;
- the M4 acceptance tests for deduplication and versioning;
- the M5 acceptance tests.

## Proposed changes (CP issues, REQ-24)

| CP | Change | State |
| --- | --- | --- |
| CP-11 | Schema constraints (migration 0002), ADR-0006 amendment 1 | Owner approved 2026-11-17; applied |
| CP-12 | Quoting of three `connectors.yaml` descriptions | Owner approved 2026-11-17; applied |
| CP-13, CP-14 | `capture.dry_run`; `capture_job.cursor` (migration 0003) | Owner approved 2026-11-17; applied |
| CP-15 | HTML extraction with the project's CSS-subset selectors on html5lib | Owner approved 2026-11-17; applied |
| CP-16 | The web page connector's fetch and isolated extraction | Owner approved 2026-11-17; applied |
| CP-17 | `POST /sources/{id}/documents` for manual sources | Owner approved 2026-11-18; applied |
| CP-18 | An `egress` network for the `search` sidecar alone (ADR-0010) | Applied |
| CP-19 | `item.fetched_host` (migration 0005) | Owner approved 2026-11-18; applied |
| CP-20 | Search indexes (migration 0006) | Owner approved 2026-11-19; applied |
| CP-21 | `item.search_vector_stemmed` (migration 0007) | Owner approved 2026-11-19; applied |
| CP-22 | The `index` Compose service: OpenSearch, internal network only, two least-privilege users (ADR-0011) | Owner decision 2026-11-19; applied |
| CP-02 | Tighten `/health` and `/version` schemas | Still proposed from G1 |

The CP issues still need opening on GitHub.

## Contract freeze for P3

At approval, `openapi/regwatch.v1.yaml` as of this commit is the v1 contract for M6 and M9. Any change after that goes through a CP.

## BACKLOG rows awaiting an owner decision

The Phase 2 rows still open are BL-87 to BL-120 where marked open in `BACKLOG.md`. These matter for P3 or operations:
- **BL-118:** the k6 concurrency run.
- **BL-119 and BL-120:** later index slices, and index freshness after admin changes.
- **BL-115:** the flaky timing tests under load.
- **BL-113, BL-114 and BL-116:** search residuals.
- **BL-82:** the test tooling advisories.
- **From G1, still open:** BL-60, whose Trivy acceptance expires 2026-12-02.

## Owner actions before approval

1. Push in stack order from `~/.workspace/regwatch-git`: `feat/M4-items`, `feat/M5-search`, `feat/M4-enrichment`, `feat/M5-map` (each with `-u`), and open the PRs so CI runs.
2. Run the demonstration above.
3. Comment `approved` on the `Gate G2` issue, or list what must change.
