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


async def test_with_the_model_flag_off_rules_alone_classify_and_nothing_calls_out(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance 4: flag off (even with a provider named), and flag on with a provider this
    build does not implement: rules tag, and no HTTP request is made (a network mock)."""
    from sqlalchemy import update

    from regwatch.admin.models import FeatureFlag, Setting
    from regwatch.processing.pipeline import reprocess_item

    def no_network(*_: Any, **__: Any) -> None:
        raise AssertionError("an outbound call was made")

    rule = await term(admin, {"keywords": ["ransomware"]})
    made = await item(admin, db, "Operators must report ransomware incidents. " * 20)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)  # after the API calls above
    await db.merge(Setting(key="classification.model_provider", value="ollama"))
    await db.commit()
    for enabled in (False, True):
        await db.execute(update(FeatureFlag).where(FeatureFlag.key == "classification.model")
                         .values(enabled=enabled))  # fmt: skip
        await db.commit()
        assert await reprocess_item(db, made.id)
        assert (await tags(db, made.id)).get(rule) == "rule"
    await db.execute(update(FeatureFlag).where(FeatureFlag.key == "classification.model")
                     .values(enabled=False))  # fmt: skip
    await db.execute(
        Setting.__table__.delete().where(Setting.key == "classification.model_provider")
    )
    await db.commit()


async def test_a_model_provider_tags_only_what_its_answer_proves(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a provider (a fake, as none is built yet): valid answers tag as ``model``; a
    failing provider never fails the item; rule and user tags are left alone."""
    import json

    from sqlalchemy import select, update

    from regwatch.admin.models import FeatureFlag, Setting
    from regwatch.processing import classifier
    from regwatch.processing.pipeline import reprocess_item
    from regwatch.taxonomy.models import Term

    rule = await term(admin, {"keywords": ["ransomware"]})
    other = await term(admin, {"keywords": ["nothing-matches-this"]})
    other_key = await db.scalar(select(Term.key).where(Term.id == other))
    made = await item(admin, db, "Operators must report ransomware incidents. " * 20)
    replies: list[str] = []

    class Fake:
        name = "fake"

        async def complete(self, prompt: str) -> str:
            assert "<<<" in prompt and "ransomware" in prompt
            if not replies:
                raise TimeoutError("model down")
            return replies.pop()

    monkeypatch.setitem(classifier.PROVIDERS, "fake", Fake)  # type: ignore[arg-type]
    await db.merge(Setting(key="classification.model_provider", value="fake"))
    await db.execute(update(FeatureFlag).where(FeatureFlag.key == "classification.model")
                     .values(enabled=True))  # fmt: skip
    await db.commit()
    try:
        assert await reprocess_item(db, made.id)  # the provider fails: rules still tag
        assert await tags(db, made.id) == {rule: "rule"}
        replies.append(
            json.dumps(
                {
                    "terms": [
                        {
                            "key": f"topic.{other_key}",
                            "confidence": 0.9,
                            "evidence": "report ransomware",
                        },
                        {"key": "topic.invented", "confidence": 1, "evidence": "report ransomware"},
                    ]
                }
            )
        )
        assert await reprocess_item(db, made.id)
        assert await tags(db, made.id) == {rule: "rule", other: "model"}
    finally:
        await db.execute(update(FeatureFlag).where(FeatureFlag.key == "classification.model")
                         .values(enabled=False))  # fmt: skip
        await db.execute(Setting.__table__.delete().where(
            Setting.key == "classification.model_provider"))  # fmt: skip
        await db.commit()


async def test_a_japanese_item_gets_english_from_the_selected_provider(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance 6: original kept, English title and summary from the provider; switching the
    provider and reprocessing replaces the translation and records the new provider; English
    rules apply to the translation."""
    from sqlalchemy import select

    from regwatch.processing import pipeline
    from regwatch.processing.models import ItemVersion
    from regwatch.processing.translate import Translation

    rule = await term(admin, {"keywords": ["incident reporting"]})
    made = await item(admin, db, "サイバー事案の報告に関する新しい規則を公表しました。" * 10)
    made.language, made.summary = "ja", "報告義務の概要"
    await db.commit()

    class Fake:
        def __init__(self, name: str) -> None:
            self.name = name

        async def translate(self, text: str, source_lang: str,
                            target_lang: str = "en") -> Translation:  # fmt: skip
            assert source_lang == "ja" and target_lang == "en"
            return Translation(f"[{self.name}] incident reporting rules", self.name)

    async def engine_a(_: Any) -> Fake:
        return Fake("alpha")

    monkeypatch.setattr(pipeline, "translator", engine_a)
    assert await pipeline.reprocess_item(db, made.id)
    got = await db.scalar(select(Item).where(Item.id == made.id)
                          .execution_options(populate_existing=True))  # fmt: skip
    assert got is not None and got.title == "Notice"  # the original is kept
    assert got is not None and got.title_en == "[alpha] incident reporting rules"
    assert got.translation_pending is False and (await tags(db, made.id)).get(rule) == "rule"
    version = await db.scalar(select(ItemVersion).where(ItemVersion.item_id == made.id))
    assert version is not None and version.translations["en"]["provider"] == "alpha"

    async def engine_b(_: Any) -> Fake:
        return Fake("beta")

    monkeypatch.setattr(pipeline, "translator", engine_b)
    assert await pipeline.reprocess_item(db, made.id)
    got = await db.scalar(select(Item).where(Item.id == made.id)
                          .execution_options(populate_existing=True))  # fmt: skip
    version = await db.scalar(select(ItemVersion).where(ItemVersion.item_id == made.id)
                              .execution_options(populate_existing=True))  # fmt: skip
    assert got is not None and got.title_en == "[beta] incident reporting rules"
    assert version is not None and version.translations["en"]["provider"] == "beta"


async def test_translation_is_off_unless_flagged_with_a_basis_and_a_url(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import update

    from regwatch.admin.models import FeatureFlag, Setting
    from regwatch.core import settings as settings_module
    from regwatch.core.settings import get_settings
    from regwatch.processing.translate import HttpTranslator, translator

    base = get_settings()
    monkeypatch.setattr(settings_module, "get_settings",
                        lambda: base.model_copy(update={"translate_api_url": None}))  # fmt: skip
    assert await translator(db) is None  # flag off
    await db.execute(update(FeatureFlag).where(FeatureFlag.key == "translation.enabled")
                     .values(enabled=True))  # fmt: skip
    await db.merge(Setting(key="translation.provider", value="http"))
    await db.commit()
    try:
        assert await translator(db) is None  # no recorded basis
        await db.merge(Setting(key="translation.data_processing_basis", value="DPA 2026-11"))
        await db.commit()
        assert await translator(db) is None  # no URL
        monkeypatch.setattr(settings_module, "get_settings", lambda: base.model_copy(
            update={"translate_api_url": "http://tr.example"}))  # fmt: skip
        assert await translator(db) is None  # plain http would send the key in clear (N29)
        monkeypatch.setattr(settings_module, "get_settings", lambda: base.model_copy(
            update={"translate_api_url": "https://tr.example"}))  # fmt: skip
        assert isinstance(await translator(db), HttpTranslator)
    finally:
        await db.execute(update(FeatureFlag).where(FeatureFlag.key == "translation.enabled")
                         .values(enabled=False))  # fmt: skip
        for key in ("translation.provider", "translation.data_processing_basis"):
            await db.execute(Setting.__table__.delete().where(Setting.key == key))
        await db.commit()
