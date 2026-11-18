"""M4 acceptance 4: with the model classifier off (Q1), processing makes no outbound call.

Nothing under regwatch.processing imports an HTTP client, a socket or the sidecar client, so
rule classification cannot reach the network whatever the flag says. Checked by syntax tree.
"""

from __future__ import annotations

import ast
import pathlib

import regwatch.processing as package

NETWORK = (
    "httpx",
    "socket",
    "urllib.request",
    "http.client",
    "requests",
    "aiohttp",
    "regwatch.core.internal",
    "regwatch.capture.safe_fetch.fetch",
)


def test_processing_imports_nothing_that_reaches_the_network() -> None:
    root = pathlib.Path(package.__file__).parent
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert not any(name == n or name.startswith(n + ".") for n in NETWORK), (
                    f"{path.name} imports {name}"
                )
