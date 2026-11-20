"""Unit: every model and foreign key resolves in a fresh process, as the worker loads them."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from regwatch.core.db import MODEL_MODULES

SRC = Path(__file__).resolve().parents[2] / "src" / "regwatch"


def test_every_models_module_is_listed() -> None:
    found = {f"regwatch.{p.parent.name}.models" for p in SRC.glob("*/models.py")}
    assert found == set(MODEL_MODULES)


def _fresh(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - our own interpreter running fixed code
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )


def test_the_mappers_configure_in_a_fresh_process() -> None:
    """What failed in the worker (M8.1): output_job's foreign keys to other modules' tables,
    when only the outputs models were imported. ``load_models`` fixes it."""
    resolve = (
        "from regwatch.core.db import Base; "
        "[fk.column for t in Base.metadata.tables.values() for fk in t.foreign_keys]"
    )
    alone = "import regwatch.outputs.models; " + resolve
    assert "NoReferencedTableError" in _fresh(alone).stderr  # the failure this guards against
    loaded = "from regwatch.core.db import load_models; load_models(); " + resolve
    done = _fresh(loaded)
    assert done.returncode == 0, done.stderr
