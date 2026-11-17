"""Integration: facets and view dimensions (M2 acceptance 1; REQ-03, REQ-11)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

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
    refused = [{"regex": ["(?<=x)a"]}, {"regex": ["a*"]}, {"regex": ["("]}, {"min_hits": 0},
               {"weight": 0}, {"keywords": ["x" * 201]}]  # fmt: skip
    for rules in refused:
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


async def test_jurisdictions_and_regions(admin: httpx.AsyncClient) -> None:
    countries = (await admin.get(_api("/jurisdictions"), params={"kind": "country"})).json()
    assert len(countries) == 250 and all(j["kind"] == "country" for j in countries)
    supra = (await admin.get(_api("/jurisdictions"), params={"kind": "supranational"})).json()
    assert {j["code"] for j in supra} == {"EU", "COE", "OECD", "UN", "INTL"}
    de = (await admin.get(_api("/jurisdictions/de"))).json()
    assert de["name"] == "Germany" and de["region_code"] == "155" and de["geometry_ref"] == "DEU"
    assert (await admin.get(_api("/jurisdictions/ZZ"))).status_code == 404

    post = lambda body: admin.post(_api("/jurisdictions"), json=body)  # noqa: E731
    by = {"code": "DE-BY", "name": "Bavaria", "kind": "subdivision", "parent_code": "DE",
          "region_code": "155"}  # fmt: skip
    created = await post(by)
    assert created.status_code == 201 and created.json()["parent_code"] == "DE"
    assert (await post(by)).status_code == 409
    for bad in ({**by, "code": "FR-75", "parent_code": "DE"},
                {**by, "code": "DE-BE", "parent_code": "EU"},
                {**by, "code": "DE-BW", "parent_code": None},
                {"code": "D", "name": "X", "kind": "country"},
                {"code": "XQ", "name": "X", "kind": "country", "region_code": "999"},
                {"code": "XQ", "name": "X", "kind": "country", "geometry_ref": "../x"},
                {"code": "XQ", "name": "X\r\n", "kind": "country"},
                {"code": "XQ", "name": "X", "kind": "planet"}):  # fmt: skip
        assert (await post(bad)).status_code == 422, bad

    patch = lambda code, body: admin.patch(_api(f"/jurisdictions/{code}"), json=body)  # noqa: E731
    assert (await patch("DE-BY", {"name": "Freistaat Bayern"})).json()["name"] == "Freistaat Bayern"
    assert (await patch("DE-BY", {"code": "DE-BB"})).status_code == 422
    assert (await patch("DE-BY", {"kind": "country"})).status_code == 422
    assert (await patch("DE-BY", {"parent_code": "AT"})).status_code == 422
    assert (await patch("AQ", {"active": False})).json()["active"] is False
    inactive = (await admin.get(_api("/jurisdictions"), params={"active": False})).json()
    assert [j["code"] for j in inactive] == ["AQ"]

    regions = {r["code"]: r for r in (await admin.get(_api("/jurisdictions/regions"))).json()}
    assert len(regions) == 17 and regions["155"]["name"] == "Western Europe"
    assert {"DE", "DE-BY", "FR"} <= set(regions["155"]["jurisdiction_codes"])
    audit = (await admin.get(_api("/admin/audit"), params={"entity_type": "jurisdiction"})).json()
    assert {r["action"] for r in audit["items"]} == {"jurisdiction.create", "jurisdiction.update"}


SEED = Path(__file__).resolve().parents[2] / "seed"
YAML_HEADERS = {"content-type": "application/yaml"}


async def _import(admin: httpx.AsyncClient, document: str | bytes) -> httpx.Response:
    return await admin.post(_api("/taxonomy/import"), content=document, headers=YAML_HEADERS)


async def test_importing_the_seed_twice_changes_nothing(admin: httpx.AsyncClient) -> None:
    """M2 acceptance 2."""
    for name in ("taxonomy.yaml", "control_framework.yaml"):
        document = (SEED / name).read_bytes()
        first = await _import(admin, document)
        assert first.status_code == 200, first.text
        assert first.json()["facets_created"] == 0 and first.json()["terms_created"] == 0
        second = (await _import(admin, document)).json()
        assert second == {"facets_created": 0, "facets_updated": 0, "terms_created": 0,
                          "terms_updated": 0}, name  # fmt: skip


async def test_export_round_trip_and_new_facets(admin: httpx.AsyncClient) -> None:
    document = """
