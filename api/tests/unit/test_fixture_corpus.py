"""Corpus fixture: schema, taxonomy and inventory checks (issue #12, REQ-25)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.fixtures import validate_corpus as vc


def test_corpus_validates() -> None:
    report = vc.validate()
    assert report.errors == []
    assert len(report.documents) == vc.EXPECTED_COUNT


def test_every_required_language_has_twenty_documents() -> None:
    langs = vc.validate().languages()
    assert {lang: langs[lang] for lang in vc.REQUIRED_LANGUAGES} == {
        lang: max(langs[lang], 20) for lang in vc.REQUIRED_LANGUAGES
    }


def test_committed_schema_matches_the_model() -> None:
    committed = json.loads(vc.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == vc.json_schema(), (
        "run: python -m tests.fixtures.validate_corpus --write-schema"
    )


def test_taxonomy_snapshot_matches_the_seed_once_merged() -> None:
    if not (vc.SEED_DIR / "taxonomy.yaml").exists():
        pytest.skip("api/seed/ from #28 is not on this branch yet; the snapshot stands in for it")
    pytest.importorskip("yaml")
    snapshot = json.loads(vc.TAXONOMY_PATH.read_text(encoding="utf-8"))
    seed = vc.snapshot_from_seed()
    assert snapshot["jurisdictions"] == seed["jurisdictions"]
    assert snapshot["facets"] == seed["facets"], (
        "run: python -m tests.fixtures.validate_corpus --snapshot-seed"
    )


def test_cli_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert vc.main([]) == 0
    assert "200 documents" in capsys.readouterr().out


@pytest.fixture
def corpus_copy(tmp_path: Path) -> Path:
    target = tmp_path / "corpus"
    shutil.copytree(vc.CORPUS_DIR, target)
    return target


def _edit(corpus: Path, name: str, **changes: object) -> None:
    path = corpus / f"{name}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        target = doc
        *parents, leaf = key.split("__")
        for p in parents:
            target = target[p]
        target[leaf] = value
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"expected__terms": {"topic": ["quantum_widgets"]}},
            "term topic:quantum_widgets is not in",
        ),
        (
            {"expected__terms": {"colour": ["red"], "topic": ["privacy"]}},
            "facet 'colour' is not in",
        ),
        ({"expected__jurisdictions": ["XX"]}, "jurisdiction 'XX' is not in"),
        ({"expected__severity": "catastrophic"}, "expected.severity"),
        ({"source_kind": "telepathy"}, "source_kind"),
        ({"text": "x" * 1501}, "text"),
        ({"url": "ftp://example.invalid/x"}, "url"),
        ({"expected__terms": {"industry": ["finance"]}}, "needs at least one topic"),
    ],
)
def test_validator_rejects_bad_entries(
    corpus_copy: Path, changes: dict[str, object], message: str
) -> None:
    _edit(corpus_copy, "001", **changes)
    report = vc.validate(corpus_copy)
    assert any(message in e for e in report.errors), report.errors


def test_validator_rejects_unknown_fields_and_gaps(corpus_copy: Path) -> None:
    _edit(corpus_copy, "002", extra_field=True)
    (corpus_copy / "200.json").unlink()
    errors = vc.validate(corpus_copy).errors
    assert any("002.json: extra_field" in e for e in errors)
    assert any("missing ['200']" in e for e in errors)
    assert any("NOTICES.md row 200 has no document" in e for e in errors)


def test_validator_requires_matching_notice(corpus_copy: Path) -> None:
    _edit(corpus_copy, "003", url="https://example.invalid/not-in-notices")
    errors = vc.validate(corpus_copy).errors
    assert any("003.json: NOTICES.md URL" in e for e in errors)


def test_validator_flags_short_language(corpus_copy: Path) -> None:
    for path in corpus_copy.glob("[0-9]*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["language"] == "ja":
            doc["language"] = "en"
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert any("language ja: 0 documents" in e for e in vc.validate(corpus_copy).errors)


def test_every_document_has_a_licence_key_in_notices() -> None:
    rows = [
        line
        for line in vc.NOTICES_PATH.read_text(encoding="utf-8").splitlines()
        if line[:5].strip("| ").isdigit()
    ]
    assert len(rows) == vc.EXPECTED_COUNT
    assert all("| `" in row and "| 2026-11-0" in row for row in rows)
