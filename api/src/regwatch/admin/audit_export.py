"""CSV export of the audit log (CP-10; 8.2: the export is an admin action, so it is audited).

Every field is quoted with quotes doubled (RFC 4180). A value a spreadsheet would read as a
formula (starting, after any whitespace, with ``=``, ``+``, ``-``, ``@`` or their full-width
forms, or starting with a tab, carriage return or line feed) gets a leading apostrophe, so
opening the file runs nothing. The export stops at ``MAX_ROWS`` rows or ``MAX_BYTES`` bytes,
whichever comes first, and says so in its last line.
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


def to_csv(entries: list[AuditEntry]) -> tuple[str, int, bool]:
    """The CSV text, the number of entries written, and whether the size cap cut it short."""
    lines = [",".join(COLUMNS)]
    size = len(lines[0]) + 2
    written = 0
    for entry in entries:
        data = entry.model_dump(mode="json")
        line = ",".join(field(data.get(c)) for c in COLUMNS)
        if size + len(line.encode()) + 2 > MAX_BYTES:
            return "\r\n".join(lines) + "\r\n", written, True
        lines.append(line)
        size += len(line.encode()) + 2
        written += 1
    return "\r\n".join(lines) + "\r\n", written, False
