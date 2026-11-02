"""Synthetic generator and security payload files (issue #12, REQ-25)."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from tests.fixtures.synthetic import generate as syn
from tests.support import payloads


def test_generator_is_deterministic(tmp_path: Path) -> None:
    a = syn.generate(2000, tmp_path / "a")
    b = syn.generate(2000, tmp_path / "b")
    c = syn.generate(2000, tmp_path / "c", seed=43)
    assert a.sha256 == b.sha256
    assert a.sha256["item.copy"] != c.sha256["item.copy"]
    assert (tmp_path / "a" / "load.sql").exists() and (tmp_path / "a" / "manifest.json").exists()


def test_generator_rows_and_distributions(tmp_path: Path) -> None:
    stats = syn.generate(20_000, tmp_path)
    assert stats.rows["item.copy"] == 20_000
    assert stats.rows["jurisdiction.stage"] == 250
    rows = (tmp_path / "item.copy").read_text(encoding="utf-8").splitlines()
    assert all(len(r.split("\t")) == 13 for r in rows)
    codes = Counter(line.split("\t")[1] for line in (tmp_path / "item_jurisdiction.stage").open())
    assert codes.most_common(1)[0][0] == "US", "skewed towards the most active jurisdiction"
    assert len(codes) > 150, "long tail reaches most of the 250 jurisdictions"
    sev = Counter(line.split("\t")[5] for line in (tmp_path / "change_event.stage").open())
    assert sev["info"] > sev["notable"] > sev["major"] > 0
    published = sorted(r.split("\t")[8] for r in rows)
    assert published[len(published) // 2] > "2024-11", "dates are denser towards the present"


def test_generator_uses_only_seed_taxonomy_keys(tmp_path: Path) -> None:
    import json

    syn.generate(3000, tmp_path)
    facets = json.loads(syn.TAXONOMY.read_text(encoding="utf-8"))["facets"]
    known = {(f, t["key"]) for f, terms in facets.items() for t in terms}
    used = {tuple(line.split("\t")[1:3]) for line in (tmp_path / "item_term.stage").open()}
    assert used <= known


def test_copy_escaping() -> None:
    assert syn._esc("a\tb\nc\\d") == "a\\tb\\nc\\\\d"
    assert syn._esc(None) == r"\N"


@pytest.mark.parametrize("category", payloads.CATEGORIES)
def test_payload_files_load(category: str) -> None:
    items = payloads.load(category)
    assert len(items) >= 10
    assert len(set(items)) == len(items), "no duplicate payloads"


def test_escaped_payloads_carry_control_characters() -> None:
    assert any("\r\n" in p for p in payloads.load("email_header"))
    assert any("​" in p for p in payloads.load("prompt_injection"))
    assert any(p.startswith("\t=") for p in payloads.load("csv_formula"))
    assert any("<script>" in p for p in payloads.load("xss"))


def test_csv_payloads_survive_a_round_trip(tmp_path: Path) -> None:
    rows = [[p] for p in payloads.load("csv_formula")]
    path = tmp_path / "out.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    with path.open(newline="", encoding="utf-8") as fh:
        assert list(csv.reader(fh)) == rows


def test_oversized_payloads_are_built_to_length() -> None:
    specs = payloads.oversized_specs()
    assert "captured_body_10mb_plus_1" in specs and "query_q_501" in specs
    for name, (length, _) in specs.items():
        if length <= 1_000_000:
            assert len(payloads.oversized(name)) == length, name
    assert payloads.oversized("multibyte_emoji_100k")[0] == "\U0001f512"


def test_decode_escapes_and_bad_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert payloads.decode_escapes(r"a\nb\\nA\U0001F512") == "a\nb\\nA\U0001f512"
    (tmp_path / "bad.txt").write_text("# no encoding line\npayload\n", encoding="utf-8")
    monkeypatch.setattr(payloads, "PAYLOAD_DIR", tmp_path)
    payloads.load.cache_clear()
    try:
        with pytest.raises(ValueError, match="encoding"):
            payloads.load("bad")
    finally:
        payloads.load.cache_clear()
