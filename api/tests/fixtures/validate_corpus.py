"""Validate the test corpus (issue #12, REQ-25; docs/contracts/fixtures.md).

Checks every ``corpus/NNN.json`` against the corpus JSON schema (``corpus/schema.json``,
generated from :class:`CorpusDocument` so the two cannot drift), checks every expected
jurisdiction and term against the seed taxonomy, and checks the inventory rules: 200
documents numbered 001 to 200, at least 20 per required language, unique URLs, an excerpt
of at most 1,500 characters, and one ``NOTICES.md`` row per document with the same URL.

Usage (from ``api/``)::

    uv run python -m tests.fixtures.validate_corpus             # validate, exit 1 on errors
    uv run python -m tests.fixtures.validate_corpus --write-schema
    uv run python -m tests.fixtures.validate_corpus --snapshot-seed   # after #28 merges
    uv run python -m tests.fixtures.validate_corpus --taxonomy path/to/taxonomy.json

The taxonomy file has the shape of ``corpus/seed_taxonomy.json``: a snapshot (keys and labels)
of the #28 seed files ``api/seed/{taxonomy,control_framework,jurisdictions}.yaml``, taken from
their branch before #28 merged. Once ``api/seed/`` is on main, a unit test fails if the
snapshot and the seed drift apart; ``--snapshot-seed`` rewrites the snapshot from the seed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

CORPUS_DIR = Path(__file__).parent / "corpus"
SCHEMA_PATH = CORPUS_DIR / "schema.json"
TAXONOMY_PATH = CORPUS_DIR / "seed_taxonomy.json"
SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
SEED_FILES = ("taxonomy.yaml", "control_framework.yaml")
NOTICES_PATH = CORPUS_DIR / "NOTICES.md"

EXPECTED_COUNT = 200
REQUIRED_LANGUAGES = ("en", "de", "fr", "es", "pt", "ja", "zh")
MIN_PER_LANGUAGE = 20
MAX_TEXT_CHARS = 1500

# Key formats from docs/contracts/schema.sql (facet.key, term.key, jurisdiction.code).
FacetKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
TermKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,60}$")]
JurisdictionCode = Annotated[
    str, StringConstraints(pattern=r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$|^[A-Z]{2,5}$")
]
Language = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")]


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    jurisdictions: list[JurisdictionCode] = Field(min_length=1)
    terms: dict[FacetKey, Annotated[list[TermKey], Field(min_length=1)]]
    severity: Literal["info", "notable", "major"]


class CorpusDocument(BaseModel):
    """One corpus entry; field names fixed by docs/contracts/fixtures.md."""

    model_config = ConfigDict(extra="forbid", strict=True, title="regwatch corpus document")

    url: Annotated[str, StringConstraints(pattern=r"^https?://[^\s]+$", max_length=2048)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    language: Language
    published_at: datetime
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_TEXT_CHARS)]
    source_kind: Literal["rss", "web_page", "web_crawl", "search_query", "api_feed", "manual"]
    expected: Expected


def json_schema() -> dict[str, object]:
    schema = CorpusDocument.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "regwatch/tests/fixtures/corpus/schema.json"
    return schema


@dataclass
class Taxonomy:
    jurisdictions: set[str]
    facets: dict[str, set[str]]

    @classmethod
    def load(cls, path: Path) -> Taxonomy:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            jurisdictions=set(data["jurisdictions"]),
            facets={k: {t["key"] for t in terms} for k, terms in data["facets"].items()},
        )


@dataclass
class Report:
    documents: dict[str, CorpusDocument] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def languages(self) -> Counter[str]:
        return Counter(d.language for d in self.documents.values())


def _notice_urls(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (\d{3}) \|.*\| <([^>]+)> \|", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def validate(
    corpus_dir: Path = CORPUS_DIR,
    taxonomy_path: Path = TAXONOMY_PATH,
    expected_count: int = EXPECTED_COUNT,
) -> Report:
    report = Report()
    err = report.errors.append
    taxonomy = Taxonomy.load(taxonomy_path)

    files = sorted(corpus_dir.glob("*.json"))
    names = [f.stem for f in files if re.fullmatch(r"\d{3}", f.stem)]
    stray = [f.name for f in files if f.stem not in names and f.parent == corpus_dir]
    stray = [n for n in stray if n not in {SCHEMA_PATH.name, TAXONOMY_PATH.name}]
    if stray:
        err(f"unexpected JSON files: {stray}")
    wanted = [f"{n:03d}" for n in range(1, expected_count + 1)]
    if names != wanted:
        missing = sorted(set(wanted) - set(names))
        extra = sorted(set(names) - set(wanted))
        err(
            f"documents must be numbered 001 to {expected_count:03d}; "
            f"missing {missing}, extra {extra}"
        )

    for name in names:
        raw = (corpus_dir / f"{name}.json").read_text(encoding="utf-8")
        try:
            doc = CorpusDocument.model_validate_json(raw)
        except ValidationError as exc:
            for e in exc.errors():
                loc = ".".join(str(p) for p in e["loc"])
                err(f"{name}.json: {loc}: {e['msg']}")
            continue
        report.documents[name] = doc
        if doc.published_at.tzinfo is None:
            err(f"{name}.json: published_at must carry a time zone")
        for code in doc.expected.jurisdictions:
            if code not in taxonomy.jurisdictions:
                err(f"{name}.json: jurisdiction {code!r} is not in the seed taxonomy")
        if len(set(doc.expected.jurisdictions)) != len(doc.expected.jurisdictions):
            err(f"{name}.json: duplicate jurisdictions")
        if "topic" not in doc.expected.terms:
            err(f"{name}.json: expected.terms needs at least one topic")
        for facet, keys in doc.expected.terms.items():
            if facet not in taxonomy.facets:
                err(f"{name}.json: facet {facet!r} is not in the seed taxonomy")
                continue
            for key in keys:
                if key not in taxonomy.facets[facet]:
                    err(f"{name}.json: term {facet}:{key} is not in the seed taxonomy")
            if len(set(keys)) != len(keys):
                err(f"{name}.json: duplicate terms in facet {facet!r}")

    urls = Counter(d.url for d in report.documents.values())
    for url, n in urls.items():
        if n > 1:
            err(f"URL used by {n} documents: {url}")

    if expected_count == EXPECTED_COUNT:
        langs = report.languages()
        for lang in REQUIRED_LANGUAGES:
            if langs[lang] < MIN_PER_LANGUAGE:
                err(f"language {lang}: {langs[lang]} documents, need at least {MIN_PER_LANGUAGE}")

    notices_path = corpus_dir / NOTICES_PATH.name
    if not notices_path.exists():
        err("NOTICES.md is missing")
    else:
        rows = _notice_urls(notices_path)
        for name, doc in report.documents.items():
            if name not in rows:
                err(f"{name}.json: no row in NOTICES.md")
            elif rows[name] != doc.url:
                err(f"{name}.json: NOTICES.md URL {rows[name]!r} differs from {doc.url!r}")
        for name in sorted(set(rows) - set(names)):
            err(f"NOTICES.md row {name} has no document")
    return report


def snapshot_from_seed(seed_dir: Path = SEED_DIR) -> dict[str, object]:
    """Keys and labels from the #28 seed YAML, in the ``seed_taxonomy.json`` shape."""
    import yaml  # added to the api dependencies by #28

    facets: dict[str, list[dict[str, str]]] = {}
    for name in SEED_FILES:
        for facet in yaml.safe_load((seed_dir / name).read_text(encoding="utf-8"))["facets"]:
            facets[facet["key"]] = [{"key": t["key"], "label": t["label"]} for t in facet["terms"]]
    juris = yaml.safe_load((seed_dir / "jurisdictions.yaml").read_text(encoding="utf-8"))
    current = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return {
        "_comment": current["_comment"],
        "jurisdictions": sorted(j["code"] for j in juris["jurisdictions"]),
        "facets": facets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=CORPUS_DIR)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    parser.add_argument("--write-schema", action="store_true", help="regenerate corpus/schema.json")
    parser.add_argument(
        "--snapshot-seed", action="store_true", help="rewrite seed_taxonomy.json from api/seed/"
    )
    args = parser.parse_args(argv)
    if args.snapshot_seed:
        snapshot = snapshot_from_seed()
        TAXONOMY_PATH.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"wrote {TAXONOMY_PATH}")
        return 0
    if args.write_schema:
        SCHEMA_PATH.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {SCHEMA_PATH}")
        return 0
    report = validate(args.corpus, args.taxonomy)
    for line in report.errors:
        print(f"ERROR {line}", file=sys.stderr)
    langs = ", ".join(f"{k} {v}" for k, v in sorted(report.languages().items()))
    status = "ok" if report.ok else f"{len(report.errors)} errors"
    print(f"{len(report.documents)} documents ({langs}): {status}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
