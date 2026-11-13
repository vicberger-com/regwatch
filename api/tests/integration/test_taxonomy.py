"""Integration: facets and view dimensions (M2 acceptance 1; REQ-03, REQ-11)."""

from __future__ import annotations

import uuid

import httpx
import pytest

from tests.integration.conftest import Postgres
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url"]  # fixtures shared with test_admin and test_auth


async def _version(admin: httpx.AsyncClient) -> int:
    settings = {s["key"]: s for s in (await admin.get(_api("/admin/settings"))).json()}
    return int(settings["taxonomy.version"]["value"])


async def test_new_facet_appears_at_once_and_bumps_the_version(admin: httpx.AsyncClient) -> None:
    before = await _version(admin)
    body = {"key": "enforcement_body", "label": "Enforcement body", "value_type": "term",
            "show_in_view_selector": True}  # fmt: skip
    created = await admin.post(_api("/taxonomy/facets"), json=body)
    assert created.status_code == 201, created.text
    assert created.json()["system"] is False and created.json()["terms"] == []
    facets = {f["key"]: f for f in (await admin.get(_api("/taxonomy/facets"))).json()}
    assert "enforcement_body" in facets and facets["topic"]["terms"]
    dims = (await admin.get(_api("/taxonomy/view-dimensions"))).json()
    assert [d["key"] for d in dims][:3] == ["country", "region", "regulation"]
    assert {"key": "enforcement_body", "label": "Enforcement body", "kind": "facet"} in dims
    assert await _version(admin) == before + 1

    hidden = await admin.patch(_api("/taxonomy/facets/enforcement_body"), json={"hidden": True})
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    dims = (await admin.get(_api("/taxonomy/view-dimensions"))).json()
    assert "enforcement_body" not in [d["key"] for d in dims]
    assert await _version(admin) == before + 2
    audit = (await admin.get(_api("/admin/audit"), params={"entity_type": "facet"})).json()
    assert [r["action"] for r in audit["items"]] == ["facet.update", "facet.create"]
    assert audit["items"][0]["before"]["hidden"] is False


async def test_facet_rules(admin: httpx.AsyncClient) -> None:
    post = lambda body: admin.post(_api("/taxonomy/facets"), json=body)  # noqa: E731
    assert (await post({"key": "region", "label": "R", "value_type": "term"})).status_code == 422
    assert (await post({"key": "x", "label": "X", "value_type": "term"})).status_code == 422
    assert (await post({"key": "notes", "value_type": "text"})).status_code == 422
    assert (await post({"key": "topic", "label": "T", "value_type": "term"})).status_code == 409
    assert (await admin.delete(_api("/taxonomy/facets/topic"))).status_code == 409
    change = await admin.patch(_api("/taxonomy/facets/topic"), json={"value_type": "text"})
    assert change.status_code == 422
    assert (
        await admin.patch(_api("/taxonomy/facets/topic"), json={"key": "t2"})
    ).status_code == 422
    assert (
        await admin.patch(_api("/taxonomy/facets/topic"), json={"hidden": True})
    ).status_code == 200
    assert (
        await admin.patch(_api("/taxonomy/facets/nope"), json={"hidden": True})
    ).status_code == 404
    assert (await post({"key": "notes", "label": "Notes", "value_type": "text"})).status_code == 201
    assert (
        await admin.patch(_api("/taxonomy/facets/notes"), json={"label": None})
    ).status_code == 422
    assert (await admin.delete(_api("/taxonomy/facets/notes"))).status_code == 204
    assert (await admin.delete(_api("/taxonomy/facets/notes"))).status_code == 404
    version = await admin.put(_api("/admin/settings/taxonomy.version"), json={"value": 99})
    assert version.status_code == 400


async def test_viewers_read_but_do_not_edit(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "tv@example.org", ["viewer"])
    assert (await viewer.get(_api("/taxonomy/facets"))).status_code == 200
    assert (await viewer.get(_api("/taxonomy/view-dimensions"))).status_code == 200
    body = {"key": "x_facet", "label": "X", "value_type": "term"}
    assert (await viewer.post(_api("/taxonomy/facets"), json=body)).status_code == 403
    await viewer.aclose()


