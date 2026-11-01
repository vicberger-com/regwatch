# 2. Requirements review

The source document (regulatory_application.docx, three paragraphs) was decomposed into 27 requirements. Twelve of them need an owner decision before a module can be finished; defaults are recorded below so work can start without blocking.

## 2.1 Numbered requirements (traceability keys)

| ID | Requirement (paraphrased from the source) | Type | Module(s) |
| --- | --- | --- | --- |
| REQ-01 | Application is written in modules and delivered in phases | Process | All |
| REQ-02 | Monitor global legal and regulatory status and changes for information technology and cybersecurity topics | Functional | M3, M4 |
| REQ-03 | Store captured data in a dynamic database that indexes and sorts by taxonomy terms, topics, keywords and user-defined attributes | Functional | M2, M5 |
| REQ-04 | Support multiple capture modes, each configured individually: target data, frequency, capture settings | Functional | M3 |
| REQ-05 | Connect to common data feeds, RSS, web page scraping and internet searches | Functional | M3 |
| REQ-06 | Primary UI is a world map; countries with updates inside a user-defined period are highlighted or change colour | UI | M6 |
| REQ-07 | Interface has a settings icon and a visible toolbar of commands | UI | M6 |
| REQ-08 | Toolbar offers display and filter commands | UI | M6 |
| REQ-09 | Toolbar offers search commands | UI | M5, M6 |
| REQ-10 | Toolbar offers stock and custom report printing | Functional | M7, M8 |
| REQ-11 | View selector changes the map view by attribute: country, regulation, region, target industry, technology; set of attributes configurable in settings | UI | M6, M2 |
| REQ-12 | Report creation tab with drag-and-drop of predefined database fields onto a page; layout configurable and stored | Functional | M7 |
| REQ-13 | Stored report configurations are saved and selectable per user | Functional | M7 |
| REQ-14 | User tab with password change, environmental controls, user-level session configuration and settings, logout | Functional | M9, M1 |
| REQ-15 | Output section sends configured reports, query outputs or predefined data to email, printers, or PDF download | Functional | M8 |
| REQ-16 | Settings area restricted to administrators; configures all application parameters; adds users with function rights and permissions | Functional, Security | M1 |
| REQ-17 | Corporate professional look, clean and modern interface | UI | M6, design system |
| REQ-18 | Light mode, dark mode and a mode for visually impaired users | UI, Accessibility | M6, M9 |
| REQ-19 | Construction begins with an intensive review of GitHub applications and components under open licenses; reuse, combine and add what is missing | Process | Phase 0, all |
| REQ-20 | All reused code comes from open licenses that permit this use | Legal | All |
| REQ-21 | Ask detailed scoping questions, then break work into design and development stages and modules | Process | Phase 0 |
| REQ-22 | Suggest capabilities, functions, features and enhancements | Process | Section 9 |
| REQ-23 | Each stage or module begins with a questioning period | Process | All |
| REQ-24 | Propose changes and enhancements discovered during development; keep a change report and backlog | Process | Section 6 |
| REQ-25 | Each module and the whole application undergo security review, peer review, use testing and adversarial analysis before user phased evaluation and testing | Quality | Section 7 |
| REQ-26 | The owner's GitHub repository stores and tracks the application | Process | Section 6 |
| REQ-27 | Any recommended open-source application may be used for design, development, tracking, testing or record storage | Process | Section 3 |

## 2.2 Gaps and ambiguities found in the source

