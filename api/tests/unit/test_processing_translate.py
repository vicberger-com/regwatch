"""Translation (M4 acceptance 6; 8.4 data handling)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from regwatch.processing.translate import HttpTranslator, redact


def test_emails_and_tokens_are_redacted() -> None:
    text = ("Contact anna.schmidt@bsi.example or Bearer abc.def; api_key=s3cr3t and "
            "ZXlKaGJHY2lPaUpJVXpJMU5pSXNJblI1Y0NJNklrcFhWQ0o5 remain? "
            "Normal words stay.")  # fmt: skip
    out = redact(text)
    for gone in ("anna.schmidt", "abc.def", "s3cr3t", "ZXlKaGJHY2lP"):
        assert gone not in out
    assert "Normal words stay." in out


@dataclass
class Got:
    status: int
    body: bytes


class Fetcher:
    def __init__(self, status: int = 200, answer: Any = None) -> None:  # noqa: ANN401
        self.status, self.answer = status, answer
        self.sent: Any = None

    async def fetch(self, url: str, **kw: Any) -> Got:
        self.sent = (url, kw)
        return Got(self.status, json.dumps(self.answer).encode())


async def test_the_http_provider_speaks_the_libretranslate_api() -> None:
    fetcher = Fetcher(answer={"translatedText": "New rules"})
    engine = HttpTranslator("https://tr.example/", "k", fetcher)
    got = await engine.translate("Neue Regeln", "de-DE")
    assert (got.text, got.provider) == ("New rules", "http")
    url, kw = fetcher.sent
    assert url == "https://tr.example/translate" and kw["method"] == "POST"
    assert json.loads(kw["content"]) == {"q": "Neue Regeln", "source": "de", "target": "en",
                                         "format": "text", "api_key": "k"}  # fmt: skip


@pytest.mark.parametrize(("status", "answer"), [(500, {}), (200, {"other": 1}), (200, [1]),
                                                (200, {"translatedText": 5})])  # fmt: skip
async def test_a_bad_answer_raises(status: int, answer: Any) -> None:  # noqa: ANN401
    with pytest.raises(ValueError):
        engine = HttpTranslator("https://tr.example", None, Fetcher(status, answer))
        await engine.translate("x", "de")


@pytest.mark.parametrize(
    "secret",
    ["AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
     "xoxb-1234567890-abcdefghij",
     "Authorization: Basic dXNlcjpwYXNz", "password: hunter2", "jane (at) agency dot gov",
     "jane＠example．com", "sk-abcdefghijklmnopqrstuv"],
)  # fmt: skip
def test_more_secret_shapes_are_redacted(secret: str) -> None:
    """Review 10, N28."""
    import unicodedata

    out = redact(f"Before {secret} after")
    assert unicodedata.normalize("NFKC", secret) not in out and "Before" in out


async def test_answers_are_stored_as_plain_text() -> None:
    """N26: a NUL never loses the document; markup and bidi marks never reach title_en."""
    from types import SimpleNamespace

    from regwatch.processing import translate
    from regwatch.processing.translate import Translation, translate_item

    class Answer:
        name = "x"

        async def translate(self, text: str, source_lang: str, target_lang: str = "en") -> Any:  # noqa: ANN401
            return Translation("<img src=x onerror=alert(1)> Rules\x00 here ‮", "x")

    item = SimpleNamespace(language="de", title="T", summary="S", title_en=None,
                           summary_en=None, translation_pending=True)  # fmt: skip

    async def values(_db: Any, _keys: Any) -> dict[str, str]:  # noqa: ANN401
        return {"translation.scope": "titles_summaries"}

    original = translate.values
    translate.values = values  # type: ignore[assignment]
    try:
        assert await translate_item(None, item, None, "", Answer())  # type: ignore[arg-type]
    finally:
        translate.values = original  # type: ignore[assignment]
    assert item.title_en == "Rules here" and "<" not in item.summary_en


async def test_a_failing_or_slow_translator_stops_for_the_manifest() -> None:
    """N27: after MAX_FAILURES in a row, or once the budget is spent, no more calls."""
    import time
    from types import SimpleNamespace

    from regwatch.processing import translate
    from regwatch.processing.translate import MAX_FAILURES, Budget, translate_item

    calls: list[str] = []

    class Down:
        name = "down"

        async def translate(self, text: str, source_lang: str, target_lang: str = "en") -> Any:  # noqa: ANN401
            calls.append(text)
            raise TimeoutError("slow")

    async def values(_db: Any, _keys: Any) -> dict[str, str]:  # noqa: ANN401
        return {"translation.scope": "titles_summaries"}

    original = translate.values
    translate.values = values  # type: ignore[assignment]
    try:
        budget = Budget()
        for _ in range(MAX_FAILURES + 3):
            item = SimpleNamespace(language="de", title="T", summary=None, translation_pending=True)
            assert not await translate_item(None, item, None, "", Down(), budget)  # type: ignore[arg-type]
            assert item.translation_pending is True
        assert len(calls) == MAX_FAILURES
        spent = Budget(started=time.monotonic() - translate.BUDGET_S - 1)
        item = SimpleNamespace(language="de", title="T", summary=None, translation_pending=True)
        assert not await translate_item(None, item, None, "", Down(), spent)  # type: ignore[arg-type]
        assert len(calls) == MAX_FAILURES
    finally:
        translate.values = original  # type: ignore[assignment]
