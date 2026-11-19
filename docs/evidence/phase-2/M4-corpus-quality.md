# M4 corpus quality (roadmap 4.9)

**Corpus:** `api/tests/fixtures/corpus/`, 200 documents (en 60, ja 26, zh 26, de 22, fr 22, es 22, pt 22) with expected jurisdictions and terms (issue #12, `docs/contracts/fixtures.md`). Excerpts are at most 1,500 characters. · **Test:** `api/tests/unit/test_corpus_quality.py`, run in `make test-api`. · **Date:** 2026-11-19

## Jurisdictions (`geotag.detect`, no source defaults)

| Precision | Recall | True positives | False positives | Missed |
| --- | --- | --- | --- | --- |
| 0.974 | 0.925 | 185 | 5 | 15 |

The test's floors are precision 0.9 and recall 0.85.

## Rule classification (`taxonomy.rules.evaluate`, minimum confidence 0.6)

These are representative keyword lists in the seven corpus languages (`corpus/rules.yaml`, test data; under M4 Q2 the owner seeds the real lists in the taxonomy).

| Term | Precision | Recall |
| --- | --- | --- |
| topic.cybersecurity | 0.83 | 0.50 |
| topic.incident-reporting | 1.00 | 0.11 |
| topic.data-protection (two hits) | 0.80 | 0.33 |
| topic.critical-infrastructure | 0.91 | 0.27 |
| topic.supply-chain-security | 1.00 (none tagged) | 0.00 |
| **All** | **0.846** | **0.283** |

The test plan's floor is 0.8 precision for rules, and it is met.

Recall is low. The expected tags are an editor's judgement over whole documents, while rules see short excerpts and literal keywords. Recall comes from the owner's seeded lists, from the model classifier once a provider exists (BL-111), and from translation (English rules on English text).

With a single hit, data protection's precision is 0.64. Passing mentions ("personal data within the meaning of Regulation 2016/679") are not the topic, so the list needs two hits.

Jurisdiction errors are recorded as BL-112 (e) and (f), and the geotag residuals as BL-107 (h).
