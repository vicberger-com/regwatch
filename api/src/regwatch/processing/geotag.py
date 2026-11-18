"""Jurisdiction detection (M4 ``process.geotag``; design notes: jurisdiction detection;
acceptance 2).

In order, with the confidence recorded:

1. The source's default jurisdictions, when it has any: ``source_default``, 1.0. Nothing else
   is looked for.
2. The gazetteer, in the title and the first ``SCAN_CHARS`` characters of the text:
   an authority of the jurisdiction 0.9, its name in a rule language 0.8, a demonym 0.75; each
   further cue for the same jurisdiction adds 0.05, up to 0.95.
3. Only when the gazetteer found nothing: the host's country-code top-level domain (``.de``,
   ``.gov.uk``, ``.europa.eu``), 0.6.

Latin-script cues match whole words, ignoring case; CJK cues match as written. Names that are
also common words (``STOPWORDS``) count only through other cues. The patterns are built once,
from data the project ships (``gazetteer.json``, ``gazetteer_extra.yaml``), never from content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

SCAN_CHARS = 2000
WEIGHTS = {"authority": 0.9, "name": 0.8, "demonym": 0.75}
EXTRA_CUE = 0.05
MAX_CONFIDENCE = 0.95
DOMAIN_CONFIDENCE = 0.6
# Country names that are also everyday words or other places; they never count on their own.
STOPWORDS = frozenset({"chad", "jersey", "georgia", "jordan", "turkey", "guinea", "dominica"})
# Second-level domains under which the country code says who publishes (gov.uk, gouv.fr ...).
TLD_ALIASES = {"uk": "GB", "eu": "EU"}
_HERE = Path(__file__).parent
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


@dataclass(frozen=True)
class Hit:
    code: str
    confidence: float
    evidence: str  # what matched, fixed text and the cue, never more than the cue itself


@lru_cache(maxsize=1)
def _cues() -> tuple[list[tuple[re.Pattern[str], str, str, str]], frozenset[str]]:
    """(pattern, code, kind, cue) for every cue, and every known code."""
    names = json.loads((_HERE / "gazetteer.json").read_text(encoding="utf-8"))["names"]
    extra = yaml.safe_load((_HERE / "gazetteer_extra.yaml").read_text(encoding="utf-8"))
    entries: list[tuple[str, str, str]] = []
    for code, found in names.items():
        entries += [(code, "name", n) for n in found if n.lower() not in STOPWORDS]
    for code, groups in extra.items():
        for kind, key in (("authority", "authorities"), ("name", "names"),
                          ("demonym", "demonyms")):  # fmt: skip
            entries += [(code, kind, cue) for cue in groups.get(key, [])]
    out: list[tuple[re.Pattern[str], str, str, str]] = []
    for code, kind, cue in entries:
        body = re.escape(cue)
        pattern = body if _CJK.search(cue) else rf"(?<![\w.]){body}(?!\w)"
        out.append((re.compile(pattern, 0 if _CJK.search(cue) else re.IGNORECASE), code, kind,
                    cue))  # fmt: skip
    return out, frozenset(names) | frozenset(extra)


def detect(title: str, text: str, url: str, defaults: list[str]) -> list[Hit]:
    """The jurisdictions of a document, most confident first."""
    if defaults:
        return [Hit(code, 1.0, "source default") for code in defaults]
    scan = f"{title}\n{text[:SCAN_CHARS]}"
    cues, codes = _cues()
    found: dict[str, list[tuple[str, str]]] = {}
    for pattern, code, kind, cue in cues:
        if pattern.search(scan):
            found.setdefault(code, []).append((kind, cue))
    hits = []
    for code, matched in found.items():
        best = max(WEIGHTS[kind] for kind, _ in matched)
        confidence = min(MAX_CONFIDENCE, best + EXTRA_CUE * (len(matched) - 1))
        kind, cue = max(matched, key=lambda m: WEIGHTS[m[0]])
        hits.append(Hit(code, round(confidence, 3), f"{kind}: {cue}"[:200]))
    if not hits:
        host = (urlsplit(url).hostname or "") if url.startswith(("http://", "https://")) else ""
        tld = host.rsplit(".", 1)[-1].upper() if "." in host else ""
        code = TLD_ALIASES.get(tld.lower(), tld)
        if code in codes:
            hits.append(Hit(code, DOMAIN_CONFIDENCE, f"domain: .{tld.lower()}"))
    return sorted(hits, key=lambda h: (-h.confidence, h.code))