schema_version: 1
facets:
  - key: enforcement_body
    label: Enforcement body
    show_in_view_selector: true
    terms:
      - { key: eu, label: EU bodies }
      - { key: edpb, label: EDPB, parent: eu, synonyms: ["European Data Protection Board"] }
      - { key: cnil, label: CNIL, match_rules: { keywords: [CNIL], min_hits: 1, weight: 1.0 } }
"""
    created = (await _import(admin, document)).json()
    assert created == {"facets_created": 1, "facets_updated": 0, "terms_created": 3,
                       "terms_updated": 0}  # fmt: skip
    export = await admin.get(_api("/taxonomy/export"))
    assert export.status_code == 200 and export.headers["content-type"].startswith(
        "application/yaml"
    )
    assert "attachment" in export.headers["content-disposition"]
    parsed = yaml.safe_load(export.text)
    assert parsed["schema_version"] == 1
    body = next(f for f in parsed["facets"] if f["key"] == "enforcement_body")
    keys = [t["key"] for t in body["terms"]]
    assert keys.index("eu") < keys.index("edpb")  # parents first
    again = (await _import(admin, export.text)).json()
    assert set(again.values()) == {0}
    assert (await admin.get(_api("/taxonomy/export"))).text == export.text

    tree = (await admin.get(_api("/taxonomy/facets/enforcement_body/terms"))).json()
    eu = next(t for t in tree if t["key"] == "eu")
    assert [c["key"] for c in eu["children"]] == ["edpb"]
    renamed = document.replace("label: EDPB,", "label: European Data Protection Board,")
    assert (await _import(admin, renamed)).json()["terms_updated"] == 1


@pytest.mark.parametrize(
    "document",
    [
        "facets: not-a-list",
        "schema_version: 2\nfacets: []",
        "facets: []\nextra: 1",
        "facets:\n  - {key: topic, value_type: text}",
        "facets:\n  - {key: new_one, terms: [{key: a, label: A, parent: missing}]}",
        "facets:\n  - {key: new_one, terms: [{key: a, label: A, match_rules: {regex: ['a*']}}]}",
        "facets:\n  - {key: new_one, terms: [{key: 'Bad Key', label: A}]}",
        "facets:\n  - {key: new_one, colour: red}",
        "facets:\n  - {key: new_one, sort_order: true}",
        "facets:\n  - {key: region}",
        "a: &x [1]\nfacets: *x",
        "facets: [\x00]",
        b"\xff\xfe",
    ],
)  # fmt: skip
async def test_bad_imports_change_nothing(admin: httpx.AsyncClient, document: str | bytes) -> None:
    before = (await admin.get(_api("/taxonomy/export"))).text
    resp = await _import(admin, document)
    assert resp.status_code == 422, (document, resp.text)
    assert (await admin.get(_api("/taxonomy/export"))).text == before


async def test_viewers_export_but_do_not_import(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "tx@example.org", ["viewer"])
    assert (await viewer.get(_api("/taxonomy/export"))).status_code == 200
    resp = await viewer.post(_api("/taxonomy/import"), content="facets: []", headers=YAML_HEADERS)
    assert resp.status_code == 403
    await viewer.aclose()


async def test_validator_follows_taxonomy_changes(admin: httpx.AsyncClient, db_url: str) -> None:
    """M2 design notes: a facet change bumps taxonomy.version, which rebuilds the validator."""
    from regwatch.core.db import create_engine, session_factory
    from regwatch.core.errors import ProblemError
    from regwatch.taxonomy.validator import get_validator

    engine = create_engine(db_url, poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            first = await get_validator(db)
            assert (await get_validator(db)) is first  # cached while the version holds
            with pytest.raises(ProblemError):
                first.validate({"enforcement_body": "edpb"})
            assert first.validate({"topic": ["privacy"]}).values == {"topic": ["privacy"]}

        await admin.post(_api("/taxonomy/facets"),
                         json={"key": "enforcement_body", "label": "E", "value_type": "term",
                               "multi": False})  # fmt: skip
        await admin.post(_api("/taxonomy/facets/enforcement_body/terms"),
                         json={"key": "edpb", "label": "EDPB"})  # fmt: skip
        async with session_factory(engine)() as db:
            second = await get_validator(db)
            assert second is not first and second.version > first.version
            assert second.validate({"enforcement_body": "edpb"}).values == {
                "enforcement_body": "edpb"
            }
    finally:
        await engine.dispose()


# --- M2 review fixes ------------------------------------------------------------------------


BAD_TERMS = [
    "{key: a, label: A, match_rules: {regex: fine}}",
    "{key: a, label: A, match_rules: {languages: en}}",
    "{key: a, label: A, match_rules: {min_hits: true}}",
    "{key: a, label: A, match_rules: {min_hits: '2'}}",
    "{key: a, label: A, match_rules: {weight: x}}",
    "{key: a, label: A, match_rules: {extra: {deep: 1}}}",
    "{key: a, label: 123}",
    "{key: a, label: A, color_token: 5}",
    "{key: a, label: A, active: 'yes'}",
    "{key: a, label: A, parent: 7}",
    "{key: a, label: A, synonyms: [1]}",
    '{key: "a\\n", label: A}',
]


@pytest.mark.parametrize("term", BAD_TERMS)
async def test_typed_import_fields_are_422_and_reads_keep_working(
    admin: httpx.AsyncClient, term: str
) -> None:
    """Review finding 2: a badly typed import is refused and cannot break reads."""
    resp = await _import(admin, f"facets:\n  - {{key: topic, terms: [{term}]}}")
    assert resp.status_code == 422, resp.text
    assert (await admin.get(_api("/taxonomy/facets"))).status_code == 200
    assert (await admin.get(_api("/taxonomy/facets/topic/terms"))).status_code == 200


async def test_facet_fields_are_bounded(admin: httpx.AsyncClient) -> None:
    """Review findings 7 and 8."""
    post = lambda body: admin.post(_api("/taxonomy/facets"), json=body)  # noqa: E731
    base = {"key": "bounded", "value_type": "term"}
    assert (await post({**base, "label": "x\x1b[31m"})).status_code == 422
    assert (await post({**base, "label": "x" * 121})).status_code == 422
    assert (await post({**base, "label": "B", "sort_order": 99_999_999_999})).status_code == 422
    assert (await post({**base, "key": "bounded\n", "label": "B"})).status_code == 422
    big = "facets:\n  - {key: bounded, label: B, sort_order: 99999999999}"
    assert (await _import(admin, big)).status_code == 422
    jur = lambda body: admin.post(_api("/jurisdictions"), json=body)  # noqa: E731
    assert (await jur({"code": "XQ\n", "name": "X", "kind": "country"})).status_code == 422
    assert (await jur({"code": "XQ", "name": "X", "kind": "country",
                       "geometry_ref": "XQ\n"})).status_code == 422  # fmt: skip
    assert (await jur({"code": "XQ", "name": "   ", "kind": "country"})).status_code == 422


async def test_references_outside_tags_block_deletes_and_follow_renames(
    admin: httpx.AsyncClient, postgres: Postgres, db_url: str
) -> None:
    """Review finding 3: attributes and source defaults count as references."""
    terms = _api("/taxonomy/facets/topic/terms")
    kept = (await admin.post(terms, json={"key": "kept", "label": "Kept"})).json()
    renamed = (await admin.post(terms, json={"key": "renam", "label": "Renamed"})).json()
    await admin.post(_api("/taxonomy/facets"), json={"key": "notes", "label": "Notes",
                                                     "value_type": "text"})  # fmt: skip
    database = db_url.rsplit("/", 1)[1]
    _tag_item(postgres, db_url, renamed["id"])
    k = uuid.UUID(kept["id"])
    postgres.psql(
        database,
        f"""
