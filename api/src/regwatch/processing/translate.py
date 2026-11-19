"""Translation (M4 ``Translator`` protocol; acceptance 6; owner decision 2026-11-19: the
protocol, settings, pipeline step and the ``http`` provider now, Argos and LibreTranslate when
their model licenses are settled, BL-42).

- It runs only when the ``translation.enabled`` flag is on, ``translation.provider`` is ``http``,
  ``REGWATCH_TRANSLATE_API_URL`` is set and ``translation.data_processing_basis`` is recorded
  (8.4; the flag cannot be turned on without it either).
- The ``http`` provider speaks the LibreTranslate API (``POST /translate``, JSON, the key in
  the body as ``api_key``) at the hosted URL, through SafeFetcher: the address checks, a 64 KB
  request, a 256 KB answer, no redirects (a body is never sent on).
- What is sent (8.4): the title, the summary and at most the first ``MAX_SENT`` characters of
  text, with email addresses and token-like strings replaced by ``[redacted]``.
- ``translation.scope``: ``titles_summaries`` fills ``title_en`` and ``summary_en``;
  ``full_text`` also stores the text's translation in ``item_version.translations``. The
  original is always kept, and each translation records its provider and time.
- A failure never blocks the pipeline: the item stays ``translation_pending``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import FeatureFlag
from regwatch.admin.services import BASIS_KEY, values
from regwatch.processing.models import Item, ItemVersion

MAX_SENT = 4000
MAX_ANSWER = 256 * 1024
TIMEOUT_S = 30.0
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(\.[\w-]{1,63})+")
_TOKEN = re.compile(r"(?i)\b(bearer\s+\S+|(api[_-]?key|token|secret)\s*[:=]\s*\S+)"
                    r"|\b[A-Za-z0-9_\-]{32,}\b")  # fmt: skip
_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Translation:
    text: str
    provider: str
    confidence: float | None = None


class Translator(Protocol):
    name: str

    async def translate(self, text: str, source_lang: str,
                        target_lang: str = "en") -> Translation: ...  # fmt: skip


def redact(text: str) -> str:
    """Email addresses and token-like strings out (8.4)."""
    return _TOKEN.sub("[redacted]", _EMAIL.sub("[redacted]", text))


class HttpTranslator:
    """A hosted LibreTranslate-compatible API, reached through SafeFetcher."""

    name = "http"

    def __init__(self, url: str, key: str | None, fetcher: Any) -> None:  # noqa: ANN401
        self.url, self.key, self.fetcher = url.rstrip("/") + "/translate", key, fetcher

    async def translate(self, text: str, source_lang: str,
                        target_lang: str = "en") -> Translation:  # fmt: skip
        body: dict[str, Any] = {"q": text, "source": source_lang.split("-")[0].lower(),
                                "target": target_lang, "format": "text"}  # fmt: skip
        if self.key:
            body["api_key"] = self.key
        got = await self.fetcher.fetch(self.url, method="POST", content=json.dumps(body).encode(),
                                       headers={"content-type": "application/json",
                                                "accept": "application/json"})  # fmt: skip
        if got.status != 200:
            raise ValueError(f"the translator answered HTTP {got.status}")
        data = json.loads(got.body[:MAX_ANSWER])
        out = data.get("translatedText") if isinstance(data, dict) else None
        if not isinstance(out, str):
            raise ValueError("the translator's answer has no translatedText")
        return Translation(out[: len(text) * 4 + 100], self.name)


async def translator(db: AsyncSession) -> Translator | None:
    """The configured translator, or None (flag off, no provider, no URL, no recorded basis)."""
    flag = await db.get(FeatureFlag, "translation.enabled")
    if flag is None or not flag.enabled:
        return None
    current = await values(db, ["translation.provider", BASIS_KEY])
    if current["translation.provider"] != "http" or not str(current[BASIS_KEY]).strip():
        return None
    from regwatch.capture.safe_fetch.fetch import FetchLimits, SafeFetcher
    from regwatch.core.settings import get_settings

    settings = get_settings()
    if settings.translate_api_url is None:
        _log.warning("translation_unconfigured", provider="http")
        return None
    key = settings.translate_api_key.get_secret_value() if settings.translate_api_key else None
    limits = FetchLimits(max_bytes=MAX_ANSWER, total_s=TIMEOUT_S, max_redirects=0)
    return HttpTranslator(str(settings.translate_api_url), key,
                          SafeFetcher("regwatch-translate", limits))  # fmt: skip


async def translate_item(db: AsyncSession, item: Item, version: ItemVersion | None, text: str,
                         engine: Translator) -> bool:  # fmt: skip
    """Translate ``item`` in place; True when done. Never raises."""
    lang = (item.language or "").lower()
    if not lang or lang.startswith("en"):
        return False
    scope = (await values(db, ["translation.scope"]))["translation.scope"]
    stamp = datetime.now(UTC).isoformat()
    try:
        title = await engine.translate(redact(item.title), lang)
        summary = await engine.translate(redact(item.summary), lang) if item.summary else None
        full = (await engine.translate(redact(text[:MAX_SENT]), lang)
                if scope == "full_text" and text.strip() else None)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - a translation failure never blocks the pipeline
        _log.warning("translation_failed", provider=engine.name, error=type(exc).__name__)
        item.translation_pending = True
        return False
    item.title_en = title.text[:2000]
    item.summary_en = summary.text[:16000] if summary else None
    item.translation_pending = False
    if version is not None:
        record: dict[str, Any] = {"provider": engine.name, "at": stamp, "scope": scope,
                                  "title": item.title_en}  # fmt: skip
        if full is not None:
            record["text"] = full.text
        version.translations = {**(version.translations or {}), "en": record}
    return True
