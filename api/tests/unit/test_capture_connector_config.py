"""Connector configuration models agree with docs/contracts/connectors.yaml (M3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from regwatch.capture.connectors import base
from regwatch.capture.connectors.config import (
    CONFIGS,
    ExtractionRules,
    validate_config,
    validate_rules,
)
from regwatch.core.errors import ProblemError

CONTRACT = yaml.safe_load(
    (Path(__file__).resolve().parents[3] / "docs/contracts/connectors.yaml").read_text()
)


def _schema(model: type) -> dict[str, Any]:
    return model.model_json_schema()  # type: ignore[attr-defined, no-any-return]


@pytest.mark.parametrize("kind", sorted(CONFIGS))
def test_each_config_model_matches_the_contract(kind: str) -> None:
    contract = CONTRACT[kind]["config"]
    schema = _schema(CONFIGS[kind])
    assert set(schema["properties"]) == set(contract["properties"])
    assert set(schema.get("required", [])) == set(contract.get("required", []))
    assert schema.get("additionalProperties") is False
    for name, spec in contract["properties"].items():
        got = schema["properties"][name]
        for key in ("default", "maximum", "minimum", "maxLength", "minItems", "maxItems"):
            if key in spec:
                assert got.get(key) == spec[key], f"{kind}.{name}.{key}"
        if "enum" in spec:
            assert got.get("enum") == spec["enum"], f"{kind}.{name}.enum"


def test_every_contract_kind_has_a_model() -> None:
    kinds = {k for k, v in CONTRACT.items() if isinstance(v, dict) and "config" in v}
    assert kinds == set(CONFIGS)


def test_extraction_rules_match_the_contract() -> None:
    contract = CONTRACT["common_extraction_rules"]
    schema = _schema(ExtractionRules)
    assert set(schema["properties"]) == set(contract["properties"])
    for name, spec in contract["properties"].items():
        if "default" in spec:
            assert schema["properties"][name].get("default") == spec["default"], name


def test_valid_configs_parse_with_defaults() -> None:
    rss = validate_config("rss", {"feed_url": "https://example.org/feed.xml"})
    assert rss.max_entries == 100 and rss.fetch_full_page is True  # type: ignore[attr-defined]
    crawl = validate_config("web_crawl", {"seed_urls": ["https://example.org/"],
                                          "allowed_domains": ["example.org"]})  # fmt: skip
    assert crawl.max_depth == 3  # type: ignore[attr-defined]
    assert validate_rules({}).min_text_length == 200


@pytest.mark.parametrize(
    ("kind", "config", "field"),
    [
        ("rss", {}, "config.feed_url"),
        ("rss", {"feed_url": "not a url"}, "config.feed_url"),
        ("rss", {"feed_url": "https://e.org/", "max_entries": 5000}, "config.max_entries"),
        ("rss", {"feed_url": "https://e.org/", "surprise": 1}, "config.surprise"),
        ("web_crawl", {"seed_urls": [], "allowed_domains": ["e.org"]}, "config.seed_urls"),
        ("search_query", {"query": "x" * 501}, "config.query"),
        ("api_feed", {"provider": "unknown"}, "config.provider"),
        ("web_page", {"page_url": "https://e.org/", "mode": "other"}, "config.mode"),
    ],
)
def test_invalid_configs_name_the_field(kind: str, config: dict[str, Any], field: str) -> None:
    with pytest.raises(ProblemError) as exc:
        validate_config(kind, config)
    assert exc.value.status == 422
    assert field in [e.field for e in exc.value.errors or []]


def test_unknown_kinds_and_bad_rules_are_refused() -> None:
    with pytest.raises(ProblemError, match="Unknown source kind"):
        validate_config("ftp", {})
    with pytest.raises(ProblemError) as exc:
        validate_rules({"min_text_length": "long", "extra": True})
    fields = {e.field for e in exc.value.errors or []}
    assert {"extraction_rules.min_text_length", "extraction_rules.extra"} <= fields


def test_the_registry_holds_one_connector_per_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "REGISTRY", {})

    class Fake:
        kind = "rss"
        config_schema = CONFIGS["rss"]

    assert base.register(Fake()) is not None  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already registered"):
        base.register(Fake())  # type: ignore[arg-type]
