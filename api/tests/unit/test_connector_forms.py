"""The admin UI's connector forms match docs/contracts/connectors.yaml (M3; screens.md)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gen_connector_forms.py"


def test_the_generated_forms_are_current() -> None:
    spec = importlib.util.spec_from_file_location("gen_connector_forms", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = module.OUTPUT.read_text(encoding="utf-8") if module.OUTPUT.exists() else ""
    assert current == module.render(), "run `make connectors`: the generated forms are stale"
    assert module.main(["--check"]) == 0
