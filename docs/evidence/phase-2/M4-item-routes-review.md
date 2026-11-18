# Security review record: M4 item routes slice

**Scope:** commits `76fe9c8` (pipeline event-kind fix), `34ce213` (item reads) and `701fe88` (tagging and reprocessing): `processing/router.py`, `processing/services.py`, `processing/pipeline.py` (`reprocess_item`), `processing/tasks.py` (`process.reprocess_item`); routes `GET /items/{id}`, `GET /items/{id}/versions`, `GET /items/{id}/diff`, `PUT /items/{id}/tags`, `POST /items/{id}/reprocess`. · **Reviewer session label:** M4 item routes independent review · **Date:** 2026-11-18 · **Author sessions excluded from review:** yes

## Method

Read the slice against the contract, the M4 spec and `docs/08-security-compliance.md`; ran the slice's tests (25 passed) and ten probe tests plus CPU benchmarks against the suite's throwaway PostgreSQL (`/tmp/m4-review/routes/`). Read-only; no dev stack, network or secrets touched.

## Findings

| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | medium | A feedback entry without a verdict (`{"term_id": R}`) cleared the `incorrect` mark, so a removed rule tag came back on reprocessing (acceptance 5). | refused with 422 in `update_tags` | verified (re-verification 1) |
| 2 | medium | The tag audit listed only term ids and codes: a removal (marked `incorrect`) and verdict changes were invisible, and an empty request was audited. | audit holds each term's origin and verdict before and after; a request that changes nothing is not audited | verified (re-verification 1) |
| 3 | medium | A viewer could tie up CPU and the shared thread pool with computed diffs between distant 1 MB versions (about 0.55 s each, unlimited). | computed diffs: 30 per user and minute (429 with `Retry-After`), on their own 2 threads; stored consecutive diffs unaffected | verified (re-verification 1) |
| 4 | medium | The reprocess publish skipped the limiter and deadline that guard capture publishes against a hanging broker. | `tasks.publish_reprocess`: own limiter, `PUBLISH_DEADLINE_S` | verified (re-verification 1) |
| 5 | low | `to` or `from` past int32 gave a 500. | 422 past `2**31 - 1` | verified (re-verification 1) |
| 6 | low | Contradictory requests were accepted (remove and judge one term; two verdicts for one term). | 422 | verified (re-verification 1) |
| 7 | low | An inactive jurisdiction could be added by hand. | 422 | verified (re-verification 1) |
| 8 | low | The reprocess audit was written before the publish, so a 503 left an audit row. | audited after a successful publish, with `after.queued` | verified (re-verification 1) |
| 9 | low | `severity` was the latest event's, not the highest the contract describes. | the highest of all the item's events | verified (re-verification 1) |
| 10 | low | A race with term deletion could give a 500, and lock order could deadlock with `merge_term`. | added terms locked `FOR KEY SHARE` in order before the item's tags; an `IntegrityError` is a 422 | verified (re-verification 1) |
| 11 | info | Wrong field names in some validation errors. | each list names itself | verified (re-verification 1) |

Note: BL-110 (a) is broader than recorded; a removed jurisdiction also returns on the next ordinary capture. BL-110 updated.

## Checked and found fine

Gate before 404 (anonymous 401, viewer 403, foreign Origin 403); reprocess 404 before publish; the task with a deleted item or disabled source; concurrency (item row locked `FOR UPDATE` by tags, reprocessing and ingest); removed rule terms stay removed after reprocessing and capture; tag input validation; per-call diff cost bounded with output at 64 KB; detail and version response sizes; response shape against the contract; no other shadowed variable in `process_manifest`; worker task names.

**Sign-off at review:** not signed off (findings 1 to 4 blocking).

## Re-verification 1 (c2b9b2d): not signed off

Fixed: 1, 4, 5, 6, 7, 8, 9, 11. Partly fixed: 2 (a jurisdiction's change of origin was not audited), 3 and 10 (below).

| # | Severity | Description | Fix | Verified |
| --- | --- | --- | --- | --- |
| N1 | medium | Queued computed diffs held pooled database connections while waiting on their two threads; 30 concurrent calls from one viewer took 15 of 15 connections and delayed every other route by seconds. | the rate is checked before any database work; at most `DIFF_PENDING` (4) computed diffs wait or run at once (503 beyond); the texts are read and the transaction ended before waiting | pending |
| N2 | low | `with_for_update(key_share=True)` renders `FOR NO KEY UPDATE`, and locking the item before the term could still deadlock with `merge_term`. | `FOR KEY SHARE` (`read=True`), taken on the added terms before the item | pending |
| 2 (gap) | low | Jurisdictions were audited as codes only. | audited as `{code: assigned_by}` | pending |

