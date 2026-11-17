"""The Celery app: workers and Beat (ADR-0006).

Valkey is the broker and holds no results (``task_ignore_result``); records live in PostgreSQL.
Messages are JSON only, so the broker can never carry pickled code. Tasks are acknowledged
after they finish; a task whose worker dies is not redelivered by the broker (that loops on a
run that kills its worker), because the schedule tick hands an unfinished run over again, at
most ``runs.MAX_HANDOVERS`` times (scheduler review findings 4 and 10).

Every broker call has connect and read timeouts and a bounded retry, so a broker that accepts
and never answers cannot hold an API thread or the capture queue (finding 2). Remote control
is off: a client with only broker access cannot rate-limit, add consumers or shut workers
down (finding 6). Beat keeps no schedule file: it fires only the periodic tasks named in
``docs/contracts/registries.yaml``, and job schedules live in ``capture_job.next_run_at``, so
its in-memory scheduler loses nothing, and no pickle file is read at start (finding 1).
"""

from __future__ import annotations

from functools import cache

from celery import Celery
from celery.signals import worker_process_init

from regwatch.core.settings import Settings, get_settings

# The last stop for a task that runs away (RSS review finding 3): a capture run of 200 pages at
# 30 a minute takes under 7 minutes, so an hour is generous. A task past its soft limit gets
# an exception it can clean up after; past the hard limit its process is replaced.
SOFT_TIME_LIMIT_S = 3300
TIME_LIMIT_S = 3600
MAX_MEMORY_PER_CHILD_KB = 1024 * 1024  # recycle a worker process after a task that grew past 1 GiB
ADDRESS_SPACE_BYTES = 4 * 1024**3  # and never let one grow past 4 GiB during a task
BROKER_TIMEOUT_S = 5.0
PUBLISH_RETRY = {"max_retries": 2, "interval_start": 0, "interval_step": 0.5, "interval_max": 1}
BEAT_SCHEDULER = "celery.beat:Scheduler"  # in memory; the default one unpickles a shelve file
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
        task_reject_on_worker_lost=False,
        task_publish_retry=True,
        task_publish_retry_policy=PUBLISH_RETRY,
        broker_connection_timeout=BROKER_TIMEOUT_S,
        broker_transport_options={
            "socket_timeout": BROKER_TIMEOUT_S,
            "socket_connect_timeout": BROKER_TIMEOUT_S,
        },
        worker_enable_remote_control=False,
        task_soft_time_limit=SOFT_TIME_LIMIT_S,
        task_time_limit=TIME_LIMIT_S,
        worker_max_memory_per_child=MAX_MEMORY_PER_CHILD_KB,
        beat_scheduler=BEAT_SCHEDULER,
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


def limit_memory(**_: object) -> None:
    """``worker_process_init``: cap the worker process's address space, so a task that runs
    away fails with MemoryError instead of taking the host down."""
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    cap = ADDRESS_SPACE_BYTES if hard == resource.RLIM_INFINITY else min(hard, ADDRESS_SPACE_BYTES)
    resource.setrlimit(resource.RLIMIT_AS, (cap, hard))


worker_process_init.connect(limit_memory, weak=False)


@cache
def celery_app() -> Celery:
    """The process's app, built on first use so importing the module needs no settings."""
    return make_app()