UPDATE item SET attributes = '{{"topic": ["kept", "renam"], "notes": "free text"}}';
UPDATE source SET default_term_ids = ARRAY['{k}'::uuid];
""",
    )
    assert (await admin.delete(_api(f"/taxonomy/terms/{kept['id']}"))).status_code == 204
    everything = {t["key"]: t for t in (await admin.get(
        terms, params={"flat": True, "include_inactive": True})).json()}  # fmt: skip
    assert everything["kept"]["active"] is False  # deactivated, not deleted
    resp = await admin.patch(_api(f"/taxonomy/terms/{renamed['id']}"), json={"key": "renamed"})
    assert resp.status_code == 200
    attributes = postgres.psql(database, "SELECT attributes::text FROM item;").strip()
    assert '"renamed"' in attributes and '"renam"' not in attributes
    assert (await admin.delete(_api("/taxonomy/facets/notes"))).status_code == 409
    retype = await admin.patch(_api("/taxonomy/facets/notes"), json={"value_type": "number"})
    assert retype.status_code == 422


async def test_concurrent_merge_and_delete_keep_every_tag(
    admin: httpx.AsyncClient, postgres: Postgres, db_url: str
) -> None:
    """Review finding 4: a delete racing a merge sees the moved tags and only deactivates."""
    import asyncio

    terms = _api("/taxonomy/facets/topic/terms")
    src = (await admin.post(terms, json={"key": "race-src", "label": "Src"})).json()
    dst = (await admin.post(terms, json={"key": "race-dst", "label": "Dst"})).json()
    for _ in range(3):
        _tag_item(postgres, db_url, src["id"])
    merged, deleted = await asyncio.gather(
        admin.post(_api(f"/taxonomy/terms/{src['id']}/merge"), json={"into_term_id": dst["id"]}),
        admin.delete(_api(f"/taxonomy/terms/{dst['id']}")),
    )
    # Either order is a clean answer, never an error (BL-89): the merge first, then the delete
    # deactivates the target that now carries the tags; or the delete first, then the merge
    # finds its target gone (404).
    assert deleted.status_code == 204
    assert merged.status_code in (200, 404), merged.text
    database = db_url.rsplit("/", 1)[1]
    tags = postgres.psql(database, "SELECT count(*) FROM item_term;").strip()
    assert tags == "3"


def _lock_waiters(postgres: Postgres, database: str) -> int:
    sql = ("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
           "AND wait_event_type = 'Lock';")  # fmt: skip
    return int(postgres.psql(database, sql).strip())


def _lock_holders(postgres: Postgres, database: str) -> int:
    sql = ("SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
           "WHERE c.relname = 'facet' AND l.mode = 'RowShareLock' AND l.granted;")  # fmt: skip
    return int(postgres.psql(database, sql).strip())


async def _until(condition: Any) -> None:
    async with asyncio.timeout(10):  # the database state should appear within moments
        while not await asyncio.to_thread(condition):  # noqa: ASYNC110 - polls another process
            await asyncio.sleep(0.05)


async def _holding_the_facet_lock(url: str, facet_key: str, then_sql: str,
                                  release: asyncio.Event) -> None:  # fmt: skip
    """Hold the facet's row lock in a second connection until ``release``, then run
    ``then_sql`` in the same transaction and commit, so a waiting request resumes after it."""
    import asyncpg

    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        async with conn.transaction():
            await conn.execute("SELECT id FROM facet WHERE key = $1 FOR UPDATE", facet_key)
            await release.wait()
            await conn.execute(then_sql)
    finally:
        await conn.close()


@pytest.mark.parametrize(
    ("change", "status"),
    [("DELETE FROM term WHERE id = '{dst}'", 404),
     ("UPDATE term SET active = false WHERE id = '{dst}'", 422)],
)  # fmt: skip
async def test_a_target_removed_while_the_merge_waits_is_a_clean_answer(
    admin: httpx.AsyncClient, postgres: Postgres, db_url: str, change: str, status: int
) -> None:
    """BL-89, deterministic: the merge has read its target and waits for the facet lock while
    another transaction deletes or deactivates the target. It answers 404 or 422, moves no tag."""
    terms = _api("/taxonomy/facets/topic/terms")
    src = (await admin.post(terms, json={"key": "w-src", "label": "Src"})).json()
    dst = (await admin.post(terms, json={"key": "w-dst", "label": "Dst"})).json()
    _tag_item(postgres, db_url, src["id"])
    release = asyncio.Event()
    holder = asyncio.create_task(_holding_the_facet_lock(
        db_url, "topic", change.format(dst=uuid.UUID(dst["id"])), release))  # fmt: skip
    database = db_url.rsplit("/", 1)[1]
    await _until(lambda: _lock_holders(postgres, database) >= 1)  # the holder has the lock
    merge = asyncio.create_task(admin.post(_api(f"/taxonomy/terms/{src['id']}/merge"),
                                           json={"into_term_id": dst["id"]}))  # fmt: skip
    # The merge has read both terms and now waits on a lock: seen in PostgreSQL, not guessed.
    await _until(lambda: _lock_waiters(postgres, database) >= 1)
    assert not merge.done()
    release.set()
    await holder
    got = await merge
    assert got.status_code == status, got.text
    still = postgres.psql(
        database, f"SELECT count(*) FROM item_term WHERE term_id = '{uuid.UUID(src['id'])}';"
    )
    assert still.strip() == "1"  # nothing moved


async def test_concurrent_parent_changes_cannot_form_a_cycle(admin: httpx.AsyncClient) -> None:
    """Review finding 6."""
    import asyncio

    terms = _api("/taxonomy/facets/topic/terms")
    a = (await admin.post(terms, json={"key": "cyc-a", "label": "A"})).json()
    b = (await admin.post(terms, json={"key": "cyc-b", "label": "B"})).json()
    results = await asyncio.gather(
        admin.patch(_api(f"/taxonomy/terms/{a['id']}"), json={"parent_id": b["id"]}),
        admin.patch(_api(f"/taxonomy/terms/{b['id']}"), json={"parent_id": a["id"]}),
    )
    assert sorted(r.status_code for r in results) == [200, 422]


async def test_merge_into_an_inactive_term_is_refused(admin: httpx.AsyncClient) -> None:
    terms = _api("/taxonomy/facets/topic/terms")
    src = (await admin.post(terms, json={"key": "m-src", "label": "Src"})).json()
    dst = (await admin.post(terms, json={"key": "m-dst", "label": "Dst", "active": False})).json()
    merge = await admin.post(_api(f"/taxonomy/terms/{src['id']}/merge"),
                             json={"into_term_id": dst["id"]})  # fmt: skip
    assert merge.status_code == 422


async def test_seeding_bumped_the_taxonomy_version(admin: httpx.AsyncClient) -> None:
    """Review 12c: the seed's facets and terms count as a taxonomy change."""
    assert await _version(admin) >= 1


