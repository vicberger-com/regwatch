# Security review record: M2 Taxonomy and dynamic data model

**Scope (PRs, routes, tasks):** branches `feat/M2-facets`, `feat/M2-terms`, `feat/M2-merge-rules`, `feat/M2-jurisdictions`, `feat/M2-import-export`, `feat/M2-attribute-validator` (`sec/M1-trusted-proxy..65eebd7`). Routes: `/taxonomy/facets[/{key}]`, `/taxonomy/facets/{key}/terms`, `/taxonomy/terms/{id}`, `/taxonomy/terms/{id}/merge`, `/taxonomy/terms/{id}/test-rules`, `/taxonomy/view-dimensions`, `/taxonomy/import`, `/taxonomy/export`, `/jurisdictions[/{code}]`, `/jurisdictions/regions`. Services: `taxonomy/services.py`, `rules.py`, `transfer.py`, `validator.py` (AttributeValidator and its process cache), the `taxonomy.version` setting and its guard in `admin/services.py`. · **Reviewer session label:** M2 independent review · **Date:** 2026-11-13 · **Author sessions excluded from review:** yes

## Data flows touched
- **Browser to API** (session cookie plus Origin):
  - JSON bodies for facets, terms, jurisdictions, merge and rule tests (rule-test text up to 50,000 characters).
  - A raw `application/yaml` body for import, up to 2 MB.
  - The YAML export, returned to any `taxonomy.read` holder.
- **API to PostgreSQL** as `regwatch_api`:
  - ORM statements, plus raw `text()` SQL in merge that rewrites `item_term`, `item.attributes` (jsonb) and `source.default_term_ids` (uuid[]).
  - Every facet or term write also writes `taxonomy.version`; every admin change writes an `audit_log` row.
- **Match rules** (`term.match_rules`): administrators enter the keywords and regexes. `rules.evaluate` runs them on sample text now, and M4 will run them on hostile captured text of up to 10 MB. That is the main trust boundary: the patterns are trusted, the input is not.
- **AttributeValidator**: checks `item.attributes` built from hostile captured data against a per-process snapshot of facets and active terms. The snapshot is refreshed when `taxonomy.version` changes.
- **Not touched:** outbound HTTP, email, printers, model provider.

## STRIDE table
| Threat | Where | Control in place | Residual risk | Finding |
| --- | --- | --- | --- | --- |
| Spoofing | All taxonomy and jurisdiction routes | App-wide `authorize` gate (session, temporary-password lock, `x-permission`); Origin check on mutating requests | None found. Viewers: 200 on the 7 read routes, 403 on the 11 manage routes. Temporary-password users: 403 everywhere. Anonymous: 401. Import without Origin: 403 | none |
| Tampering | Merge, delete, rename, facet type change, import, concurrent writers | Bound parameters in `text()` SQL; same-facet and ancestor checks; system facets cannot be deleted or retyped; aliases refused in YAML; `taxonomy.version` refused by the settings API | Lost tags under concurrency; dangling references; parent cycles; badly typed `match_rules` stored by import | 2, 3, 4, 6, 7 |
| Repudiation | `taxonomy.import` | One audit row with counts | No per-entity before/after values for imports | 11 |
| Information disclosure | Problem responses, audit rows, export | Generic 500 bodies; `hide_parameters`; export permission matches the contract (`taxonomy.read`) | Validator errors echo unbounded keys and values | 9, 12 |
| Denial of service | Rule test and its reuse by M4, YAML import, unbounded tree and list endpoints | Nested-quantifier heuristic; 200-character pattern limit; MAX_HITS; 50,000-character sample; 2 MB body; MAX_FACETS and MAX_TERMS | Heuristic can be bypassed; ordinary patterns are polynomial; regex and YAML work runs on the event loop; one import breaks `GET /taxonomy/facets` for everyone | 1, 2, 5, 10 |
| Elevation of privilege | Manage routes, settings API | `taxonomy.manage` on every write; `taxonomy.version` not writable through settings; `system` ignored on import | None found | none |

