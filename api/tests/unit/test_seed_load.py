"""Unit: seed files parse, agree with the contracts and the sources, and errors are caught."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from regwatch.core import seed

API_DIR = Path(__file__).resolve().parents[2]
SEED_DIR = API_DIR / "seed"
CONTRACT = API_DIR.parent / "docs" / "contracts" / "registries.yaml"


@pytest.fixture(scope="module")
def data() -> seed.SeedData:
    return seed.load(SEED_DIR)


def test_registry_copy_matches_contract() -> None:
    assert (SEED_DIR / "registries.yaml").read_bytes() == CONTRACT.read_bytes()


def test_registry_text_is_rejoined_where_yaml_split_it(data: seed.SeedData) -> None:
    assert data.permissions["items.read"]["description"] == "Read items, versions, diffs and search"
    assert data.feature_flags["outputs.email"] == {
        "description": "Enable email delivery, default true",
        "enabled": True,
    }
    enabled = sorted(k for k, v in data.feature_flags.items() if v["enabled"])
    assert enabled == ["capture.js_rendering", "outputs.email", "reports.builder"]


def test_registry_counts(data: seed.SeedData) -> None:
    assert (len(data.permissions), len(data.roles), len(data.settings)) == (24, 4, 43)  # BL-148
    assert data.roles["admin"] == ["*"]
    assert data.settings["map.default_period_days"] == 30
    assert data.settings["outputs.allowed_recipient_domains"] == []


def test_jurisdictions(data: seed.SeedData) -> None:
    j = data.jurisdictions
    assert len(j) == 255
    assert all(isinstance(code, str) for code in j)  # "NO" stays Norway, not False
    assert j["NO"]["geometry_ref"] == "NOR"
    assert j["CN"] == {
        "code": "CN", "name": "People's Republic of China", "kind": "country",
        "region_code": "030", "geometry_ref": "CHN",
    }  # fmt: skip
    assert j["AU"]["geometry_ref"] == "AUS"
    assert j["GF"]["geometry_ref"] is None  # drawn inside France (ADR-0004)
    supranational = sorted(c for c, v in j.items() if v["kind"] == "supranational")
    assert supranational == ["COE", "EU", "INTL", "OECD", "UN"]
    assert all(re.fullmatch(r"\d{3}", v.get("region_code") or "000") for v in j.values())


def test_facets_and_terms(data: seed.SeedData) -> None:
    expected = {
        "topic",
        "industry",
        "technology",
        "regulation_type",
        "control_framework",
        "effective_date",
    }  # the M4 date facet (owner decision 2026-11-19)
    assert set(data.facets) == expected
    for key, terms in data.terms.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]{1,40}", key)
        for term in terms:
            assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,60}", term["key"]), term
    topics = {t["key"] for t in data.terms["topic"]}
    assert {"supply-chain-security", "ai-governance"} <= topics and len(topics) == 14
    sc = next(t for t in data.terms["topic"] if t["key"] == "supply-chain-security")
    assert "SBOM" in sc["match_rules"]["keywords"]
    cf = data.terms["control_framework"]
    assert [t["key"] for t in cf if "parent" not in t] == ["gv", "id", "pr", "de", "rs", "rc"]
    assert len(cf) == 28
    assert "id-be" not in {t["key"] for t in cf}  # withdrawn CSF 1.1 category
    assert data.facets["control_framework"]["system"] is False
    assert {t["key"] for t in data.terms["regulation_type"]} >= {"enforcement_action"}


def _write(tmp: Path, name: str, doc: dict[str, Any]) -> None:
    (tmp / name).write_text(yaml.safe_dump(doc), encoding="utf-8")


FACET = {"key": "topic", "label": "Topic", "terms": [{"key": "a", "label": "A"}]}


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({}, "no seed files"),
        ({"a.yaml": {"other": 1}}, "unknown top-level keys"),
        ({"a.yaml": {"facets": [FACET]}, "b.yaml": {"facets": [FACET]}}, "duplicate facet"),
        ({"a.yaml": {"roles": {"viewer": ["nope"]}}}, "unknown permissions"),
        (
            {"a.yaml": {"jurisdictions": [{"code": "FR"}, {"code": "FR"}]}},
            "duplicate jurisdiction",
        ),
        (
            {
                "a.yaml": {
                    "facets": [{**FACET, "terms": [{"key": "b", "label": "B", "parent": "x"}]}]
                }
            },  # noqa: E501
            "unknown or later parent",
        ),
        (
            {"a.yaml": {"facets": [{**FACET, "terms": [FACET["terms"][0]] * 2}]}},  # type: ignore[index]
            "duplicate term",
        ),
    ],
)
def test_inconsistent_seed_files_are_rejected(
    tmp_path: Path, files: dict[str, dict[str, Any]], message: str
) -> None:
    for name, doc in files.items():
        _write(tmp_path, name, doc)
    with pytest.raises(seed.SeedError, match=message):
        seed.load(tmp_path)


def test_main_reports_counts(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(seed_dir: Path, url: str) -> dict[str, int]:
        seen.update(dir=seed_dir, url=url)
        return {"permission": 23, "term": 0}

    monkeypatch.setattr(seed, "run", fake_run)
    assert seed.main(["--dir", "x"]) == 0
    assert seen == {"dir": Path("x"), "url": valid_env["REGWATCH_DATABASE_URL"]}
    assert capsys.readouterr().out.strip() == "regwatch-seed: permission +23, term +0"


def test_main_reports_seed_errors(
    valid_env: dict[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed.main(["--dir", str(tmp_path)]) == 1
    assert "no seed files" in capsys.readouterr().err


def test_seed_entrypoint_exits_with_main_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from regwatch.core import entrypoints

    monkeypatch.setattr(seed, "main", lambda argv: 0)
    with pytest.raises(SystemExit) as exc:
        entrypoints.seed()
    assert exc.value.code == 0


def test_packaged_registry_matches_contract() -> None:
    from importlib.resources import files

    packaged = files("regwatch.core").joinpath("registries.yaml").read_bytes()
    assert packaged == CONTRACT.read_bytes()


def test_registry_setting_definitions() -> None:
    from regwatch.core import registry

    defs = registry.settings()
    assert {d.type for d in defs.values()} <= registry.SETTING_TYPES
    assert defs["map.projection"].values == ("equal-earth", "mercator")
    assert defs["auth.lockout_threshold"].default == 10
    assert defs["general.contact_email"].note == "used in the crawler User-Agent and footers"
    assert "users.manage" in registry.permission_keys()


FEED = {
    "key": "test-feed",
    "name": "Test feed",
    "summary": "A feed for tests.",
    "kind": "rss",
    "url": "https://example.org/feed.xml",
    "jurisdictions": ["FR"],
    "config": {"feed_url": "https://example.org/feed.xml"},
    "job": {"interval_seconds": 3600},
}
PLACES = {"jurisdictions": [{"code": "FR", "name": "France", "kind": "country"}]}


def test_the_catalogue_is_checked_like_a_new_source(data: seed.SeedData) -> None:
    """CP-25: every entry passes the checks an admin's new source gets, short of DNS."""
    assert set(data.catalogue) == {
        "us-federal-register-it", "eu-eurlex-cellar-it", "eu-eurlex-rss-ep-council",
        "gb-legislation-it",
    }  # fmt: skip
    for key, entry in data.catalogue.items():
        assert entry["catalogue_key"] == key and entry["summary"] and entry["terms_url"]
        assert "enabled" not in entry and "enabled" not in entry["job"]  # the seed decides
        assert "npc.gov.cn" not in str(entry)  # R-03 C15: never captured


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"key": "Bad Key"}, "lower-case letters"),
        ({"owner": "x"}, "unknown fields"),
        ({"summary": ""}, "a summary of 1 to 300"),
        ({"summary": "x" * 301}, "a summary of 1 to 300"),
        ({"summary": "bad‮text"}, "a summary of 1 to 300"),
        ({"jurisdictions": "FR"}, "list of codes"),
        ({"jurisdictions": ["ZZ"]}, "unknown jurisdictions"),
        ({"config": {"feed_url": "ftp://example.org/x"}}, "not valid"),
        ({"config": {"feed_url": "http://example.org/x"}}, "not valid"),
        ({"url": "javascript:alert(1)"}, "not valid"),
        ({"kind": "teleport"}, "the kind is one of"),
        ({"kind": "web_crawl"}, "the kind is one of"),
        (
            {
                "job": {
                    "interval_seconds": 3600,
                    "max_items_per_run": 2000,
                    "rate_limit_per_minute": 1,
                }
            },
            "not valid",
        ),  # fmt: skip
    ],
)
def test_bad_catalogue_entries_are_rejected(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    _write(tmp_path, "a.yaml", {**PLACES, "catalogue": [{**FEED, **change}]})
    with pytest.raises(seed.SeedError, match=message):
        seed.load(tmp_path)


def test_catalogue_keys_are_unique(tmp_path: Path) -> None:
    _write(tmp_path, "a.yaml", {**PLACES, "catalogue": [FEED, FEED]})
    with pytest.raises(seed.SeedError, match="duplicate catalogue key"):
        seed.load(tmp_path)
    _write(tmp_path, "a.yaml", {**PLACES, "catalogue": [FEED]})
    _write(tmp_path, "b.yaml", {"catalogue": [FEED]})
    with pytest.raises(seed.SeedError, match="duplicate catalogue entry"):
        seed.load(tmp_path)
