"""Language detection (M4 scope; Q6, lingua-language-detector 2.2.0 approved 2026-11-18).

Used only when a capture row names no language. The detector knows the languages the rules
and the gazetteer cover, plus a few common in official sources; it runs on the title and the
first ``SAMPLE_CHARS`` characters, offline (its models ship in the wheel), and answers only
when its confidence reaches ``MIN_CONFIDENCE`` and the sample has ``MIN_LETTERS`` letters.
"""

from __future__ import annotations

from functools import lru_cache

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

SAMPLE_CHARS = 2000
MIN_LETTERS = 20
MIN_CONFIDENCE = 0.5
LANGUAGES = (Language.ENGLISH, Language.GERMAN, Language.FRENCH, Language.SPANISH,
             Language.PORTUGUESE, Language.JAPANESE, Language.CHINESE, Language.ITALIAN,
             Language.DUTCH)  # fmt: skip


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(*LANGUAGES).build()


def detect(title: str, text: str) -> str | None:
    """An ISO 639-1 code in lower case, or None when unsure."""
    sample = f"{title}\n{text[:SAMPLE_CHARS]}"
    if sum(ch.isalpha() for ch in sample) < MIN_LETTERS:
        return None
    found = _detector().compute_language_confidence_values(sample)
    if not found or found[0].value < MIN_CONFIDENCE:
        return None
    return found[0].language.iso_code_639_1.name.lower()
