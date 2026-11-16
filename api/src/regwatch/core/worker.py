"""The Celery app: workers and Beat (ADR-0006).

Valkey is the broker and holds no results (``task_ignore_result``); records live in PostgreSQL.
Tasks are acknowledged after they finish and re-delivered if a worker dies, which is safe
because every task is idempotent (a run is claimed with ``SKIP LOCKED``). Messages are JSON
only, so the broker can never carry pickled code. Beat fires only the periodic tasks named in
``docs/contracts/registries.yaml``; job schedules live in ``capture_job.next_run_at``.
"""

from __future__ import annotations

from functools import cache

from celery import Celery

from regwatch.core.settings import Settings, get_settings

QUEUES = ("capture",)  # the queues this module's tasks use; M4 adds process
BEAT = {
    "capture.schedule_tick": {"task": "capture.schedule_tick", "schedule": 60.0},
    "capture.health_check": {"task": "capture.health_check", "schedule": 3600.0},
}


def broker_url(settings: Settings) -> str:
    """kombu's Redis transport speaks to Valkey; it knows the scheme only as ``redis``."""
    url = settings.queue_url.get_secret_value()
    return "redis://" + url[len("valkey://") :] if url.startswith("valkey://") else url


def make_app(settings: Settings | None = None) -> Celery:
    app = Celery("regwatch", broker=broker_url(settings or get_settings()))
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_backend=None,
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        task_default_queue="capture",
        task_routes={"capture.*": {"queue": "capture"}},
        beat_schedule=BEAT,
        timezone="UTC",
        enable_utc=True,
        worker_hijack_root_logger=False,
    )
    app.conf.include = ["regwatch.capture.tasks"]
    return app


@cache
def celery_app() -> Celery:
    """The process's app, built on first use so importing the module needs no settings."""
    return make_app()
