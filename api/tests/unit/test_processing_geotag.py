"""Jurisdiction detection (M4 acceptance 2; design notes)."""

from __future__ import annotations

import pytest

from regwatch.processing.geotag import detect


def codes(hits: list) -> list[tuple[str, float]]:  # type: ignore[type-arg]
    return [(h.code, h.confidence) for h in hits]


def test_a_german_authority_tags_germany_above_0_7_without_a_default() -> None:
    """Acceptance 2."""
    hits = detect("Neue Leitlinie", "Das Bundesamt für Sicherheit in der Informationstechnik "
                  "veröffentlicht eine Leitlinie.", "https://example.org/x", [])  # fmt: skip
    assert codes(hits) == [("DE", 0.9)] and hits[0].evidence.startswith("authority:")


def test_source_defaults_come_first_and_alone() -> None:
    hits = detect(
        "x", "Bundesamt für Sicherheit in der Informationstechnik", "https://a.de", ["FR"]
    )
    assert codes(hits) == [("FR", 1.0)]


@pytest.mark.parametrize(
    ("title", "text", "expected"),
    [("Rules in Deutschland", "", [("DE", 0.8)]), ("新しい規則", "日本の個人情報", [("JP", 0.8)]),
     ("A German rule", "", [("DE", 0.75)]),
     ("Germany", "The German Bundesnetzagentur and Deutschland", [("DE", 0.95)]),
     ("Chad", "", []), ("New jersey design", "", []),
     ("Germanyx and Xgermany", "", [])],
)  # fmt: skip
def test_names_demonyms_and_word_boundaries(title: str, text: str,
                                            expected: list[tuple[str, float]]) -> None:  # fmt: skip
    assert codes(detect(title, text, "https://example.org/", [])) == expected


def test_the_domain_counts_only_when_nothing_else_does() -> None:
    assert codes(detect("x", "y", "https://www.bsi.bund.de/a", [])) == [("DE", 0.6)]
    assert codes(detect("x", "y", "https://www.ico.org.uk/a", [])) == [("GB", 0.6)]
    assert codes(detect("x", "y", "https://eur-lex.europa.eu/a", [])) == [("EU", 0.6)]
    assert codes(detect("French", "y", "https://www.bsi.bund.de/a", [])) == [("FR", 0.75)]
    assert detect("x", "y", "https://example.com/", []) == []
    assert detect("x", "y", "urn:sha256:" + "a" * 64, []) == []


def test_only_the_first_2000_characters_are_read() -> None:
    late = "word " * 500 + "Deutschland"
    assert detect("x", late, "https://example.org/", []) == []


def test_several_jurisdictions_are_all_returned_most_confident_first() -> None:
    hits = detect("x", "The Information Commissioner's Office and France", "https://e.org/", [])
    assert codes(hits) == [("GB", 0.9), ("FR", 0.8)]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("サマリーです", []),
        ("インドネシアの規則", [("ID", 0.8)]),
        ("インドの規則", [("IN", 0.8)]),
        ("パプアニューギニア", [("PG", 0.8)]),
        ("El equipo gana", []),
        ("Indian Ocean rules", []),
    ],
)
def test_false_positives_from_the_review_are_gone(
    title: str, expected: list[tuple[str, float]]
) -> None:
    """M4 pipeline review finding 8."""
    assert codes(detect(title, "", "https://example.org/", [])) == expected


def test_a_text_naming_every_country_tags_ten() -> None:
    """Finding 4: no flood of jurisdictions (and events) from one text."""
    import json
    import pathlib

    from regwatch.processing import geotag

    names = json.loads((pathlib.Path(geotag.__file__).parent / "gazetteer.json").read_text())
    text = ", ".join(n[0] for n in names["names"].values())
    assert len(detect("x", text, "https://example.org/", [])) == geotag.MAX_HITS
