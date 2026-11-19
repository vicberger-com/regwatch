# M4 Processing and enrichment: module completion record

**Branches:** `feat/M4-items` (items, pipeline, item routes), `feat/M4-enrichment` (language, near-duplicates, classifier, snapshots, dates, PDF and XHTML, translation), both stacked under `feat/M5-map`. · **Date:** 2026-11-19 · **Status:** acceptance 1 to 6 met by tests. The fixes made after sign-off are listed below; they wait for the M4 completion review.

## Acceptance criteria (`docs/modules/M4-processing-enrichment.md`)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Two fetches of identical content make one item with one version; a changed fetch makes version 2 with a readable diff and `item.changed` | **Met** | `tests/integration/test_processing_ingest.py::test_one_item_one_version_then_a_changed_version`; `test_processing_pipeline.py::test_a_change_raises_content_changed_and_a_rerun_nothing`; `test_items.py` (the diff routes) |
| 2 | A text naming the Bundesamt für Sicherheit in der Informationstechnik is tagged Germany above 0.7 with no source default | **Met** | `test_processing_pipeline.py::test_a_new_item_is_tagged_and_raises_an_event` (0.9); corpus jurisdictions precision 0.974, recall 0.925 (`M4-corpus-quality.md`) |
| 3 | A rule with keywords "ransomware, incident reporting" tags `incident reporting` on a matching document only | **Met** | `test_processing_classify.py::test_a_keyword_rule_tags_matching_documents_only`; corpus rule precision 0.846 against a floor of 0.8 |
| 4 | With the model flag off, classification works through rules only, with no outbound call (network mock) | **Met** | `test_processing_classify.py::test_with_the_model_flag_off_rules_alone_classify_and_nothing_calls_out`; `tests/unit/test_processing_offline.py` |
| 5 | Reprocessing after taxonomy changes updates tags and keeps user tags | **Met** | `test_items.py::test_tags_reprocessing_and_who_may_change_them`; `test_processing_classify.py::test_reclassifying_keeps_user_tags_and_judged_tags` |
| 6 | A Japanese item keeps its original text and gets an English title and summary from the selected provider; switching the provider and reprocessing replaces the translation and records the new provider | **Met with the `http` provider** | `test_processing_classify.py::test_a_japanese_item_gets_english_from_the_selected_provider` (two providers); `tests/unit/test_processing_translate.py` (the LibreTranslate API, redaction, cleaning, budget). Argos and LibreTranslate as sidecars wait for the model licenses (BL-42) |

## Slices and their security reviews

| Slice | Commits | Review | Sign-off |
| --- | --- | --- | --- |
| Items, versions, ingest, jurisdictions, events, rule classification, pipeline | `f1070ec` to `4235bd6` | `M4-pipeline-review.md` (re-verifications 1 to 5) | yes (5) |
| Pipeline additions: ownership by credibility (N8), language detection, near-duplicates, model classifier gate, low residuals | `a2abdd4` to `984a55e`, `74785aa` | `M4-pipeline-review.md` (6 to 8) | yes (8) |
| Item routes: detail, versions, diff, tags, reprocess | `34ce213` to `915947f` | `M4-item-routes-review.md` | yes (2) |
| Enrichment: snapshots, effective dates, PDF and XHTML, translation, SafeFetcher POST | `9589c35` to `bf3f55a`, `ad97c7a` | `M4-pipeline-review.md` (9, 10) | yes (10) |
| Corpus quality report | `1cd1ebe` | n/a (a test) | n/a |

**Fixed after sign-off, waiting for the M4 completion review:**
- N17: an unfetched copy never silences a fetched item.
- `76fe9c8`: the event kind no longer shadows the source kind.
- N25 to N29 (`bb672a2`):
  - the snapshot budget;
  - cleaning of translations;
  - the translation budget and failure stop;
  - redaction;
  - https for the translator.

## Decisions made during M4

- **CP-19:** `item.fetched_host`, ownership from the fetched row, migration 0005 (BL-108).
- **CP-20:** indexes, migration 0006.
- **Owner decisions of 2026-11-19:**
  - effective dates as a seeded date facet;
  - pypdf 7.1.1 in a sandboxed child;
  - translation through the `http` provider first;
  - snapshots stored now and served later.
- **Dependencies:** lingua-language-detector 2.2.0 and rapidfuzz 3.14.6 (owner approved, M4 Q6).
- **Assumptions:** M4 Q1 to Q5 and Q7 are in ASSUMPTIONS (assumed on "continue").

## Open follow-ups (backlog)

- **BL-106 and BL-107:** PDF and pipeline residuals.
- **BL-110:** item route residuals.
  - (a) A removed jurisdiction comes back when the item is reprocessed.
  - (b) The reprocess route has no rate limit.
- **BL-111:** model classifier providers.
- **BL-112:**
  - the near-duplicate twin link;
  - CJK titles;
  - non-ASCII digits.
- **BL-115:**
  - skipping an unchanged body;
  - charsets in snapshots;
  - the CP for the snapshot route;
  - two timing tests that flake under load.

## Owner items

- **Assumptions:** confirm the M4 assumption rows.
- **Model licenses:** decide the Argos de→en and ja→en models (BL-42) before translation sidecars.
- **Translation:** enable it only once a hosted provider and a data-processing basis are chosen (8.4).
