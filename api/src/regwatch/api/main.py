"""``regwatch-api``: run the API under uvicorn."""

from __future__ import annotations

import argparse

import uvicorn

from regwatch.core.settings import get_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="regwatch-api")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 in containers)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="development hot reload")
    args = parser.parse_args(argv)
    settings = get_settings()  # fail fast before uvicorn starts
    uvicorn.run(
        "regwatch.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips=",".join(str(net) for net in settings.trusted_proxies),
    )
