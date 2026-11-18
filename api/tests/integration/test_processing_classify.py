"""Rule classification (M4 acceptance 3 and 5; Q3)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.classify import classify, load_rules
from regwatch.processing.ingest import ingest
from regwatch.processing.models import Item, ItemTerm
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_sources import fixed_dns, rss

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures

MATCHING = "A ransomware attack must be reported under the incident reporting rules. " * 5
OTHER = "The regulator published guidance on accessibility of public websites. " * 5


async def term(admin: httpx.AsyncClient, rules: dict[str, Any]) -> uuid.UUID:
    key = f"t-{uuid.uuid4().hex[:8]}"
    made = await admin.post(
        _api("/taxonomy/facets/topic/terms"), json={"key": key, "label": key, "match_rules": rules}
    )
    assert made.status_code == 201, made.text
    return uuid.UUID(made.json()["id"])


async def item(admin: httpx.AsyncClient, db: AsyncSession, text: str) -> Item:
    made = await admin.post(_api("/sources"), json=rss())
    sid = uuid.UUID(made.json()["id"])
    got = await ingest(
        db,
        sid,
        None,
        {"url": f"https://e.org/{uuid.uuid4()}", "text": text, "title": "Notice", "language": "en"},
        5.0,
    )
    found = await db.get(Item, got.item_id)
    assert found is not None
    return found


async def tags(db: AsyncSession, item_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        select(ItemTerm.term_id, ItemTerm.assigned_by).where(ItemTerm.item_id == item_id)
    )
    return dict(rows.tuples().all())


async def test_a_keyword_rule_tags_matching_documents_only(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 3."""
    tid = await term(admin, {"keywords": ["ransomware", "incident reporting"], "min_hits": 1})
    rules = await load_rules(db)
    yes = await item(admin, db, MATCHING)
    no = await item(admin, db, OTHER)
    assert tid in await classify(db, yes, MATCHING, rules, [])
    assert tid not in await classify(db, no, OTHER, rules, [])
    await db.commit()
    assert (await tags(db, yes.id)).get(tid) == "rule" and tid not in await tags(db, no.id)
    evidence = await db.scalar(
        select(ItemTerm.evidence).where(ItemTerm.item_id == yes.id, ItemTerm.term_id == tid)
    )
    assert evidence and "ransomware" in evidence


async def test_reclassifying_keeps_user_tags_and_judged_tags(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 5 and Q3: user tags and tags a user judged are never replaced."""
    rule_term = await term(admin, {"keywords": ["ransomware"]})
    judged = await term(admin, {"keywords": ["incident reporting"]})
    mine = await term(admin, {"keywords": ["nothing in this text"]})
    rules = await load_rules(db)
    found = await item(admin, db, MATCHING)
    await classify(db, found, MATCHING, rules, [])
    db.add(ItemTerm(item_id=found.id, term_id=mine, assigned_by="user"))
    await db.execute(
        update(ItemTerm)
        .where(ItemTerm.item_id == found.id, ItemTerm.term_id == judged)
        .values(feedback="incorrect")
    )
    await db.commit()
    # The taxonomy changes: the rule term no longer matches; reclassify.
    await db.execute(
        update(ItemTerm).where(ItemTerm.term_id == rule_term).values(assigned_by="rule")
    )
    changed = [r for r in rules if r.term_id != rule_term]
    await classify(db, found, MATCHING, changed, [])
    await db.commit()
    now = await tags(db, found.id)
    assert rule_term not in now  # the stale rule tag went
    assert now.get(mine) == "user" and judged in now  # kept as the user left them


async def test_source_default_terms_and_the_minimum_confidence(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    weak = await term(admin, {"keywords": ["ransomware"], "weight": 0.5})  # 0.6 x 0.5 = 0.3
    default = await term(admin, {"keywords": ["never"]})
    rules = await load_rules(db)
    found = await item(admin, db, "One ransomware mention.")
    tagged = await classify(db, found, "One ransomware mention.", rules, [default])
    assert default in tagged and weak not in tagged
    await db.commit()
    assert (await tags(db, found.id)).get(default) == "source_default"