def _tag_item(postgres: Postgres, db_url: str, term_id: str) -> None:
    """Insert a source, an item and one tag directly (capture and processing land in M3, M4)."""
    database = db_url.rsplit("/", 1)[1]
    term = uuid.UUID(term_id)  # validated, so the literal below is safe
    postgres.psql(
        database,
        f"""
WITH s AS (INSERT INTO source (name, kind) VALUES ('fixture', 'manual') RETURNING id),
     i AS (INSERT INTO item (source_id, canonical_url, url_hash, title, content_hash)
           SELECT id, 'https://example.org/' || gen_random_uuid(), gen_random_uuid()::text,
                  'Item', 'h' FROM s RETURNING id)
INSERT INTO item_term (item_id, term_id, assigned_by) SELECT id, '{term}', 'user' FROM i;
""",
    )


async def test_terms_tree_flat_rules_and_soft_delete(
    admin: httpx.AsyncClient, postgres: Postgres, db_url: str
) -> None:
    await admin.post(_api("/taxonomy/facets"),
                     json={"key": "enforcement_body", "label": "Enforcement body",
                           "value_type": "term"})  # fmt: skip
    terms = _api("/taxonomy/facets/enforcement_body/terms")
    root = (await admin.post(terms, json={"key": "eu", "label": "EU bodies"})).json()
    synonyms = [" European  Data Protection Board ", "european data protection board", ""]
    edpb = {"key": "edpb", "label": "EDPB", "parent_id": root["id"], "synonyms": synonyms}
    child = await admin.post(terms, json=edpb)
    assert child.status_code == 201, child.text
    assert child.json()["synonyms"] == ["European Data Protection Board"]
    third = (await admin.post(terms, json={"key": "cnil", "label": "CNIL"})).json()

    tree = (await admin.get(terms)).json()
    assert [t["key"] for t in tree] == ["cnil", "eu"]
    eu = next(t for t in tree if t["key"] == "eu")
    assert [c["key"] for c in eu["children"]] == ["edpb"]
    assert len((await admin.get(terms, params={"flat": True})).json()) == 3

    cycle = await admin.patch(_api(f"/taxonomy/terms/{root['id']}"),
                              json={"parent_id": child.json()["id"]})  # fmt: skip
    assert cycle.status_code == 422
    topic = (await admin.get(_api("/taxonomy/facets/topic/terms"), params={"flat": True})).json()
    other = await admin.patch(_api(f"/taxonomy/terms/{third['id']}"),
                              json={"parent_id": topic[0]["id"]})  # fmt: skip
    assert other.status_code == 422  # parent from another facet
    for rules in ({"regex": ["(a+)+$"]}, {"regex": ["("]}, {"min_hits": 0}, {"weight": 0},
                  {"keywords": ["x" * 201]}):  # fmt: skip
        resp = await admin.patch(
            _api(f"/taxonomy/terms/{third['id']}"), json={"match_rules": rules}
        )
        assert resp.status_code == 422, rules
    ok = {"keywords": ["CNIL"], "regex": [r"\bdélibération\b"], "min_hits": 1, "weight": 1.5}
    resp = await admin.patch(_api(f"/taxonomy/terms/{third['id']}"), json={"match_rules": ok})
    assert resp.status_code == 200 and resp.json()["match_rules"]["weight"] == 1.5
    assert (await admin.post(terms, json={"key": "cnil", "label": "Again"})).status_code == 409
    assert (await admin.post(terms, json={"key": "Bad Key", "label": "X"})).status_code == 422

    _tag_item(postgres, db_url, third["id"])
    flat = {t["key"]: t for t in (await admin.get(terms, params={"flat": True})).json()}
    assert flat["cnil"]["item_count"] == 1
    assert (await admin.delete(_api(f"/taxonomy/terms/{third['id']}"))).status_code == 204
    keys = [t["key"] for t in (await admin.get(terms, params={"flat": True})).json()]
    assert "cnil" not in keys  # deactivated, still referenced
    everything = (await admin.get(terms, params={"flat": True, "include_inactive": True})).json()
    assert next(t for t in everything if t["key"] == "cnil")["active"] is False
    assert (await admin.delete(_api("/taxonomy/facets/enforcement_body"))).status_code == 409

    assert (await admin.delete(_api(f"/taxonomy/terms/{root['id']}"))).status_code == 204
    tree = (await admin.get(terms)).json()
    assert [t["key"] for t in tree] == ["edpb"]  # the child moved up
    text_facet = {"key": "notes", "label": "Notes", "value_type": "text"}
    await admin.post(_api("/taxonomy/facets"), json=text_facet)
    no_terms = await admin.post(
        _api("/taxonomy/facets/notes/terms"), json={"key": "a", "label": "A"}
    )
    assert no_terms.status_code == 422
    audit = (await admin.get(_api("/admin/audit"), params={"entity_type": "term"})).json()
    assert {"term.create", "term.update", "term.deactivate", "term.delete"} <= {
        r["action"] for r in audit["items"]
    }


