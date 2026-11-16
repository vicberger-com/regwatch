"""CP-10: the audit export's CSV is quoted, defuses formulas and stops at its caps."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from regwatch.admin import audit_export
from regwatch.admin.schemas import AuditEntry


def entry(**kw: object) -> AuditEntry:
    base = {"id": uuid.uuid4(), "occurred_at": datetime(2026, 11, 16, tzinfo=UTC),
            "action": "role.update", "entity_type": "role"}  # fmt: skip
    return AuditEntry(**{**base, **kw})


def test_fields_are_quoted_and_json_is_compact() -> None:
    assert audit_export.field('say "hi"') == '"say ""hi"""'
    assert audit_export.field(None) == '""'
    assert audit_export.field({"a": [1, "é"]}) == '"{""a"":[1,""é""]}"'


@pytest.mark.parametrize("value", ["=1+1", "+x", "-2", "@cmd", "  =x", "＝1", "\tx", "\rx", "\nx"])
def test_formulas_are_defused(value: str) -> None:
    assert audit_export.field(value).startswith("\"'")


def test_plain_text_is_unchanged() -> None:
    assert audit_export.field("plain text") == '"plain text"'


def test_csv_has_a_header_and_crlf_rows() -> None:
    text, rows, cut = audit_export.to_csv([entry(actor_email="=evil()")])
    lines = text.split("\r\n")
    assert lines[0].startswith("id,occurred_at,actor_email,") and rows == 1 and not cut
    assert '"\'=evil()"' in lines[1] and lines[2] == ""


def test_the_size_cap_stops_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_export, "MAX_BYTES", 600)
    big = [entry(after={"text": "x" * 200}) for _ in range(5)]
    text, rows, cut = audit_export.to_csv(big)
    assert cut and 0 < rows < 5 and len(text.encode()) <= 600
