# ADR-0009: Own HTML extraction on html5lib, instead of trafilatura and readability-lxml

**Status:** accepted by the owner on 2026-11-17 · **Date:** 2026-11-17 · **Requirements:** REQ-04, REQ-05, REQ-20
**Research:** R-01 C19 and C20; `docs/03-architecture.md` 3.4, 3.5 and 3.6; `docs/modules/M3-capture-framework.md`; ADR-0003; CP-15

## Context

- **The plan.** 3.4 and M3 name trafilatura 1.8+ for main-text extraction, with readability-lxml as the fallback. The contract (`connectors.yaml`, the extraction rules) says empty `content_selectors` means trafilatura, and an omitted `date_format` means dateparser.
- **What resolving them pulls in fails 3.5.** This was checked on 2026-11-17, resolving for Python 3.12 with `uv pip compile`.
  - trafilatura 2.3.1 needs lxml 6.1.3. lxml's official binary wheels statically link GNU libiconv, which is LGPL-2.1. lxml's own `LICENSES.txt` in the wheel says so, and the string is present in `etree.so`. LGPL is not allowed in bundled code; psycopg was refused for LGPL-3.0 (CP-01).
  - readability-lxml 0.9 needs chardet 5.2.0, which is LGPL-2.1-or-later.
  - trafilatura needs htmldate, which needs dateparser, which needs regex. regex is "Apache-2.0 AND CNRI-Python", and CNRI-Python is not on the allow-list.
  - The rest of the tree is permissive: trafilatura, htmldate, courlan (Apache-2.0), justext (BSD-2), lxml-html-clean and dateparser (BSD-3), pytz (MIT).
- **Full CSS selectors need beautifulsoup4 with soupsieve.** beautifulsoup4's repository is on Launchpad, which refuses automated requests (403). Its LICENSE file cannot be read at a tag, and ADR-0003 decision 1 requires that.

## Decision

1. **Parsing.** HTML is parsed with html5lib 1.1, a pure-Python parser of the WHATWG algorithm, so the tree matches a browser's: implicit `tbody`, and the browser's repair of misnested tags. Its one new dependency is webencodings 0.5.1. six is already in the register.
2. **Selectors.** The extraction rules use a CSS subset implemented in the project and checked when a source is saved (CP-15). Anything outside the subset is refused with a message.
3. **Main text.** When `content_selectors` is empty, a built-in heuristic picks the main text: it removes `exclude_selectors`, scripts, styles, navigation, headers, footers and asides, then takes the block element with the most paragraph text, scored by text length less link text.
4. **Dates.** An omitted `date_format` means ISO 8601 and a short fixed list of common formats. dateparser is not used.
5. **Bounds.** Parsing runs in a worker thread and only on bodies within the fetch cap. The tree's depth and node count are capped, so a hostile page cannot exhaust memory.
6. **The plan rows.** The register rows for trafilatura and readability-lxml stay as research records, marked "not used (ADR-0009)".

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **Own extractor on html5lib (chosen)** | MIT, BSD-3 | No native code and no copyleft; the tree matches browsers, so selectors copied from developer tools match | Weaker main-text extraction on cluttered pages than trafilatura; a selector subset to maintain; html5lib has had no release since 2020 |
| trafilatura with lxml built from source against Debian's libxml2 | Apache-2.0 and others, plus CNRI-Python | Strong main-text extraction | A compiler in the build stage and slower builds; a CI check that the binary wheel was not used; needs an exception for CNRI-Python |
| trafilatura with the binary wheels and an LGPL exception | LGPL-2.1 (libiconv, static) | Fastest to build | Relinking and notice duties for a proprietary product |
| Python's `html.parser` | PSF (standard library) | No new dependency | The tree differs from a browser's, so copied selectors match less reliably |

## Consequences

- Two register rows, html5lib 1.1 (MIT, V `f87487a`) and webencodings 0.5.1 (BSD-3, V `fa2cb5d`), were approved by the owner on 2026-11-17. webencodings stays below 0.6: 0.6.1 on PyPI has no tag in its repository.
- CP-15 changes three descriptions in `connectors.yaml` to match.
- html5lib is unmaintained. If a security issue appears with no fix, either vendor a patched copy or replace the tree builder, which is the only place html5lib is used.
