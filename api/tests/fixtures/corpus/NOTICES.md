# Corpus notices

Licence, source and retrieval date for every document in `api/tests/fixtures/corpus/` (issue #12, REQ-25). The contract in `docs/contracts/fixtures.md` puts this file at `tests/fixtures/corpus/NOTICES.md`; the api test layout from #27 puts it under `api/`.

## What each document holds

Each `NNN.json` holds only what a test needs: the official title, one article or section (or, for the Federal Register, the published abstract) cut to at most 1,500 characters at a line break, the publication date, and the expected labels. No document is a bulk copy. Whitespace and layout were normalised and footnotes and amendment annotations removed, so no excerpt is an official version. Expected labels are the project's own annotations, not the publishers'.

All documents were fetched on the retrieval date shown with the User-Agent `regwatch-fixtures/0.1 (test corpus; issue 12)`, at or below each site's stated crawl delay (legislation.gov.uk 5 s, legislation.gov.au 10 s, others 1 to 1.5 s). Collection scripts were run from a scratch directory and are not committed. The method for each source is under 'Sources' below.

## Licences

| Key | Licence or basis | Attribution and conditions | Source | Documents |
| --- | --- | --- | --- | --- |
| `US-PD` | US government work | 17 U.S.C. 105; OFR and GPO place no restriction on downstream reuse (R-03 C4), except that only OFR and GPO may present a copy as the official version. No NARA seal or Federal Register logo is used. | Federal Register API | 34 |
| `EU-2011/833` | Commission Decision 2011/833/EU | © European Union, https://eur-lex.europa.eu. Reuse is authorised provided the source is acknowledged (R-06, R-08). Only the electronic Official Journal is authentic. | EUR-Lex / Cellar | 78 |
| `OGL-UK-3.0` | Open Government Licence v3.0 | © Crown and database right. Contains public sector information licensed under the Open Government Licence v3.0 (R-03 C3, R-06). | legislation.gov.uk | 10 |
| `OGL-CA` | Open Government Licence - Canada | LICENSE.md in github.com/justicecanada/laws-lois-xml at 0507465; the file does not state a version (R-03 C7). Also the Reproduction of Federal Law Order. Not an official version. | Justice Laws XML | 11 |
| `CC-BY-4.0-AU` | CC BY 4.0 | Sourced from the Federal Register of Legislation at 2 November 2026. For the latest information on Australian Government law please go to https://www.legislation.gov.au (prescribed wording, R-03 C8). | Federal Register of Legislation | 5 |
| `UrhG-5` | Amtliches Werk, § 5 Abs. 1 UrhG | German statutes are not protected by copyright. The gesetze-im-internet.de pages read state no further reuse terms; robots.txt allows all paths. This licence was not checked in an earlier research record, so it is new here (see 'Licence choices made in this task'). | gesetze-im-internet.de | 4 |
| `BOE-2024` | BOE reuse conditions | Condiciones de reutilización, licencia tipo approved by Resolución de la Agencia Estatal BOE of 27 June 2024 (Ley 37/2007): reuse for any purpose; the source must be cited, the meaning must not be distorted, and the date of last update stated. Read on 2026-11-02 at https://www.boe.es/informacion/aviso_legal/index.php. New here, as for UrhG-5. | BOE open data API | 6 |
| `PDL-1.0` | 公共データ利用規約（第1.0版）(PDL1.0) | 出典：e-Gov法令検索 (https://laws.e-gov.go.jp)（デジタル庁）. The excerpts are edited (one article each; whitespace and layout changed) and are not presented as made by the State (R-03 C9). | e-Gov Law API v2 | 26 |
| `TW-OGDL-1.0` | 政府資料開放授權條款－第1版 (Open Government Data License, version 1) | Per the site's 政府網站資料開放宣告 (read 2026-11-02 at https://law.moj.gov.tw/Service/Copyright.aspx): free, non-exclusive, irrevocable reuse, including adaptation, with the source cited. 出處：法務部全國法規資料庫. robots.txt allows /LawClass/LawAll.aspx, the only path fetched. New here, as for UrhG-5. | 全國法規資料庫 (Taiwan) | 21 |
| `CN-STATUTE` | Statutory text, PRC Copyright Law Art. 5 (exception) | See 'Exception: PRC statutory excerpts' below. | R-08 passages (npc.gov.cn) | 5 |

Total: 200 documents.

## Licence choices made in this task

- **Allowed by ADR-0003 decision 5 (open class):** `US-PD`, `EU-2011/833`, `OGL-UK-3.0`, `OGL-CA`, `CC-BY-4.0-AU`, `PDL-1.0`.
- **Not yet named in ADR-0003, used because they are official and allow reuse:** `TW-OGDL-1.0`, an open licence that permits adaptation with attribution (clause 4(2) of the licence text at https://data.gov.tw/license, read 2026-11-02, declares it compatible with CC BY 4.0); `BOE-2024`, an open reuse licence under Ley 37/2007; and `UrhG-5`, under which statutes carry no copyright. They are recorded as BL-59 in `BACKLOG.md` so the owner can add them to the ADR-0003 data-terms list at the next gate. If the owner declines one, delete the documents with that key and rerun the validator.
- **Excluded:** sources ADR-0003 places in class (ii) or (iii) are not used: Singapore CSA (all rights reserved), China CAC (all rights reserved), Brazil ANPD (CC BY-ND 3.0), and flk.npc.gov.cn (`robots.txt` forbids automated collection). Hong Kong e-Legislation was considered for Chinese and left out because its `robots.txt` disallows all paths for generic agents. Brazil has no Portuguese document because planalto.gov.br did not answer from this session and LexML's terms were not found (R-03 C12); all Portuguese documents are EU texts.

## Exception: PRC statutory excerpts

Documents with key `CN-STATUTE` are five short passages of the Personal Information Protection Law of the PRC (Arts. 1, 4 para. 1, 40, 52, 66 para. 1), from 43 to 148 characters each. They are reused unchanged from `docs/research/R-08-data/passages-outputs.jsonl`, already in this repository. No open official source exists for mainland China. The CAC site is all rights reserved (R-03 C14) and the national database forbids crawling (C15). Statutory text is excluded from copyright by PRC Copyright Law Art. 5. The npc.gov.cn page the text came from is marked all rights reserved. That notice covers the site's own content, and none of that content is used. These five documents give the tests mainland-China coverage, a day-one jurisdiction. They are flagged for the owner in BL-59: deleting them leaves 21 Chinese documents, all from Taiwan.

## Sources

- **Federal Register:** `GET https://www.federalregister.gov/api/v1/documents.json` with term and type conditions; title and abstract. Document number and type are in the row.
- **EUR-Lex:** `GET http://publications.europa.eu/resource/celex/{CELEX}` with `Accept: application/xhtml+xml` and the three-letter `Accept-Language` (R-08 method, because eur-lex.europa.eu answers with a bot challenge). The URL recorded is the public EUR-Lex page for that language.
- **legislation.gov.uk:** `GET /{type}/{year}/{number}/{section}/{enacted|made}/data.xml` (CLML), using the original version of each provision.
- **Justice Laws (Canada):** XML files from `github.com/justicecanada/laws-lois-xml` at `0507465393c224c0491fc8c17c88340217acc656`; the URL recorded is the matching section page on laws-lois.justice.gc.ca.
- **Federal Register of Legislation (Australia):** the title's text page, then the epub document it embeds (`.../epub/OEBPS/document_1/document_1.html`), one section each.
- **gesetze-im-internet.de:** the single-paragraph pages `/{law}/__{n}.html`.
- **BOE:** `GET https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{id}/metadatos` and `/texto/bloque/{block}`, using the latest version of the block.
- **e-Gov:** `GET https://laws.e-gov.go.jp/api/2/laws?law_title=...` then `/api/2/law_data/{law_id}?law_full_text_format=xml`; one article from the main provisions.
- **全國法規資料庫:** `GET https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}` (allowed by robots.txt); one article. The URL recorded is the site's per-article address (`LawSingle.aspx`), which was not fetched.

URLs are unique per document. Where a site has no per-provision address (legislation.gov.au, npc.gov.cn), a fragment names the provision (`#s27`, `#art40`); e-Gov URLs use the site's own article anchors (`#Mp-At_26`).

## Documents

| # | Lang | Licence | Source | URL | Retrieved |
| --- | --- | --- | --- | --- | --- |
| 001 | en | `US-PD` | Federal Register API, document 2025-17359 (Rule; Defense Department, Defense Acquisition Regulations System) | <https://www.federalregister.gov/documents/2025/09/10/2025-17359/defense-federal-acquisition-regulation-supplement-assessing-contractor-implementation-of> | 2026-11-02 |
| 002 | en | `US-PD` | Federal Register API, document 2024-04752 (Rule; Defense Department, Office of the Secretary) | <https://www.federalregister.gov/documents/2024/03/12/2024-04752/department-of-defense-dod-defense-industrial-base-dib-cybersecurity-cs-activities> | 2026-11-02 |
| 003 | en | `US-PD` | Federal Register API, document 2025-00708 (Rule; Homeland Security Department, Coast Guard) | <https://www.federalregister.gov/documents/2025/01/17/2025-00708/cybersecurity-in-the-marine-transportation-system> | 2026-11-02 |
| 004 | en | `US-PD` | Federal Register API, document 2026-15601 (Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2026/07/31/2026-15601/modernization-of-the-nations-alerting-systems-protecting-the-nations-communications-systems-from> | 2026-11-02 |
| 005 | en | `US-PD` | Federal Register API, document 2023-03682 (Rule; National Credit Union Administration) | <https://www.federalregister.gov/documents/2023/03/01/2023-03682/cyber-incident-notification-requirements-for-federally-insured-credit-unions> | 2026-11-02 |
| 006 | en | `US-PD` | Federal Register API, document 2026-02948 (Proposed Rule; Homeland Security Department) | <https://www.federalregister.gov/documents/2026/02/13/2026-02948/cyber-incident-reporting-for-critical-infrastructure-act-circia-rulemaking-town-hall-meetings> | 2026-11-02 |
| 007 | en | `US-PD` | Federal Register API, document 2024-06526 (Proposed Rule; Homeland Security Department) | <https://www.federalregister.gov/documents/2024/04/04/2024-06526/cyber-incident-reporting-for-critical-infrastructure-act-circia-reporting-requirements> | 2026-11-02 |
| 008 | en | `US-PD` | Federal Register API, document 2023-21328 (Proposed Rule; Defense Department, General Services Administration, National Aeronautics and Space Administration) | <https://www.federalregister.gov/documents/2023/10/03/2023-21328/federal-acquisition-regulation-cyber-threat-and-incident-reporting-and-information-sharing> | 2026-11-02 |
| 009 | en | `US-PD` | Federal Register API, document 2024-21466 (Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2024/09/20/2024-21466/schools-and-libraries-cybersecurity-pilot-program> | 2026-11-02 |
| 010 | en | `US-PD` | Federal Register API, document 2024-14148 (Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2024/07/30/2024-14148/cybersecurity-labeling-for-internet-of-things> | 2026-11-02 |
| 011 | en | `US-PD` | Federal Register API, document 2024-22905 (Rule; Defense Department, Office of the Secretary) | <https://www.federalregister.gov/documents/2024/10/15/2024-22905/cybersecurity-maturity-model-certification-cmmc-program> | 2026-11-02 |
| 012 | en | `US-PD` | Federal Register API, document 2026-17894 (Notice; Homeland Security Department, Transportation Security Administration) | <https://www.federalregister.gov/documents/2026/09/01/2026-17894/revision-of-agency-information-collection-activity-under-omb-review-cybersecurity-measures-for> | 2026-11-02 |
| 013 | en | `US-PD` | Federal Register API, document 2026-10893 (Notice; Homeland Security Department) | <https://www.federalregister.gov/documents/2026/06/01/2026-10893/agency-information-collection-activities-state-and-local-cybersecurity-grant-program-slcgp> | 2026-11-02 |
| 014 | en | `US-PD` | Federal Register API, document 2025-11669 (Notice; Health and Human Services Department, Food and Drug Administration) | <https://www.federalregister.gov/documents/2025/06/27/2025-11669/cybersecurity-in-medical-devices-quality-system-considerations-and-content-of-premarket-submissions> | 2026-11-02 |
| 015 | en | `US-PD` | Federal Register API, document 2026-10779 (Notice; Commerce Department, National Institute of Standards and Technology) | <https://www.federalregister.gov/documents/2026/05/29/2026-10779/nist-artificial-intelligence-consortium> | 2026-11-02 |
| 016 | en | `US-PD` | Federal Register API, document 2026-13628 (Notice; Federal Trade Commission) | <https://www.federalregister.gov/documents/2026/07/07/2026-13628/policy-statement-concerning-the-suppression-of-accuracy-in-artificial-intelligence-systems> | 2026-11-02 |
| 017 | en | `US-PD` | Federal Register API, document 2026-00206 (Notice; Commerce Department, National Institute of Standards and Technology) | <https://www.federalregister.gov/documents/2026/01/08/2026-00206/request-for-information-regarding-security-considerations-for-artificial-intelligence-agents> | 2026-11-02 |
| 018 | en | `US-PD` | Federal Register API, document 2026-16371 (Notice; Commerce Department, National Institute of Standards and Technology) | <https://www.federalregister.gov/documents/2026/08/12/2026-16371/request-for-information-rfi-on-modernizing-the-national-vulnerability-database-in-the-age-of> | 2026-11-02 |
| 019 | en | `US-PD` | Federal Register API, document 2024-20529 (Proposed Rule; Commerce Department, Industry and Security Bureau) | <https://www.federalregister.gov/documents/2024/09/11/2024-20529/establishment-of-reporting-requirements-for-the-development-of-advanced-artificial-intelligence> | 2026-11-02 |
| 020 | en | `US-PD` | Federal Register API, document 2024-16977 (Proposed Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2024/08/05/2024-16977/disclosure-and-transparency-of-artificial-intelligence-generated-content-in-political-advertisements> | 2026-11-02 |
| 021 | en | `US-PD` | Federal Register API, document 2023-12925 (Rule; Commerce Department) | <https://www.federalregister.gov/documents/2023/06/16/2023-12925/securing-the-information-and-communications-technology-and-services-supply-chain-connected-software> | 2026-11-02 |
| 022 | en | `US-PD` | Federal Register API, document 2026-18535 (Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2026/09/11/2026-18535/protecting-against-national-security-threats-to-the-communications-supply-chain-through-the> | 2026-11-02 |
| 023 | en | `US-PD` | Federal Register API, document 2025-00592 (Rule; Commerce Department, Industry and Security Bureau) | <https://www.federalregister.gov/documents/2025/01/16/2025-00592/securing-the-information-and-communications-technology-and-services-supply-chain-connected-vehicles> | 2026-11-02 |
| 024 | en | `US-PD` | Federal Register API, document 2025-18394 (Rule; Energy Department, Federal Energy Regulatory Commission) | <https://www.federalregister.gov/documents/2025/09/23/2025-18394/supply-chain-risk-management-reliability-standards-revisions-equipment-and-services-produced-or> | 2026-11-02 |
| 025 | en | `US-PD` | Federal Register API, document 2024-31486 (Rule; Justice Department) | <https://www.federalregister.gov/documents/2025/01/08/2024-31486/preventing-access-to-us-sensitive-personal-data-and-government-related-data-by-countries-of-concern> | 2026-11-02 |
| 026 | en | `US-PD` | Federal Register API, document 2024-11116 (Rule; Securities and Exchange Commission) | <https://www.federalregister.gov/documents/2024/06/03/2024-11116/regulation-s-p-privacy-of-consumer-financial-information-and-safeguarding-customer-information> | 2026-11-02 |
| 027 | en | `US-PD` | Federal Register API, document 2024-23881 (Rule; Homeland Security Department) | <https://www.federalregister.gov/documents/2024/10/25/2024-23881/minimum-standards-for-drivers-licenses-and-identification-cards-acceptable-by-federal-agencies-for> | 2026-11-02 |
| 028 | en | `US-PD` | Federal Register API, document 2025-12309 (Rule; Energy Department, Federal Energy Regulatory Commission) | <https://www.federalregister.gov/documents/2025/07/02/2025-12309/critical-infrastructure-protection-reliability-standard-cip-015-1-cyber-security-internal-network> | 2026-11-02 |
| 029 | en | `US-PD` | Federal Register API, document 2025-17899 (Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2025/09/16/2025-17899/resilient-networks-concerning-disruptions-to-communications> | 2026-11-02 |
| 030 | en | `US-PD` | Federal Register API, document 2026-09822 (Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2026/05/15/2026-09822/promoting-the-integrity-and-security-of-telecommunications-certification-bodies-measurement> | 2026-11-02 |
| 031 | en | `US-PD` | Federal Register API, document 2024-30983 (Proposed Rule; Health and Human Services Department, Office of the Secretary) | <https://www.federalregister.gov/documents/2025/01/06/2024-30983/hipaa-security-rule-to-strengthen-the-cybersecurity-of-electronic-protected-health-information> | 2026-11-02 |
| 032 | en | `US-PD` | Federal Register API, document 2025-03718 (Proposed Rule; Federal Communications Commission) | <https://www.federalregister.gov/documents/2025/03/13/2025-03718/review-of-submarine-cable-landing-license-rules-and-procedures-to-assess-evolving-national-security> | 2026-11-02 |
| 033 | en | `US-PD` | Federal Register API, document 2024-24704 (Proposed Rule; Homeland Security Department, Transportation Security Administration) | <https://www.federalregister.gov/documents/2024/11/07/2024-24704/enhancing-surface-cyber-risk-management> | 2026-11-02 |
| 034 | en | `US-PD` | Federal Register API, document 2023-05766 (Proposed Rule; Securities and Exchange Commission) | <https://www.federalregister.gov/documents/2023/03/21/2023-05766/cybersecurity-risk-management-for-investment-advisers-registered-investment-companies-and-business> | 2026-11-02 |
| 035 | en | `OGL-UK-3.0` | legislation.gov.uk, uksi/2018/506/regulation/11/made | <https://www.legislation.gov.uk/uksi/2018/506/regulation/11> | 2026-11-02 |
| 036 | en | `OGL-UK-3.0` | legislation.gov.uk, ukpga/2018/12/section/67/enacted | <https://www.legislation.gov.uk/ukpga/2018/12/section/67> | 2026-11-02 |
| 037 | en | `OGL-UK-3.0` | legislation.gov.uk, ukpga/2022/46/section/1/enacted | <https://www.legislation.gov.uk/ukpga/2022/46/section/1> | 2026-11-02 |
| 038 | en | `OGL-UK-3.0` | legislation.gov.uk, uksi/2023/1007/schedule/1/made | <https://www.legislation.gov.uk/uksi/2023/1007/schedule/1> | 2026-11-02 |
| 039 | en | `OGL-UK-3.0` | legislation.gov.uk, ukpga/2021/31/section/1/enacted | <https://www.legislation.gov.uk/ukpga/2021/31/section/1> | 2026-11-02 |
| 040 | en | `OGL-UK-3.0` | legislation.gov.uk, uksi/2022/933/regulation/3/made | <https://www.legislation.gov.uk/uksi/2022/933/regulation/3> | 2026-11-02 |
| 041 | en | `OGL-UK-3.0` | legislation.gov.uk, ukpga/1990/18/section/1/enacted | <https://www.legislation.gov.uk/ukpga/1990/18/section/1> | 2026-11-02 |
| 042 | en | `OGL-UK-3.0` | legislation.gov.uk, uksi/2003/2426/regulation/5/made | <https://www.legislation.gov.uk/uksi/2003/2426/regulation/5> | 2026-11-02 |
| 043 | en | `OGL-UK-3.0` | legislation.gov.uk, ukpga/2021/25/section/1/enacted | <https://www.legislation.gov.uk/ukpga/2021/25/section/1> | 2026-11-02 |
| 044 | en | `OGL-UK-3.0` | legislation.gov.uk, ukpga/2023/50/section/1/enacted | <https://www.legislation.gov.uk/ukpga/2023/50/section/1> | 2026-11-02 |
| 045 | en | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), eng/acts/P-8.6.xml s. 3 | <https://laws-lois.justice.gc.ca/eng/acts/P-8.6/section-3.html> | 2026-11-02 |
| 046 | en | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), eng/acts/P-8.6.xml s. 10.1 | <https://laws-lois.justice.gc.ca/eng/acts/P-8.6/section-10.1.html> | 2026-11-02 |
| 047 | en | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), eng/regulations/SOR-2018-64.xml s. 2 | <https://laws-lois.justice.gc.ca/eng/regulations/SOR-2018-64/section-2.html> | 2026-11-02 |
| 048 | en | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), eng/acts/C-46.xml s. 342.1 | <https://laws-lois.justice.gc.ca/eng/acts/C-46/section-342.1.html> | 2026-11-02 |
| 049 | en | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), eng/acts/P-21.xml s. 2 | <https://laws-lois.justice.gc.ca/eng/acts/P-21/section-2.html> | 2026-11-02 |
| 050 | en | `CC-BY-4.0-AU` | Federal Register of Legislation, C2024A00098 s. 27 (https://www.legislation.gov.au/C2024A00098/asmade/2024-11-29/text/2/epub/OEBPS/document_1/document_1.html) | <https://www.legislation.gov.au/C2024A00098/latest/text#s27> | 2026-11-02 |
| 051 | en | `CC-BY-4.0-AU` | Federal Register of Legislation, C2024A00098 s. 14 (https://www.legislation.gov.au/C2024A00098/asmade/2024-11-29/text/2/epub/OEBPS/document_1/document_1.html) | <https://www.legislation.gov.au/C2024A00098/latest/text#s14> | 2026-11-02 |
| 052 | en | `CC-BY-4.0-AU` | Federal Register of Legislation, C2018A00029 s. 30BC (https://www.legislation.gov.au/C2018A00029/2026-06-04/2026-06-04/text/1/epub/OEBPS/document_1/document_1.html) | <https://www.legislation.gov.au/C2018A00029/latest/text#s30BC> | 2026-11-02 |
| 053 | en | `CC-BY-4.0-AU` | Federal Register of Legislation, C2018A00029 s. 30AH (https://www.legislation.gov.au/C2018A00029/2026-06-04/2026-06-04/text/1/epub/OEBPS/document_1/document_1.html) | <https://www.legislation.gov.au/C2018A00029/latest/text#s30AH> | 2026-11-02 |
| 054 | en | `CC-BY-4.0-AU` | Federal Register of Legislation, C2004A03712 s. 26WK (https://www.legislation.gov.au/C2004A03712/2026-06-04/2026-06-04/text/original/epub/OEBPS/document_1/document_1.html) | <https://www.legislation.gov.au/C2004A03712/latest/text#s26WK> | 2026-11-02 |
| 055 | en | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022L2555, Art. 23 | <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022L2555> | 2026-11-02 |
| 056 | en | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R2847, Art. 14 | <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R2847> | 2026-11-02 |
| 057 | en | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R1689, Art. 50 | <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689> | 2026-11-02 |
| 058 | en | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022R2554, Art. 19 | <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2554> | 2026-11-02 |
| 059 | en | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R2854, Art. 32 | <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R2854> | 2026-11-02 |
| 060 | en | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R1781, Art. 1 | <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R1781> | 2026-11-02 |
| 061 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32016R0679, Art. 33 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32016R0679> | 2026-11-02 |
| 062 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022L2555, Art. 23 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32022L2555> | 2026-11-02 |
| 063 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022R2554, Art. 19 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32022R2554> | 2026-11-02 |
| 064 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R1689, Art. 50 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32024R1689> | 2026-11-02 |
| 065 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R2847, Art. 14 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32024R2847> | 2026-11-02 |
| 066 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32019R0881, Art. 46 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32019R0881> | 2026-11-02 |
| 067 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R2854, Art. 32 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32023R2854> | 2026-11-02 |
| 068 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R1183, Art. 1 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32024R1183> | 2026-11-02 |
| 069 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32014R0910, Art. 19 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32014R0910> | 2026-11-02 |
| 070 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32002L0058, Art. 4 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32002L0058> | 2026-11-02 |
| 071 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022L2557, Art. 1 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32022L2557> | 2026-11-02 |
| 072 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32025R0038, Art. 1 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32025R0038> | 2026-11-02 |
| 073 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018L1972, Art. 40 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32018L1972> | 2026-11-02 |
| 074 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32016L0680, Art. 1 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32016L0680> | 2026-11-02 |
| 075 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018R1807, Art. 4 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32018R1807> | 2026-11-02 |
| 076 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022R0030, Art. 1 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32022R0030> | 2026-11-02 |
| 077 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R2690, Art. 3 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32024R2690> | 2026-11-02 |
| 078 | de | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32013L0040, Art. 3 | <https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32013L0040> | 2026-11-02 |
| 079 | de | `UrhG-5` | gesetze-im-internet.de, bsig_2025/__1 | <https://www.gesetze-im-internet.de/bsig_2025/__1.html> | 2026-11-02 |
| 080 | de | `UrhG-5` | gesetze-im-internet.de, bsig_2025/__32 | <https://www.gesetze-im-internet.de/bsig_2025/__32.html> | 2026-11-02 |
| 081 | de | `UrhG-5` | gesetze-im-internet.de, bsig_2025/__30 | <https://www.gesetze-im-internet.de/bsig_2025/__30.html> | 2026-11-02 |
| 082 | de | `UrhG-5` | gesetze-im-internet.de, ttdsg/__25 | <https://www.gesetze-im-internet.de/ttdsg/__25.html> | 2026-11-02 |
| 083 | fr | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), fra/lois/P-8.6.xml s. 3 | <https://laws-lois.justice.gc.ca/fra/lois/P-8.6/article-3.html> | 2026-11-02 |
| 084 | fr | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), fra/lois/P-8.6.xml s. 10.1 | <https://laws-lois.justice.gc.ca/fra/lois/P-8.6/article-10.1.html> | 2026-11-02 |
| 085 | fr | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), fra/reglements/DORS-2018-64.xml s. 2 | <https://laws-lois.justice.gc.ca/fra/reglements/DORS-2018-64/article-2.html> | 2026-11-02 |
| 086 | fr | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), fra/lois/C-46.xml s. 342.1 | <https://laws-lois.justice.gc.ca/fra/lois/C-46/article-342.1.html> | 2026-11-02 |
| 087 | fr | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), fra/lois/P-21.xml s. 2 | <https://laws-lois.justice.gc.ca/fra/lois/P-21/article-2.html> | 2026-11-02 |
| 088 | fr | `OGL-CA` | Justice Laws XML (github.com/justicecanada/laws-lois-xml @0507465), fra/reglements/DORS-2005-30.xml s. 2 | <https://laws-lois.justice.gc.ca/fra/reglements/DORS-2005-30/article-2.html> | 2026-11-02 |
| 089 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R2854, Art. 32 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32023R2854> | 2026-11-02 |
| 090 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R1183, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32024R1183> | 2026-11-02 |
| 091 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32014R0910, Art. 19 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32014R0910> | 2026-11-02 |
| 092 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32002L0058, Art. 4 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32002L0058> | 2026-11-02 |
| 093 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022L2557, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32022L2557> | 2026-11-02 |
| 094 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32025R0038, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32025R0038> | 2026-11-02 |
| 095 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018L1972, Art. 40 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32018L1972> | 2026-11-02 |
| 096 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32016L0680, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32016L0680> | 2026-11-02 |
| 097 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018R1807, Art. 4 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32018R1807> | 2026-11-02 |
| 098 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022R0030, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32022R0030> | 2026-11-02 |
| 099 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R2690, Art. 3 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32024R2690> | 2026-11-02 |
| 100 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32013L0040, Art. 3 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32013L0040> | 2026-11-02 |
| 101 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R1781, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32023R1781> | 2026-11-02 |
| 102 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32019R0452, Art. 4 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32019R0452> | 2026-11-02 |
| 103 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023D1795, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32023D1795> | 2026-11-02 |
| 104 | fr | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32021D0914, Art. 1 | <https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32021D0914> | 2026-11-02 |
| 105 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32014R0910, Art. 19 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32014R0910> | 2026-11-02 |
| 106 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32002L0058, Art. 4 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32002L0058> | 2026-11-02 |
| 107 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022L2557, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32022L2557> | 2026-11-02 |
| 108 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32025R0038, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32025R0038> | 2026-11-02 |
| 109 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018L1972, Art. 40 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32018L1972> | 2026-11-02 |
| 110 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32016L0680, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32016L0680> | 2026-11-02 |
| 111 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018R1807, Art. 4 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32018R1807> | 2026-11-02 |
| 112 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022R0030, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32022R0030> | 2026-11-02 |
| 113 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R2690, Art. 3 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32024R2690> | 2026-11-02 |
| 114 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32013L0040, Art. 3 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32013L0040> | 2026-11-02 |
| 115 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R1781, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32023R1781> | 2026-11-02 |
| 116 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32019R0452, Art. 4 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32019R0452> | 2026-11-02 |
| 117 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023D1795, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32023D1795> | 2026-11-02 |
| 118 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32021D0914, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32021D0914> | 2026-11-02 |
| 119 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32025R0327, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32025R0327> | 2026-11-02 |
| 120 | es | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024L2853, Art. 1 | <https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32024L2853> | 2026-11-02 |
| 121 | es | `BOE-2024` | BOE datos abiertos, legislación consolidada BOE-A-2018-12257, bloque a1-11 | <https://www.boe.es/buscar/act.php?id=BOE-A-2018-12257> | 2026-11-02 |
| 122 | es | `BOE-2024` | BOE datos abiertos, legislación consolidada BOE-A-2018-16673, bloque a1 | <https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673> | 2026-11-02 |
| 123 | es | `BOE-2024` | BOE datos abiertos, legislación consolidada BOE-A-2022-7191, bloque a1 | <https://www.boe.es/buscar/act.php?id=BOE-A-2022-7191> | 2026-11-02 |
| 124 | es | `BOE-2024` | BOE datos abiertos, legislación consolidada BOE-A-2020-14046, bloque a1 | <https://www.boe.es/buscar/act.php?id=BOE-A-2020-14046> | 2026-11-02 |
| 125 | es | `BOE-2024` | BOE datos abiertos, legislación consolidada BOE-A-2022-10757, bloque a6-2 | <https://www.boe.es/buscar/act.php?id=BOE-A-2022-10757> | 2026-11-02 |
| 126 | es | `BOE-2024` | BOE datos abiertos, legislación consolidada BOE-A-2021-1192, bloque a1 | <https://www.boe.es/buscar/act.php?id=BOE-A-2021-1192> | 2026-11-02 |
| 127 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32016R0679, Art. 33 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32016R0679> | 2026-11-02 |
| 128 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022L2555, Art. 23 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32022L2555> | 2026-11-02 |
| 129 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022R2554, Art. 19 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32022R2554> | 2026-11-02 |
| 130 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R1689, Art. 50 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32024R1689> | 2026-11-02 |
| 131 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R2847, Art. 14 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32024R2847> | 2026-11-02 |
| 132 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32019R0881, Art. 46 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32019R0881> | 2026-11-02 |
| 133 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R2854, Art. 32 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32023R2854> | 2026-11-02 |
| 134 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R1183, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32024R1183> | 2026-11-02 |
| 135 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32014R0910, Art. 19 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32014R0910> | 2026-11-02 |
| 136 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32002L0058, Art. 4 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32002L0058> | 2026-11-02 |
| 137 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022L2557, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32022L2557> | 2026-11-02 |
| 138 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32025R0038, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32025R0038> | 2026-11-02 |
| 139 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018L1972, Art. 40 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32018L1972> | 2026-11-02 |
| 140 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32016L0680, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32016L0680> | 2026-11-02 |
| 141 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32018R1807, Art. 4 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32018R1807> | 2026-11-02 |
| 142 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32022R0030, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32022R0030> | 2026-11-02 |
| 143 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32024R2690, Art. 3 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32024R2690> | 2026-11-02 |
| 144 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023R1781, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32023R1781> | 2026-11-02 |
| 145 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32019R0452, Art. 4 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32019R0452> | 2026-11-02 |
| 146 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32023D1795, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32023D1795> | 2026-11-02 |
| 147 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32021D0914, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32021D0914> | 2026-11-02 |
| 148 | pt | `EU-2011/833` | EUR-Lex (Publications Office Cellar), CELEX 32025R0327, Art. 1 | <https://eur-lex.europa.eu/legal-content/PT/TXT/?uri=CELEX:32025R0327> | 2026-11-02 |
| 149 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 426AC1000000104, revision 426AC1000000104_20261001_507AC0000000043, Art. 1 | <https://laws.e-gov.go.jp/law/426AC1000000104#Mp-At_1> | 2026-11-02 |
| 150 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 426AC1000000104, revision 426AC1000000104_20261001_507AC0000000043, Art. 2 | <https://laws.e-gov.go.jp/law/426AC1000000104#Mp-At_2> | 2026-11-02 |
| 151 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 415AC0000000057, revision 415AC0000000057_20261102_508AC0000000062, Art. 1 | <https://laws.e-gov.go.jp/law/415AC0000000057#Mp-At_1> | 2026-11-02 |
| 152 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 415AC0000000057, revision 415AC0000000057_20261102_508AC0000000062, Art. 26 | <https://laws.e-gov.go.jp/law/415AC0000000057#Mp-At_26> | 2026-11-02 |
| 153 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 415AC0000000057, revision 415AC0000000057_20261102_508AC0000000062, Art. 28 | <https://laws.e-gov.go.jp/law/415AC0000000057#Mp-At_28> | 2026-11-02 |
| 154 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 411AC0000000128, revision 411AC0000000128_20250601_504AC0000000068, Art. 1 | <https://laws.e-gov.go.jp/law/411AC0000000128#Mp-At_1> | 2026-11-02 |
| 155 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 411AC0000000128, revision 411AC0000000128_20250601_504AC0000000068, Art. 8 | <https://laws.e-gov.go.jp/law/411AC0000000128#Mp-At_8> | 2026-11-02 |
| 156 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 412AC0000000102, revision 412AC0000000102_20250601_504AC0000000068, Art. 1 | <https://laws.e-gov.go.jp/law/412AC0000000102#Mp-At_1> | 2026-11-02 |
| 157 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 359AC0000000086, revision 359AC0000000086_20260527_507AC0000000046, Art. 4 | <https://laws.e-gov.go.jp/law/359AC0000000086#Mp-At_4> | 2026-11-02 |
| 158 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 359AC0000000086, revision 359AC0000000086_20260527_507AC0000000046, Art. 28 | <https://laws.e-gov.go.jp/law/359AC0000000086#Mp-At_28> | 2026-11-02 |
| 159 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 504AC0000000043, revision 504AC0000000043_20260918_508AC0000000038, Art. 1 | <https://laws.e-gov.go.jp/law/504AC0000000043#Mp-At_1> | 2026-11-02 |
| 160 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 504AC0000000043, revision 504AC0000000043_20260918_508AC0000000038, Art. 50 | <https://laws.e-gov.go.jp/law/504AC0000000043#Mp-At_50> | 2026-11-02 |
| 161 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 507AC0000000042, revision 507AC0000000042_20261001_000000000000000, Art. 1 | <https://laws.e-gov.go.jp/law/507AC0000000042#Mp-At_1> | 2026-11-02 |
| 162 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 507AC0000000053, revision 507AC0000000053_20250901_000000000000000, Art. 1 | <https://laws.e-gov.go.jp/law/507AC0000000053#Mp-At_1> | 2026-11-02 |
| 163 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 425AC0000000027, revision 425AC0000000027_20261001_507AC0000000087, Art. 1 | <https://laws.e-gov.go.jp/law/425AC0000000027#Mp-At_1> | 2026-11-02 |
| 164 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 414AC0100000026, revision 414AC0100000026_20250601_504AC0000000068, Art. 1 | <https://laws.e-gov.go.jp/law/414AC0100000026#Mp-At_1> | 2026-11-02 |
| 165 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 413AC0000000137, revision 413AC0000000137_20260717_508AC1000000058, Art. 1 | <https://laws.e-gov.go.jp/law/413AC0000000137#Mp-At_1> | 2026-11-02 |
| 166 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 502AC0000000038, revision 502AC0000000038_20260521_505AC0000000063, Art. 1 | <https://laws.e-gov.go.jp/law/502AC0000000038#Mp-At_1> | 2026-11-02 |
| 167 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 336AC0000000159, revision 336AC0000000159_20250601_504AC0000000068, Art. 35_16 | <https://laws.e-gov.go.jp/law/336AC0000000159#Mp-At_35_16> | 2026-11-02 |
| 168 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 428M60020000003, revision 428M60020000003_20260614_508M60020000002, Art. 7 | <https://laws.e-gov.go.jp/law/428M60020000003#Mp-At_7> | 2026-11-02 |
| 169 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 414AC0000000153, revision 414AC0000000153_20260614_506AC0000000059, Art. 1 | <https://laws.e-gov.go.jp/law/414AC0000000153#Mp-At_1> | 2026-11-02 |
| 170 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 345AC0000000090, revision 345AC0000000090_20261001_507AC0000000043, Art. 1 | <https://laws.e-gov.go.jp/law/345AC0000000090#Mp-At_1> | 2026-11-02 |
| 171 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 429AC0000000028, revision 429AC0000000028_20261001_507AC0000000087, Art. 1 | <https://laws.e-gov.go.jp/law/429AC0000000028#Mp-At_1> | 2026-11-02 |
| 172 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 421AC0000000059, revision 421AC0000000059_20260812_508AC0000000064, Art. 63_8 | <https://laws.e-gov.go.jp/law/421AC0000000059#Mp-At_63_8> | 2026-11-02 |
| 173 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 429AC0000000064, revision 429AC0000000064_20260527_507AC0000000046, Art. 1 | <https://laws.e-gov.go.jp/law/429AC0000000064#Mp-At_1> | 2026-11-02 |
| 174 | ja | `PDL-1.0` | e-Gov Law API v2, law_id 507AC0000000042, revision 507AC0000000042_20261001_000000000000000, Art. 2 | <https://laws.e-gov.go.jp/law/507AC0000000042#Mp-At_2> | 2026-11-02 |
| 175 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030297, 第 1 條 (fetched from LawAll.aspx?pcode=A0030297) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030297&flno=1> | 2026-11-02 |
| 176 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030297, 第 10 條 (fetched from LawAll.aspx?pcode=A0030297) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030297&flno=10> | 2026-11-02 |
| 177 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030297, 第 11 條 (fetched from LawAll.aspx?pcode=A0030297) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030297&flno=11> | 2026-11-02 |
| 178 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030297, 第 17 條 (fetched from LawAll.aspx?pcode=A0030297) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030297&flno=17> | 2026-11-02 |
| 179 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030297, 第 20 條 (fetched from LawAll.aspx?pcode=A0030297) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030297&flno=20> | 2026-11-02 |
| 180 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030297, 第 24 條 (fetched from LawAll.aspx?pcode=A0030297) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030297&flno=24> | 2026-11-02 |
| 181 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030297, 第 33 條 (fetched from LawAll.aspx?pcode=A0030297) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030297&flno=33> | 2026-11-02 |
| 182 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030305, 第 2 條 (fetched from LawAll.aspx?pcode=A0030305) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030305&flno=2> | 2026-11-02 |
| 183 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030305, 第 6 條 (fetched from LawAll.aspx?pcode=A0030305) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030305&flno=6> | 2026-11-02 |
| 184 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode A0030307, 第 2 條 (fetched from LawAll.aspx?pcode=A0030307) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030307&flno=2> | 2026-11-02 |
| 185 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode I0050021, 第 1 條 (fetched from LawAll.aspx?pcode=I0050021) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=1> | 2026-11-02 |
| 186 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode I0050021, 第 12 條 (fetched from LawAll.aspx?pcode=I0050021) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=12> | 2026-11-02 |
| 187 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode I0050021, 第 21 條 (fetched from LawAll.aspx?pcode=I0050021) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=21> | 2026-11-02 |
| 188 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode I0050021, 第 20-1 條 (fetched from LawAll.aspx?pcode=I0050021) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=20-1> | 2026-11-02 |
| 189 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode I0050022, 第 12 條 (fetched from LawAll.aspx?pcode=I0050022) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050022&flno=12> | 2026-11-02 |
| 190 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode J0080037, 第 1 條 (fetched from LawAll.aspx?pcode=J0080037) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=J0080037&flno=1> | 2026-11-02 |
| 191 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode K0060111, 第 42 條 (fetched from LawAll.aspx?pcode=K0060111) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=K0060111&flno=42> | 2026-11-02 |
| 192 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode K0060111, 第 43 條 (fetched from LawAll.aspx?pcode=K0060111) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=K0060111&flno=43> | 2026-11-02 |
| 193 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode K0060044, 第 1 條 (fetched from LawAll.aspx?pcode=K0060044) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=K0060044&flno=1> | 2026-11-02 |
| 194 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode C0000001, 第 358 條 (fetched from LawAll.aspx?pcode=C0000001) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=C0000001&flno=358> | 2026-11-02 |
| 195 | zh | `TW-OGDL-1.0` | 全國法規資料庫, pcode C0000001, 第 360 條 (fetched from LawAll.aspx?pcode=C0000001) | <https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=C0000001&flno=360> | 2026-11-02 |
| 196 | zh | `CN-STATUTE` | Personal Information Protection Law of the PRC (2021), Art. 1; text reused from docs/research/R-08-data/passages-outputs.jsonl (zh-1, retrieved 2026-11-01) | <http://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html#art1> | 2026-11-01 |
| 197 | zh | `CN-STATUTE` | Personal Information Protection Law of the PRC (2021), Art. 4 para. 1; text reused from docs/research/R-08-data/passages-outputs.jsonl (zh-2, retrieved 2026-11-01) | <http://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html#art4> | 2026-11-01 |
| 198 | zh | `CN-STATUTE` | Personal Information Protection Law of the PRC (2021), Art. 40; text reused from docs/research/R-08-data/passages-outputs.jsonl (zh-3, retrieved 2026-11-01) | <http://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html#art40> | 2026-11-01 |
| 199 | zh | `CN-STATUTE` | Personal Information Protection Law of the PRC (2021), Art. 52; text reused from docs/research/R-08-data/passages-outputs.jsonl (zh-4, retrieved 2026-11-01) | <http://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html#art52> | 2026-11-01 |
| 200 | zh | `CN-STATUTE` | Personal Information Protection Law of the PRC (2021), Art. 66 para. 1; text reused from docs/research/R-08-data/passages-outputs.jsonl (zh-5, retrieved 2026-11-01) | <http://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html#art66> | 2026-11-01 |
