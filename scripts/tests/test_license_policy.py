"""Tests for scripts/license_policy.py (#29, REQ-20).

Run from api/: uv run pytest ../scripts/tests
"""
# ruff: noqa: S101, S603

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import license_policy as lp  # noqa: E402


@pytest.mark.parametrize(
    ("expression", "verdict"),
    [
        ("MIT", "allowed"),
        ("MIT License", "allowed"),
        ("Mozilla Public License 2.0 (MPL 2.0)", "allowed"),
        ("(MIT OR Apache-2.0)", "allowed"),
        ("MIT OR GPL-3.0-only", "allowed"),
        ("MIT AND GPL-2.0-or-later", "prohibited"),
        ("GPL-2.0 WITH Classpath-exception-2.0", "prohibited"),
        ("AGPL-3.0-only", "prohibited"),
        ("SSPL-1.0", "prohibited"),
        ("BUSL-1.1", "prohibited"),
        ("CC-BY-NC-4.0", "prohibited"),
        ("LGPL-2.1-or-later", "review"),
        ("EPL-2.0", "review"),
        ("PSF-2.0", "allowed"),
        ("MIT-0", "allowed"),
        ("BlueOak-1.0.0", "allowed"),
        ("Python-2.0", "allowed"),
        ("OFL-1.1", "font-only"),
        ("BSD License", "unknown"),
        ("UNKNOWN", "unknown"),
        ("", "unknown"),
        ("SEE LICENSE IN LICENSE.txt", "unknown"),
        ("MIT License; Apache Software License", "allowed"),
        ("MIT; GPLv3", "prohibited"),
        ("Proprietary", "unknown"),
    ],
)
def test_evaluate(expression: str, verdict: str) -> None:
    assert lp.evaluate(expression)[0] == verdict


def test_only_fonts() -> None:
    assert lp.only_fonts(["files/inter.woff2", "OFL.txt", "package.json", "README.md"])
    assert not lp.only_fonts(["index.js", "inter.woff2", "LICENSE"])
    assert not lp.only_fonts(["LICENSE"])


Inventory = dict[str, list[dict[str, object]]]


def _run(
    tmp_path: Path, node: Inventory, prod: Inventory, exceptions: str = ""
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "node.json").write_text(json.dumps(node))
    (tmp_path / "prod.json").write_text(json.dumps(prod))
    (tmp_path / "exc.toml").write_text(exceptions)
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPTS / "license_policy.py"),
            "--node-inventory",
            str(tmp_path / "node.json"),
            "--node-prod",
            str(tmp_path / "prod.json"),
            "--exceptions",
            str(tmp_path / "exc.toml"),
            "--repo-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _pkg(name: str, lic: str, path: Path) -> dict[str, object]:
    return {"name": name, "versions": ["1.0.0"], "paths": [str(path)], "license": lic}


def test_font_package_with_ofl_passes_and_code_package_fails(tmp_path: Path) -> None:
    font, code = tmp_path / "font", tmp_path / "code"
    font.mkdir()
    code.mkdir()
    (font / "inter.woff2").write_bytes(b"x")
    (font / "OFL.txt").write_text("SIL OFL 1.1")
    (code / "index.js").write_text("module.exports = 1")
    ok = _run(tmp_path, {"OFL-1.1": [_pkg("font", "OFL-1.1", font)]}, {})
    assert ok.returncode == 0, ok.stdout
    bad = _run(tmp_path, {"OFL-1.1": [_pkg("code", "OFL-1.1", code)]}, {})
    assert bad.returncode == 1
    assert "font-only-misused" in bad.stdout


def test_unknown_fails_and_tooling_exception_is_dev_only(tmp_path: Path) -> None:
    exc = (
        '[[exception]]\necosystem = "node"\npackage = "lib"\nversion = "1.0.0"\n'
        'license = "WTFPL"\nscope = "tooling"\nreason = "r"\nreviewed = "r"\n'
    )
    pkg = {"WTFPL": [_pkg("lib", "WTFPL", tmp_path)]}
    assert _run(tmp_path, pkg, {}).returncode == 1
    assert _run(tmp_path, pkg, {}, exc).returncode == 0
    bundled = _run(tmp_path, pkg, pkg, exc)
    assert bundled.returncode == 1
    assert "tooling only" in bundled.stdout


def test_prohibited_needs_adr_even_with_exception(tmp_path: Path) -> None:
    exc = (
        '[[exception]]\necosystem = "node"\npackage = "lib"\nversion = "*"\n'
        'license = "GPL-3.0-only"\nscope = "tooling"\nreason = "r"\nreviewed = "r"\n'
    )
    result = _run(tmp_path, {"GPL-3.0": [_pkg("lib", "GPL-3.0", tmp_path)]}, {}, exc)
    assert result.returncode == 1
    assert "ADR" in result.stdout
