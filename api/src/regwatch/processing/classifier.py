"""The model classifier (M4 ``Classifier`` protocol, ``ModelClassifier``; acceptance 4; design
notes: model classifier, optional, disabled by default).

- It runs only when the ``classification.model`` flag is on **and**
  ``classification.model_provider`` names a provider this build implements. None is
  implemented yet (``ollama`` and ``http`` come with their own slice), so today the pipeline
  classifies by rules alone and makes no outbound call, whatever the settings say.
- Prompts are versioned files in ``processing/prompts/``; the document is fenced as data.
- A model's answer is never trusted: it must be JSON of the expected shape; only keys from the
  active term list are kept, with a confidence of at least ``min_confidence`` (0.6) and an
  evidence quote that really occurs in the document (at most ``MAX_EVIDENCE`` characters). So a
  document that instructs the model cannot add terms outside the list or invent evidence.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import FeatureFlag
from regwatch.admin.services import values
from regwatch.processing.models import Item, ItemTerm
from regwatch.taxonomy.models import Facet, Term

PROMPT_VERSION = "classify_v1"
MAX_TEXT = 8000
MAX_EVIDENCE = 200
MAX_ANSWER = 64_000
_PROMPTS = Path(__file__).parent / "prompts"
_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TermAssignment:
    term_id: uuid.UUID
    confidence: float
    evidence: str


class ModelProvider(Protocol):
    name: str

    async def complete(self, prompt: str) -> str: ...


PROVIDERS: dict[str, type[ModelProvider]] = {}  # none implemented yet (BL-111)


def prompt(terms: dict[str, str], language: str | None, text: str) -> str:
    template = (_PROMPTS / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
    listing = "\n".join(f"{key}: {label}" for key, label in sorted(terms.items()))
    return (template.replace("{terms}", listing).replace("{language}", language or "unknown")
            .replace("{text}", text[:MAX_TEXT].replace(">>>", "> > >")))  # fmt: skip


def parse(answer: str, terms: dict[str, uuid.UUID], text: str,
          min_confidence: float) -> list[TermAssignment]:  # fmt: skip
    """The assignments an answer may make; anything malformed or outside the list is dropped."""
    try:
        data: Any = json.loads(answer[:MAX_ANSWER])
    except ValueError:
        return []
    found = data.get("terms") if isinstance(data, dict) else None
    out: dict[uuid.UUID, TermAssignment] = {}
    for entry in found if isinstance(found, list) else []:
        if not isinstance(entry, dict):
            continue
        key, confidence, evidence = entry.get("key"), entry.get("confidence"), entry.get("evidence")
        if not isinstance(key, str) or key not in terms:
            continue
        if isinstance(confidence, bool) or not isinstance(confidence, int | float):
            continue
        if not 0 <= confidence <= 1 or confidence < min_confidence:
            continue
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > MAX_EVIDENCE:
            continue
        if evidence.strip().lower() not in text[:MAX_TEXT].lower():
            continue  # evidence must be a real quote
        out.setdefault(terms[key], TermAssignment(terms[key], float(confidence), evidence.strip()))
    return list(out.values())


async def model_provider(db: AsyncSession) -> ModelProvider | None:
    """The configured provider, or None: flag off, provider ``none``, or not implemented."""
    flag = await db.get(FeatureFlag, "classification.model")
    if flag is None or not flag.enabled:
        return None
    name = str(
        (await values(db, ["classification.model_provider"]))["classification.model_provider"]
    )
    made = PROVIDERS.get(name)
    if made is None:
        if name != "none":
            _log.warning("model_provider_unavailable", provider=name)
        return None
    return made()


async def classify_by_model(
    db: AsyncSession,
    item: Item,
    text: str,
    provider: ModelProvider,
    kept: set[uuid.UUID],
    min_confidence: float,
) -> list[uuid.UUID]:
    """Tag ``item`` with what the model says, for terms not already kept; never fails the row."""
    # Term keys are unique within a facet, so the model sees ``facet.term``.
    rows = await db.execute(select(Term.id, Facet.key, Term.key, Term.label)
                            .join(Facet, Facet.id == Term.facet_id).where(Term.active))  # fmt: skip
    by_key = {f"{facet}.{key}": (tid, label) for tid, facet, key, label in rows.tuples().all()}
    try:
        answer = await provider.complete(prompt({k: v[1] for k, v in by_key.items()},
                                                item.language, text))  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - a model failure never blocks the pipeline
        _log.warning("model_classifier_failed", provider=provider.name, error=type(exc).__name__)
        return []
    found = parse(answer, {k: v[0] for k, v in by_key.items()}, text, min_confidence)
    tagged = []
    for got in found:
        if got.term_id in kept:
            continue
        db.add(ItemTerm(item_id=item.id, term_id=got.term_id, assigned_by="model",
                        confidence=Decimal(str(round(got.confidence, 3))),
                        evidence=got.evidence))  # fmt: skip
        kept.add(got.term_id)
        tagged.append(got.term_id)
    _log.info("model_classified", provider=provider.name, prompt=PROMPT_VERSION,
              prompt_chars=min(len(text), MAX_TEXT), tagged=len(tagged))  # fmt: skip
    return tagged