async def test_merge_moves_every_reference(
    admin: httpx.AsyncClient, postgres: Postgres, db_url: str
) -> None:
    """M2 acceptance 3: merging re-tags all items and leaves no dangling references."""
    terms = _api("/taxonomy/facets/topic/terms")
    old_ai = {"key": "old-ai", "label": "Old AI", "synonyms": ["Artificial intelligence"]}
    old = (await admin.post(terms, json=old_ai)).json()
    new = (await admin.post(terms, json={"key": "new-ai", "label": "New AI"})).json()
    child = (await admin.post(terms, json={"key": "ai-sub", "label": "Sub",
                                           "parent_id": old["id"]})).json()  # fmt: skip
    _tag_item(postgres, db_url, old["id"])
    _tag_item(postgres, db_url, old["id"])
    database = db_url.rsplit("/", 1)[1]
    o, n = uuid.UUID(old["id"]), uuid.UUID(new["id"])
    postgres.psql(
        database,
        f"""
INSERT INTO item_term (item_id, term_id, assigned_by, confidence)
  SELECT item_id, '{n}', 'rule', 0.4 FROM item_term WHERE term_id = '{o}' LIMIT 1;
UPDATE item SET attributes = '{{"topic": ["old-ai", "new-ai", "other"]}}';
UPDATE source SET default_term_ids = ARRAY['{o}'::uuid, '{n}'::uuid];
""",
    )

    merge = _api(f"/taxonomy/terms/{old['id']}/merge")
    assert (await admin.post(merge, json={"into_term_id": old["id"]})).status_code == 422
    assert (await admin.post(merge, json={"into_term_id": child["id"]})).status_code == 422
    resp = await admin.post(merge, json={"into_term_id": new["id"]})
    assert resp.status_code == 200 and resp.json() == {"items_moved": 2}

    left = postgres.psql(
        database,
        f"""
SELECT (SELECT count(*) FROM item_term WHERE term_id = '{o}'),
       (SELECT count(*) FROM item_term WHERE term_id = '{n}'),
       (SELECT max(confidence) FROM item_term WHERE term_id = '{n}'),
       (SELECT count(*) FROM item WHERE attributes::text LIKE '%old-ai%'),
       (SELECT string_agg(DISTINCT array_to_string(default_term_ids, ','), ';') FROM source),
       (SELECT count(*) FROM term WHERE id = '{o}');
""",
    ).strip()
    dangling, tagged, confidence, attrs, defaults, gone = left.split("|")
    assert (dangling, tagged, attrs, gone) == ("0", "2", "0", "0")
    assert float(confidence) == 1.0 and defaults == str(n)
    flat = {t["key"]: t for t in (await admin.get(terms, params={"flat": True})).json()}
    assert flat["ai-sub"]["parent_id"] == new["id"]
    assert {"Old AI", "Artificial intelligence"} <= set(flat["new-ai"]["synonyms"])


async def test_rule_test_endpoint(admin: httpx.AsyncClient) -> None:
    terms = _api("/taxonomy/facets/topic/terms")
    rules = {"keywords": ["ransomware", "incident reporting"]}
    term = (await admin.post(terms, json={"key": "ir", "label": "Incident reporting",
                                          "match_rules": rules})).json()  # fmt: skip
    test = _api(f"/taxonomy/terms/{term['id']}/test-rules")
    hit = (await admin.post(test, json={"text": "Ransomware incident reporting rules"})).json()
    assert hit["matched"] is True and hit["confidence"] == 0.7 and hit["evidence"]
    miss = (await admin.post(test, json={"text": "Nothing relevant"})).json()
    assert miss == {"matched": False, "confidence": 0.0, "evidence": []}
