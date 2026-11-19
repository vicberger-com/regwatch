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