async def test_imports_audit_every_change_and_cap_the_size(admin: httpx.AsyncClient) -> None:
    """Review findings 11 and 5."""
    document = "facets:\n  - {key: topic, label: Topics, terms: [{key: imp-a, label: A}]}"
    assert (await _import(admin, document)).status_code == 200
    rows = (await admin.get(_api("/admin/audit"), params={"page_size": 10})).json()["items"]
    actions = {r["action"]: r for r in rows}
    assert {"taxonomy.import", "taxonomy.import.facet_update",
            "taxonomy.import.term_create"} <= set(actions)  # fmt: skip
    update = actions["taxonomy.import.facet_update"]
    assert update["before"]["label"] == "Topic" and update["after"]["label"] == "Topics"
    assert actions["taxonomy.import.term_create"]["after"]["key"] == "imp-a"

    terms = ", ".join(f"{{key: t{j}, label: T}}" for j in range(60))
    many = "facets:\n" + "".join(f"  - {{key: f{i:03d}, terms: [{terms}]}}\n" for i in range(170))
    resp = await _import(admin, many)
    assert resp.status_code == 422 and "10000 terms" in resp.text


async def test_reverify_followups(admin: httpx.AsyncClient) -> None:
    """M2 re-verification N3, N4 and N5."""
    import asyncio

    terms = _api("/taxonomy/facets/topic/terms")
    surrogate = {"key": "sur", "label": "S", "match_rules": {"keywords": ["a\ud800"]}}
    body = __import__("json").dumps(surrogate)  # httpx's json= would refuse the surrogate
    sent = await admin.post(terms, content=body, headers={"content-type": "application/json"})
    assert sent.status_code == 422
    persian = await admin.post(terms, json={"key": "fa", "label": "حریم‌خصوصی‏"})
    assert persian.status_code == 201

    one = "facets:\n  - {key: topic, label: T1}\n  - {key: industry, label: I1}"
    two = "facets:\n  - {key: industry, label: I2}\n  - {key: topic, label: T2}"
    results = await asyncio.gather(_import(admin, one), _import(admin, two))
    assert [r.status_code for r in results] == [200, 200]

    update = "facets:\n  - {key: topic, terms: [{key: fa, label: Privacy}]}"
    assert (await _import(admin, update)).json()["terms_updated"] == 1
    query = {"action": "taxonomy.import.term_update"}
    rows = (await admin.get(_api("/admin/audit"), params=query)).json()["items"]
    assert rows[0]["before"] == {"label": "حریم‌خصوصی‏"}
    assert rows[0]["after"] == {"label": "Privacy", "key": "fa", "facet": "topic"}


