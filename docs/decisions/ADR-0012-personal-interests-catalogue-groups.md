# ADR-0012: Personal interests, a curated feed catalogue, and groups

**Status:** proposed 2026-11-20 at the owner's request. Accepted on recommendation under the owner's standing instruction; the three choices below were asked and left at their recommended answers, and the owner may override them at G3. · **Requirements:** REQ-07, REQ-08, REQ-14, REQ-04, REQ-01 · **Research:** R-03 (starter sources), M1 (roles), M5 (saved views), M9 (preferences)

## Context

The owner confirmed that RSS feeds are added, captured, updated and listed on the map and the items page, and that the audit log records the changes. The owner asked that each user's configuration, content and output follow their own interests, with two examples: European laws on supply-chain resilience for one user, and China's AI laws for another. The request had five parts:
- interests as interface filters, or as output sort and query filters;
- a curated list of feeds that ships with the application, which users tick to select;
- the existing add function for further custom feeds;
- groups;
- OAuth sign-in later.

What exists today:
- per-user preferences;
- saved views (private or shared), with filters for jurisdictions, regions, facet terms, sources, severity, status and dates;
- a landing view the map opens with;
- roles and permissions;
- admin-managed sources;
- R-03's verified starter sources, which were never seeded.

## Decision

1. **Interests are default filters, never a limit.**
   - A user, or a group, has an interest profile. It holds jurisdictions and regions, facet terms (for example `topic: supply chain security`, `topic: AI governance`), followed sources and optional keywords.
   - The map, the items table, search, and later reports and digests (M7, M8) open filtered by the profile, ordered by relevance to it.
   - A visible "My interests" chip set shows the filter, and one action widens it to everything.
   - Every user can still see all content. Access control stays with roles, so the search index, exports and the API need no per-item visibility.
   - The profile is stored in the user's preferences as `interests` (CP-24), with the same shapes as the M5 filters and checked against `GET /me/interest-options`. That needs no migration, and it reuses the reviewed preference path.
2. **A curated feed catalogue ships with the application.**
   - `seed/catalogue.yaml` lists R-03's verified starter sources. For each it gives the connector configuration, terms URL, credibility, jurisdictions, topics and a one-line description, and leaves out the sources R-03 rules out, such as `flk.npc.gov.cn`.
   - The seed creates them as sources that are disabled, marked `catalogue`.
   - The User tab gets a "Feeds" section: a catalogue grouped by region and topic, with tick boxes.
   - Ticking a feed follows it: it joins the user's interest profile. A source is captured while it has at least one follower, or while an admin enables it.
   - Capture stays shared: one fetch per source, whoever follows it.
3. **Custom feeds are shared and marked as user-added.**
   - Users with `sources.manage` add a feed directly, as today. It joins the catalogue marked "added by …", and anyone can follow it.
   - Other users submit a feed request (URL, reason). An editor approves it, which creates the source, or declines it. Requests are audited.
   - SafeFetcher's address checks apply in both paths, as now.
4. **Groups.**
   - A group has members, roles and an interest profile. Examples are an EU policy team and an APAC team.
   - A member's effective profile is their own, or their group's when they have not set one. They can switch between them, as with views.
   - Roles granted to a group apply to its members, alongside their own roles.
   - Shared views can be shared with a group instead of with everyone.
5. **OAuth and OpenID Connect stay in Phase 5 (M1b),** with group claims mapped to these groups. Groups built now are the target of that mapping, so no rework is needed.

## Alternatives considered

| Option | Why not chosen now |
| --- | --- |
| Interests as a hard limit on what a user can see | It needs per-item visibility in search, the OpenSearch index, the map aggregations and exports, which brings more security risk and duplicated logic. The owner can revisit at G3. |
| Private custom feeds | Same per-item visibility cost, and duplicate captures of popular feeds. |
| Any user adds feeds directly | More capture load and URL vetting. The request flow keeps an editor in the loop. |

## Consequences

- **New data:**
  - `saved_view.kind`;
  - `user_group`, `group_member` and `group_role`;
  - `source.catalogue` and `source.added_by`;
  - `feed_request`;
  - a follow table (`source_follower`).
- **New migrations:** 0008 onwards. A CP each for the OpenAPI additions: `/me/interests`, `/catalogue`, `/feed-requests` and `/admin/groups`.
- **The seed** gains `catalogue.yaml`. Each catalogue source records its terms and licence; R-03's data-licence rows go into the register (BL-20).
- **Capture:** the scheduler runs enabled sources and followed catalogue sources.
- **Phasing:** proposed as module M11 "Interests and catalogue", in slices:
  - 11.1 interest profile and default filters;
  - 11.2 catalogue seed and the Feeds tab;
  - 11.3 feed requests;
  - 11.4 groups.

  It runs before M7 and M8, so reports and digests can use the profiles. Each slice gets tests and an independent security review.
