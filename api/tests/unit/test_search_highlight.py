"""Search highlights hold no markup from captured text (M5; 08 security: hostile content)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from regwatch.search.services import highlight, words


def test_words_are_marked_and_everything_else_escaped() -> None:
    got = highlight('NIS2 <script>alert("x")</script> incident & more', words("nis2 INCIDENT"))
    assert got == ['<mark>NIS2</mark> &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; '
                   '<mark>incident</mark> &amp; more']  # fmt: skip


def test_a_query_word_cannot_inject_markup() -> None:
    (got,) = highlight("a <b>bold</b> claim", words("<b> bold"))
    assert got.replace("<mark>", "").replace("</mark>", "") == "a &lt;b&gt;bold&lt;/b&gt; claim"


def test_no_match_no_highlight_and_snippets_are_bounded() -> None:
    assert highlight("nothing here", words("absent")) == []
    long = "x " * 1000 + "target " + "y " * 1000
    (snippet,) = highlight(long, words("target"), snippet=True)
    assert "<mark>target</mark>" in snippet and len(snippet) < 400


@given(st.text(max_size=300), st.text(max_size=50))
def test_only_mark_tags_ever_appear(value: str, q: str) -> None:
    for out in highlight(value, words(q), snippet=True):
        stripped = out.replace("<mark>", "").replace("</mark>", "")
        assert "<" not in stripped and ">" not in stripped


def test_case_and_normal_forms_still_highlight() -> None:
    """Search review finding 11."""
    import unicodedata

    assert highlight("Die Straße ist", words("Straße")) == ["Die <mark>Straße</mark> ist"]
    nfd = unicodedata.normalize("NFD", "le café et l'école")
    (got,) = highlight(nfd, words(unicodedata.normalize("NFD", "école café")))
    assert got == "le <mark>café</mark> et l&#x27;<mark>école</mark>"


def test_websearch_operators_are_not_words() -> None:
    """Search re-verification 1, N3."""
    assert words('"incident reporting" or nis2 -guidance -"old text"') == [
        "incident", "reporting", "nis2"]  # fmt: skip
    assert words("NIS2 or incident") == ["NIS2", "incident"]


def test_dotted_capitals_and_combining_marks_stay_whole() -> None:
    """Re-verification 1, #11 leftovers."""
    assert highlight("İstanbul rules", words("İstanbul")) == ["<mark>İstanbul</mark> rules"]
    assert words("İstanbul") == ["İstanbul"]
    (got,) = highlight("the q̃uick fox", words("q̃uick"))
    assert got == "the <mark>q̃uick</mark> fox"