| # | Gap | Why it matters | Default adopted until the owner answers |
| --- | --- | --- | --- |
| G1 | No deployment target (cloud, on-premises, single server) | Drives infrastructure, secrets, email and printing design | Docker Compose on a single Linux host, cloud-portable; Kubernetes manifests deferred to backlog |
| G2 | No user population or concurrency figure | Sizing, caching, licensing of map tiles | Up to 50 named users, 10 concurrent; single tenant |
| G3 | "Change" and "update" are undefined | Determines what highlights a country on the map | A new or materially changed captured item linked to a jurisdiction, where "materially" means normalized text diff above a configurable threshold (default 5 percent) or a change in status fields |
| G4 | Jurisdiction scope: countries only, or also states, EU, international bodies | Map model and taxonomy | ISO 3166-1 countries plus supranational bodies (EU, Council of Europe, OECD, UN) and optional first-level subdivisions (ISO 3166-2) |
| G5 | Languages of monitored sources | Capture, search and classification | Capture any language; store original; machine translation to English is a backlog item |
| G6 | Whether large language models may be used for classification and summarization | Cost, accuracy, data handling | Allowed behind a feature flag with a rules-based fallback; no captured text leaves the deployment without admin opt-in |
| G7 | "Environmental controls" in the user tab | UI scope | Theme, contrast mode, font scale, density, language, time zone, default landing view |
| G8 | "User-level session configuration" | Security and UX | Session timeout, remember-me, concurrent session limit, default filters |
| G9 | "Stock reports" are not enumerated | Report module scope | Five stock reports defined in M7 |
| G10 | Printing: browser print or server-side printing to network printers | Output module design | Browser print always; server-side IPP printing to admin-registered printers behind a feature flag |
| G11 | Internet search provider: paid API, self-hosted metasearch, or both | Cost and licensing | Pluggable provider interface; first providers are a self-hosted metasearch instance run as a separate service and a configurable commercial API key |
| G12 | Legal and ethical limits on scraping (robots.txt, terms of use, rate limits) | Liability | Respect robots.txt by default, per-source override only by an admin with a recorded justification; polite rate limits |
| G13 | Authentication: local accounts only, or single sign-on | Identity module | Local accounts with optional OpenID Connect federation in phase 5 |
| G14 | Email delivery infrastructure | Output module | Any SMTP relay configured by an admin; a local mail catcher in development |
| G15 | Data retention and audit duration | Storage and compliance | Keep captured items indefinitely with versioning; audit log 2 years; configurable |
| G16 | Mobile or tablet support | UI effort | Responsive down to tablet width; phone layout is backlog |
| G17 | Repository name and structure | Process | Monorepo at the owner's repository; structure in section 6 |

## 2.3 Interpretation notes

- "keyworks" in the source is read as "keywords".
- "Target industry" and "technology" are treated as taxonomy facets alongside country, region and regulation type.
- "Stock and custom report printing" is read as two paths: predefined report templates shipped with the application, and user-built layouts from the report builder.
- "World view map" is read as a choropleth-style map where fill colour encodes recency or count of changes; an accessible table equivalent is mandatory (REQ-18).
- The source's instructions to ask questions and begin each module with a questioning period are process requirements; the autonomous equivalent used here is to record every question with a default assumption, then confirm with the owner at each phase gate.

## 2.4 Global questioning-period record (Phase 0)

Questions the owner should answer before Phase 1 ends. Each has the default used if unanswered.

1. Who are the users (compliance analysts, legal, security leadership)? Default: compliance and security analysts in one organisation.
2. Which jurisdictions must be covered on day one? Default: EU, United States (federal), United Kingdom, Canada, Australia, Japan, Singapore, India, Brazil, plus EU member states via EUR-Lex.
3. Which topics are in scope under "information technology and cybersecurity"? Default: cybersecurity, data protection and privacy, critical infrastructure, incident reporting, AI governance, digital identity, telecoms security, product security (such as the EU Cyber Resilience Act), cloud and outsourcing, cross-border data transfer.
4. What is the acceptable freshness? Default: feeds every 15 minutes to 24 hours per source, configurable; map highlights default to a 30-day window.
5. Is machine learning or a hosted language model allowed to touch captured text? Default: see G6.
6. Where does the application run and who operates it? Default: see G1.
7. Which SMTP relay and which printers exist? Default: see G10 and G14.
8. Must the application integrate with existing identity providers? Default: see G13.
9. Are there branding assets (logo, colours, typeface) to apply? Default: neutral corporate palette defined in the design system, replaceable through settings.
10. What export formats beyond PDF are needed (CSV, Excel, JSON, DOCX)? Default: PDF and CSV in phase 4; Excel and DOCX backlog.
11. Should changes be alerted proactively (email digest, webhook) in addition to the map? Default: daily email digest in phase 4 (enhancement E1 in section 9).
12. What is the budget for paid search or news APIs? Default: zero; self-hosted options first.