## Checklist
- [ ] Input validation on every field (types, sizes, enumerations): **failed at review** (findings 2, 7, 8, 9, 10).
- [ ] Output encoding in UI, templates, emails, CSV: no UI or template in scope. The export uses `yaml.safe_dump`; nothing else was verified.
- [x] Authentication and authorization on every route and task: verified with a PoC matrix (viewer, temporary password, anonymous, missing Origin).
- [ ] Session handling (cookie flags, rotation, revocation): M1, not re-reviewed.
- [x] Secrets not logged or committed: the M2 diff adds no secrets and no logging.
- [x] Outbound requests only through SafeFetcher or registered services: M2 makes none.
- [ ] File and body size limits; content-type checks: the 2 MB and 50,000-character limits exist, but import does not check Content-Type and the limits do not bound CPU time (findings 1, 5).
- [ ] Logging excludes sensitive data; audit rows written: written on every write route, but the import row is incomplete (finding 11).
- [ ] Dependency, image and license scans attached and clean: not attached in this review.

## Findings
| # | Severity | Description | Fix PR | Verified |
| --- | --- | --- | --- | --- |
| 1 | high | **Regex denial of service in match rules; the rule test blocks the event loop.** The nested-quantifier heuristic misses `((a+))+$` and `((?:a+))+$`, whose run time doubles with each extra character (1.4 s at n=24). Patterns without nesting are also polynomial under `re.finditer`: `\d+\s*EUR` on 50,000 digits takes 16 s, and `\w*\w*\w*z` on 2,000 characters takes over 60 s. The full match list is built before the hit cap, and `rules.evaluate` runs synchronously in the async handler. **Scenario:** an admin saves `\d+\s*EUR` and tests it on 50,000 digits; the API worker freezes for 16 s (a concurrent `/health` waited 16.3 s). Once M4 reuses the evaluator on captured pages of up to 10 MB, hostile pages can stall processing for hours. | `sec/M2-regex` | yes (author): `test_backtracking_shapes_run_in_linear_time`; 10 MB evaluation under 2 s; awaits re-verification |
| 2 | medium | **Import stores badly typed `match_rules` and breaks taxonomy reads for every user.** Import only checks that `match_rules` is a mapping, and `check_match_rules` checks neither types nor keys. The stored values then fail `MatchRules` when read back. **Scenario:** an import with `regex: fine` returns 200; afterwards `GET /taxonomy/facets` and `GET /taxonomy/facets/topic/terms` return 500 for every role. Other wrong types (label, color token, active, min_hits, parent, sort_order) give 500 instead of 422. | `sec/M2-integrity` | yes (author): `test_typed_import_fields_are_422_and_reads_keep_working` (12 cases); awaits re-verification |
| 3 | medium | **Dangling references after term delete or rename, facet delete and value-type change.** `delete_term` checks only `item_term`, so a term named only in `item.attributes` or `source.default_term_ids` is hard-deleted. Renames do not rewrite attributes. `delete_facet` and `update_facet` ignore attribute values. | `sec/M2-integrity` | yes (author): `test_references_outside_tags_block_deletes_and_follow_renames`; awaits re-verification |
| 4 | medium | **Check-then-act races in delete and merge lose item tags.** **Scenario:** admin A merges `src` (3 tagged items) into `dst` while admin B deletes `dst`, which still showed 0 tags. All 3 items lose both tags. The same window exists for M4 tagging and for `delete_facet`. | `sec/M2-integrity` | yes (author): `test_concurrent_merge_and_delete_keep_every_tag` fails without the locks and passes with them; awaits re-verification |
| 5 | low | **YAML import is CPU-bound work on the event loop.** Parsing a 2 MB document takes 9 to 16 s and blocks every request on that worker. A valid file can also hold over 100,000 terms. | `sec/M2-import` | yes (author): parse runs in a worker thread; 10,000-term cap tested in `test_imports_audit_every_change_and_cap_the_size`; awaits re-verification |
| 6 | low | **Parent cycles through concurrent updates.** Two PATCHes setting A.parent=B and B.parent=A both commit; both terms then disappear from the tree views. | `sec/M2-integrity` | partly (author): hierarchy changes lock the facet row. `test_concurrent_parent_changes_cannot_form_a_cycle` passes but does not reproduce the race (it also passes without the locks); verified by code reading only; awaits re-verification |
| 7 | low | **`$` in `re.match` accepts a trailing newline** in facet keys, term keys, jurisdiction codes and geometry ids. A second "Germany" with code `DE\n` was created; whitespace-only names were accepted. | `sec/M2-integrity` | yes (author): `test_facet_fields_are_bounded`, `test_typed_import_fields_are_422_and_reads_keep_working`; awaits re-verification |
| 8 | low | **Facet labels and sort_order unvalidated.** A label with ESC and 100,000 characters was accepted; an out-of-range `sort_order` gave 500. | `sec/M2-integrity` | yes (author): `test_facet_fields_are_bounded`; awaits re-verification |
| 9 | low | **AttributeValidator accepts values the database or one-line fields reject, and echoes input without limit.** Lone surrogates, U+2028, U+200B, U+FEFF, U+061C and U+200F passed; 2**63 passed; a 1 MB key came back as a 1 MB field name; errors had no cap. | `sec/M2-integrity` | yes (author): `test_invisible_and_unstorable_characters_are_refused`, `test_int64_bounds_and_bounded_errors`; awaits re-verification |
| 10 | low | **Empty regex accepted and matches every text** (`regex: [""]` matched "zzz" with confidence 0.9). | `sec/M2-regex` | yes (author): `test_invalid_rules_are_refused` (`""`, `a*`, `(x|)`); awaits re-verification |
| 11 | low | **Import audit row records counts only**, not the facets and terms changed or their before/after values. | `sec/M2-import` | yes (author): `test_imports_audit_every_change_and_cap_the_size`; awaits re-verification |
| 12 | info | (a) Merge accepts an inactive target term. (b) Merge does not rewrite `regulation.attributes`. (c) Re-seeding does not bump `taxonomy.version`. (d) `registries.yaml` says `taxonomy.manage` covers "import and export", but the contract gives export `taxonomy.read`. (e) Import does not check Content-Type. | (a), (c) `sec/M2-integrity`; (b), (d), (e) see author response | (a), (c) yes (author) |

