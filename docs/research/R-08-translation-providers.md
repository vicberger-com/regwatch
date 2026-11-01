# R-08: Translation providers for the M4 `Translator`

**Issue:** #11 · **Module:** M4 · **Requirements:** REQ-02 (also REQ-19, REQ-20 for licenses) · **Backlog:** BL-09 · **Date:** 2026-11-01
**Policy:** `docs/03-architecture.md` 3.5 · **Register:** 3.6 · **Protocol:** 3.8 · **Data handling:** `docs/08-security-compliance.md` 8.4
**Evidence:** `docs/research/R-08-data/` (passages, both providers' outputs, harness scripts). Model files and raw logs are not committed.

## Question

Which translation providers should the M4 `Translator` ship with at launch, and what is the default? The owner wants foreign-language content translated to English, with a setting to choose the provider (section 2.4, answer 5).

## Answer

1. **Launch providers:** `libretranslate` (the official image, run unmodified as a separate service) and `http` (a hosted API selected by key). `argos` stays in the settings enum, but no in-process Argos provider ships at launch (F1, F2; BL-40).
2. **Default when an admin turns on `translation.enabled`:** `libretranslate`. The contract default `translation.provider: none` stays unchanged, so translation remains opt-in.
3. **`translation.scope` default:** `titles_summaries` (unchanged). Full text is an opt-in per source.
4. **Languages:** de, fr, es and pt are adequate for titles and summaries, with term errors. zh is usable only for triage. **ja is not adequate** (3 of 15 adequacy points, with omissions and hallucination), so Japanese sources should be routed to a hosted provider through the per-source override once a data-processing basis is recorded (8.4). Otherwise ja output is shown with a "machine translation, low confidence" marker.
5. **Licensing blockers for local models:** the Argos de 1.3 and ja 1.1 packages carry no license statement (F3). Japanese is a day-one jurisdiction, so this needs an owner decision or a replacement model (BL-42).
6. **Load at about 200 non-English items a day** (assumed at 700 characters of title and summary per item): about 7 minutes of CPU a day on LibreTranslate, with a worst case of about 34 minutes if every item were Chinese on in-process Argos. Full text at an assumed 15,000 characters per item would take about 2.4 hours a day. See "Expected load".

## Method

- **Machine:** cloud container, 4 vCPU, 15 GiB RAM, no GPU, Docker 29.9.2. CPU only throughout (`ARGOS_DEVICE_TYPE=cpu`; the LibreTranslate image is the CPU build).
- **Argos Translate:** run in-process through the Python API, at 1.11.0 and at 1.10.0, in uv virtual environments using CPU-only torch. One fresh process per language. Each process loads the model, runs one warm-up call, then times each passage with `time.perf_counter`. Peak memory is `ru_maxrss` for that process.
- **LibreTranslate:** `libretranslate/libretranslate:latest`, which resolved to image `sha256:cf85439147da…6efb007` (created 2026-10-26, `/app/VERSION` 1.9.6). It was run unmodified with `LT_LOAD_ONLY=en,zh,ja,de,fr,es,pt`. Only proxy and CA settings were passed, as environment variables and a read-only volume. It was measured twice: once with the default 4 gunicorn workers and once with `LT_THREADS=1`. The client sent eight warm-up calls per language, then timed `POST /translate` one call at a time. Peak memory is the maximum of `docker stats` samples taken about once a second, so it can miss short spikes.
- **Inputs:** each passage was translated whole ("full"). For EU passages the article title was also translated alone ("title"), to approximate the `titles_summaries` scope.
- **Outputs:** Argos 1.10.0 and 1.11.0 produced byte-identical outputs on all 50 inputs. LibreTranslate with 1 worker and with 4 workers also produced identical outputs on all 50. Each provider's columns below therefore cover both of its runs.

## Passages

There are 30 passages, five per language. Full text, outputs and references are in `R-08-data/passages-outputs.jsonl`.

| IDs | Language | Source (official) | Reuse terms | English reference |
| --- | --- | --- | --- | --- |
| zh-1..5 | zh | Personal Information Protection Law of the PRC, Arts. 1, 4 (para. 1), 40, 52, 66 (para. 1); npc.gov.cn (URL in data file) | Statutory text is excluded from copyright (PRC Copyright Law Art. 5) | NPC English translation ("for reference only"; the site is marked All Rights Reserved). Used for scoring only; the text is not committed. |
| ja-1..5 | ja | Act on the Protection of Personal Information (Act No. 57 of 2003), Arts. 1, 23, 26(1), 28(1), 148(1); Japanese text as paired by the Japanese Law Translation (JLT) database, version Act No. 37 of 2021; authoritative source laws.e-gov.go.jp | Statutory text is excluded from copyright (Japan Copyright Act Art. 13) | JLT English (Ministry of Justice). It is not an official text, and the site is marked All Rights Reserved. Used for scoring only; the text is not committed. |
| de-1..5 | de | GDPR Art. 33(1); NIS2 Art. 23(1); DORA Art. 19(1); AI Act Art. 50(1); CRA Art. 14(1) | EUR-Lex: © European Union, reuse authorised with acknowledgement (Decision 2011/833/EU) | Official English language version, equally authentic |
| fr-1..5 | fr | GDPR Art. 34(1); NIS2 Art. 21(1); DORA Art. 28(1); AI Act Art. 4; CRA Art. 13(1) | as above | as above |
| es-1..5 | es | GDPR Art. 25(1); NIS2 Art. 20(1); DORA Art. 5(1); AI Act Art. 73(1); CRA Art. 13(2) | as above | as above |
| pt-1..5 | pt | GDPR Art. 44; NIS2 Art. 32(1); DORA Art. 26(1); AI Act Art. 99(1); CRA Art. 64(1) | as above | as above |

The EU texts were fetched from the Publications Office Cellar (`http://publications.europa.eu/resource/celex/<CELEX>` with `Accept-Language`) because eur-lex.europa.eu answered with a bot challenge. All 30 passages have a reference. Passages range from 43 to 898 characters, 12,521 characters in total.

## Results

Times are warm seconds per passage. Argos ran in-process (1.10.0; 1.11.0 is within 0.37 s of it on every passage). LibreTranslate (LT) ran with 1 worker. chrF is sentence-level chrF2 (sacrebleu 2.6.0) against the reference. Adequacy is my 0 to 3 judgement (method below); "1 / 2" means Argos / LT where their outputs differ.

| ID | Chars | Argos s | LT s | Title s (Argos / LT) | chrF Argos | chrF LT | Adequacy | Key errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| de-1 | 618 | 2.06 | 0.76 | 0.29 / 0.09 | 74.1 | 74.1 | 3 | none material. "Article 51" is copied faithfully from the German text, where the English text says 55. |
| de-2 | 898 | 3.53 | 1.21 | 0.08 / 0.04 | 73.6 | 73.6 | 3 | "security incident" for "incident" |
| de-3 | 229 | 0.73 | 0.22 | 0.40 / 0.15 | 72.5 | 72.5 | 1 | cross-references swapped (Article 46 and paragraph 4); "serious" for the defined term "major" |
| de-4 | 822 | 2.93 | 1.08 | 0.32 / 0.11 | 81.1 | 81.1 | 2 | "operators" for the defined term "deployers" |
| de-5 | 391 | 1.73 | 0.63 | 0.20 / 0.08 | 78.3 | 78.3 | 2 | "digital element product" |
| fr-1 | 377 | 0.95 | 0.46 | 0.27 / 0.12 | 70.8 | 70.8 | 2 | "as soon as possible" for "without undue delay" (a changed legal standard) |
| fr-2 | 566 | 1.47 | 0.66 | 0.14 / 0.05 | 80.3 | 80.3 | 3 | none material |
| fr-3 | 283 | 0.86 | 0.44 | 0.07 / 0.03 | 82.2 | 82.2 | 3 | paraphrase of "ICT third-party risk" |
| fr-4 | 631 | 1.93 | 0.89 | 0.12 / 0.06 | 8.0 | 8.2 | 0 | **silent truncation** after "Providers and deployers of d" (F5); title "Mastery of AI" for "AI literacy" |
| fr-5 | 285 | 0.87 | 0.39 | 0.13 / 0.06 | 95.0 | 95.0 | 3 | none |
| es-1 | 801 | 2.41 | 5.94 | 0.18 / 0.37 | 66.6 | 70.2 | 2 | "treatment" for "processing"; "state of the technique" |
| es-2 | 365 | 0.79 | 2.02 | 0.06 / 0.12 | 50.3 | 73.2 | 1 / 2 | Argos **omits** "cybersecurity risk-management measures"; both use "key" for the defined term "essential" |
| es-3 | 301 | 1.02 | 1.62 | 0.09 / 0.18 | 68.2 | 81.4 | 2 | "financial institutions" for "financial entities" |
| es-4 | 276 | 0.71 | 1.47 | 0.10 / 0.17 | 84.4 | 80.3 | 2 | Argos "A system" and LT "IA systems" for "AI systems" |
| es-5 | 579 | 1.68 | 3.46 | 0.10 / 0.19 | 77.1 | 81.3 | 2 | "cyber-safety" (Argos); "digital element product" (LT) |
| pt-1 | 770 | 2.44 | 1.19 | 0.12 / 0.07 | 80.8 | 80.8 | 3 | none material |
| pt-2 | 341 | 0.95 | 0.41 | 0.23 / 0.09 | 86.3 | 86.3 | 3 | none |
| pt-3 | 588 | 1.83 | 0.87 | 0.29 / 0.15 | 78.1 | 78.1 | 2 | "TLPT-based tools" (attached to the wrong noun); broken punctuation in the cross-reference |
| pt-4 | 706 | 2.56 | 1.01 | 0.09 / 0.06 | 86.0 | 86.0 | 3 | none material |
| pt-5 | 417 | 1.61 | 0.57 | 0.00 / 0.00 | 90.3 | 90.3 | 3 | none |
| zh-1 | 43 | 0.82 | 0.49 | n/a | 64.8 | 64.4 | 3 | none material |
| zh-2 | 51 | 0.58 | 0.28 | n/a | 67.4 | 66.8 | 2 | awkward but complete definition |
| zh-3 | 127 | 1.57 | 0.87 | n/a | 45.0 | 45.0 | 1 | 国家网信部门 (national cyberspace department) becomes "national web services" / "National Networking Service"; the export condition is garbled |
| zh-4 | 66 | 0.94 | 0.46 | n/a | 57.3 | 57.2 | 1 | same wrong authority |
| zh-5 | 148 | 2.48 | 1.47 | n/a | 57.1 | 57.1 | 1 | 元 (yuan) becomes "dollars"; "application" misread; the order list is flattened |
| ja-1 | 320 | 1.73 | 0.86 | n/a | 29.6 | 29.6 | 0 | about half the purpose clause **omitted**; "we establish" is hallucinated |
| ja-2 | 75 | 0.69 | 0.30 | n/a | 62.3 | 62.2 | 2 | "by the Company" is **hallucinated**; the duty-holder is lost |
| ja-3 | 296 | 2.62 | 1.11 | n/a | 55.4 | 55.4 | 1 | broken fragments ("in。 with"); "Committee" for "Commission" |
| ja-4 | 405 | 4.27 | 1.75 | n/a | 52.9 | 52.8 | 0 | garbled; the consent requirement is lost |
| ja-5 | 746 | 7.88 | 3.59 | n/a | 29.9 | 29.9 | 0 | garbled list of cross-references; recommendation and order powers lost |

**Totals by language** (adequacy out of 15; corpus chrF, Argos / LT): zh 8 (55.2 / 55.0); ja 3 (40.1 / 40.1); de 11 (76.3 / 76.3); fr 11 (65.0 / 65.0); es 9 / 10 (69.1 / 76.0); pt 14 (83.7 / 83.7).

| Measure | Argos 1.11.0 | Argos 1.10.0 | LT 1.9.6, 4 workers | LT 1.9.6, 1 worker |
| --- | --- | --- | --- | --- |
| Total time, 30 full passages (12,521 chars) | 58.0 s | 56.7 s | 41.6 s | 36.5 s |
| Throughput, all / zh / ja / EU languages (chars per second) | 216 / 68 / 106 / 299 | 221 / 68 / 107 / 310 | 301 / 130 / 249 / 332 | 343 / 122 / 242 / 405 |
| Median / maximum per passage | 1.71 / 7.89 s | 1.64 / 7.88 s | 0.91 / 9.39 s | 0.87 / 5.94 s |
| Median / maximum per title (20 EU titles) | 0.13 / 0.43 s | 0.12 / 0.40 s | 0.12 / 1.59 s | 0.09 / 0.37 s |
| Load and first call | 5.2 to 8.6 s per language | 3.6 to 5.6 s (zh 23.4 s, including the spaCy model download) | first call 0.2 to 3.2 s per worker per language | 0.3 to 3.1 s per language |
| Peak memory | 576 to 750 MB per one-language process | 592 to 819 MB | 5.9 GiB (sampled) | 1.5 GiB (sampled) |
| Download size | zh 74.5 MB, ja 117.2 MB, de 150.5 MB, fr 66.6 MB, es 285.2 MB, pt 69.4 MB: 763.4 MB for the six xx→en packages | same | image 1,016.6 MB plus models fetched at first start: 14 packages (both directions), 1.66 GB on disk | same |

LibreTranslate is faster than in-process Argos on the same model files. Its bundled fork, `argos-translate-lt` 1.12.1, depends on `minisbd` and not on Stanza for sentence splitting. Outputs differ only in es (a different sentence split, which scored better) and in a trailing "。" that LT appends to zh and ja output.

## Adequacy method

- **Manual rubric (primary):**
  - 3: all legal content kept and defined terms correct.
  - 2: meaning kept, but a defined term or the register is wrong.
  - 1: an obligation, actor, authority, number or condition is lost or wrong.
  - 0: unusable, with a large omission, garbling or hallucination.

  I read each output against the reference and the source, and checked defined terms of the instrument (for example "deployer", "essential entity", "major ICT-related incident") and named authorities.
- **chrF2 (automatic):** a character n-gram F-score against the single reference. It is robust to inflection, rewards overlap of surface form, and flags gross failures well (fr-4 scored 8.0; ja-1 and ja-5 scored about 30).
- **What chrF does not show:** it does not show whether a legal term is right. Swapping "deployers" for "operators", or "yuan" for "dollars", costs a few points while changing the legal meaning, so de-3 (adequacy 1) scores 72.5. It is also not comparable across languages: zh and ja references are freer translations, so their scores run lower. BLEU was computed as well (see `score.py`) but is not reported per passage, because it is unstable on single sentences.
- **Contamination caveat:** the OPUS training corpora include EU legislation (DGT, EUR-Lex, Europarl), so the EU-passage scores may overstate quality on national sources that read less like EU text.
- **Single reviewer:** one reviewer, not a bilingual lawyer. Treat the adequacy scores as indicative.

## License findings

Policy results follow 3.5. Code licenses were read from the LICENSE file at the commit shown. Model terms were read from each package's own `README.md` and `metadata.json`, which are the only license statements the packages carry. The Argos package index (`argospm-index`, MIT or CC0, HEAD `ff90de6`) has no license field for any package.

| Component | Version / commit | License (as read) | Policy result |
| --- | --- | --- | --- |
| Argos Translate | v1.11.0, `63b84ecb46c7`; v1.10.0, `561369af792b` | MIT (LICENSE) | allowed, but see F1 and F2 |
| minisbd (required by Argos 1.11.0) | v0.9.5, `ecd822577296` | AGPL-3.0 (LICENSE) | **prohibited in bundled code (F1)** |
| spaCy `xx_sent_ud_sm` 3.8.0 (Argos 1.10.0 downloads it at import) | model `meta.json` | CC BY-SA 3.0 (UD v2.8 treebanks) | **not on the allow list; review (F2)** |
| Stanza tokenizer models inside each package | Stanza v1.10.1, `af3d42b70ef2`, Apache-2.0 (code) | model license not stated; trained on UD treebanks | review (F4) |
| LibreTranslate | v1.9.6, `497f6c678bdb`; `/app/LICENSE` in the image | AGPL-3.0 | service boundary only, unmodified |
| argos-translate-lt (inside the LT image) | 1.12.1 | MIT (bundled licence file) | inside the AGPL service; not our code |
| Argos zh→en 1.9, fr→en 1.9, es→en 1.9, pt→en 1.9 | package README | "derived from OPUS-MT … licensed CC-BY 4.0" (the Helsinki-NLP zh-en model card also says cc-by-4.0) | allowed as data, **with attribution** |
| Argos de→en 1.3 | package README is a title only | **none stated** | **unverified: fails (F3)** |
| Argos ja→en 1.1 | package README credits OPUS, CCAligned, WikiMatrix, OpenSubtitles and "dictionary data from Wiktionary" | **none stated**; Wiktionary content is CC BY-SA | **unverified: fails (F3)** |

- **F1:** argostranslate 1.11.0 lists `minisbd` in `requirements.txt`, and `argostranslate/sbd.py` imports it at module level. The library cannot be installed or imported without an AGPL package, which rules out an in-process `argos` provider at 1.11 or later.
- **F2:** argostranslate 1.10.0, the last release without minisbd, calls `cache_spacy()` at import. That function downloads `xx_sent_ud_sm` through pip at runtime (it failed in a uv environment until pip was added). This is a CC BY-SA model fetched outside SafeFetcher. 1.10.0 also pulls torch and Stanza (a 1.3 GB virtual environment).
- **F3:** the de and ja packages state no license. Helsinki-NLP's own `opus-mt-de-en` and `opus-mt-ja-en` model cards declare Apache-2.0, so a converted replacement is plausible but was not built or tested here (BL-42).
- **F4:** the Stanza tokenizer license is not stated. This only matters if we bundle the packages; LibreTranslate downloads its own.
- **F5:** this is a quality defect, not a license one. In the fr model, the typographic apostrophe U+2019 truncates or corrupts output: "d’IA" becomes "d" or "d的IA". Replacing it with U+0027 fixed fr-4, though "AI control" remained for "AI literacy". All four EU texts use U+2019, so input normalisation is required (BL-43).
- **Trademark:** LibreTranslate's TRADEMARK.md treats container orchestration of LibreTranslate as "modified" for trademark purposes. The admin UI should name it descriptively ("LibreTranslate-compatible server") and not use the logo.

## Hosted APIs (documentation only; nothing measured; no keys used)

All facts below were read on 2026-11-01 from each provider's pricing, privacy, quota and region pages. All four support zh, ja, de, fr, es and pt into English.

| Provider | Price per 1M chars | Free tier | Retention and training | Regions | Rate limits |
| --- | --- | --- | --- | --- | --- |
| Azure AI Translator | $10 (S1; from the Azure Retail Prices API, eastus) | F0: 2M chars a month (a separate tier) | No-Trace: text is not stored | `api-eur` (France Central or West Europe); global endpoint may fail over outside the geography | 50,000 chars per request; S1 40M chars an hour |
| Google Cloud Translation v2 / v3 | $20 (500K to 1B chars) | 500K chars a month (a $10 credit) | Held briefly in memory; not used for training | v3 `translate-eu.googleapis.com` (pre-trained NMT only); v2 global only | 6M chars a minute; v3 30K code points per request |
| DeepL API (Pro tiers) | €22.00 plus a monthly base fee, read from the page's embedded plan data. **The rendered price was not verified**; plan names appear to have changed. | 500K or 1M chars a month (plan names not verified) | Pro: kept temporarily and not used for training. **Free: used to train for an unstated period, so not acceptable.** | EU by default; US and JP need an addendum | 128 KiB per request; requests per second not published |
| Amazon Translate | $15 | 2M chars a month for 12 months | **May store inputs and use them to improve services**, possibly in another region, unless an AWS Organizations opt-out policy is set | 17 regions, including eu-central-1 | 10,000 bytes per request; TPS not stated |

Sources: azure.microsoft.com/pricing/details/cognitive-services/translator, learn.microsoft.com (translator data-privacy-security, service-limits, region-support), prices.azure.com; cloud.google.com/translate/pricing, docs.cloud.google.com/translate (data-usage, quotas, advanced/endpoints); deepl.com/pro-api, deepl.com/privacy, developers.deepl.com (usage-limits, regional-endpoints); aws.amazon.com/translate (pricing, faqs), docs.aws.amazon.com/translate (what-is-limits).

**Preferred hosted options:** Azure through `api-eur` or Google v3 through the EU endpoint. DeepL is acceptable on paid tiers only. Amazon needs the opt-out policy first. Every hosted call follows 8.4: an admin-recorded basis, title plus the first 4,000 characters, and redaction. The owner's budget for paid APIs is zero (section 2.4, answer 12), which is one more reason to keep the default local.

## Component evaluations (condensed from `docs/templates/COMPONENT_EVALUATION.md`)

| Criterion (1 to 5) | Argos Translate (in-process) | LibreTranslate (service) | Hosted API (Azure or Google EU) |
| --- | --- | --- | --- |
| License fit | 1: AGPL dependency from 1.11; CC BY-SA runtime download in 1.10; de and ja models unlicensed | 4: AGPL behind the boundary is allowed; model caveats as for Argos | 4: commercial terms; 8.4 basis required |
| Activity in the last 12 months | 4: v1.10.0 (2025-10) and v1.11.0 (2026-02) | 5: v1.9.6, image built 2026-10-26 | n/a |
| Tests and CI | 3 | 3 | n/a |
| Documentation | 3 | 4 | 5 |
| Open security advisories | not checked | not checked | n/a |
| API fit | 4: Python call | 5: simple HTTP API; fits `http`-style adapters and the SafeFetcher boundary | 5 |
| Size or footprint | 2: 1.3 GB virtual environment plus 763 MB of models; 0.6 to 0.8 GB per language in memory | 3: 1.0 GB image plus 1.66 GB of models; 1.5 GiB with 1 worker | 5 |
| **Decision** | **reject for launch** (BL-40 reopens it) | **service (default)** | **dependency (`http`, optional)** |

**Notices:** if any OPUS-MT-derived model is used, the CC-BY 4.0 attribution (Tiedemann and Thottingal 2020, OPUS-MT) belongs in `THIRD_PARTY_NOTICES.md` and on the About page. A draft entry is left to the M4 implementation PR.

## Expected load at about 200 non-English items a day

These numbers assume a title and summary of about 700 characters per item and a full-text average of about 15,000 characters. Both are assumptions, not measurements. The throughputs are single-stream measurements from this run on 4 vCPU.

| Scope | Characters a day | LT, 1 worker (343 chars/s overall; zh 122) | Argos in-process (221 overall; zh 68) | Hosted, per month (30 days) |
| --- | --- | --- | --- | --- |
| `titles_summaries` | 140,000 | about 7 min (all-zh worst case about 19 min) | about 11 min (all-zh worst case about 34 min) | 4.2M chars: Azure S1 about $42; Google about $74 |
| `full_text` | 3,000,000 | about 2.4 h (all-zh about 6.8 h) | about 3.8 h (all-zh about 12.3 h) | 90M chars: Azure about $900; Google about $1,790. Section 8.4 caps hosted text at 4,000 chars anyway. |

`titles_summaries` fits comfortably in the `process` queue on CPU-only hardware. Full text would occupy one core for hours a day, and the measured quality on long ja text is poor. Full text therefore stays opt-in per source and should be scheduled off-peak.

## Exact commands

```sh
# Argos (CPU only); repeat with argostranslate==1.10.0 (add pip to that venv: it downloads a spaCy model at import)
uv venv -p 3.12 argosenv
VIRTUAL_ENV=$PWD/argosenv uv pip install --index-strategy unsafe-best-match \
  --extra-index-url https://download.pytorch.org/whl/cpu torch argostranslate sacrebleu psutil
for f in zh_en-1_9 ja_en-1_1 de_en-1_3 fr_en-1_9 es_en-1_9 pt_en-1_9; do
  curl -sSLo translate-$f.argosmodel https://argos-net.com/v1/translate-$f.argosmodel; done
argosenv/bin/python -c "import argostranslate.package as p,glob; [p.install_from_path(f) for f in glob.glob('*.argosmodel')]"
for l in zh ja de fr es pt; do ARGOS_DEVICE_TYPE=cpu argosenv/bin/python -I bench_argos.py $l passages.json out/argos_$l.json; done

# LibreTranslate, unmodified official image (proxy and CA settings are environment-specific)
docker run -d --name lt --network host -e LT_LOAD_ONLY=en,zh,ja,de,fr,es,pt [-e LT_THREADS=1] libretranslate/libretranslate:latest
python3 -I bench_lt.py passages.json out/lt.json        # while: docker stats --no-stream lt  (about 1 s samples)

# Scoring (sacrebleu 2.6.0, chrF2 and BLEU)
argosenv/bin/python -I score.py passages.json out
```

## Limitations

- Each passage was translated once. The timings are single runs on a shared cloud VM, so treat differences under about 20% as noise.
- Concurrency and batch throughput were not measured.
- No summaries were translated; titles stand in for them.
- zh and ja passages have no separate titles.
- The ja Japanese text follows the 2021 version paired by JLT. The e-Gov current revision (in force 2026-11-02) was not diffed for these articles.
- Hosted providers were not measured. Their quality on these passages is unknown.
