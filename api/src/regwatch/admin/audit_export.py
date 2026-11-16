"""CSV export of the audit log (CP-10; 8.2: the export is an admin action, so it is audited).

Every field is quoted with quotes doubled (RFC 4180). A value a spreadsheet would read as a
formula (starting, after any whitespace, with ``=``, ``+``, ``-``, ``@`` or their full-width
forms, or starting with a tab, carriage return or line feed) gets a leading apostrophe, so
opening the file runs nothing. The export stops at ``MAX_ROWS`` rows or ``MAX_BYTES`` bytes,
whichever comes first; the ``X-Export-Truncated`` response header says whether it did.
"""

from __future__ import annotations

import json
import re
from typing import Any

from regwatch.admin.schemas import AuditEntry

MAX_ROWS = 10_000
MAX_BYTES = 20 * 1024 * 1024
COLUMNS = (
    "id", "occurred_at", "actor_email", "actor_user_id", "action", "entity_type", "entity_id",
    "ip", "request_id", "before", "after",
)  # fmt: skip
_FORMULA = re.compile(r"^\s*[=+\-@＝＋－＠]|^[\t\r\n]")


def field(value: Any) -> str:  # noqa: ANN401 - any JSON
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    if _FORMULA.match(text):
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


class CsvBuilder:
    """Collects CSV lines until ``MAX_ROWS`` rows or ``MAX_BYTES`` bytes; ``add`` says when full."""

    def __init__(self) -> None:
        self.lines = [",".join(COLUMNS)]
        self.size = len(self.lines[0]) + 2
        self.rows = 0

    def add(self, entry: AuditEntry) -> bool:
        if self.rows >= MAX_ROWS:
            return False
        data = entry.model_dump(mode="json")
        line = ",".join(field(data.get(c)) for c in COLUMNS)
        if self.size + len(line.encode()) + 2 > MAX_BYTES:
            return False
        self.lines.append(line)
        self.size += len(line.encode()) + 2
        self.rows += 1
        return True

    def text(self) -> str:
        return "\r\n".join(self.lines) + "\r\n"


def to_csv(entries: list[AuditEntry]) -> tuple[str, int, bool]:
    """The CSV text, the number of entries written, and whether a cap cut it short."""
    out = CsvBuilder()
    cut = any(not out.add(e) for e in entries)
    return out.text(), out.rows, cut
