"""Severity (M4 Q4; pipeline review finding 4)."""

from __future__ import annotations

import pytest

from regwatch.processing.events import severity


@pytest.mark.parametrize(
    ("title", "pct", "level"),
    [("A fine day", 1.0, "info"), ("Fine-tuning guidance", 1.0, "info"),
     ("Sanctions list update", 1.0, "info"), ("Adopted text of the guidance", 1.0, "info"),
     ("Company fined 2 million", 1.0, "major"), ("The Act enters into force", None, "major"),
     ("Gesetz tritt in Kraft", None, "major"), ("法律が施行された", None, "major"),
     ("罰金の通知", None, "major"), ("A note", 25.0, "notable"), ("A note", 20.0, "info")],
)  # fmt: skip
def test_severity(title: str, pct: float | None, level: str) -> None:
    assert severity(title, pct) == level
