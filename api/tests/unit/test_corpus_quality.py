"""M4 corpus quality (roadmap 4.9; M4 test plan: the chain on a 200-document fixture corpus with
expected tags, precision and recall reported, a floor of 0.8 precision for rules).

Jurisdictions: ``geotag.detect`` with no source defaults. Rules: ``taxonomy.rules.evaluate`` with
the representative keyword lists of ``corpus/rules.yaml`` at the default minimum confidence.
The numbers are printed (``-s``) and recorded in docs/evidence/phase-2/M4-corpus-quality.md.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import yaml

from regwatch.processing import geotag
from regwatch.processing.classify import MIN_CONFIDENCE
from regwatch.taxonomy.rules import evaluate

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "corpus"


def documents() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CORPUS.glob("[0-9]*.json"))]


def score(tp: int, fp: int, fn: int) -> tuple[float, float]:
    return (tp / (tp + fp) if tp + fp else 1.0), (tp / (tp + fn) if tp + fn else 1.0)


def test_jurisdictions_on_the_corpus() -> None:
    tp = fp = fn = 0
    for doc in documents():
        got = {h.code for h in geotag.detect(doc["title"], doc["text"], doc["url"], [])}
        want = set(doc["expected"]["jurisdictions"])
        tp, fp, fn = tp + len(got & want), fp + len(got - want), fn + len(want - got)
    precision, recall = score(tp, fp, fn)
    print(f"jurisdictions: precision {precision:.3f}, recall {recall:.3f} ({tp} {fp} {fn})")
    assert len(documents()) == 200
    assert precision >= 0.9 and recall >= 0.85


def test_rule_precision_is_at_least_the_floor() -> None:
    rules: dict[str, dict[str, Any]] = yaml.safe_load((CORPUS / "rules.yaml").read_text())
    total = [0, 0, 0]
    for facet, terms in rules.items():
        for key, spec in terms.items():
            spec = spec if isinstance(spec, dict) else {"keywords": spec}
            rule = {"keywords": spec["keywords"], "regex": [], "languages": [],
                    "min_hits": spec.get("min_hits", 1), "weight": 1.0}  # fmt: skip
            tp = fp = fn = 0
            for doc in documents():
                found = evaluate(rule, f"{doc['title']}\n{doc['text']}", doc["language"])
                hit = found.matched and found.confidence >= MIN_CONFIDENCE
                want = key in doc["expected"]["terms"].get(facet, [])
                tp, fp, fn = tp + (hit and want), fp + (hit and not want), fn + (want and not hit)
            precision, recall = score(tp, fp, fn)
            print(f"{facet}.{key}: precision {precision:.2f}, recall {recall:.2f}")
            total = [total[0] + tp, total[1] + fp, total[2] + fn]
    precision, recall = score(*total)
    print(f"rules overall: precision {precision:.3f}, recall {recall:.3f}")
    assert precision >= 0.8
