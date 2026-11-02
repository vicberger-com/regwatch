"""License allow-list check run by scripts/license-scan.sh (REQ-20, 8.6 item 1).

Encodes docs/03-architecture.md 3.5 and ADR-0003 with its 2026-11-02 amendments. Standard
library only; run with `python3 -I`. Exit status 1 on any prohibited, review-required or
unknown license that no reviewed entry in scripts/license-exceptions.toml covers.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import cast

# 3.5: allowed for bundled code and assets.
ALLOWED = {
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "Apache-2.0",
    "PostgreSQL",
    "Zlib",
    "Unlicense",
    "CC0-1.0",
    "Public-Domain",
    "PSF-2.0",
    "MIT-0",  # ADR-0003 amendment 2, BL-59
    "BlueOak-1.0.0",  # ADR-0003 amendment 2, BL-59
    "Python-2.0",  # ADR-0003 amendment 2, BL-59
    "MPL-2.0",
}
FONT_ONLY = {"OFL-1.1"}  # ADR-0003 amendment, BL-57: font files only
FONT_SUFFIXES = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
PACKAGE_METADATA = re.compile(
    r"(?i)^(license|licence|ofl|copying|notice|readme|changelog)"
    r"([.-].*)?$|^package\.json$|^RECORD$|^METADATA$|^WHEEL$|"
    r"^INSTALLER$|^REQUESTED$|^direct_url\.json$|\.md$|\.txt$"
)
# 3.5: review required (ADR per use). Prefix match.
REVIEW = ("LGPL-", "EPL-")
# 3.5 and ADR-0003 decision 3: prohibited in bundled code. Prefix match.
PROHIBITED = (
    "GPL-",
    "AGPL-",
    "SSPL",
    "BUSL",
    "Elastic-",
    "RSAL",
    "Commons-Clause",
    "SUL-",
    "CC-BY-NC",
    "CC-BY-SA",
)

ALIASES = {
    "mit license": "MIT",
    "the mit license": "MIT",
    "mit/x11": "MIT",
    "expat": "MIT",
    "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "apache 2": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0",
    "bsd-3": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "new bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "bsd-2": "BSD-2-Clause",
    "bsd 2-clause": "BSD-2-Clause",
    "simplified bsd": "BSD-2-Clause",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "mpl 2.0": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
    "psf": "PSF-2.0",
    "psfl": "PSF-2.0",
    "the unlicense (unlicense)": "Unlicense",
    "cc0": "CC0-1.0",
    "cc0 1.0 universal": "CC0-1.0",
    "postgresql license": "PostgreSQL",
    "zlib license": "Zlib",
    "public domain": "Public-Domain",
    "sil open font license 1.1": "OFL-1.1",
    "sil open font license 1.1 (ofl-1.1)": "OFL-1.1",
}


def unwrap(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")") and text.count("(") == 1:
        text = text[1:-1].strip()
    return text


def normalise(term: str) -> str:
    term = unwrap(term)
    term = re.sub(r"\s+WITH\s+.*$", "", term)  # judge the base license, ignore exceptions
    term = re.sub(r"-(only|or-later)$|\+$", "", term)
    return ALIASES.get(term.lower(), term)


def classify(term: str) -> str:
    """Return allowed, font-only, review, prohibited or unknown for one license term."""
    lic = normalise(term)
    if lic in ALLOWED:
        return "allowed"
    if lic in FONT_ONLY:
        return "font-only"
    if lic.startswith(REVIEW):
        return "review"
    if lic.startswith(PROHIBITED) or "GPL" in lic.upper().replace("LGPL", ""):
        return "prohibited"
    return "unknown"


def evaluate(expression: str) -> tuple[str, list[str]]:
    """Evaluate an SPDX-like expression. OR takes the best branch; AND, ';' and ',' take the
    worst (pip-licenses joins several classifiers with '; ', so that is read conservatively)."""
    order = ["allowed", "font-only", "review", "unknown", "prohibited"]
    expr = (expression or "").strip()
    if not expr or expr.upper() in {"UNKNOWN", "UNLICENSED", "NONE"} or "SEE LICEN" in expr.upper():
        return "unknown", [expr or "(empty)"]
    worst = "allowed"
    terms: list[str] = []
    for conj in re.split(r"\s+AND\s+|;|,(?![^()]*\))", unwrap(expr)):
        best = "prohibited"
        for alt in re.split(r"\s+OR\s+|\s*/\s*(?![^()]*\))", unwrap(conj)):
            if not alt.strip():
                continue
            cls = classify(alt)
            terms.append(f"{normalise(alt)}={cls}")
            best = min(best, cls, key=order.index)
        worst = max(worst, best, key=order.index)
    return worst, terms


def pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def only_fonts(files: list[str]) -> bool:
    content = [f for f in files if not PACKAGE_METADATA.search(Path(f).name)]
    return bool(content) and all(Path(f).suffix.lower() in FONT_SUFFIXES for f in content)


def node_files(path: str) -> list[str]:
    root = Path(path)
    return [
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and "node_modules" not in p.relative_to(root).parts
    ]


def python_files(python: str, name: str) -> list[str]:
    code = (
        "import importlib.metadata as m,sys;"
        "print('\\n'.join(str(f) for f in (m.distribution(sys.argv[1]).files or [])))"
    )
    out = subprocess.run(  # noqa: S603 (argv built here, no shell)
        [python, "-I", "-c", code, name],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in out.stdout.splitlines() if "__pycache__" not in line]


def load_inventory(args: argparse.Namespace) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if args.python_inventory:
        prod = {pep503(n) for n in Path(args.python_prod).read_text().split()}
        for pkg in json.loads(Path(args.python_inventory).read_text()):
            if pep503(pkg["Name"]) == pep503(args.own_python):
                continue
            rows.append(
                {
                    "eco": "python",
                    "name": pkg["Name"],
                    "version": pkg["Version"],
                    "license": pkg["License"],
                    "bundled": pep503(pkg["Name"]) in prod,
                    "files": lambda n=pkg["Name"]: python_files(args.python_exe, n),
                }
            )
    if args.node_inventory:

        def flatten(path: str) -> dict[tuple[str, str], tuple[str, str]]:
            data = json.loads(Path(path).read_text() or "{}")
            return {
                (p["name"], v): (p.get("license") or lic, pth)
                for lic, pkgs in data.items()
                for p in pkgs
                for v, pth in zip(
                    p["versions"], p.get("paths") or [""] * len(p["versions"]), strict=False
                )
            }

        node_prod = flatten(args.node_prod)
        for (name, version), (lic, path) in sorted(flatten(args.node_inventory).items()):
            rows.append(
                {
                    "eco": "node",
                    "name": name,
                    "version": version,
                    "license": lic,
                    "bundled": (name, version) in node_prod,
                    "files": lambda p=path: node_files(p),
                }
            )
    return rows


def find_exception(
    exceptions: list[dict[str, str]], row: dict[str, object]
) -> dict[str, str] | None:
    for exc in exceptions:
        same_name = (
            pep503(exc["package"]) == pep503(str(row["name"]))
            if row["eco"] == "python"
            else exc["package"] == row["name"]
        )
        if exc["ecosystem"] == row["eco"] and same_name and exc["version"] in ("*", row["version"]):
            return exc
    return None


def check_repo_fonts(root: Path) -> list[str]:
    """Contract: fonts ship with their license file beside them (ADR-0003 amendment)."""
    out = subprocess.run(  # noqa: S603 (argv built here, no shell)
        ["git", "-C", str(root), "ls-files"],  # noqa: S607 (git from PATH)
        capture_output=True,
        text=True,
        check=False,
    )
    errors = []
    for rel in out.stdout.splitlines():
        if Path(rel).suffix.lower() in FONT_SUFFIXES:
            siblings = [p.name for p in (root / rel).parent.iterdir()]
            if not any(re.match(r"(?i)^(ofl|license|licence)", s) for s in siblings):
                errors.append(f"repo   {rel}: font file without a license file beside it")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    for opt in ("python-inventory", "python-prod", "python-exe", "node-inventory", "node-prod"):
        parser.add_argument(f"--{opt}")
    parser.add_argument("--own-python", default="regwatch")
    parser.add_argument("--exceptions", required=True)
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    exceptions = tomllib.loads(Path(args.exceptions).read_text()).get("exception", [])
    for exc in exceptions:
        required = {"ecosystem", "package", "version", "license", "scope", "reason", "reviewed"}
        missing = required - set(exc)
        if missing:
            print(f"license-exceptions.toml entry {exc.get('package')} lacks {sorted(missing)}")
            return 1

    errors, used, counts = check_repo_fonts(Path(args.repo_root)), set(), {"ok": 0, "exception": 0}
    for row in load_inventory(args):
        label = f"{row['eco']:6} {row['name']}@{row['version']} ({row['license']})"
        exc = find_exception(exceptions, row)
        lic = exc["license"] if exc else str(row["license"])
        verdict, terms = evaluate(lic)
        if verdict == "font-only":
            files = cast("Callable[[], list[str]]", row["files"])()
            verdict = "allowed" if only_fonts(files) else "font-only-misused"
        if exc and (verdict != "allowed" or exc["scope"] == "tooling"):
            if verdict in ("prohibited", "review", "font-only-misused") and not exc.get("adr"):
                errors.append(
                    f"{label}: {verdict} license needs an owner-approved ADR named in "
                    "the exception's `adr` field"
                )
                continue
            if exc["scope"] == "tooling" and row["bundled"]:
                errors.append(
                    f"{label}: exception is for tooling only, but the package is a "
                    "runtime dependency"
                )
                continue
            used.add((exc["ecosystem"], exc["package"]))
            counts["exception"] += 1
            continue
        if exc:
            used.add((exc["ecosystem"], exc["package"]))
        if verdict == "allowed":
            counts["ok"] += 1
        else:
            errors.append(f"{label}: {verdict} [{', '.join(terms)}]")

    for exc in exceptions:
        if (exc["ecosystem"], exc["package"]) not in used:
            print(f"warning: unused exception {exc['ecosystem']} {exc['package']}@{exc['version']}")
    print(
        f"license scan: {counts['ok']} allowed, {counts['exception']} by reviewed exception, "
        f"{len(errors)} failing"
    )
    for err in errors:
        print(f"FAIL {err}")
    if errors:
        print(
            "Fix: replace the package, or after reading its LICENSE file add a reviewed entry "
            "to scripts/license-exceptions.toml (prohibited and review-required licenses need "
            "an owner-approved ADR first; docs/03-architecture.md 3.5)."
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
