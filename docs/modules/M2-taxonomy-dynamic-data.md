# M2 Taxonomy and dynamic data model

**Phase:** P1 · **Size:** M · **Parallelism:** one session for schema and API, one for admin UI after the API PR merges.
**Requirements:** REQ-03, REQ-11

## Purpose
Let administrators define the dimensions by which items are indexed, sorted, filtered and viewed (topics, industries, technologies, regulation types, custom facets) and manage jurisdictions and regions, without code changes.

## Scope
In: facet and term CRUD with hierarchy and synonyms, jurisdiction and region management, attribute validation service, taxonomy import and export (YAML), match rules editor for rule-based tagging (consumed by M4), seed data.
Out: automatic taxonomy learning; multilingual labels (enhancement E10).

## Interfaces
- `GET|POST|PATCH|DELETE /taxonomy/facets`, `/taxonomy/facets/{key}/terms` (tree and flat forms), `POST /taxonomy/terms/{id}/merge` (re-tags items).
- `GET|POST|PATCH /jurisdictions`, `GET /jurisdictions/regions`.
- `POST /taxonomy/import` and `GET /taxonomy/export` (YAML, versioned schema).
- Python service `AttributeValidator.validate(attributes: dict) -> ValidatedAttributes` used by M3, M4, M5 and M7.
- `GET /taxonomy/view-dimensions` returns facets flagged for the view selector (consumed by M6).

## Data
`facet`, `term`, `jurisdiction`, `item_term`, `item_jurisdiction`.

## Open-source components
i18n-iso-countries (MIT) for names and codes, Natural Earth (public domain) feature ids, pyyaml (MIT), SKOS vocabulary concepts as a pattern for hierarchy and synonyms (no code).

## Design notes
- System facets (`topic`, `industry`, `technology`, `regulation_type`) cannot be deleted; they can be hidden.
- Term deletion is soft (`active=false`) unless no items reference it; merge moves references and records an audit row.
- Facet changes bump a `taxonomy_version` setting that invalidates attribute-validation caches in workers.
- `match_rules` schema: `{keywords: [..], regex: [..], languages: [..], min_hits: 1, weight: 1.0}`; rules are evaluated by M4, edited here with a "test against sample text" button.

## Acceptance criteria
1. An admin adds a facet "enforcement_body" with three terms; within 60 seconds it appears in filters and the view selector without a restart.
2. Importing the seed YAML twice is idempotent.
3. Merging two terms re-tags all items and leaves no dangling references.
4. Validation rejects an unknown attribute key and a non-term value for a term facet, with a problem-details response naming the field.

## Test plan
- Unit: validator for each value type, hierarchy cycles rejected, synonyms normalised.
- Integration: import, export, round-trip equality; cache invalidation across API and worker.
- E2E: admin facet creation visible in M6 filters.
- Property-based (Hypothesis): random attribute documents against random facet sets never crash the validator.

## Question bank
1. Is there an existing corporate taxonomy or control framework (NIST CSF, ISO 27001 clauses) to map to? Default: none; provide mapping facet later.
2. Are jurisdictions below country level needed on day one (US states, German Länder)? Default: schema supports, UI hides until requested.
3. Who may edit taxonomy: admins only or editors? Default: admins.
4. Should terms carry multilingual labels? Default: English only (E10).

## Enhancements to propose
E10 multilingual labels; mapping facets to control frameworks; term usage analytics.
