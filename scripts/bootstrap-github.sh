#!/usr/bin/env bash
# Creates labels and the Phase 0 issues. Requires the GitHub CLI authenticated with push access.
# Usage: scripts/bootstrap-github.sh owner/repo
set -euo pipefail
REPO="${1:?usage: $0 owner/repo}"

label() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force >/dev/null && echo "label $1"; }
for m in M0 M1 M2 M3 M4 M5 M6 M7 M8 M9 M10; do label "module:$m" 1d76db "Module $m"; done
for p in P0 P1 P2 P3 P4 P5 P6; do label "phase:$p" 5319e7 "Phase $p"; done
for t in feature bug test security docs question research usability; do label "type:$t" fbca04 "Type $t"; done
for s in ready claimed in-review blocked done; do label "status:$s" 0e8a16 "Status $s"; done
label "gate" d93f0b "Phase gate decision for the owner"
label "assumed" c2e0c6 "Answer assumed by an agent; owner to confirm"
label "claude" 7B3FE4 "Add to an issue to have the Claude Code GitHub Action work on it"

issue() { # title labels bodyfile  (REST API so it works where GraphQL is unavailable)
  jq -n --arg t "$1" --arg l "$2" --rawfile b "$3" '{title:$t, body:$b, labels:($l|split(","))}' \
    | gh api "repos/$REPO/issues" --input - --jq '"issue #\(.number): \(.title)"'
}
B=$(mktemp -d)

cat > "$B/questions.md" <<'MD'
Global questioning period for Phase 0 (docs/02-requirements.md section 2.4). Each row has the default that applies if unanswered at Gate G0; unanswered rows are copied to docs/decisions/ASSUMPTIONS.md tagged `assumed`.

| # | Question | Default if unanswered | Owner answer | Status |
| --- | --- | --- | --- | --- |
| 1 | Who are the users? | Compliance and security analysts in one organisation | | open |
| 2 | Which jurisdictions on day one? | EU, US federal, UK, Canada, Australia, Japan, Singapore, India, Brazil, EU member states via EUR-Lex | | open |
| 3 | Which topics count as IT and cybersecurity? | Cybersecurity, data protection and privacy, critical infrastructure, incident reporting, AI governance, digital identity, telecoms security, product security, cloud and outsourcing, cross-border transfer | | open |
| 4 | Acceptable freshness? | 15 minutes to 24 hours per source; map window 30 days | | open |
| 5 | May a language model touch captured text? | No; rules only (flag off) | | open |
| 6 | Where does it run and who operates it? | Docker Compose on one Linux host; owner operates | | open |
| 7 | SMTP relay and printers? | Admin-configured relay; browser print at launch | | open |
| 8 | Integrate with an identity provider? | Local accounts; OpenID Connect in P5 | | open |
| 9 | Branding assets? | Neutral palette, Inter typeface | | open |
| 10 | Export formats beyond PDF? | PDF and CSV in P4; Excel and DOCX backlog | | open |
| 11 | Proactive alerts besides the map? | Daily email digest in P4 (E1) | | open |
| 12 | Budget for paid search or news APIs? | Zero; self-hosted first | | open |
| 13 | License for this repository's own code? | Owner decision; no default | | open |
| 14 | Phase dates and pilot group? | Unset | | open |
MD
issue "Questions: Phase 0 global scoping" "phase:P0,type:question" "$B/questions.md"

cat > "$B/gate.md" <<'MD'
Owner decision closing Phase 0. Closes only with an owner comment `approved`.

- [ ] Questions: Phase 0 answered or assumptions recorded in docs/decisions/ASSUMPTIONS.md
- [ ] Research items R-01 to R-07 closed with evaluation records in docs/research/
- [ ] Component register rows upgraded to status V with LICENSE commit hashes (docs/03-architecture.md 3.6)
- [ ] ADR-0001 to ADR-0008 written and accepted (docs/decisions/)
- [ ] Backlog rows BL-01 to BL-08 and enhancements E1 to E25 decided (BACKLOG.md)
- [ ] Phase 1 issues created from module specs M0, M1, M2 using the task card template
- [ ] Owner comment: approved

Evidence folder: docs/evidence/phase-0/
MD
issue "Gate G0: discovery and open-source review" "phase:P0,gate" "$B/gate.md"

mk_research() { # id title module body
cat > "$B/$1.md" <<MD
Phase 0 research item $1 (docs/09-enhancements-backlog.md). Record the result with docs/templates/COMPONENT_EVALUATION.md under docs/research/ and link it here. Follow the open-source review protocol in docs/03-architecture.md section 3.8 and the license policy in section 3.5.

**Question to settle:** $3

**Done when:** evaluation record committed, component register updated, finding summarised in a closing comment, and any ADR affected is referenced.
MD
issue "$1: $2" "phase:P0,type:research,$4" "$B/$1.md"
}
mk_research R-01 "Verify every component register row against its LICENSE file" "Open each project's LICENSE file at a tagged release, record the commit hash and the SPDX identifier, and upgrade the row to status V. Flag any mismatch with the register." "module:M0"
mk_research R-02 "Confirm Puck fits the report builder" "Confirm Puck supports keyboard-only drag and drop and server-side rendering of its data model; otherwise plan the dnd-kit fallback and draft ADR-0005." "module:M7"
mk_research R-03 "Evaluate OpenSSF cyber policy working group and UNCTAD tracker as data sources" "Assess the OpenSSF Global Cyber Policy working group repository and the UNCTAD cyberlaw tracker as data sources or seed taxonomies, not as code; record formats, licenses and update cadence." "module:M3"
mk_research R-04 "Confirm a permissively licensed IPP client for server-side printing" "Confirm an MIT or Apache licensed IPP client (Node ipp or alternative) prints to a test IPP server; otherwise browser print only at launch." "module:M8"
mk_research R-05 "Choose the vendored Natural Earth resolution for the map" "Measure MapLibre choropleth render time and payload size with 1:50m versus 1:110m Natural Earth admin-0 and choose the vendored resolution; draft ADR-0004." "module:M6"
mk_research R-06 "Check terms and rate limits of official APIs" "Check EUR-Lex, Federal Register and legislation.gov.uk API terms and rate limits; document them in the starter source configs." "module:M3"
mk_research R-07 "Decide search provider for the first release" "Compare self-hosted SearXNG against a commercial search API on 20 benchmark regulatory queries for relevance and cost; recommend one for Phase 2." "module:M3"

cat > "$B/adrs.md" <<'MD'
Write ADR-0001 to ADR-0008 listed in docs/03-architecture.md section 3.7 using docs/templates/ADR.md. Each ADR cites the research items it depends on and the requirement IDs. Status `proposed` until the owner accepts at Gate G0.

- [ ] ADR-0001 Modular monolith API plus worker pool
- [ ] ADR-0002 PostgreSQL as system of record and first search engine
- [ ] ADR-0003 License policy and the service-boundary exception
- [ ] ADR-0004 MapLibre with vendored Natural Earth GeoJSON (after R-05)
- [ ] ADR-0005 Puck for the report builder (after R-02)
- [ ] ADR-0006 Celery and Valkey for scheduling
- [ ] ADR-0007 Local authentication first, OpenID Connect later
- [ ] ADR-0008 Gotenberg for PDF
MD
issue "Write ADR-0001 to ADR-0008" "phase:P0,type:docs,status:ready" "$B/adrs.md"
rm -rf "$B"
echo done
