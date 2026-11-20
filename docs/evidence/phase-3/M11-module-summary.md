# M11 Interests and catalogue: module status record

**Branch:** `feat/M11-interests` (stacked on `feat/M6-help`) · **Date:** 2026-11-20 · **Decision record:** ADR-0012, accepted on recommendation under the owner's standing instruction · **Status:**
- **Built:** the four slices in ADR-0012: 11.1 interests, 11.2 the feed catalogue, 11.3 feed requests and 11.4 groups. Each has an API part and a web part.
- **Security:** every slice is signed off by the independent reviewer, with fixes re-verified. One Medium was found and fixed: an approval could revive a paused source past the robots.txt override permission (11.3, `64a2971`).
- **Tests:** `make test-api` passes: 1,495 unit tests (96.13% coverage) and 417 database tests. `make test-web` passes 205 tests, and `make lint` is clean. `make e2e` passes 4 of 4 on the QA stack; the axe sweep now covers `/admin/groups` and `/me` in three themes, and it found two target-size issues, now fixed (`80415c2`, `280890b`).

## What the owner asked for (2026-11-20) and where it is

| Request | Built | Evidence |
| --- | --- | --- |
| Configuration, content and output follow each user's login and interests | **11.1:** interests (regions, jurisdictions, topics) are default filters on the map and the items list. Places combine as any of, and the chip says what is applied; "Show everything" widens it. They are never a limit on what anyone may see. | `test_preferences.py`, `InterestsEditor.test.tsx`, `map/api.test.ts` |
| A curated list of feeds that ships with the application, chosen by tick boxes | **11.2:** `seed/catalogue.yaml` holds R-06's four verified official sources. Feeds on the User tab follows them, and a source is captured while an active user follows it. Admins see "captured: followed by n users". | `test_catalogue.py`, `test_seed.py`, `test_capture_runs.py`, `FeedsEditor.test.tsx` |
| Custom feeds through the add function | **11.3:** users ask for a feed, and the URL is never fetched for the request. Editors create the source in the source editor, then approve it into the catalogue (the requester follows it) or decline it. Admins still add sources directly, as before. | `test_feed_requests.py`, `FeedRequests.test.tsx` |
| Groups, and OAuth later | **11.4:** groups with roles, members and shared interests. A group never carries `users.manage` or `roles.manage`. OIDC with group claims stays in M1b (Phase 5). | `test_groups.py`, `GroupsPage.test.tsx` |

## Contract changes (accepted on recommendation; listed for the owner at G3)

| CP | Change | Migration |
| --- | --- | --- |
| CP-24 | `Preferences.interests`, `GET /me/interest-options`, and the search jurisdiction filter up to 300 codes | none |
| CP-25 | `source.catalogue_key`, `source.summary`, `source_follower`; `GET /catalogue`; `PUT` and `DELETE /catalogue/{id}/follow`; `captured` and `followers` on sources | 0008 |
| CP-26 | `feed_request` and `/feed-requests` (create, list, withdraw, decide) | 0009 |
| CP-27 | `user_group`, `group_member` and `group_role`; `/admin/groups` and its members; `GET /me/groups` | 0010 |

## Open (BACKLOG)

- **BL-136:**
  - (a) Verify and add the other starter sources in 4.5. CISA advisories answers, but has no reuse-terms page; NIST, ENISA, ICO, OPC and OAIC did not answer at the feed addresses tried.
  - (b) Catalogue topics.
  - (c) legislation.gov.uk needs the contact email set.
  - (f) to (k): smaller follow-ups.
- **BL-137:** a Valkey rate test that is sensitive to timing under load.
- **BL-138:** notifying requesters of decisions (M8).
- **BL-139:** views shared with a group; group-grantable permissions in the registry; the "Members get" preview for admins without `roles.manage`; OIDC group mapping (M1b).