**Sign-off at review:** not signed off; one high (1) and three medium (2, 3, 4) open · M2 independent review · 2026-11-13

## Evidence (reviewer)
1. **Finding 1:** `/tmp/m2_redos2.py`: `((a+))+$` accepted, 1.40 s at n=24. `\d+\s*EUR` on 50,000 digits: 15.96 s. `\w*\w*\w*z` on 2,000 characters: over 60 s. Integration PoC: test-rules returned after 16.3 s while `/health` waited 16.3 s. The M4 impact is from code reading.
2. **Finding 2:** integration PoC `test_import_type_confusion_breaks_reads`: import 200, then 500 on both list routes. The other wrong types gave 500 in the same test.
3. **Finding 3:** integration PoC `test_delete_and_rename_leave_dangling_refs`: delete 204, rename 200, retype 200, facet delete 204; the attributes and source defaults were left dangling.
4. **Finding 4:** integration PoC `test_merge_vs_delete_race_loses_tags`: 0 `item_term` rows and 0 terms remained.
5. **Finding 5:** `/tmp/m2_unit.py`: 16.15 s and 9.28 s to parse 2 MB documents.
6. **Finding 6:** integration PoC `test_parent_cycle_race`: cycle stored; both terms missing from the tree.
7. **Findings 7 to 11:** unit and integration PoCs as described in each row; finding 11 by code reading.
8. **Authorization and baseline:**
   - authorization matrix PoC as summarised in the STRIDE table;
   - repository suites: unit 421 passed, integration 69 passed.

## Author response (M2 session, 2026-11-13)
- **Finding 1 and BL-74:** match-rule regexes now compile and run on RE2 (google-re2 1.1.20251105, BSD-3-Clause; register row V `927f5d5`; reviewed licence exception). RE2 does not backtrack, so evaluation is linear in the text. Keywords use a linear substring scan. Hit collection stops at the cap. The rule test runs in a worker thread. The nested-quantifier heuristic is removed. RE2 refuses backreferences and lookaround, which is recorded as an assumption.
- **12(b):** `regulation.attributes` is written by M4 and M5, not yet. M4's task card should include rewriting it on merge; BL-75 records this.
- **12(d):** the contract wins: export needs `taxonomy.read`, which also matches what `GET /taxonomy/facets` already exposes. The `registries.yaml` description is corrected by the CP proposed as BL-75.
- **12(e):** accepted. The Origin check prevents cross-site posting, and a body that is not YAML fails parsing with 422.
