"""Rule classification (M4 ``process.classify``; ``RuleClassifier``; acceptance 3 and 5; Q1, Q3).

- Every active term whose ``match_rules`` has keywords or patterns is evaluated with M2's
  ``taxonomy.rules.evaluate``: RE2 and plain substring scans, linear in the text. The text is
  the title, the summary and the first ``MAX_TEXT`` characters of the version's text.
- A term is tagged when its confidence reaches ``classification.min_confidence`` (0.6), with the
  evidence snippets M2 returns; a source's default terms are tagged at 1.0.
- Reclassifying replaces the earlier rule, model and source-default tags. A user's own tag,
  and any tag a user has marked ``correct`` or ``incorrect``, is never replaced: a judged tag
  stays as judged, and a term marked incorrect is not tagged again by a rule.
- No model classifier runs: it is off (Q1), and nothing here calls out.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.models import Item, ItemTerm
from regwatch.taxonomy.models import Term
from regwatch.taxonomy.rules import evaluate

MAX_TEXT = 100_000
MIN_CONFIDENCE = 0.6
MAX_EVIDENCE = 1000


@dataclass(frozen=True)
class Rule:
    term_id: uuid.UUID
    rules: dict[str, Any]


async def load_rules(db: AsyncSession) -> list[Rule]:
    """The active terms that have something to match, once per manifest."""
    rows = await db.execute(select(Term.id, Term.match_rules).where(Term.active))
    return [
        Rule(tid, rules)
        for tid, rules in rows
        if isinstance(rules, dict) and (rules.get("keywords") or rules.get("regex"))
    ]


async def classify(
    db: AsyncSession,
    item: Item,
    text: str,
    rules: list[Rule],
    defaults: list[uuid.UUID],
    min_confidence: float = MIN_CONFIDENCE,
) -> list[uuid.UUID]:
    """Tag ``item``; the ids of the terms it now carries from rules and defaults."""
    kept = set(
        (
            await db.scalars(
                select(ItemTerm.term_id).where(
                    ItemTerm.item_id == item.id,
                    or_(ItemTerm.assigned_by == "user", ItemTerm.feedback.is_not(None)),
                )
            )
        ).all()
    )
    await db.execute(
        delete(ItemTerm).where(
            ItemTerm.item_id == item.id, ItemTerm.assigned_by != "user", ItemTerm.feedback.is_(None)
        )
    )
    scan = "\n".join(part for part in (item.title, item.summary or "", text[:MAX_TEXT]) if part)
    tagged: list[uuid.UUID] = []
    for term_id in defaults:
        if term_id not in kept:
            db.add(
                ItemTerm(
                    item_id=item.id,
                    term_id=term_id,
                    assigned_by="source_default",
                    confidence=Decimal("1"),
                )
            )
            kept.add(term_id)
            tagged.append(term_id)
    for rule in rules:
        if rule.term_id in kept:
            continue
        result = evaluate(rule.rules, scan, item.language)
        if not result.matched or result.confidence < min_confidence:
            continue
        evidence = " … ".join(result.evidence)[:MAX_EVIDENCE] or None
        db.add(
            ItemTerm(
                item_id=item.id,
                term_id=rule.term_id,
                assigned_by="rule",
                confidence=Decimal(str(result.confidence)),
                evidence=evidence,
            )
        )
        kept.add(rule.term_id)
        tagged.append(rule.term_id)
    return tagged
