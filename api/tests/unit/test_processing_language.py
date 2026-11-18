"""Language detection (M4 Q6)."""

from __future__ import annotations

import pytest

from regwatch.processing.language import detect


@pytest.mark.parametrize(
    ("title", "text", "code"),
    [("Neue Leitlinie", "Das Bundesamt für Sicherheit in der Informationstechnik veröffentlicht "
      "neue Regeln für Betreiber kritischer Anlagen.", "de"),
     ("Nouvelle règle", "La Commission nationale de l'informatique et des libertés publie une "
      "nouvelle recommandation.", "fr"),
     ("新しい規則", "個人情報保護委員会は新しい規則を公表しました。"
      "事業者は報告しなければなりません。", "ja"),
     ("New rule", "Providers shall report incidents to the authority within 24 hours.", "en"),
     ("x", "12345 67890 !!!", None), ("", "", None)],
)  # fmt: skip
def test_detect(title: str, text: str, code: str | None) -> None:
    assert detect(title, text) == code


def test_a_long_text_reads_only_a_sample() -> None:
    import time

    started = time.monotonic()
    assert detect("Rule", "Providers shall report incidents. " * 30_000) == "en"
    assert time.monotonic() - started < 2
