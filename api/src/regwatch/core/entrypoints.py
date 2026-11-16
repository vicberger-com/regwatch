"""Console entry points.

``regwatch-worker`` and ``regwatch-beat`` run Celery (:mod:`regwatch.core.worker`, M3).
``regwatch-seed`` runs the seed loader (:mod:`regwatch.core.seed`); ``regwatch-admin`` runs
:mod:`regwatch.identity.admin_cli`.
"""

from __future__ import annotations

import sys

import structlog

from regwatch.core.logging_setup import configure_logging

_log = structlog.get_logger("regwatch.entrypoints")
BEAT_SCHEDULE_FILE = "/tmp/regwatch-beat-schedule"  # noqa: S108 - Beat's own last-run times


def worker() -> None:
    """Celery worker (``regwatch-worker``) on the capture queue."""
    from regwatch.core.worker import QUEUES, celery_app

    configure_logging()
    argv = ["worker", "--queues", ",".join(QUEUES), "--loglevel", "INFO", "--concurrency", "2",
            "--without-gossip", "--without-mingle"]  # fmt: skip
    celery_app().worker_main(argv)


def beat() -> None:
    """Celery beat (``regwatch-beat``); exactly one runs (ADR-0006)."""
    from regwatch.core.worker import celery_app

    configure_logging()
    celery_app().start(["beat", "--loglevel", "INFO", "--schedule", BEAT_SCHEDULE_FILE])


def seed() -> None:
    """Idempotent seed loader (``regwatch-seed``)."""
    from regwatch.core.seed import main

    raise SystemExit(main(sys.argv[1:]))


def admin() -> None:
    """Administration commands (``regwatch-admin create-user``)."""
    from regwatch.identity.admin_cli import main

    raise SystemExit(main(sys.argv[1:]))
