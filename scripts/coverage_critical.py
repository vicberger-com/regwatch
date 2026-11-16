"""Require 100 percent line and branch coverage on security-critical modules (#29, REQ-25).

docs/07-testing-quality.md 7.1 names SafeFetcher, permission checks, the attribute validator
and output destination validation. Patterns below match their modules once they exist; a
pattern that matches nothing is reported and skipped. Input: `coverage json` output.
Usage: python3 -I scripts/coverage_critical.py api/coverage.json
"""

from __future__ import annotations

import json
import sys
from fnmatch import fnmatch

CRITICAL = {
    "SafeFetcher": ["*/regwatch/*safe_fetch*.py", "*/regwatch/*/safe_fetch*/*.py"],
    "permission checks": ["*/regwatch/*/permissions.py"],
    # The M2 module is taxonomy/validator.py; the first pattern never matched it (PR 25 review).
    "attribute validator": ["*/regwatch/*attribute*valid*.py", "*/regwatch/taxonomy/validator.py"],
    "output destination validation": ["*/regwatch/outputs/*destination*.py"],
}


def main(path: str) -> int:
    files = json.loads(open(path, encoding="utf-8").read())["files"]
    failures = 0
    for name, patterns in CRITICAL.items():
        matched = {f: v for f, v in files.items() if any(fnmatch(f, p) for p in patterns)}
        if not matched:
            print(f"skip  {name}: no module yet ({', '.join(patterns)})")
            continue
        for file, data in sorted(matched.items()):
            pct = data["summary"]["percent_covered"]
            ok = pct >= 100.0
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'}  {name}: {file} {pct:.1f}% (floor 100%)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
