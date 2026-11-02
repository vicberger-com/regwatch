r"""Deterministic synthetic data for performance tests (issue #12, REQ-25; fixtures.md).

Writes PostgreSQL COPY text files for N items across 250 jurisdictions, with skewed
jurisdiction, topic, date and severity distributions, plus ``load.sql`` for psql. The same
seed and N give byte-identical files. Used by perf tests only; nothing here is loaded by unit
tests. Usage (from ``api/``)::

    uv run python -m tests.fixtures.synthetic.generate --items 1000000 \
        --out tests/fixtures/synthetic/out
    cd tests/fixtures/synthetic/out && psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f load.sql

``load.sql`` uses ``\copy`` with paths relative to the working directory, hence the ``cd``.
Items reference jurisdictions and terms by code and key through staging tables, so the files
load against whatever ids migration 0001 and the seed command (#28) created. Term keys are
those in ``corpus/seed_taxonomy.json`` (the #28 seed keys); rows whose key the seed lacks are
skipped and counted by ``load.sql``. Measured on 2026-11-02 against docs/contracts/schema.sql
on PostgreSQL 16: 1,000,000 items generate in 76 s and load in 294 s.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import uuid
from bisect import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import accumulate
from pathlib import Path
from typing import IO

SEED = 42
NOW = datetime(2026, 11, 1, tzinfo=UTC)
SPAN_DAYS = 5 * 365
TAXONOMY = Path(__file__).resolve().parent.parent / "corpus" / "seed_taxonomy.json"
# Not used, so that exactly 250 jurisdictions remain (245 ISO codes plus 5 supranational).
EXCLUDED_CODES = frozenset({"BV", "HM", "UM", "TF", "XK"})
# Most active first; the rest follow alphabetically. Weight of rank r is 1 / r**1.1.
TOP = [
    "US",
    "EU",
    "GB",
    "CN",
    "JP",
    "DE",
    "FR",
    "AU",
    "CA",
    "IN",
    "SG",
    "BR",
    "KR",
    "ES",
    "IT",
    "NL",
    "CH",
    "IE",
    "SE",
    "TW",
    "AE",
    "SA",
    "ZA",
    "MX",
    "NZ",
    "INTL",
    "OECD",
    "UN",
    "COE",
]
LANG = {
    "US": "en",
    "GB": "en",
    "AU": "en",
    "CA": "en",
    "IN": "en",
    "SG": "en",
    "IE": "en",
    "NZ": "en",
    "ZA": "en",
    "EU": "en",
    "INTL": "en",
    "OECD": "en",
    "UN": "en",
    "COE": "en",
    "DE": "de",
    "CH": "de",
    "AT": "de",
    "FR": "fr",
    "BE": "fr",
    "LU": "fr",
    "ES": "es",
    "MX": "es",
    "AR": "es",
    "CO": "es",
    "CL": "es",
    "PT": "pt",
    "BR": "pt",
    "JP": "ja",
    "CN": "zh",
    "TW": "zh",
    "KR": "ko",
    "IT": "it",
    "NL": "nl",
    "SE": "sv",
    "SA": "ar",
    "AE": "ar",
}
SUPRANATIONAL = {"EU", "COE", "OECD", "UN", "INTL"}
SOURCE_KINDS = [("rss", 50), ("web_page", 30), ("api_feed", 15), ("search_query", 5)]
ITEM_STATUS = [("new", 70), ("updated", 20), ("unchanged", 8), ("archived", 2)]
SEVERITY = [("info", 60), ("notable", 30), ("major", 10)]
TOPIC_WEIGHT = {
    "cybersecurity": 20,
    "data-protection": 16,
    "privacy": 10,
    "incident-reporting": 9,
    "critical-infrastructure": 8,
    "ai-governance": 8,
    "supply-chain-security": 6,
    "telecoms-security": 5,
    "cloud-outsourcing": 4,
    "cross-border-transfer": 4,
    "product-security": 4,
    "digital-identity": 3,
    "consumer-protection": 3,
    "encryption": 2,
}
FILES = (
    "jurisdiction.stage",
    "source.copy",
    "item.copy",
    "item_jurisdiction.stage",
    "item_term.stage",
    "change_event.stage",
)


class Picker:
    """Weighted choice with a precomputed cumulative table."""

    def __init__(self, items: Sequence[str], weights: Sequence[float]) -> None:
        self.items = list(items)
        self.cum = list(accumulate(weights))

    def __call__(self, rng: random.Random) -> str:
        return self.items[bisect(self.cum, rng.random() * self.cum[-1])]


def _picker(pairs: Sequence[tuple[str, float]]) -> Picker:
    return Picker([p[0] for p in pairs], [p[1] for p in pairs])


def _esc(value: object) -> str:
    """COPY text-format field."""
    if value is None:
        return r"\N"
    s = value if isinstance(value, str) else str(value)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _row(fh: IO[str], *values: object) -> None:
    fh.write("\t".join(_esc(v) for v in values) + "\n")


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S+00")


def _uuid7(rng: random.Random, at: datetime) -> str:
    ms = int(at.timestamp() * 1000) & ((1 << 48) - 1)
    rand = rng.getrandbits(74)
    value = (
        (ms << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    )
    return str(uuid.UUID(int=value))


def jurisdictions() -> list[str]:
    """The 250 jurisdiction codes, most active first."""
    data = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    codes = [c for c in data["jurisdictions"] if c not in EXCLUDED_CODES]
    rest = sorted(set(codes) - set(TOP))
    ordered = TOP + rest
    if len(ordered) != 250:
        raise RuntimeError(f"expected 250 jurisdictions, got {len(ordered)}")
    return ordered


@dataclass
class Stats:
    items: int = 0
    sources: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    sha256: dict[str, str] = field(default_factory=dict)


def generate(n_items: int, out: Path, seed: int = SEED, n_sources: int = 400) -> Stats:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data, not security
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))["facets"]
    codes = jurisdictions()
    juris_pick = Picker(codes, [1 / (r**1.1) for r in range(1, len(codes) + 1)])
    topic_pick = _picker(list(TOPIC_WEIGHT.items()))
    industry_keys = [t["key"] for t in taxonomy["industry"]]
    technology_keys = [t["key"] for t in taxonomy["technology"]]
    regtype_pick = _picker(
        [
            ("act", 10),
            ("regulation", 25),
            ("directive", 5),
            ("bill", 10),
            ("guidance", 25),
            ("standard", 5),
            ("decision", 8),
            ("enforcement_action", 7),
            ("consultation", 5),
        ]
    )
    kind_pick, status_pick, sev_pick = (
        _picker(SOURCE_KINDS),
        _picker(ITEM_STATUS),
        _picker(SEVERITY),
    )
    labels = {f: {t["key"]: t["label"] for t in terms} for f, terms in taxonomy.items()}
    out.mkdir(parents=True, exist_ok=True)
    fh = {name: (out / name).open("w", encoding="utf-8", newline="\n") for name in FILES}
    rows = dict.fromkeys(FILES, 0)
    try:
        for code in codes:
            kind = "supranational" if code in SUPRANATIONAL else "country"
            _row(fh["jurisdiction.stage"], code, code, kind)
            rows["jurisdiction.stage"] += 1

        sources: list[tuple[str, str, str]] = []
        for s in range(n_sources):
            home = juris_pick(rng)
            sid = _uuid7(rng, NOW - timedelta(days=SPAN_DAYS + 30))
            lang = LANG.get(home, "en")
            kind = kind_pick(rng)
            _row(
                fh["source.copy"],
                sid,
                f"Synthetic source {s:04d} ({home})",
                kind,
                f"https://synthetic.example.invalid/{home.lower()}/source-{s:04d}",
                "official" if rng.random() < 0.8 else "secondary",
                lang,
                "https://synthetic.example.invalid/terms",
            )
            sources.append((sid, home, lang))
        rows["source.copy"] = len(sources)
        source_pick = Picker(
            [str(i) for i in range(n_sources)], [1 / math.sqrt(i + 1) for i in range(n_sources)]
        )

        for n in range(n_items):
            sid, home, lang = sources[int(source_pick(rng))]
            age = SPAN_DAYS * (1 - math.sqrt(rng.random()))  # denser towards NOW
            published = NOW - timedelta(days=age, seconds=rng.randrange(86400))
            discovered = published + timedelta(hours=rng.randrange(1, 72))
            status = status_pick(rng)
            changed = (
                discovered + timedelta(days=rng.randrange(1, 60))
                if status == "updated"
                else discovered
            )
            changed = min(changed, NOW)
            item_id = _uuid7(rng, discovered)
            topics = sorted({topic_pick(rng) for _ in range(rng.choice((1, 1, 2, 2, 3)))})
            regtype = regtype_pick(rng)
            item_juris = [home]
            if rng.random() < 0.25:
                extra = juris_pick(rng)
                if extra not in item_juris:
                    item_juris.append(extra)
            topic_label = labels["topic"][topics[0]].lower()
            title = f"{labels['regulation_type'][regtype]} on {topic_label} ({home}) no. {n:07d}"
            summary = (
                f"Synthetic {regtype.replace('_', ' ')} covering "
                f"{', '.join(labels['topic'][t].lower() for t in topics)}."
            )
            url = f"https://synthetic.example.invalid/{home.lower()}/items/{n:07d}"
            _row(
                fh["item.copy"],
                item_id,
                sid,
                url,
                hashlib.sha256(url.encode()).hexdigest(),
                f"SYN-{n:07d}",
                title,
                summary,
                lang,
                _ts(published),
                _ts(discovered),
                _ts(changed),
                hashlib.sha256(f"{title}|{n}|{status}".encode()).hexdigest(),
                status,
            )
            rows["item.copy"] += 1
            for code in item_juris:
                _row(fh["item_jurisdiction.stage"], item_id, code, "1.000", "source_default")
                rows["item_jurisdiction.stage"] += 1
            terms = [("topic", t) for t in topics] + [("regulation_type", regtype)]
            terms += [("industry", k) for k in rng.sample(industry_keys, rng.choice((0, 1, 1, 2)))]
            terms += [
                ("technology", k) for k in rng.sample(technology_keys, rng.choice((0, 0, 1, 2)))
            ]
            for facet, key in terms:
                conf = f"{rng.uniform(0.55, 1.0):.3f}"
                _row(fh["item_term.stage"], item_id, facet, key, conf, "rule")
                rows["item_term.stage"] += 1
            severity = sev_pick(rng)
            if (
                regtype in ("act", "regulation", "directive")
                and severity == "info"
                and rng.random() < 0.3
            ):
                severity = "notable"
            events = [("new_item", discovered)]
            if status == "updated":
                events.append(("content_changed", changed))
            if rng.random() < 0.03:
                events.append(("status_changed", min(changed + timedelta(days=7), NOW)))
            if rng.random() < 0.05:
                events.append(("effective_date_reached", min(published + timedelta(days=180), NOW)))
            for kind, at in events:
                for code in item_juris:
                    _row(
                        fh["change_event.stage"],
                        _uuid7(rng, at),
                        item_id,
                        code,
                        kind,
                        _ts(at),
                        severity if kind != "status_changed" else "notable",
                        f"{kind}: {title}",
                    )
                    rows["change_event.stage"] += 1
    finally:
        for f in fh.values():
            f.close()
    (out / "load.sql").write_text(LOAD_SQL, encoding="utf-8")
    stats = Stats(items=n_items, sources=n_sources, rows=rows)
    for name in FILES:
        stats.sha256[name] = hashlib.sha256((out / name).read_bytes()).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps({"seed": seed, "items": n_items, "rows": rows, "sha256": stats.sha256}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return stats


LOAD_SQL = r"""-- Generated by tests/fixtures/synthetic/generate.py (issue #12).
-- Run with psql from this directory:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f load.sql
\timing on
BEGIN;
CREATE TEMP TABLE stage_jurisdiction (code text, name text, kind text);
\copy stage_jurisdiction FROM 'jurisdiction.stage'
INSERT INTO jurisdiction (code, name, kind)
  SELECT code, name, kind FROM stage_jurisdiction ON CONFLICT (code) DO NOTHING;
\copy source (id, name, kind, url, credibility, language, terms_url) FROM 'source.copy'
\copy item (id, source_id, canonical_url, url_hash, external_id, title, summary, language, published_at, discovered_at, last_changed_at, content_hash, status) FROM 'item.copy'
CREATE TEMP TABLE stage_item_jurisdiction
  (item_id uuid, code text, confidence numeric, assigned_by text);
\copy stage_item_jurisdiction FROM 'item_jurisdiction.stage'
INSERT INTO item_jurisdiction (item_id, jurisdiction_id, confidence, assigned_by)
  SELECT s.item_id, j.id, s.confidence, s.assigned_by
  FROM stage_item_jurisdiction s JOIN jurisdiction j ON j.code = s.code;
CREATE TEMP TABLE stage_item_term
  (item_id uuid, facet_key text, term_key text, confidence numeric, assigned_by text);
\copy stage_item_term FROM 'item_term.stage'
INSERT INTO item_term (item_id, term_id, confidence, assigned_by)
  SELECT s.item_id, t.id, s.confidence, s.assigned_by
  FROM stage_item_term s
  JOIN facet f ON f.key = s.facet_key
  JOIN term t ON t.facet_id = f.id AND t.key = s.term_key
  ON CONFLICT DO NOTHING;
SELECT count(*) AS item_term_rows_skipped_unknown_key
  FROM stage_item_term s
  LEFT JOIN facet f ON f.key = s.facet_key
  LEFT JOIN term t ON t.facet_id = f.id AND t.key = s.term_key
  WHERE t.id IS NULL;
CREATE TEMP TABLE stage_change_event (id uuid, item_id uuid, code text, kind text,
  occurred_at timestamptz, severity text, summary text);
\copy stage_change_event FROM 'change_event.stage'
INSERT INTO change_event (id, item_id, jurisdiction_id, kind, occurred_at, severity, summary)
  SELECT s.id, s.item_id, j.id, s.kind, s.occurred_at, s.severity, s.summary
  FROM stage_change_event s JOIN jurisdiction j ON j.code = s.code;
COMMIT;
ANALYZE;
"""  # noqa: E501 - psql meta-commands must stay on one line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write synthetic COPY files (seed 42)")
    parser.add_argument("--items", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    args = parser.parse_args(argv)
    stats = generate(args.items, args.out, args.seed)
    print(json.dumps({"out": str(args.out), "rows": stats.rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