async def test_hierarchy_depth_is_capped(admin: httpx.AsyncClient) -> None:
    """Web re-verification N4: deep chains would break serialising GET /taxonomy/facets."""
    from regwatch.taxonomy.services import MAX_TERM_DEPTH

    terms = _api("/taxonomy/facets/topic/terms")
    parent = None
    for i in range(MAX_TERM_DEPTH):
        body = {"key": f"deep-{i}", "label": f"Deep {i}", "parent_id": parent}
        resp = await admin.post(terms, json=body)
        assert resp.status_code == 201, (i, resp.text)
        parent = resp.json()["id"]
    too_deep = await admin.post(terms, json={"key": "deep-x", "label": "X", "parent_id": parent})
    assert too_deep.status_code == 422 and "32 levels" in too_deep.text
    top = (await admin.post(terms, json={"key": "new-top", "label": "Top"})).json()
    flat = {t["key"]: t for t in (await admin.get(terms, params={"flat": True})).json()}
    move = await admin.patch(_api(f"/taxonomy/terms/{flat['deep-0']['id']}"),
                             json={"parent_id": top["id"]})  # fmt: skip
    assert move.status_code == 422  # the moved subtree would reach 33 levels
    last = f"deep-{MAX_TERM_DEPTH - 1}"
    imported = f"facets:\n  - {{key: topic, terms: [{{key: deep-y, label: Y, parent: {last}}}]}}"
    assert (await _import(admin, imported)).status_code == 422
    assert (await admin.get(_api("/taxonomy/facets"))).status_code == 200
