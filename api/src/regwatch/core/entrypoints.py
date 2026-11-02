"""Console entry points whose implementations land in later issues.

``regwatch-worker`` and ``regwatch-beat`` stay up and idle until Celery lands (M3), so the
Compose stack keeps its contract services; ``regwatch-seed`` and ``regwatch-admin`` exit with
status 2 and say which issue delivers them.
"""

from __future__ import annotations

import signal
import sys

import structlog

from regwatch.core.logging_setup import configure_logging

_log = structlog.get_logger("regwatch.entrypoints")


def _idle(process: str) -> None:
    configure_logging()
    _log.warning("stub_process_idle", process=process, lands_in="M3 capture framework (Celery)")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.pause()


def _not_yet(command: str, issue: str) -> None:
    print(f"{command}: not implemented yet; lands in {issue}", file=sys.stderr)
    raise SystemExit(2)


def worker() -> None:
    """Celery worker (``regwatch-worker``)."""
    _idle("worker")


def beat() -> None:
    """Celery beat (``regwatch-beat``); exactly one runs."""
    _idle("beat")


def seed() -> None:
    """Idempotent seed loader (``regwatch-seed``)."""
    _not_yet("regwatch-seed", "#28")


def admin() -> None:
    """Administration commands (``regwatch-admin create-user``)."""
    _not_yet("regwatch-admin", "#31")
