# M4 Processing and enrichment pipeline

**Phase:** P2 · **Size:** L · **Parallelism:** pipeline core (one session), classification rules (one session), optional model classifier (one session, behind flag).
**Requirements:** REQ-02, REQ-03, REQ-06 (change events feed the map)

## Purpose
Turn raw documents into canonical items: extract text, detect language, deduplicate, version and diff content, tag jurisdictions and taxonomy terms, raise change events with severity.

## Scope
In: extraction and cleaning, language detection, canonical URL and hash dedupe, fuzzy near-duplicate detection, versioning and diffs, rule-based classification using M2 match rules, jurisdiction detection (source defaults, country names and codes, domain heuristics), effective-date extraction from text patterns, change events, optional model-based classification and summary.
Out: translation (E9), legal analysis.

## Interfaces
- Celery chain per candidate: `process.extract -> process.dedupe -> process.version -> process.classify -> process.geotag -> process.events`.
- `POST /items/{id}/reprocess`, `POST /items/{id}/tags` (manual override, `assigned_by=user`), `GET /items/{id}/versions`, `GET /items/{id}/diff?from=&to=`.
- `Classifier` protocol: `classify(text, lang, facets) -> list[TermAssignment(term_key, confidence, evidence)]`; implementations `RuleClassifier`, `ModelClassifier` (flag `classification.model`).
- Events: `item.captured`, `item.changed` with `{item_id, jurisdiction_ids, kind, severity}`.

## Data
`item`, `item_version`, `item_term`, `item_jurisdiction`, `change_event`.

## Open-source components
trafilatura (Apache-2.0), lingua-py (Apache-2.0) or langdetect (Apache-2.0), rapidfuzz (MIT), python-dateutil (Apache-2.0 and BSD), dateparser (BSD-3), difflib (stdlib), bleach or nh3 (Apache-2.0 and MIT) for HTML sanitising, spaCy (MIT) optional for entity extraction, Ollama (MIT) optional local model server.

## Design notes
- Sanitize extracted HTML with nh3 before storage; store plain text for search and sanitized HTML reference for display.
- Dedupe order: exact `url_hash`, then `content_hash`, then rapidfuzz token-set ratio on title above 92 within the same jurisdiction and 7-day window.
- Change threshold: `changed_pct = differing characters / max(len(old), len(new))`; below the job threshold produces `unchanged` and no event; status changes always produce events.
- Severity rules (configurable): `major` when regulation status moves to adopted or in force, or title matches enforcement keywords; `notable` when changed_pct above 20; else `info`.
- Jurisdiction detection: source defaults first; then gazetteer match on country names and demonyms in title and first 2000 characters; then domain country-code heuristics; confidence recorded.
- Model classifier (optional): one interface with providers `ollama` (local) and `http` (hosted API); prompt templates versioned in `processing/prompts/`; outputs validated against the facet term list; never auto-assign below confidence 0.6; all model calls logged with token counts; disabled by default.
- Idempotency: processing a `RawDocument` twice yields no new version.

## Acceptance criteria
1. Two fetches of identical content create one item with one version; a changed fetch creates version 2 with a readable diff and `item.changed`.
2. An item whose text contains "Bundesamt für Sicherheit in der Informationstechnik" is tagged Germany with confidence above 0.7 when the source has no default jurisdiction.
3. A rule with keywords "ransomware, incident reporting" tags the topic `incident reporting` on a matching document and not on a non-matching one.
4. Disabling the model flag leaves classification working through rules only, with no outbound call (verified by a network mock).
5. Reprocessing an item after taxonomy changes updates tags and preserves user-assigned tags.

## Test plan
- Unit: each stage with fixtures in 5 languages; threshold math; severity rules; sanitiser against XSS payloads.
- Integration: chain end to end on a fixture corpus of 200 documents with expected tags (precision and recall reported, floor 0.8 precision for rules).
- Property-based: random text never raises; dedupe is symmetric.
- Security: prompt-injection fixtures for the model classifier (content instructing the model to change tags must not alter outputs beyond the term list); oversized documents truncated safely.

## Question bank
1. Is a hosted model provider acceptable, and under what data agreement? Default: disabled.
2. Which languages must classification support with rules? Default: English plus keyword lists in French, German, Spanish, Portuguese, Japanese seeded by the owner.
3. Should users be able to mark false positives to tune rules? Default: yes, feedback stored on `item_term`.
4. What makes a change "major" for the owner's team? Default: status to in force or adopted, enforcement actions.

## Enhancements to propose
E4 summaries and obligation extraction with a model; E9 machine translation; E11 confidence-weighted map colouring.
