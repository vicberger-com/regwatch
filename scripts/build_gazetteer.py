"""Write api/src/regwatch/processing/gazetteer.json, the country names M4 tags jurisdictions by.

Names come from i18n-iso-countries v7.14.0 (MIT), the same commit the jurisdiction seed uses
(register 3.6, V `55c3a72`), in the rule languages of M4 Q2: en, de, fr, es, pt and ja. Each
file's SHA-256 is pinned, so a changed upstream file fails the build instead of changing tags.

Usage, in an empty directory:
    I18N=55c3a72603faf0185661e80841074e1c2fcf8db5
    for l in en de fr es pt ja; do
      curl -sSLO https://raw.githubusercontent.com/michaelwittig/node-i18n-iso-countries/$I18N/langs/$l.json
    done
    python3 -I scripts/build_gazetteer.py DIRECTORY
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "api" / "src" / "regwatch" / "processing" / "gazetteer.json"
PINNED = {
    "en.json": "7445185d6424e574027a7cd14029e000784eaa03a2b83ab097742079f701e702",
    "de.json": "4334ec32316a5643e449f64b98b711da0d627c47cc1028e9edf9023908534d88",
    "fr.json": "3d644418bcb8a49b6aebc7c227929d0fc9c5c8a56a82c4321ba3f1bb1f4c590d",
    "es.json": "be537177022e360ce5e684ee2a7f71d9e975da3782bb7a70464b98a93f1d52b2",
    "pt.json": "035f64df90918a28f4ac4acbebb19f94320b3b09ce98dbf85f30e614ed6c0b14",
    "ja.json": "926b92040762d5d614734bce125eb1190fdbbb423b382305db9f366ed41e89d2",
}
MIN_NAME = 4  # shorter names ("Chad" passes; "Oman" passes) are kept; two- and three-letter
#               strings such as codes are never names here


def main(src: Path) -> None:
    names: dict[str, set[str]] = {}
    for file, digest in PINNED.items():
        data = (src / file).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit(f"{file}: not the pinned file")
        for code, value in json.loads(data)["countries"].items():
            for name in value if isinstance(value, list) else [value]:
                if isinstance(name, str) and len(name) >= MIN_NAME or (file == "ja.json" and name):
                    names.setdefault(code, set()).add(name)
    out = {"source": "i18n-iso-countries v7.14.0 (MIT), commit 55c3a72; en de fr es pt ja",
           "names": {code: sorted(found) for code, found in sorted(names.items())}}  # fmt: skip
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=False) + "\n",
                   encoding="utf-8")  # fmt: skip
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out['names'])} codes")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
