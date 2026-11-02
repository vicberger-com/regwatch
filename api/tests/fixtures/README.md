# Test fixtures

Fixtures for the M3 capture, M4 processing and M5 search tests (issue #12, REQ-25). The inventory and acceptance criteria are in `docs/contracts/fixtures.md`; this file says where each path ended up and how to use it.

## Paths

The contract gives repository-relative `tests/...` paths. The api test layout from #27 keeps all Python tests under `api/tests/`, so every path moves under `api/`:

| Contract path | Path in the repository |
| --- | --- |
| `tests/fixtures/corpus/` | `api/tests/fixtures/corpus/` (`NNN.json`, `NOTICES.md`, `schema.json`, `seed_taxonomy.json`) |
| `tests/fixtures/feeds/` | `api/tests/fixtures/feeds/` (plus `generate.py` for the files that are not committed) |
| `tests/fixtures/pages/` | `api/tests/fixtures/pages/` |
| `tests/fixtures/synthetic/generate.py` | `api/tests/fixtures/synthetic/generate.py` |
| `tests/support/fixture_server.py` | `api/tests/support/fixture_server.py` |
| `tests/security/payloads/` | `api/tests/security/payloads/` (loader: `api/tests/support/payloads.py`) |

Smoke tests are in `api/tests/unit/test_fixture_*.py` and run with `make test`. `make fixtures-check` runs the corpus validator and those tests on their own.

## Corpus

200 documents: 60 in English and 22 each in German, French, Spanish and Portuguese. There are 26 each in Japanese and Chinese. Each is one JSON object in the contract's shape:

```json
{"url": "...", "title": "...", "language": "de", "published_at": "2022-12-27T00:00:00Z",
 "text": "Artikel 23 ...", "source_kind": "rss",
 "expected": {"jurisdictions": ["EU"], "terms": {"topic": ["incident-reporting"]}, "severity": "major"}}
```

- `text` is the minimum a test needs: one article or section, or a Federal Register abstract, cut to at most 1,500 characters at a line break. It is never a whole act.
- `url` is unique per document. Several documents excerpt different articles of the same act; where a site has no per-article address, a fragment names the provision.
- Licences, sources and retrieval dates are in `corpus/NOTICES.md`. That file also records the licence decisions made in this task and the one exception (five PRC statutory excerpts) for the owner to confirm.
- The same EU acts appear in several languages (Cellar language versions of the same article), so the corpus doubles as a small parallel set for translation tests.
- `source_kind` is how the document would be captured: an EUR-Lex or legislation.gov.uk feed (`rss`), the Federal Register, e-Gov or BOE APIs (`api_feed`), or a page (`web_page`). The R-08 Chinese passages are `manual`.

### Expected labels

The labels are hand-assigned from the title and excerpt, not from the whole act. The facet keys are those of the #28 seed files.

- **jurisdictions:** the publishing jurisdiction (`EU` for EU acts, `GB` for the UK).
- **terms:** every document has at least one `topic`; `industry`, `technology`, `regulation_type` and `control_framework` (NIST CSF 2.0 categories, BL-21) are added where the excerpt supports them. `industry: all` marks cross-sector obligations.
- **severity:** the severity of the change event the item would raise if it were new.
  - `major`: a binding act or rule that creates or changes obligations.
  - `notable`: implementing or delegated acts, proposed rules, binding guidance, decisions, and narrower or older provisions.
  - `info`: notices, information collections, consultations on process, definitions and institutional provisions.

### Validator

```
cd api
uv run python -m tests.fixtures.validate_corpus              # exit 1 on any error
uv run python -m tests.fixtures.validate_corpus --write-schema
uv run python -m tests.fixtures.validate_corpus --snapshot-seed   # after #28 merges
```

- **Schema:** `corpus/schema.json` (JSON Schema 2020-12) is generated from the Pydantic model in `validate_corpus.py`. A test fails if the two drift.
- **Taxonomy:** expected terms and jurisdictions are checked against `corpus/seed_taxonomy.json`. It is a snapshot (keys and labels) of the #28 seed files at `94f7dc4`, taken before #28 merged. Once `api/seed/` is on main, `test_taxonomy_snapshot_matches_the_seed_once_merged` compares the two; it is skipped until then.
- **Inventory:** the validator also checks the numbering, at least 20 documents per required language, unique URLs, and a `NOTICES.md` row with the same URL for every document.

## Feeds

| File | What it tests |
| --- | --- |
| `valid_rss.xml`, `valid_atom.xml` | 10 items each, taken from corpus documents |
| `malformed.xml` | an undeclared entity, a bare `&`, a mismatched tag, an unclosed item, an unquoted attribute, truncation |
| `hostile.xml` | script and event handlers in titles and descriptions, `javascript:` and `data:` links, external entities (a local file and `169.254.169.254`), nesting 1,200 levels deep, and a prompt-injection title |
| `encoding_latin1.xml` | ISO-8859-1 bytes with a matching declaration |
| `future_dates.xml` | dates in 2099 and 9999, 31 February, a +14:00 offset, a missing date, the epoch, ISO 8601 in `pubDate`, a two-digit year |
| `huge_10mb.xml`, `entity_expansion.xml`, `deep_nesting.xml` | generated at test time by `feeds/generate.py` (or served by the fixture server); never committed |

## Pages

- **Change sequence:** `page_v1.html`, then `page_v2.html` (about 5 percent of the visible words change), then `page_v3.html` (only the status line changes from v2). `sequences.json` defines the sequence the server plays at `/sequence/change_detection`, and the change class expected at each step.
- `listing.html`: exactly 30 item links in `ul.results`, plus navigation links that must not count. The server serves every item page.
- `js_rendered.html`: the content arrives only after its script fetches `js_rendered_data.json`.
- **robots.txt variants:** `robots_allow.txt`, `robots_disallow.txt`, `robots_crawl_delay.txt`.
- **Redirect configs:** `redirect_chain.json`, `private_redirect.json`.
- `zip_bomb.html.gz` is generated on each request by the fixture server (second #12 pull request) and never committed.

The fixture server, the synthetic data generator and the security payloads are added in the second #12 pull request.
